import math
from pathlib import Path
from typing import Callable

import cv2
import numpy as np


class AnalysisCancelledError(RuntimeError):
    pass


class SmartThumbnailGenerator:
    """Two-pass, low-memory torso-change analysis for fixed-camera videos."""

    SAMPLE_INTERVAL = 0.25
    REFINE_INTERVAL = 0.08
    FRAME_WIDTH = 400
    GRID_SIZE = 4
    CHANGE_THRESHOLD = 0.25
    CHANGE_CELLS_REQUIRED = 2
    CONFIRMATIONS_REQUIRED = 3
    REFINE_CONFIRMATIONS_REQUIRED = 5
    MAX_PREVIEWS = 32

    def __init__(self) -> None:
        self.detector = cv2.HOGDescriptor()
        self.detector.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        self.light_normalizer = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        self.background = cv2.createBackgroundSubtractorMOG2(
            history=240, varThreshold=24, detectShadows=False
        )

    def generate(
        self,
        video_path: str,
        output_dir: Path,
        cancelled,
        report_progress: Callable[[int, str], None],
    ) -> list[dict[str, object]]:
        capture = cv2.VideoCapture(video_path)
        if not capture.isOpened():
            raise RuntimeError("Impossibile aprire il video con OpenCV.")
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            fps = float(capture.get(cv2.CAP_PROP_FPS))
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = frame_count / fps if fps > 0 and frame_count > 0 else 0.0
            if duration <= 0:
                raise RuntimeError("Durata del video non disponibile.")

            tracks, candidates = self._scan(capture, duration, frame_count, cancelled, report_progress)
            if cancelled.is_set():
                raise AnalysisCancelledError("Analisi annullata.")
            chosen = self._refine(capture, candidates, duration, frame_count, cancelled, report_progress)
            chosen.sort(key=lambda item: (float(item["timestamp"]), str(item["personId"])))
            chosen = self._deduplicate(chosen)[: self.MAX_PREVIEWS]
            if not chosen:
                return []

            results = []
            for index, event in enumerate(chosen):
                if cancelled.is_set():
                    raise AnalysisCancelledError("Analisi annullata.")
                capture.set(cv2.CAP_PROP_POS_MSEC, float(event["timestamp"]) * 1000)
                ok, frame = capture.read()
                if not ok or frame is None:
                    continue
                height, width = frame.shape[:2]
                scale = min(1.0, self.FRAME_WIDTH / max(width, height))
                if scale < 1:
                    frame = cv2.resize(
                        frame,
                        (max(1, round(width * scale)), max(1, round(height * scale))),
                        interpolation=cv2.INTER_AREA,
                    )
                target = output_dir / f"{index:04d}.png"
                ok, encoded = cv2.imencode(".png", frame)
                if ok:
                    target.write_bytes(encoded.tobytes())
                    results.append({**event, "thumbnailPath": str(target)})
                report_progress(90 + round((index + 1) * 10 / len(chosen)), "Salvataggio anteprime")
            return results
        finally:
            capture.release()

    def _scan(self, capture, duration, frame_count, cancelled, report_progress):
        tracks: dict[int, dict[str, object]] = {}
        candidates: list[dict[str, object]] = []
        next_person_id = 1
        timestamp = 0.0
        while timestamp < duration:
            if cancelled.is_set():
                raise AnalysisCancelledError("Analisi annullata.")
            frame = self._read_small_frame(capture, timestamp)
            if frame is not None:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                foreground = self.background.apply(gray, learningRate=0.002)
                detections = self._detect_people(frame, foreground)
                matches, next_person_id = self._match_tracks(
                    detections, tracks, timestamp, next_person_id
                )
                for detection, track_id in matches:
                    track = tracks[track_id]
                    if track.get("light_signature") is None:
                        track["light_signature"] = self._light_signature(frame)
                    light_offset = self._light_offset(frame, track["light_signature"])
                    features = self._torso_features(frame, detection, light_offset)
                    if features is None:
                        continue
                    frame_index = round(timestamp * frame_count / duration)
                    if track.get("baseline") is None:
                        track["baseline"] = features
                        if len(candidates) < self.MAX_PREVIEWS * 3:
                            candidates.append({
                                "timestamp": timestamp,
                                "frameIndex": frame_index,
                                "personId": f"person-{track_id}",
                                "eventType": "FIRST_APPEARANCE",
                                "changeScore": 1.0,
                                "bbox": detection,
                            })
                        continue
                    if self._is_moving(track, detection):
                        track["pending"] = None
                        continue
                    score, changed_cells, strongest_cell = self._compare(track["baseline"], features)
                    if not self._is_outfit_change(score, changed_cells, strongest_cell):
                        track["pending"] = None
                        continue
                    pending = track.get("pending")
                    if pending and self._compare(pending["features"], features)[0] < 0.2:
                        pending["hits"] += 1
                        pending["best"] = self._sharper(pending["best"], {
                            "timestamp": timestamp,
                            "frameIndex": frame_index,
                            "bbox": detection,
                            "features": features,
                            "sharpness": self._sharpness(frame, detection),
                            "changeScore": score,
                        })
                    else:
                        pending = {
                            "hits": 1,
                            "features": features,
                            "best": {
                                "timestamp": timestamp,
                                "frameIndex": frame_index,
                                "bbox": detection,
                                "features": features,
                                "sharpness": self._sharpness(frame, detection),
                                "changeScore": score,
                            },
                        }
                        track["pending"] = pending
                    if pending["hits"] >= self.CONFIRMATIONS_REQUIRED:
                        event = dict(pending["best"])
                        event.update(
                            personId=f"person-{track_id}",
                            eventType="TORSO_OUTFIT_CHANGE",
                            baseline=track["baseline"],
                            baseline_light=track["light_signature"],
                        )
                        if len(candidates) < self.MAX_PREVIEWS * 3:
                            candidates.append(event)
                        track["baseline"] = pending["features"]
                        track["pending"] = None
            report_progress(min(55, round((timestamp / duration) * 55)), "Scansione leggera")
            timestamp += self.SAMPLE_INTERVAL
        return tracks, candidates

    def _refine(self, capture, candidates, duration, frame_count, cancelled, report_progress):
        events = []
        change_candidates = [item for item in candidates if item["eventType"] == "TORSO_OUTFIT_CHANGE"]
        first_appearances = [item for item in candidates if item["eventType"] == "FIRST_APPEARANCE"]
        total = max(1, len(change_candidates))
        for candidate in first_appearances:
            events.append({key: candidate[key] for key in ("timestamp", "frameIndex", "personId", "eventType", "changeScore")})

        for candidate_index, candidate in enumerate(change_candidates):
            if cancelled.is_set():
                raise AnalysisCancelledError("Analisi annullata.")
            anchor_time = float(candidate["timestamp"])
            baseline = candidate["baseline"]
            best = None
            consecutive = 0
            timestamp = max(0.0, anchor_time - 0.32)
            end_time = min(duration, anchor_time + 1.28)
            previous_features = None
            while timestamp <= end_time:
                if cancelled.is_set():
                    raise AnalysisCancelledError("Analisi annullata.")
                frame = self._read_small_frame(capture, timestamp)
                if frame is not None:
                    detection = self._nearest_detection(frame, candidate["bbox"])
                    if detection is not None and not self._is_unstable(candidate["bbox"], detection):
                        light_offset = self._light_offset(frame, candidate["baseline_light"])
                        features = self._torso_features(frame, detection, light_offset)
                        if features is not None:
                            score, changed_cells, strongest_cell = self._compare(baseline, features)
                            changed = self._is_outfit_change(score, changed_cells, strongest_cell)
                            consistent = previous_features is None or self._compare(previous_features, features)[0] < 0.24
                            consecutive = consecutive + 1 if changed and consistent else 0
                            if changed:
                                proposal = {
                                    "timestamp": timestamp,
                                    "frameIndex": round(timestamp * frame_count / duration),
                                    "bbox": detection,
                                    "sharpness": self._sharpness(frame, detection),
                                    "changeScore": score,
                                }
                                best = self._sharper(best, proposal)
                            previous_features = features
                            if consecutive >= self.REFINE_CONFIRMATIONS_REQUIRED and best is not None:
                                break
                timestamp += self.REFINE_INTERVAL
            if consecutive >= self.REFINE_CONFIRMATIONS_REQUIRED and best is not None:
                events.append({
                    "timestamp": best["timestamp"],
                    "frameIndex": best["frameIndex"],
                    "personId": candidate["personId"],
                    "eventType": "TORSO_OUTFIT_CHANGE",
                    "changeScore": round(float(best["changeScore"]), 3),
                })
            report_progress(55 + round((candidate_index + 1) * 35 / total), "Verifica cambi sospetti")
        return events

    def _read_small_frame(self, capture, timestamp):
        capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, timestamp) * 1000)
        ok, frame = capture.read()
        if not ok or frame is None:
            return None
        height, width = frame.shape[:2]
        scale = min(1.0, self.FRAME_WIDTH / max(width, height))
        return cv2.resize(
            frame,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        ) if scale < 1 else frame

    def _detect_people(self, frame, foreground_mask=None):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        normalized = self.light_normalizer.apply(gray)
        boxes, weights = self.detector.detectMultiScale(
            normalized, winStride=(8, 8), padding=(8, 8), scale=1.05, hitThreshold=0.0
        )
        detections = []
        for (x, y, width, height), weight in zip(boxes, weights):
            if float(weight) < -0.1 or width < 14 or height < 28:
                continue
            box = (int(x), int(y), int(width), int(height))
            if not any(self._iou(box, prior) > 0.55 for prior in detections):
                detections.append(box)
        if foreground_mask is not None:
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 11))
            mask = cv2.morphologyEx(foreground_mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            frame_area = frame.shape[0] * frame.shape[1]
            minimum_area = max(90, round(frame_area * 0.0008))
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                x, y, width, height = cv2.boundingRect(contour)
                area = cv2.contourArea(contour)
                aspect = height / max(1, width)
                if (
                    area < minimum_area
                    or area > frame_area * 0.16
                    or width < 10
                    or height < 18
                    or not 0.45 <= aspect <= 6.0
                ):
                    continue
                box = (x, y, width, height)
                if not any(self._iou(box, prior) > 0.3 for prior in detections):
                    detections.append(box)
        return detections

    def _match_tracks(self, detections, tracks, timestamp, next_person_id):
        pairs = []
        available = set(tracks)
        for detection in detections:
            center = self._center(detection)
            options = []
            for track_id in available:
                track = tracks[track_id]
                previous = track["bbox"]
                distance = math.dist(center, self._center(previous))
                scale = max(30.0, math.hypot(previous[2], previous[3]))
                if distance <= scale * 1.35 or self._iou(detection, previous) > 0.12:
                    options.append((distance / scale - self._iou(detection, previous), track_id))
            if options:
                _, track_id = min(options)
                available.remove(track_id)
            else:
                track_id = next_person_id
                next_person_id += 1
                tracks[track_id] = {"bbox": detection, "last_seen": timestamp, "baseline": None, "pending": None}
            track = tracks[track_id]
            track["previous_bbox"] = track["bbox"]
            track["bbox"] = detection
            track["last_seen"] = timestamp
            pairs.append((detection, track_id))
        for track_id in list(tracks):
            if timestamp - float(tracks[track_id]["last_seen"]) > 45:
                del tracks[track_id]
        return pairs, next_person_id

    def _nearest_detection(self, frame, expected):
        detections = self._detect_people(frame)
        if not detections:
            x, y, width, height = map(int, expected)
            crop = frame[
                max(0, y):min(frame.shape[0], y + height),
                max(0, x):min(frame.shape[1], x + width),
            ]
            if crop.size and float(np.std(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY))) >= 3:
                return tuple(expected)
            return None
        expected = tuple(expected)
        return min(
            detections,
            key=lambda box: math.dist(self._center(box), self._center(expected)) / max(30, expected[2])
            - self._iou(box, expected),
        )

    def _torso_features(self, frame, person_box, illumination_offset=0.0):
        x, y, width, height = person_box
        left = max(0, x + round(width * 0.08))
        right = min(frame.shape[1], x + round(width * 0.92))
        if height / max(1, width) < 1.35:
            top = max(0, y + round(height * 0.05))
            bottom = min(frame.shape[0], y + round(height * 0.82))
        else:
            top = max(0, y + round(height * 0.15))
            bottom = min(frame.shape[0], y + round(height * 0.60))
        if right - left < 12 or bottom - top < 12:
            return None
        roi = frame[top:bottom, left:right]
        if illumination_offset:
            roi = np.clip(roi.astype(np.int16) - round(illumination_offset), 0, 255).astype(np.uint8)
        roi = cv2.resize(roi, (64, 64), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        hsv[:, :, 2] = self.light_normalizer.apply(hsv[:, :, 2])
        gray = hsv[:, :, 2]
        features = []
        for row in range(self.GRID_SIZE):
            for column in range(self.GRID_SIZE):
                y0, y1 = row * 16, (row + 1) * 16
                x0, x1 = column * 16, (column + 1) * 16
                cell = hsv[y0:y1, x0:x1]
                hue = cv2.calcHist([cell], [0], None, [8], [0, 180]).flatten()
                saturation = cv2.calcHist([cell], [1], None, [4], [0, 256]).flatten()
                value = cv2.calcHist([cell], [2], None, [4], [0, 256]).flatten()
                hue /= max(1.0, float(hue.sum()))
                saturation /= max(1.0, float(saturation.sum()))
                value /= max(1.0, float(value.sum()))
                edges = cv2.Canny(gray[y0:y1, x0:x1], 60, 140)
                features.append((hue, saturation, value, float(np.mean(edges > 0))))
        return features

    @staticmethod
    def _light_signature(frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA)

    def _light_offset(self, frame, baseline_signature):
        current = self._light_signature(frame).astype(np.int16)
        baseline = np.asarray(baseline_signature, dtype=np.int16)
        return float(np.median(current - baseline))

    def _compare(self, left, right):
        cell_scores = []
        for (left_h, left_s, left_v, left_edge), (right_h, right_s, right_v, right_edge) in zip(left, right):
            hue = cv2.compareHist(left_h.astype(np.float32), right_h.astype(np.float32), cv2.HISTCMP_BHATTACHARYYA)
            saturation = cv2.compareHist(left_s.astype(np.float32), right_s.astype(np.float32), cv2.HISTCMP_BHATTACHARYYA)
            value = cv2.compareHist(left_v.astype(np.float32), right_v.astype(np.float32), cv2.HISTCMP_BHATTACHARYYA)
            cell_scores.append(
                0.38 * hue + 0.24 * saturation + 0.2 * value
                + 0.18 * min(1.0, abs(left_edge - right_edge) * 3)
            )
        changed = sum(score >= 0.22 for score in cell_scores)
        return float(np.mean(cell_scores)), changed, max(cell_scores, default=0.0)

    def _is_outfit_change(self, score, changed_cells, strongest_cell):
        broad_change = score >= self.CHANGE_THRESHOLD and changed_cells >= self.CHANGE_CELLS_REQUIRED
        persistent_local_change = score >= 0.06 and strongest_cell >= 0.16
        return broad_change or persistent_local_change

    def _is_moving(self, track, detection):
        previous = track.get("previous_bbox")
        return previous is not None and self._is_unstable(previous, detection)

    def _is_unstable(self, previous, detection):
        distance = math.dist(self._center(previous), self._center(detection))
        size = max(24.0, math.hypot(previous[2], previous[3]))
        scale_change = abs(math.log(max(1, detection[2] * detection[3]) / max(1, previous[2] * previous[3])))
        aspect_change = abs(detection[2] / max(1, detection[3]) - previous[2] / max(1, previous[3]))
        return distance / size > 0.18 or scale_change > 0.24 or aspect_change > 0.16

    @staticmethod
    def _center(box):
        return (box[0] + box[2] / 2, box[1] + box[3] / 2)

    @staticmethod
    def _iou(left, right):
        x0, y0 = max(left[0], right[0]), max(left[1], right[1])
        x1 = min(left[0] + left[2], right[0] + right[2])
        y1 = min(left[1] + left[3], right[1] + right[3])
        intersection = max(0, x1 - x0) * max(0, y1 - y0)
        union = left[2] * left[3] + right[2] * right[3] - intersection
        return intersection / union if union else 0.0

    @staticmethod
    def _sharpness(frame, box):
        x, y, width, height = box
        crop = frame[max(0, y):y + height, max(0, x):x + width]
        if crop.size == 0:
            return 0.0
        return float(cv2.Laplacian(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())

    @staticmethod
    def _sharper(current, proposal):
        return proposal if current is None or proposal["sharpness"] > current["sharpness"] else current

    @staticmethod
    def _deduplicate(events):
        result = []
        for event in events:
            if any(
                item["personId"] == event["personId"]
                and item["eventType"] == event["eventType"]
                and abs(float(item["timestamp"]) - float(event["timestamp"])) < 0.7
                for item in result
            ):
                continue
            result.append(event)
        return result