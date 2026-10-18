import cv2
import hashlib
import http.server
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit
from smart_thumbnail_generator import AnalysisCancelledError, SmartThumbnailGenerator

APP_NAME = "Lumen Video Lite"
VIDEO_EXTENSIONS = {".avi", ".mkv", ".mov", ".mp4", ".m4v", ".webm", ".wmv"}
THUMBNAIL_COUNT = 5
OUTPUT_FOLDERS = {
    "top": "1_Top",
    "main": "2_Main",
    "linger": "3_Linger",
}


def default_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        return base / "LumenVideoLite" / "data"
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / "lumen-video-search"


def default_cache_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        return base / "LumenVideoLite" / "cache" / "previews"
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "lumen-video-search" / "previews"


def default_output_dir() -> Path:
    if os.name == "nt":
        return Path.home() / "Videos" / "LumenVideoLite"
    return Path.cwd() / "media_output"


def preview_timestamp(duration: float, index: int) -> float:
    return duration * (index + 1) / (THUMBNAIL_COUNT + 1)


def cache_key(path: str) -> str:
    return hashlib.sha256(path.encode("utf-8", errors="replace")).hexdigest()[:20]


def preview_cache_key(path: str) -> str:
    return f"{cache_key(path)}_interior"


def preview_index(path: Path) -> int:
    match = re.fullmatch(r".+?_(\d+)(?:_\d+)?(?:_(?:smart|std)_[a-f0-9]+)?\.png", path.name)
    return int(match.group(1)) if match else 0


def preview_time(path: Path) -> float:
    match = re.fullmatch(r".+?_(\d+)(?:_(\d+))?(?:_(?:smart|std)_[a-f0-9]+)?\.png", path.name)
    return int(match.group(2)) / 1000 if match and match.group(2) else 0.0


def thumbnail_paths(cache_dir: Path, path: str) -> list[Path]:
    prefix = preview_cache_key(path)
    paths = cache_dir.glob(f"{prefix}_*.png")

    def sort_key(item: Path) -> tuple[int, int]:
        match = re.fullmatch(rf"{re.escape(prefix)}_(\d+)(?:_(\d+))?(?:_(?:smart|std)_[a-f0-9]+)?\.png", item.name)
        return (int(match.group(1)), int(match.group(2) or 0)) if match else (0, 0)

    return sorted(paths, key=sort_key)


def smart_manifest_path(cache_dir: Path, path: str) -> Path:
    return cache_dir / f"{preview_cache_key(path)}_smart.json"


def standard_manifest_path(cache_dir: Path, path: str) -> Path:
    return cache_dir / f"{preview_cache_key(path)}_standard.json"


def decoder_available() -> bool:
    if cv2 is None:
        return False
    try:
        return cv2.cuda.getCudaEnabledDeviceCount() > 0
    except (AttributeError, cv2.error):
        return False


def open_capture(path: str, use_gpu: bool = False):
    if cv2 is None:
        return None
    if use_gpu and decoder_available():
        try:
            capture = cv2.VideoCapture(
                path,
                cv2.CAP_FFMPEG,
                [cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_ANY],
            )
            if capture.isOpened():
                return capture
            capture.release()
        except (AttributeError, cv2.error, TypeError):
            pass
    capture = cv2.VideoCapture(path)
    return capture if capture.isOpened() else None


