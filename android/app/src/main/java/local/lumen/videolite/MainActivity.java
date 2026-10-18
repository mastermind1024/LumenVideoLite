package local.lumen.videolite;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ContentResolver;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.Typeface;
import android.media.MediaMetadataRetriever;
import android.net.Uri;
import android.os.Bundle;
import android.provider.DocumentsContract;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.HorizontalScrollView;
import android.widget.ImageButton;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import androidx.documentfile.provider.DocumentFile;
import androidx.media3.common.MediaItem;
import androidx.media3.common.PlaybackParameters;
import androidx.media3.common.Player;
import androidx.media3.ui.AspectRatioFrameLayout;
import androidx.media3.ui.PlayerView;
import androidx.media3.exoplayer.ExoPlayer;

import java.io.InputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private static final int PICK_VIDEO_FOLDER = 12;
    private static final int PICK_OUTPUT_TOP = 13;
    private static final int PICK_OUTPUT_MAIN = 14;
    private static final int PICK_OUTPUT_LINGER = 15;
    private static final int PREVIEW_COUNT = 5;
    private static final String PREFS = "lite_local";
    private static final String PREF_TREE = "video_tree_uri";
    private static final String PREF_TOP = "output_top";
    private static final String PREF_MAIN = "output_main";
    private static final String PREF_LINGER = "output_linger";
    private static final int GREEN = Color.rgb(40, 107, 84);
    private static final int INK = Color.rgb(32, 53, 47);
    private static final int MUTED = Color.rgb(113, 128, 122);
    private static final int PAPER = Color.rgb(255, 254, 250);

    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final List<VideoEntry> videos = new ArrayList<>();
    private final Map<String, Button> outputButtons = new HashMap<>();
    private DocumentFile videoRoot;
    private VideoEntry selectedVideo;
    private ExoPlayer player;
    private PlayerView playerView;
    private LinearLayout page;
    private LinearLayout videoList;
    private LinearLayout previewStrip;
    private TextView statusLabel;
    private TextView selectedTitle;
    private TextView selectedPath;
    private Spinner speedSpinner;
    private boolean syncingSpeed;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Color.rgb(244, 245, 239));
        getWindow().setNavigationBarColor(Color.rgb(244, 245, 239));
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        player = new ExoPlayer.Builder(this).build();
        player.addListener(new Player.Listener() {
            @Override
            public void onPlaybackParametersChanged(PlaybackParameters parameters) {
                syncSpeed(parameters.speed);
            }
        });
        buildScreen();
        restoreVideoFolder();
    }

    private void buildScreen() {
        ScrollView outer = new ScrollView(this);
        outer.setFillViewport(true);
        page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        page.setPadding(dp(15), dp(14), dp(15), dp(22));
        page.setBackgroundColor(Color.rgb(244, 245, 239));
        outer.addView(page, new ScrollView.LayoutParams(-1, -2));
        setContentView(outer);

        LinearLayout header = new LinearLayout(this);
        header.setGravity(Gravity.CENTER_VERTICAL);
        LinearLayout identity = new LinearLayout(this);
        identity.setOrientation(LinearLayout.VERTICAL);
        TextView brand = text("LUMEN / VIDEO LITE", 10, MUTED);
        brand.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        identity.addView(brand);
        TextView title = text("Raccolta video", 22, INK);
        title.setTypeface(Typeface.SERIF, Typeface.BOLD);
        identity.addView(title);
        header.addView(identity, new LinearLayout.LayoutParams(0, -2, 1));
        Button settings = button("Impostazioni");
        settings.setCompoundDrawablesWithIntrinsicBounds(android.R.drawable.ic_menu_preferences, 0, 0, 0);
        settings.setCompoundDrawablePadding(dp(5));
        settings.setOnClickListener(view -> showSettings());
        header.addView(settings);
        page.addView(header, spaced(-1, -2, 0, 0, 0, 10));

        statusLabel = text("Scegli la cartella input da Impostazioni", 11, MUTED);
        page.addView(statusLabel, spaced(-1, -2, 0, 0, 0, 9));

        TextView videosHeading = label("VIDEO");
        page.addView(videosHeading, spaced(-1, -2, 0, 4, 0, 6));
        ScrollView listScroll = new ScrollView(this);
        videoList = new LinearLayout(this);
        videoList.setOrientation(LinearLayout.VERTICAL);
        videoList.setBackgroundColor(PAPER);
        listScroll.addView(videoList);
        page.addView(listScroll, new LinearLayout.LayoutParams(-1, dp(174)));

        selectedTitle = text("Seleziona un video", 17, INK);
        selectedTitle.setTypeface(Typeface.SERIF, Typeface.BOLD);
        page.addView(selectedTitle, spaced(-1, -2, 0, 14, 0, 2));
        selectedPath = text("", 10, MUTED);
        selectedPath.setSingleLine(true);
        selectedPath.setEllipsize(TextUtils.TruncateAt.MIDDLE);
        page.addView(selectedPath, spaced(-1, -2, 0, 0, 0, 7));

        playerView = new PlayerView(this);
        playerView.setPlayer(player);
        playerView.setUseController(true);
        playerView.setControllerShowTimeoutMs(3500);
        playerView.setControllerHideOnTouch(true);
        playerView.setResizeMode(AspectRatioFrameLayout.RESIZE_MODE_FIT);
        playerView.setBackgroundColor(Color.rgb(23, 39, 34));
        int playerWidth = getResources().getDisplayMetrics().widthPixels - dp(30);
        int playerHeight = playerWidth * 9 / 16;
        page.addView(playerView, new LinearLayout.LayoutParams(-1, playerHeight));

        HorizontalScrollView previewsScroll = new HorizontalScrollView(this);
        previewsScroll.setHorizontalScrollBarEnabled(false);
        previewStrip = new LinearLayout(this);
        previewStrip.setGravity(Gravity.CENTER_VERTICAL);
        previewStrip.setOrientation(LinearLayout.HORIZONTAL);
        previewsScroll.addView(previewStrip);
        page.addView(previewsScroll, spaced(-1, dp(70), 0, 7, 0, 9));

        HorizontalScrollView controlsScroll = new HorizontalScrollView(this);
        controlsScroll.setHorizontalScrollBarEnabled(true);
        LinearLayout actionLine = new LinearLayout(this);
        actionLine.setGravity(Gravity.BOTTOM | Gravity.CENTER_VERTICAL);
        actionLine.setOrientation(LinearLayout.HORIZONTAL);
        buildSeekGroup(actionLine);
        buildSpeedGroup(actionLine);
        Button external = button("Apri player esterno");
        external.setOnClickListener(view -> openExternalPlayer());
        actionLine.addView(external, spaced(-2, dp(42), 0, 0, 8, 0));
        buildOutputGroup(actionLine);
        controlsScroll.addView(actionLine);
        page.addView(controlsScroll, spaced(-1, dp(66), 0, 8, 0, 9));
    }

    private void buildSeekGroup(LinearLayout parent) {
        LinearLayout group = new LinearLayout(this);
        group.setOrientation(LinearLayout.VERTICAL);
        group.addView(label("CONTROLLI"));
        LinearLayout buttons = new LinearLayout(this);
        addSeekButton(buttons, "◀ 1s", "Indietro di un secondo", -1000);
        addSeekButton(buttons, "1s ▶", "Avanti di un secondo", 1000);
        addSeekButton(buttons, "|◀", "Indietro di un fotogramma", -1);
        addSeekButton(buttons, "▶|", "Avanti di un fotogramma", 1);
        group.addView(buttons);
        parent.addView(group, spaced(-2, -2, 0, 0, 9, 0));
    }

    private void addSeekButton(LinearLayout parent, String title, String description, long delta) {
        Button button = button(title);
        button.setContentDescription(description);
        button.setMinWidth(dp(39));
        button.setPadding(dp(6), 0, dp(6), 0);
        button.setOnClickListener(view -> seek(delta));
        parent.addView(button, spaced(-2, dp(42), 0, 0, 4, 0));
    }

    private void buildSpeedGroup(LinearLayout parent) {
        LinearLayout group = new LinearLayout(this);
        group.setOrientation(LinearLayout.VERTICAL);
        group.addView(label("VELOCITÀ"));
        speedSpinner = new Spinner(this);
        String[] speeds = {"x1", "x3", "x4", "x5"};
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, speeds);
        speedSpinner.setAdapter(adapter);
        speedSpinner.setSelection(0);
        speedSpinner.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(android.widget.AdapterView<?> parentView, View view, int position, long id) {
                if (!syncingSpeed && player != null) {
                    float[] rates = {1f, 3f, 4f, 5f};
                    player.setPlaybackParameters(new PlaybackParameters(rates[position]));
                }
            }

            @Override
            public void onNothingSelected(android.widget.AdapterView<?> parentView) { }
        });
        group.addView(speedSpinner, new LinearLayout.LayoutParams(dp(72), dp(42)));
        parent.addView(group, spaced(-2, -2, 0, 0, 7, 0));
    }

    private void buildOutputGroup(LinearLayout parent) {
        LinearLayout group = new LinearLayout(this);
        group.setOrientation(LinearLayout.VERTICAL);
        group.addView(label("CARTELLE DI OUTPUT"));
        LinearLayout buttons = new LinearLayout(this);
        addOutputButton(buttons, "top", "1_Top");
        addOutputButton(buttons, "main", "2_Main");
        addOutputButton(buttons, "linger", "3_Linger");
        ImageButton delete = new ImageButton(this);
        delete.setImageResource(android.R.drawable.ic_menu_delete);
        delete.setColorFilter(Color.rgb(180, 35, 24));
        delete.setBackgroundResource(android.R.drawable.btn_default);
        delete.setContentDescription("Elimina definitivamente");
        delete.setOnClickListener(view -> confirmDelete());
        buttons.addView(delete, new LinearLayout.LayoutParams(dp(42), dp(42)));
        group.addView(buttons);
        parent.addView(group, spaced(-2, -2, 0, 0, 0, 0));
    }

    private void addOutputButton(LinearLayout parent, String key, String fallback) {
        String path = getPreferences(MODE_PRIVATE).getString(outputPreferenceKey(key), fallback);
        DocumentFile selected = path.startsWith("content:")
            ? DocumentFile.fromTreeUri(this, Uri.parse(path)) : null;
        String displayName = selected != null && selected.getName() != null ? selected.getName() : lastPathPart(path);
        Button button = button(displayName);
        button.setContentDescription("Sposta in " + displayName);
        button.setTextSize(10);
        button.setPadding(dp(7), 0, dp(7), 0);
        button.setOnClickListener(view -> moveToOutput(key));
        outputButtons.put(key, button);
        parent.addView(button, spaced(-2, dp(42), 0, 0, 4, 0));
    }

    private void showSettings() {
        SharedPreferences preferences = getPreferences(MODE_PRIVATE);
        ScrollView scroll = new ScrollView(this);
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(16), dp(8), dp(16), dp(10));
        scroll.addView(content);

        content.addView(label("CARTELLE INPUT"), spaced(-1, -2, 0, 0, 0, 5));
        TextView currentFolder = text(videoRoot == null ? "Nessuna cartella selezionata" : videoRoot.getName(), 12, INK);
        currentFolder.setSingleLine(true);
        currentFolder.setEllipsize(TextUtils.TruncateAt.MIDDLE);
        content.addView(currentFolder, spaced(-1, -2, 0, 0, 0, 6));

        final AlertDialog[] dialogHolder = new AlertDialog[1];
        Button chooseFolder = button("Scegli cartella input");
        chooseFolder.setOnClickListener(view -> {
            dialogHolder[0].dismiss();
            openVideoFolderPicker();
        });
        content.addView(chooseFolder, spaced(-1, -2, 0, 0, 0, 14));

        addOutputFolderPicker(content, dialogHolder, "top", "CARTELLA TOP", PICK_OUTPUT_TOP, "1_Top");
        addOutputFolderPicker(content, dialogHolder, "main", "CARTELLA MAIN", PICK_OUTPUT_MAIN, "2_Main");
        addOutputFolderPicker(content, dialogHolder, "linger", "CARTELLA LINGER", PICK_OUTPUT_LINGER, "3_Linger");

        Button clearCache = button("Svuota cache anteprime");
        clearCache.setOnClickListener(view -> confirmClearPreviewCache());
        content.addView(clearCache, spaced(-1, -2, 0, 4, 0, 0));

        AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle("Impostazioni")
                .setView(scroll)
                .setNegativeButton("Chiudi", null)
                .create();
        dialogHolder[0] = dialog;
        dialog.show();
    }

    private void addOutputFolderPicker(LinearLayout parent, AlertDialog[] dialogHolder,
            String key, String title, int requestCode, String fallback) {
        parent.addView(label(title), spaced(-1, -2, 0, 0, 0, 4));
        String selected = getPreferences(MODE_PRIVATE).getString(outputPreferenceKey(key), fallback);
        DocumentFile folder = selected.startsWith("content:")
                ? DocumentFile.fromTreeUri(this, Uri.parse(selected)) : null;
        TextView current = text(folder == null ? selected : folder.getName(), 12, INK);
        current.setSingleLine(true);
        current.setEllipsize(TextUtils.TruncateAt.MIDDLE);
        parent.addView(current, spaced(-1, -2, 0, 0, 0, 5));
        Button choose = button("Scegli cartella…");
        choose.setOnClickListener(view -> {
            dialogHolder[0].dismiss();
            openOutputFolderPicker(requestCode);
        });
        parent.addView(choose, spaced(-1, -2, 0, 0, 0, 10));
    }

    private void confirmClearPreviewCache() {
        new AlertDialog.Builder(this)
                .setTitle("Svuotare la cache?")
                .setMessage("Verranno eliminate solo le anteprime generate. I video non verranno modificati.")
                .setNegativeButton("Annulla", null)
                .setPositiveButton("Svuota cache", (dialog, which) -> worker.execute(() -> {
                    int removed = clearPreviewCacheFiles();
                    runOnUiThread(() -> {
                        Toast.makeText(this, removed + " anteprime eliminate", Toast.LENGTH_LONG).show();
                    });
                }))
                .show();
    }

    private int clearPreviewCacheFiles() {
        File directory = new File(getCacheDir(), "previews");
        File[] files = directory.listFiles();
        int removed = 0;
        if (files == null) return 0;
        for (File file : files) {
            if (file.isFile() && file.getName().endsWith(".png") && file.delete()) removed++;
        }
        return removed;
    }

    private String outputPreferenceKey(String key) {
        if ("top".equals(key)) return PREF_TOP;
        if ("main".equals(key)) return PREF_MAIN;
        return PREF_LINGER;
    }

    private String validateRelativePath(String value) {
        String path = value.trim().replace('\\', '/');
        if (path.isEmpty() || path.startsWith("/") || path.matches("^[A-Za-z]:.*")) {
            throw new IllegalArgumentException("Indica un percorso relativo alla cartella input.");
        }
        for (String part : path.split("/")) {
            if (part.isEmpty() || ".".equals(part) || "..".equals(part)) {
                throw new IllegalArgumentException("Il percorso non può contenere segmenti vuoti o '..'.");
            }
        }
        return path;
    }

    private String lastPathPart(String path) {
        int separator = path.lastIndexOf('/');
        return separator < 0 ? path : path.substring(separator + 1);
    }

    private void openVideoFolderPicker() {
        openDocumentTreePicker(PICK_VIDEO_FOLDER);
    }

    private void openOutputFolderPicker(int requestCode) {
        openDocumentTreePicker(requestCode);
    }

    private void openDocumentTreePicker(int requestCode) {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        startActivityForResult(intent, requestCode);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (resultCode != RESULT_OK || data == null || data.getData() == null) return;
        Uri uri = data.getData();
        int flags = data.getFlags() & (Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
        try {
            getContentResolver().takePersistableUriPermission(uri, flags);
        } catch (SecurityException ignored) {
            Toast.makeText(this, "Accesso temporaneo alla cartella", Toast.LENGTH_SHORT).show();
        }
        if (requestCode == PICK_VIDEO_FOLDER) {
            getPreferences(MODE_PRIVATE).edit().putString(PREF_TREE, uri.toString()).apply();
            videoRoot = DocumentFile.fromTreeUri(this, uri);
            statusLabel.setText("Cartella input: " + (videoRoot != null ? videoRoot.getName() : uri.getLastPathSegment()));
            scanVideoFolder();
            return;
        }
        String key = requestCode == PICK_OUTPUT_TOP ? "top"
            : requestCode == PICK_OUTPUT_MAIN ? "main"
            : requestCode == PICK_OUTPUT_LINGER ? "linger" : null;
        if (key == null) return;
        DocumentFile selectedFolder = DocumentFile.fromTreeUri(this, uri);
        if (selectedFolder == null || !selectedFolder.canWrite()) {
            Toast.makeText(this, "La cartella selezionata non consente la scrittura", Toast.LENGTH_LONG).show();
            return;
        }
        getPreferences(MODE_PRIVATE).edit().putString(outputPreferenceKey(key), uri.toString()).apply();
        Button outputButton = outputButtons.get(key);
        if (outputButton != null && selectedFolder.getName() != null) {
            outputButton.setText(selectedFolder.getName());
            outputButton.setContentDescription("Sposta in " + selectedFolder.getName());
        }
        Toast.makeText(this, "Cartella " + key.toUpperCase(Locale.ROOT) + " salvata", Toast.LENGTH_SHORT).show();
    }

    private void restoreVideoFolder() {
        SharedPreferences preferences = getPreferences(MODE_PRIVATE);
        String saved = preferences.getString(PREF_TREE, null);
        if (saved == null) return;
        try {
            Uri uri = Uri.parse(saved);
            videoRoot = DocumentFile.fromTreeUri(this, uri);
            if (videoRoot != null && videoRoot.canRead()) {
                statusLabel.setText("Cartella input: " + videoRoot.getName());
                scanVideoFolder();
            }
        } catch (RuntimeException error) {
            statusLabel.setText("Seleziona di nuovo la cartella video");
        }
    }

    private void scanVideoFolder() {
        if (videoRoot == null) return;
        statusLabel.setText("Scansione locale dei video…");
        worker.execute(() -> {
            List<VideoEntry> found = new ArrayList<>();
            collectVideos(videoRoot, found, "");
            Collections.sort(found, Comparator.comparing(item -> item.name.toLowerCase(Locale.ROOT)));
            runOnUiThread(() -> {
                videos.clear();
                videos.addAll(found);
                renderVideoList();
                statusLabel.setText(found.size() + " video nella cartella selezionata");
                if (!found.isEmpty()) selectVideo(found.get(0));
                else clearSelection();
            });
        });
    }

    private void collectVideos(DocumentFile folder, List<VideoEntry> result, String parentPath) {
        DocumentFile[] children = folder.listFiles();
        for (DocumentFile child : children) {
            String name = child.getName();
            if (name == null) continue;
            String relativePath = parentPath.isEmpty() ? name : parentPath + "/" + name;
            if (child.isDirectory()) {
                if (!isOutputDirectoryOrParent(relativePath)) collectVideos(child, result, relativePath);
            } else if (child.isFile() && isVideo(name) && !isInsideOutputFolder(relativePath)) {
                result.add(readVideoMetadata(child));
            }
        }
    }

    private boolean isOutputDirectoryOrParent(String relativePath) {
        for (String output : configuredOutputPaths()) {
            if (output.equals(relativePath) || output.startsWith(relativePath + "/")) return true;
        }
        return false;
    }

    private boolean isInsideOutputFolder(String relativePath) {
        for (String output : configuredOutputPaths()) {
            if (relativePath.equals(output) || relativePath.startsWith(output + "/")) return true;
        }
        return false;
    }

    private List<String> configuredOutputPaths() {
        SharedPreferences preferences = getPreferences(MODE_PRIVATE);
        List<String> paths = new ArrayList<>();
        for (String key : new String[]{"top", "main", "linger"}) {
            String selected = preferences.getString(outputPreferenceKey(key), defaultOutputPath(key));
            String relative = relativeOutputPath(selected);
            if (relative != null && !relative.isEmpty()) paths.add(relative);
        }
        return paths;
    }

    private String defaultOutputPath(String key) {
        if ("top".equals(key)) return "1_Top";
        if ("main".equals(key)) return "2_Main";
        return "3_Linger";
    }

    private String relativeOutputPath(String storedPath) {
        if (videoRoot == null) return null;
        if (!storedPath.startsWith("content:")) return storedPath;
        try {
            String rootId = DocumentsContract.getTreeDocumentId(videoRoot.getUri());
            String outputId = DocumentsContract.getTreeDocumentId(Uri.parse(storedPath));
            if (rootId.equals(outputId)) return "";
            String prefix = rootId + "/";
            if (outputId.startsWith(prefix)) return outputId.substring(prefix.length()).replace(':', '/');
        } catch (Exception ignored) { }
        return null;
    }

    private VideoEntry readVideoMetadata(DocumentFile file) {
        VideoEntry item = new VideoEntry(file);
        MediaMetadataRetriever retriever = new MediaMetadataRetriever();
        try {
            retriever.setDataSource(this, file.getUri());
            item.durationMs = parseLong(retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION));
            item.width = (int) parseLong(retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH));
            item.height = (int) parseLong(retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT));
            item.fps = parseFloat(retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_CAPTURE_FRAMERATE), 30f);
            if (item.fps <= 0) item.fps = 30f;
            File cacheDirectory = new File(getCacheDir(), "previews");
            if (!cacheDirectory.exists()) cacheDirectory.mkdirs();
            String cacheKey = previewCacheKey(file);
            for (int index = 0; index < PREVIEW_COUNT; index++) {
                long time = item.durationMs * (index + 1) / (PREVIEW_COUNT + 1);
                File cached = new File(cacheDirectory, cacheKey + "_" + index + ".png");
                Bitmap thumbnail = cached.isFile() ? BitmapFactory.decodeFile(cached.getAbsolutePath()) : null;
                if (thumbnail == null) {
                    Bitmap frame = retriever.getFrameAtTime(time * 1000, MediaMetadataRetriever.OPTION_CLOSEST_SYNC);
                    if (frame == null) continue;
                    int width = Math.min(180, frame.getWidth());
                    int height = Math.max(1, frame.getHeight() * width / frame.getWidth());
                    thumbnail = Bitmap.createScaledBitmap(frame, width, height, true);
                    if (thumbnail != frame) frame.recycle();
                    try (FileOutputStream output = new FileOutputStream(cached)) {
                        thumbnail.compress(Bitmap.CompressFormat.PNG, 100, output);
                    } catch (Exception ignored) {
                        cached.delete();
                    }
                }
                if (thumbnail != null) {
                    item.thumbnails.add(thumbnail);
                    item.previewTimesMs.add(time);
                }
            }
        } catch (Exception ignored) {
            item.durationMs = 0;
        } finally {
            try { retriever.release(); } catch (Exception ignored) { }
        }
        return item;
    }

    private void renderVideoList() {
        videoList.removeAllViews();
        for (VideoEntry item : videos) {
            TextView row = text(item.name + "\n" + formatDuration(item.durationMs)
                    + " · " + (item.width > 0 ? item.width + " × " + item.height : "Video"), 12, INK);
            row.setPadding(dp(11), dp(10), dp(8), dp(10));
            row.setBackgroundColor(item == selectedVideo ? Color.rgb(237, 244, 235) : PAPER);
            row.setOnClickListener(view -> selectVideo(item));
            videoList.addView(row, new LinearLayout.LayoutParams(-1, -2));
            View divider = new View(this);
            divider.setBackgroundColor(Color.rgb(233, 236, 230));
            videoList.addView(divider, new LinearLayout.LayoutParams(-1, dp(1)));
        }
        if (videos.isEmpty()) {
            TextView empty = text("Nessun video supportato trovato", 12, MUTED);
            empty.setPadding(dp(12), dp(18), dp(12), dp(18));
            videoList.addView(empty);
        }
    }

    private void selectVideo(VideoEntry item) {
        selectedVideo = item;
        selectedTitle.setText(item.name);
        selectedPath.setText(item.file.getUri().getPath());
        renderVideoList();
        previewStrip.removeAllViews();
        for (int index = 0; index < item.thumbnails.size(); index++) {
            final long time = item.previewTimesMs.get(index);
            ImageView image = new ImageView(this);
            image.setImageBitmap(item.thumbnails.get(index));
            image.setScaleType(ImageView.ScaleType.CENTER_CROP);
            image.setContentDescription("Anteprima a " + formatDuration(time));
            image.setOnClickListener(view -> {
                player.seekTo(time);
                player.pause();
            });
            previewStrip.addView(image, spaced(dp(112), dp(63), 0, 0, 6, 0));
        }
        player.setMediaItem(MediaItem.fromUri(item.file.getUri()));
        player.prepare();
        player.pause();
        playerView.hideController();
    }

    private void clearSelection() {
        selectedVideo = null;
        selectedTitle.setText("Seleziona un video");
        selectedPath.setText("");
        previewStrip.removeAllViews();
        player.clearMediaItems();
    }

    private void seek(long deltaMs) {
        if (selectedVideo == null) return;
        long delta = deltaMs == -1 ? Math.round(-1000f / selectedVideo.fps)
                : deltaMs == 1 ? Math.round(1000f / selectedVideo.fps) : deltaMs;
        long duration = player.getDuration();
        long next = Math.max(0, player.getCurrentPosition() + delta);
        if (duration > 0) next = Math.min(next, duration - 1);
        player.seekTo(next);
    }

    private void syncSpeed(float speed) {
        if (speedSpinner == null) return;
        int selected = Math.round(speed) == 3 ? 1 : Math.round(speed) == 4 ? 2 : Math.round(speed) == 5 ? 3 : 0;
        syncingSpeed = true;
        speedSpinner.setSelection(selected);
        syncingSpeed = false;
    }

    private void openExternalPlayer() {
        if (selectedVideo == null) return;
        Intent intent = new Intent(Intent.ACTION_VIEW);
        intent.setDataAndType(selectedVideo.file.getUri(), mimeType(selectedVideo.name));
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try {
            startActivity(intent);
        } catch (Exception error) {
            Toast.makeText(this, "Nessun player esterno disponibile", Toast.LENGTH_LONG).show();
        }
    }

    private void moveToOutput(String key) {
        if (selectedVideo == null || videoRoot == null) return;
        String preferenceKey = outputPreferenceKey(key);
        String fallback = defaultOutputPath(key);
        String selectedPath = getPreferences(MODE_PRIVATE).getString(preferenceKey, fallback);
        DocumentFile chosenFolder = selectedPath.startsWith("content:")
            ? DocumentFile.fromTreeUri(this, Uri.parse(selectedPath)) : null;
        String relativePath = chosenFolder != null && chosenFolder.getName() != null
            ? chosenFolder.getName() : selectedPath;
        VideoEntry item = selectedVideo;
        statusLabel.setText("Spostamento in " + relativePath + "…");
        worker.execute(() -> {
            try {
                DocumentFile destinationFolder = selectedPath.startsWith("content:")
                        ? DocumentFile.fromTreeUri(this, Uri.parse(selectedPath))
                        : findOrCreateRelativeDirectory(videoRoot, relativePath);
                if (destinationFolder == null || !destinationFolder.canWrite()) {
                    throw new IllegalStateException("Cartella di destinazione non accessibile");
                }
                DocumentFile destination = destinationFolder.createFile(mimeType(item.name), item.name);
                if (destination == null) throw new IllegalStateException("Impossibile creare il file di destinazione");
                try (InputStream input = getContentResolver().openInputStream(item.file.getUri());
                     OutputStream out = getContentResolver().openOutputStream(destination.getUri(), "w")) {
                    if (input == null || out == null) throw new IllegalStateException("Accesso al file non disponibile");
                    byte[] buffer = new byte[64 * 1024];
                    int count;
                    while ((count = input.read(buffer)) != -1) out.write(buffer, 0, count);
                    out.flush();
                } catch (Exception error) {
                    destination.delete();
                    throw error;
                }
                if (!item.file.delete()) {
                    destination.delete();
                    throw new IllegalStateException("Copia riuscita, ma il provider non ha permesso di rimuovere l’originale");
                }
                runOnUiThread(() -> {
                    Toast.makeText(this, "Spostato in " + relativePath, Toast.LENGTH_LONG).show();
                    scanVideoFolder();
                });
            } catch (Exception error) {
                runOnUiThread(() -> Toast.makeText(this, error.getMessage(), Toast.LENGTH_LONG).show());
            }
        });
    }

    private void confirmDelete() {
        if (selectedVideo == null) return;
        VideoEntry item = selectedVideo;
        new AlertDialog.Builder(this)
                .setTitle("Eliminazione definitiva")
            .setMessage("\"" + item.name + "\" verrà eliminato definitivamente e non sarà recuperabile.")
                .setNegativeButton("Annulla", null)
                .setPositiveButton("Elimina definitivamente", (dialog, which) -> worker.execute(() -> {
                    boolean deleted = item.file.delete();
                    runOnUiThread(() -> {
                        if (deleted) {
                            Toast.makeText(this, "Video eliminato definitivamente", Toast.LENGTH_LONG).show();
                            scanVideoFolder();
                        } else {
                            Toast.makeText(this, "Il provider non ha consentito l’eliminazione", Toast.LENGTH_LONG).show();
                        }
                    });
                }))
                .show();
    }

    private DocumentFile findOrCreateDirectory(DocumentFile parent, String name) {
        DocumentFile found = parent.findFile(name);
        if (found != null && found.isDirectory()) return found;
        DocumentFile created = parent.createDirectory(name);
        if (created == null) throw new IllegalStateException("Impossibile creare la cartella " + name);
        return created;
    }

    private DocumentFile findOrCreateRelativeDirectory(DocumentFile parent, String relativePath) {
        DocumentFile current = parent;
        for (String part : validateRelativePath(relativePath).split("/")) {
            current = findOrCreateDirectory(current, part);
        }
        return current;
    }

    private String previewCacheKey(DocumentFile file) {
        String identity = file.getUri().toString() + "|" + file.length() + "|" + file.lastModified();
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(identity.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            StringBuilder value = new StringBuilder();
            for (int index = 0; index < 12; index++) value.append(String.format(Locale.ROOT, "%02x", digest[index]));
            return value.toString();
        } catch (NoSuchAlgorithmException error) {
            return Integer.toHexString(identity.hashCode());
        }
    }

    private boolean isVideo(String name) {
        if (name == null) return false;
        String lower = name.toLowerCase(Locale.ROOT);
        return lower.endsWith(".avi") || lower.endsWith(".mkv") || lower.endsWith(".mov")
                || lower.endsWith(".mp4") || lower.endsWith(".m4v") || lower.endsWith(".webm")
                || lower.endsWith(".wmv") || lower.endsWith(".3gp");
    }

    private String mimeType(String name) {
        String lower = name.toLowerCase(Locale.ROOT);
        if (lower.endsWith(".mkv")) return "video/x-matroska";
        if (lower.endsWith(".webm")) return "video/webm";
        if (lower.endsWith(".mov")) return "video/quicktime";
        if (lower.endsWith(".avi")) return "video/x-msvideo";
        return "video/mp4";
    }

    private String formatDuration(long millis) {
        long seconds = Math.max(0, millis / 1000);
        return String.format(Locale.ROOT, "%02d:%02d:%02d", seconds / 3600, (seconds % 3600) / 60, seconds % 60);
    }

    private long parseLong(String value) {
        try { return value == null ? 0 : Long.parseLong(value); }
        catch (NumberFormatException ignored) { return 0; }
    }

    private float parseFloat(String value, float fallback) {
        try { return value == null ? fallback : Float.parseFloat(value); }
        catch (NumberFormatException ignored) { return fallback; }
    }

    private TextView text(String value, int sp, int color) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(sp);
        view.setTextColor(color);
        return view;
    }

    private TextView label(String value) {
        TextView view = text(value, 10, MUTED);
        view.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        view.setGravity(Gravity.CENTER_VERTICAL);
        return view;
    }

    private Button button(String value) {
        Button view = new Button(this);
        view.setText(value);
        view.setTextSize(11);
        view.setTextColor(INK);
        view.setMinHeight(dp(38));
        view.setPadding(dp(8), 0, dp(8), 0);
        return view;
    }

    private LinearLayout.LayoutParams spaced(int width, int height, int left, int top, int right, int bottom) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(width, height);
        params.setMargins(dp(left), dp(top), dp(right), dp(bottom));
        return params;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    @Override
    protected void onDestroy() {
        worker.shutdownNow();
        if (player != null) {
            player.release();
            player = null;
        }
        super.onDestroy();
    }

    private static final class VideoEntry {
        final DocumentFile file;
        final String name;
        final List<Bitmap> thumbnails = new ArrayList<>();
        final List<Long> previewTimesMs = new ArrayList<>();
        long durationMs;
        int width;
        int height;
        float fps = 30f;

        VideoEntry(DocumentFile file) {
            this.file = file;
            this.name = file.getName() == null ? "Video" : file.getName();
        }
    }
}