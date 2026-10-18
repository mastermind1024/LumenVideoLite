# Lumen Video Lite

Applicazione web locale per sfogliare e rivedere video. Mantiene un catalogo SQLite incrementale e una cache locale con cinque anteprime interne per video.

## Avvio

```bash
python -m pip install -r requirements.txt
python video_search_lite.py
```

Apri [http://localhost:8000](http://localhost:8000) nel browser. In un container o Codespace, inoltra la porta 8000 dalla scheda **Ports** e apri l'indirizzo locale mostrato da VS Code. Il server ascolta solo su localhost; usa `LUMEN_PORT` per scegliere un'altra porta e `LUMEN_HOST` solo se serve un'interfaccia di rete diversa. Arresta il server con **Ctrl+C**.

Apri **Impostazioni** per scegliere **CARTELLE INPUT** e avviare **Indicizza / aggiorna**. Le scansioni successive elaborano solo file nuovi o modificati. Nelle stesse impostazioni puoi modificare i percorsi di tre cartelle rapide e svuotare la cache delle anteprime. La lista mostra i video della cartella selezionata; il player include cinque anteprime cliccabili, controlli nativi a scomparsa, avanzamento per secondo o fotogramma e velocità x1, x3, x4 e x5. Puoi aprire il video nel player di sistema, spostarlo in una cartella di output oppure inviarlo al cestino con conferma.
Sotto il player puoi usare **Rigenera anteprime smart** per analizzare solo il video selezionato. L’analisi gira in un singolo thread Python, mostra l’avanzamento e può essere annullata. Le anteprime correnti restano attive se l’analisi viene annullata, fallisce o non trova eventi affidabili. Il generatore standard durante l’indicizzazione resta il fallback.

I parametri di campionamento e selezione sono configurabili in `SmartThumbnailGenerator` in `smart_thumbnail_generator.py`: `SAMPLE_INTERVAL` (0,25 s), `REFINE_INTERVAL` (0,08 s), `FRAME_WIDTH`, `GRID_SIZE`, le soglie di cambiamento/conferma e `MAX_PREVIEWS`. L’analisi combina HOG, foreground della camera fissa, compensazione delle variazioni luminose e descrittori colore/contorni del torso. Non usa modelli neurali aggiuntivi: pose molto occluse o soggetti quasi indistinguibili dallo sfondo possono ancora richiedere verifica sui video reali.

La modalità GPU compare solo quando OpenCV rileva un decoder CUDA disponibile; altrimenti l’indicizzazione usa CPU senza mostrare una combobox. Le dipendenze Python dirette sono OpenCV e Send2Trash.

Su Windows il cestino usa il Cestino di sistema. Su Android l’app prova Termux:API tramite `termux-trash`; se il cestino non è disponibile, mostra un secondo avviso e richiede conferma esplicita prima di cancellare definitivamente il file.

## APK Android autonomo

Il progetto nativo è in `android/`. Non avvia né richiede il server Python: seleziona la cartella video da **Impostazioni**, genera le anteprime sul telefono e riproduce con Media3. Il player usa proporzioni 16:9. Input, cache e percorsi delle tre cartelle output si configurano dalle impostazioni; le destinazioni vengono create dentro la cartella selezionata. Il selettore documenti non offre un cestino generico, quindi l’APK avvisa e chiede conferma prima dell’eliminazione definitiva.

Con Java 21 e Android SDK 36 installati, compila dalla root del repository:

```bash
ANDROID_HOME="$HOME/Android/Sdk" ANDROID_SDK_ROOT="$HOME/Android/Sdk" ./android/gradlew -p android assembleDebug
```

L’APK installabile è `android/app/build/outputs/apk/debug/app-debug.apk`. Richiede Android 8.0 (API 26) o successivo. Per l’installazione via ADB: `adb install -r android/app/build/outputs/apk/debug/app-debug.apk`.