def create_previews(path: str, cache_dir: Path, use_gpu: bool = False) -> dict[str, object]:
    if cv2 is None:
        raise RuntimeError("OpenCV non è installato. Esegui: python -m pip install -r requirements.txt")
    capture = open_capture(path, use_gpu)
    if capture is None:
        raise RuntimeError("Impossibile aprire il video.")
    try:
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = frame_count / fps if fps > 0 and frame_count > 0 else 0.0
        count = min(THUMBNAIL_COUNT, frame_count) if frame_count > 0 else THUMBNAIL_COUNT
        cache_dir.mkdir(parents=True, exist_ok=True)
        prefix = preview_cache_key(path)
        smart_manifest_path(cache_dir, path).unlink(missing_ok=True)
        standard_manifest_path(cache_dir, path).unlink(missing_ok=True)
        for old_path in cache_dir.glob(f"{prefix}_*.png"):
            old_path.unlink(missing_ok=True)
        for index in range(count):
            timestamp = preview_timestamp(duration, index)
            if duration:
                timestamp = min(timestamp, max(0.0, duration - 0.05))
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            frame_height, frame_width = frame.shape[:2]
            scale = min(1.0, 480 / max(frame_width, frame_height))
            if scale < 1:
                frame = cv2.resize(
                    frame,
                    (int(frame_width * scale), int(frame_height * scale)),
                    interpolation=cv2.INTER_AREA,
                )
            ok, encoded = cv2.imencode(".png", frame)
            if ok:
                target = cache_dir / f"{prefix}_{index:04d}_{int(timestamp * 1000):012d}.png"
                target.write_bytes(encoded.tobytes())
        return {"duration": duration, "width": width, "height": height, "fps": fps}
    finally:
        capture.release()


def regenerate_standard_previews(path: str, cache_dir: Path) -> list[dict[str, object]]:
    if cv2 is None:
        raise RuntimeError("OpenCV non è installato.")
    capture = open_capture(path)
    if capture is None:
        raise RuntimeError("Impossibile aprire il video.")
    cache_dir.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(tempfile.mkdtemp(prefix="lumen-standard-", dir=cache_dir))
    published: list[Path] = []
    prefix = preview_cache_key(path)
    generation = uuid.uuid4().hex[:8]
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = frame_count / fps if fps > 0 and frame_count > 0 else 0.0
        if duration <= 0:
            raise RuntimeError("Durata del video non disponibile.")
        previews = []
        for index in range(THUMBNAIL_COUNT):
            timestamp = min(duration * (index + 1) / (THUMBNAIL_COUNT + 1), max(0.0, duration - 0.05))
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            ok, frame = capture.read()
            if not ok or frame is None:
                raise RuntimeError(f"Impossibile acquisire il frame standard {index + 1}.")
            height, width = frame.shape[:2]
            scale = min(1.0, 480 / max(width, height))
            if scale < 1:
                frame = cv2.resize(
                    frame, (max(1, round(width * scale)), max(1, round(height * scale))),
                    interpolation=cv2.INTER_AREA,
                )
            staged = temporary_dir / f"{index:04d}.png"
            ok, encoded = cv2.imencode(".png", frame)
            if not ok:
                raise RuntimeError(f"Impossibile codificare il frame standard {index + 1}.")
            staged.write_bytes(encoded.tobytes())
            previews.append({
                "index": index,
                "frameIndex": round(timestamp * fps),
                "time": timestamp,
                "filename": f"{prefix}_{index:04d}_{int(timestamp * 1000):012d}_std_{generation}.png",
            })

        for item in previews:
            target = cache_dir / item["filename"]
            os.replace(temporary_dir / f"{item['index']:04d}.png", target)
            published.append(target)
        staged_manifest = temporary_dir / "manifest.json"
        staged_manifest.write_text(json.dumps({"version": 1, "type": "standard", "previews": previews}), encoding="utf-8")
        os.replace(staged_manifest, standard_manifest_path(cache_dir, path))
        published.clear()
        try:
            smart_manifest_path(cache_dir, path).unlink(missing_ok=True)
        except OSError:
            pass
        keep = {item["filename"] for item in previews}
        for old_preview in thumbnail_paths(cache_dir, path):
            if old_preview.name not in keep:
                try:
                    old_preview.unlink(missing_ok=True)
                except OSError:
                    pass
        return previews
    except Exception:
        for image in published:
            image.unlink(missing_ok=True)
        raise
    finally:
        capture.release()
        shutil.rmtree(temporary_dir, ignore_errors=True)


class Catalog:
    def __init__(self, database: Path, cache_dir: Path):
        self.database = database
        self.cache_dir = cache_dir
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS videos (
                    path TEXT PRIMARY KEY,
                    root TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    modified REAL NOT NULL,
                    duration REAL NOT NULL DEFAULT 0,
                    width INTEGER NOT NULL DEFAULT 0,
                    height INTEGER NOT NULL DEFAULT 0,
                    fps REAL NOT NULL DEFAULT 0,
                    missing INTEGER NOT NULL DEFAULT 0,
                    archived INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(videos)")}
            if "missing" not in columns:
                connection.execute("ALTER TABLE videos ADD COLUMN missing INTEGER NOT NULL DEFAULT 0")
            if "archived" not in columns:
                connection.execute("ALTER TABLE videos ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
            connection.execute("DROP TABLE IF EXISTS video_search")

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database, timeout=20)

    @staticmethod
    def columns() -> tuple[str, ...]:
        return (
            "path", "root", "filename", "file_size", "modified", "duration",
            "width", "height", "fps", "missing", "archived",
        )

    def upsert_video(self, record: dict[str, object]) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO videos (path, root, filename, file_size, modified,
                    duration, width, height, fps, missing, archived)
                VALUES (:path, :root, :filename, :file_size, :modified,
                    :duration, :width, :height, :fps, 0, 0)
                ON CONFLICT(path) DO UPDATE SET
                    root=excluded.root, filename=excluded.filename,
                    file_size=excluded.file_size, modified=excluded.modified,
                    duration=excluded.duration, width=excluded.width,
                    height=excluded.height, fps=excluded.fps,
                    missing=0, archived=0
                """,
                record,
            )

    def list_videos(self, root: str) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT path, root, filename, file_size, modified, duration, width, height, fps, missing, archived "
                "FROM videos WHERE root=? AND missing=0 AND archived=0 ORDER BY filename COLLATE NOCASE",
                (root,),
            ).fetchall()
        return [dict(zip(self.columns(), row)) for row in rows]

    def get_video(self, path: str) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT path, root, filename, file_size, modified, duration, width, height, fps, missing, archived "
                "FROM videos WHERE path=?",
                (path,),
            ).fetchone()
        return dict(zip(self.columns(), row)) if row else None

    def known_files(self, root: str) -> dict[str, tuple[int, float]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT path, file_size, modified FROM videos WHERE root=? AND archived=0",
                (root,),
            ).fetchall()
        return {row[0]: (row[1], row[2]) for row in rows}

    def mark_missing(self, paths: set[str]) -> None:
        if not paths:
            return
        with self.connect() as connection:
            connection.executemany(
                "UPDATE videos SET missing=1 WHERE path=?",
                ((path,) for path in paths),
            )

    def move_video(self, source: str, destination: str) -> None:
        stat = Path(destination).stat()
        with self.connect() as connection:
            connection.execute(
                "UPDATE videos SET path=?, root=?, filename=?, file_size=?, modified=?, missing=0, archived=1 "
                "WHERE path=?",
                (destination, str(Path(destination).parent), Path(destination).name,
                 stat.st_size, stat.st_mtime, source),
            )

    def mark_removed(self, path: str) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE videos SET missing=1, archived=1 WHERE path=?", (path,))


class LocalWebApp:
    def __init__(self):
        data_dir = default_data_dir()
        self.settings_path = data_dir / "settings.json"
        try:
            settings = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            settings = {}
        cache_dir = Path(settings.get("cache_dir", str(default_cache_dir()))).expanduser()
        self.catalog = Catalog(data_dir / "catalog.sqlite3", cache_dir)
        self.root = str(Path(settings.get("input_root", Path.cwd() / "media_input")).expanduser().resolve())
        self.output_dir = default_output_dir().resolve()
        self.desktop_mode = os.environ.get("LUMEN_DESKTOP", "") == "1" and sys.platform == "win32"
        self.output_folders = {
            key: self._validate_output_path(
                settings.get("output_folders", {}).get(key, str(self.output_dir / default))
            )
            for key, default in OUTPUT_FOLDERS.items()
        }
        self.cuda_available = decoder_available()
        self.lock = threading.Lock()
        self.standard_running = False
        self.folder_picker = None
        self.smart_job: dict[str, object] | None = None
        self.smart_cancel: threading.Event | None = None
        self.state: dict[str, object] = {
            "running": False,
            "message": "Scegli una cartella e avvia l’indicizzazione",
            "updated": 0,
            "failed": 0,
            "removed": 0,
        }

    def api_state(self) -> dict[str, object]:
        count = len(self.catalog.list_videos(self.root))
        with self.lock:
            current = dict(self.state)
        return {
            **current,
            "root": self.root,
            "count": count,
            "cuda_available": self.cuda_available,
            "desktop_mode": self.desktop_mode,
            "output_folders": dict(self.output_folders),
        }

    def _validate_output_path(self, value: object) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("Indica un percorso assoluto per la cartella di output.")
        folder = Path(text).expanduser()
        if not folder.is_absolute():
            folder = self.output_dir / folder
        return str(folder.resolve())

    def save_settings(self, input_root: str, output_folders: dict[str, object]) -> dict[str, object]:
        if not input_root.strip():
            raise ValueError("Seleziona o inserisci la cartella input.")
        root = Path(input_root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError("La cartella input selezionata non esiste.")
        normalized = {
            key: self._validate_output_path(output_folders.get(key, self.output_folders[key]))
            for key in OUTPUT_FOLDERS
        }
        with self.lock:
            if self.state["running"] or self.standard_running or self.smart_job and self.smart_job["running"]:
                raise RuntimeError("Non puoi cambiare le impostazioni durante un’elaborazione.")
            self.root = str(root)
            self.output_folders = normalized
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings = {
            "input_root": str(root),
            "output_folders": normalized,
            "cache_dir": str(self.catalog.cache_dir),
        }
        self.settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"root": str(root), "output_folders": dict(normalized)}

    def pick_folder(self, kind: str, current: str = "") -> str:
        if not self.desktop_mode:
            raise ValueError("Il selettore nativo è disponibile solo nella versione Windows.")
        if kind not in {"input", "output"}:
            raise ValueError("Tipo di cartella non valido.")
        if not self.folder_picker:
            raise RuntimeError("Il selettore cartelle desktop non è stato inizializzato.")
        return self.folder_picker(kind, current)

    def clear_preview_cache(self) -> int:
        with self.lock:
            if self.state["running"] or self.standard_running or self.smart_job and self.smart_job["running"]:
                raise RuntimeError("Attendi la fine dell’elaborazione prima di svuotare la cache.")
        removed = 0
        for preview in (*self.catalog.cache_dir.glob("*.png"), *self.catalog.cache_dir.glob("*_smart.json"), *self.catalog.cache_dir.glob("*_standard.json")):
            preview.unlink(missing_ok=True)
            removed += 1
        return removed

    def start_smart_generation(self, path: str) -> str:
        video = self.catalog.get_video(path)
        if not video or video["missing"] or video["archived"] or not Path(path).is_file():
            raise ValueError("Video non trovato o non disponibile.")
        with self.lock:
            if self.state["running"] or self.standard_running:
                raise RuntimeError("Attendi la fine dell’indicizzazione prima di rigenerare le anteprime.")
            if self.smart_job and self.smart_job["running"]:
                raise RuntimeError("È già in corso una rigenerazione smart.")
            job_id = uuid.uuid4().hex
            cancel_event = threading.Event()
            self.smart_cancel = cancel_event
            self.smart_job = {
                "jobId": job_id,
                "path": path,
                "running": True,
                "progress": 0,
                "message": "Preparazione analisi…",
                "status": "running",
            }
        threading.Thread(
            target=self._smart_worker,
            args=(path, job_id, cancel_event),
            daemon=True,
            name="smart-thumbnail-generator",
        ).start()
        return job_id

    def _smart_worker(self, path: str, job_id: str, cancel_event: threading.Event) -> None:
        prefix = preview_cache_key(path)
        temporary_dir = Path(tempfile.mkdtemp(prefix="lumen-smart-", dir=self.catalog.cache_dir))
        published: list[Path] = []

        def report(progress: int, message: str) -> None:
            with self.lock:
                if self.smart_job and self.smart_job["jobId"] == job_id:
                    self.smart_job.update(progress=progress, message=message)

        try:
            generated = SmartThumbnailGenerator().generate(path, temporary_dir, cancel_event, report)
            if cancel_event.is_set():
                raise AnalysisCancelledError("Analisi annullata.")
            if not generated:
                with self.lock:
                    self.smart_job.update(
                        running=False, progress=100,
                        message="Nessuna anteprima affidabile trovata; anteprime precedenti conservate.",
                        status="no_results",
                    )
                return

            previous = thumbnail_paths(self.catalog.cache_dir, path)
            previews = []
            for index, item in enumerate(generated):
                timestamp = float(item["timestamp"])
                filename = f"{prefix}_{index:04d}_{int(timestamp * 1000):012d}_smart_{job_id[:8]}.png"
                target = self.catalog.cache_dir / filename
                os.replace(item["thumbnailPath"], target)
                published.append(target)
                previews.append({
                    "index": index,
                    "frameIndex": int(item["frameIndex"]),
                    "time": timestamp,
                    "personId": item["personId"],
                    "eventType": item["eventType"],
                    "changeScore": float(item["changeScore"]),
                    "filename": filename,
                })
            if cancel_event.is_set():
                raise AnalysisCancelledError("Analisi annullata.")

            manifest = smart_manifest_path(self.catalog.cache_dir, path)
            staged_manifest = temporary_dir / "manifest.json"
            staged_manifest.write_text(json.dumps({"version": 1, "previews": previews}), encoding="utf-8")
            with self.lock:
                if cancel_event.is_set():
                    raise AnalysisCancelledError("Analisi annullata.")
                os.replace(staged_manifest, manifest)
                self.smart_job.update(
                    running=False, progress=100,
                    message=f"Completato: {len(previews)} anteprime smart.", status="completed",
                )
            published.clear()
            try:
                standard_manifest_path(self.catalog.cache_dir, path).unlink(missing_ok=True)
            except OSError:
                pass
            current_names = {item["filename"] for item in previews}
            for old_preview in previous:
                if old_preview.name not in current_names:
                    try:
                        old_preview.unlink(missing_ok=True)
                    except OSError:
                        pass
        except AnalysisCancelledError as error:
            for preview in published:
                preview.unlink(missing_ok=True)
            with self.lock:
                self.smart_job.update(running=False, message=str(error), status="cancelled")
        except Exception as error:
            for preview in published:
                preview.unlink(missing_ok=True)
            with self.lock:
                self.smart_job.update(
                    running=False,
                    message=f"Analisi smart non riuscita: {error}. Anteprime precedenti conservate.",
                    status="failed",
                )
        finally:
            shutil.rmtree(temporary_dir, ignore_errors=True)

    def smart_job_status(self, job_id: str) -> dict[str, object]:
        with self.lock:
            if not self.smart_job or self.smart_job["jobId"] != job_id:
                raise ValueError("Elaborazione smart non trovata.")
            return dict(self.smart_job)

    def cancel_smart_generation(self, job_id: str) -> None:
        with self.lock:
            if not self.smart_job or self.smart_job["jobId"] != job_id:
                raise ValueError("Elaborazione smart non trovata.")
            if self.smart_job["running"] and self.smart_cancel:
                self.smart_cancel.set()

    def regenerate_standard(self, path: str) -> list[dict[str, object]]:
        video = self.catalog.get_video(path)
        if not video or video["missing"] or video["archived"] or not Path(path).is_file():
            raise ValueError("Video non trovato o non disponibile.")
        with self.lock:
            if self.state["running"] or self.standard_running or self.smart_job and self.smart_job["running"]:
                raise RuntimeError("Attendi la fine dell’elaborazione in corso.")
            self.standard_running = True
        try:
            return regenerate_standard_previews(path, self.catalog.cache_dir)
        finally:
            with self.lock:
                self.standard_running = False

    def start_index(self, root_text: str, mode: str = "CPU") -> None:
        root = Path(root_text).expanduser().resolve()
        if not root.is_dir():
            raise ValueError("La cartella selezionata non esiste.")
        if cv2 is None:
            raise RuntimeError("OpenCV non è installato. Esegui: python -m pip install -r requirements.txt")
        with self.lock:
            if self.state["running"] or self.standard_running:
                raise RuntimeError("Un’indicizzazione è già in corso.")
            if self.smart_job and self.smart_job["running"]:
                raise RuntimeError("Attendi la fine della rigenerazione smart.")
            self.root = str(root)
            self.state.update(running=True, message="Scansione della cartella in corso…")
        use_gpu = mode == "GPU" and self.cuda_available
        threading.Thread(target=self._index_worker, args=(root, use_gpu), daemon=True).start()

    def _index_worker(self, root: Path, use_gpu: bool) -> None:
        root_text = str(root)
        previous = self.catalog.known_files(root_text)
        seen: set[str] = set()
        updated = failed = visited = 0
        for folder, _subfolders, filenames in os.walk(root):
            for filename in filenames:
                if Path(filename).suffix.casefold() not in VIDEO_EXTENSIONS:
                    continue
                path = Path(folder, filename).resolve()
                path_text = str(path)
                try:
                    stat = path.stat()
                    seen.add(path_text)
                    old = previous.get(path_text)
                    if old == (stat.st_size, stat.st_mtime) and thumbnail_paths(self.catalog.cache_dir, path_text):
                        continue
                    details = create_previews(path_text, self.catalog.cache_dir, use_gpu)
                    self.catalog.upsert_video({
                        "path": path_text,
                        "root": root_text,
                        "filename": path.name,
                        "file_size": stat.st_size,
                        "modified": stat.st_mtime,
                        **details,
                    })
                    updated += 1
                except Exception:
                    failed += 1
                finally:
                    visited += 1
                    if visited % 10 == 0:
                        with self.lock:
                            self.state["message"] = f"Scansione: {visited} video controllati"
        self.catalog.mark_missing(set(previous) - seen)
        with self.lock:
            self.state.update(
                running=False,
                updated=updated,
                failed=failed,
                removed=len(set(previous) - seen),
                message=f"Indice aggiornato · {updated} aggiornati · {len(set(previous) - seen)} rimossi · {failed} errori",
            )

    def video_items(self) -> list[dict[str, object]]:
        videos = self.catalog.list_videos(self.root)
        for video in videos:
            path = str(video["path"])
            images = thumbnail_paths(self.catalog.cache_dir, path)
            manifests = [
                manifest for manifest in (
                    smart_manifest_path(self.catalog.cache_dir, path),
                    standard_manifest_path(self.catalog.cache_dir, path),
                ) if manifest.is_file()
            ]
            manifest_path = max(manifests, key=lambda manifest: manifest.stat().st_mtime_ns) if manifests else None
            try:
                smart_previews = json.loads(manifest_path.read_text(encoding="utf-8"))["previews"] if manifest_path else None
                if not all((self.catalog.cache_dir / item["filename"]).is_file() for item in smart_previews):
                    raise ValueError("Manifest anteprime incompleto")
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                smart_previews = None
            if smart_previews is not None:
                video["thumbnails"] = []
                for item in smart_previews:
                    image_url = (
                        f"/api/thumbnail?path={quote(path, safe='')}&index={item['index']}"
                        f"&file={quote(item['filename'], safe='')}"
                        f"&v={int((self.catalog.cache_dir / item['filename']).stat().st_mtime_ns)}"
                    )
                    video["thumbnails"].append({
                        **{key: item[key] for key in ("frameIndex", "personId", "eventType", "changeScore") if key in item},
                        "index": item["index"],
                        "time": item["time"],
                        "timestamp": item["time"],
                        "url": image_url,
                        "imageUrl": image_url,
                    })
            else:
                video["thumbnails"] = [
                    {
                        "index": preview_index(image),
                        "time": preview_time(image),
                        "url": (
                            f"/api/thumbnail?path={quote(path, safe='')}&index={preview_index(image)}"
                            f"&v={image.stat().st_mtime_ns}"
                        ),
                    }
                    for image in images[:THUMBNAIL_COUNT]
                ]
        return videos

    def move_video_to_output(self, path: str, subfolder: str) -> str:
        with self.lock:
            if self.standard_running:
                raise RuntimeError("Attendi la fine della rigenerazione standard prima di spostare il video.")
            if self.smart_job and self.smart_job["running"] and self.smart_job["path"] == path:
                raise RuntimeError("Attendi la fine dell’analisi smart prima di spostare il video.")
        if subfolder not in self.output_folders:
            raise ValueError("Scegli una delle cartelle di output disponibili.")
        video = self.catalog.get_video(path)
        source = Path(path).resolve()
        if not video or video["missing"] or video["archived"] or not source.is_file():
            raise ValueError("Video non trovato o già archiviato.")
        destination_dir = Path(self.output_folders[subfolder]).resolve()
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / source.name
        if destination.exists():
            raise FileExistsError(f"Esiste già un file in {destination}.")
        old_prefix = preview_cache_key(path)
        new_path = shutil.move(str(source), str(destination))
        try:
            self.catalog.move_video(path, new_path)
        except Exception:
            shutil.move(new_path, str(source))
            raise
        new_prefix = preview_cache_key(new_path)
        for image in thumbnail_paths(self.catalog.cache_dir, path):
            try:
                image.rename(image.with_name(new_prefix + image.name[len(old_prefix):]))
            except OSError:
                pass
        for manifest_path in (smart_manifest_path, standard_manifest_path):
            old_manifest = manifest_path(self.catalog.cache_dir, path)
            new_manifest = manifest_path(self.catalog.cache_dir, new_path)
            if old_manifest.exists():
                try:
                    manifest = json.loads(old_manifest.read_text(encoding="utf-8"))
                    manifest["previews"] = [
                        {**item, "filename": item["filename"].replace(old_prefix, new_prefix, 1)}
                        for item in manifest["previews"]
                    ]
                    new_manifest.write_text(json.dumps(manifest), encoding="utf-8")
                    old_manifest.unlink(missing_ok=True)
                except (OSError, ValueError, KeyError, TypeError):
                    old_manifest.unlink(missing_ok=True)
        return new_path

    def delete_video(self, path: str, confirmed: bool = False) -> None:
        if not confirmed:
            raise ValueError("È necessaria la conferma per eliminare il video.")
        with self.lock:
            if self.standard_running:
                raise RuntimeError("Attendi la fine della rigenerazione standard prima di eliminare il video.")
            if self.smart_job and self.smart_job["running"] and self.smart_job["path"] == path:
                raise RuntimeError("Attendi la fine dell’analisi smart prima di rimuovere il video.")
        video = self.catalog.get_video(path)
        source = Path(path).resolve()
        if not video or video["missing"] or video["archived"] or not source.is_file():
            raise ValueError("Video non trovato o già archiviato.")
        if self.desktop_mode:
            try:
                from send2trash import send2trash
            except ImportError as error:
                raise RuntimeError("Per il cestino Windows installa desktop/requirements.txt.") from error
            send2trash(str(source))
        else:
            source.unlink()
        self.catalog.mark_removed(path)
        for preview in thumbnail_paths(self.catalog.cache_dir, path):
            preview.unlink(missing_ok=True)
        smart_manifest_path(self.catalog.cache_dir, path).unlink(missing_ok=True)
        standard_manifest_path(self.catalog.cache_dir, path).unlink(missing_ok=True)


class LocalWebServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, app: LocalWebApp):
        self.app = app
        super().__init__(address, LocalWebRequestHandler)


class LocalWebRequestHandler(http.server.BaseHTTPRequestHandler):
    server: LocalWebServer

    def log_message(self, _format: str, *args: object) -> None:
        return

    def send_json(self, data: object, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise ValueError("Richiesta troppo grande.")
        value = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(value, dict):
            raise ValueError("Corpo JSON non valido.")
        return value

    def do_GET(self) -> None:
        request = urlsplit(self.path)
        app = self.server.app
        if request.path == "/":
            try:
                body = Path(__file__).with_name("video_search_lite.html").read_bytes()
            except OSError:
                self.send_error(500, "Interfaccia lite non trovata")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif request.path == "/api/state":
            self.send_json(app.api_state())
        elif request.path == "/api/videos":
            videos = app.video_items()
            self.send_json({"videos": videos, "count": len(videos)})
        elif request.path == "/api/smart/status":
            job_id = parse_qs(request.query).get("job_id", [""])[0]
            try:
                self.send_json(app.smart_job_status(job_id))
            except ValueError as error:
                self.send_json({"error": str(error)}, 404)
        elif request.path == "/api/thumbnail":
            params = parse_qs(request.query)
            path = params.get("path", [""])[0]
            try:
                index = int(params.get("index", ["0"])[0])
                video = app.catalog.get_video(path)
                previews = thumbnail_paths(app.catalog.cache_dir, path) if video else []
                filename = Path(params.get("file", [""])[0]).name
                image = next(
                    (item for item in previews if item.name == filename), None
                ) if filename else next((item for item in previews if preview_index(item) == index), None)
                if image is None:
                    self.send_error(404)
                    return
                body = image.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(body)
            except (OSError, ValueError):
                self.send_error(404)
        elif request.path == "/api/video":
            path = parse_qs(request.query).get("path", [""])[0]
            video = app.catalog.get_video(path)
            file_path = Path(path)
            if not video or not file_path.is_file():
                self.send_error(404)
                return
            self.send_video(file_path)
        else:
            self.send_error(404)

    def send_video(self, path: Path) -> None:
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        range_header = self.headers.get("Range")
        if range_header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
            if not match or (not match.group(1) and not match.group(2)):
                self.send_error(416)
                return
            if match.group(1):
                start = int(match.group(1))
                end = min(int(match.group(2)), size - 1) if match.group(2) else size - 1
            else:
                start = max(0, size - int(match.group(2)))
            if start >= size or start > end:
                self.send_error(416)
                return
            status = 206
        length = max(0, end - start + 1)
        self.send_response(status)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        try:
            with path.open("rb") as file:
                file.seek(start)
                remaining = length
                while remaining:
                    chunk = file.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self) -> None:
        try:
            data = self.read_json()
            app = self.server.app
            if self.path == "/api/index":
                app.start_index(str(data.get("root", "")), str(data.get("mode", "CPU")))
                self.send_json({"ok": True}, 202)
            elif self.path == "/api/smart/start":
                job_id = app.start_smart_generation(str(data.get("path", "")))
                self.send_json({"ok": True, "jobId": job_id}, 202)
            elif self.path == "/api/smart/cancel":
                app.cancel_smart_generation(str(data.get("jobId", "")))
                self.send_json({"ok": True})
            elif self.path == "/api/previews/standard":
                previews = app.regenerate_standard(str(data.get("path", "")))
                self.send_json({"ok": True, "previews": previews})
            elif self.path == "/api/folder/pick":
                path = app.pick_folder(str(data.get("kind", "")), str(data.get("current", "")))
                self.send_json({"ok": True, "path": path})
            elif self.path == "/api/settings":
                result = app.save_settings(
                    str(data.get("input_root", "")),
                    data.get("output_folders", {}),
                )
                self.send_json({"ok": True, **result})
            elif self.path == "/api/cache/clear":
                self.send_json({"ok": True, "removed": app.clear_preview_cache()})
            elif self.path == "/api/move":
                destination = app.move_video_to_output(
                    str(data.get("path", "")), str(data.get("subfolder", ""))
                )
                self.send_json({"ok": True, "path": destination})
            elif self.path == "/api/delete":
                app.delete_video(str(data.get("path", "")), confirmed=bool(data.get("confirmed", False)))
                self.send_json({"ok": True})
            else:
                self.send_error(404)
        except (ValueError, TypeError, json.JSONDecodeError, OSError, RuntimeError) as error:
            self.send_json({"error": str(error)}, 400)


def main() -> int:
    host = os.environ.get("LUMEN_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("LUMEN_PORT", "8000"))
        app = LocalWebApp()
        server = LocalWebServer((host, port), app)
    except (OSError, ValueError) as error:
        print(f"Impossibile avviare {APP_NAME}: {error}", file=sys.stderr)
        return 1
    print(f"{APP_NAME} disponibile su http://{host}:{port} (Ctrl+C per terminare)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer arrestato.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())