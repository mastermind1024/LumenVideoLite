# Lumen Video Lite

Applicazione web locale per sfogliare e rivedere video. Mantiene un catalogo SQLite incrementale e una cache locale con cinque anteprime interne per video.

## Avvio

```bash
python -m pip install -r requirements.txt
python video_search_lite.py
```

Apri [http://localhost:8000](http://localhost:8000) nel browser. In un container o Codespace, inoltra la porta 8000 dalla scheda **Ports** e apri l'indirizzo locale mostrato da VS Code. Il server ascolta solo su localhost; usa `LUMEN_PORT` per scegliere un'altra porta e `LUMEN_HOST` solo se serve un'interfaccia di rete diversa. Arresta il server con **Ctrl+C**.

Apri **Impostazioni** per scegliere **CARTELLE INPUT** e avviare **Indicizza / aggiorna**. Le scansioni successive elaborano solo file nuovi o modificati. Nelle stesse impostazioni puoi modificare i percorsi di tre cartelle rapide e svuotare la cache delle anteprime. La lista mostra i video della cartella selezionata; il player include cinque anteprime cliccabili, controlli nativi a scomparsa, avanzamento per secondo o fotogramma e velocità x1, x3, x4 e x5. Puoi aprire il video nel player di sistema, spostarlo in una cartella di output oppure inviarlo al cestino con conferma.
La versione web usa percorsi assoluti modificabili per input e output, indicizzazione incrementale e cache locale. Le destinazioni predefinite sono `media_output/1_Top`, `media_output/2_Main` e `media_output/3_Linger`. Puoi rigenerare le cinque anteprime standard ai timestamp 1/6, 2/6, …, 5/6 della durata o avviare l’analisi smart; entrambe le rigenerazioni conservano la collezione precedente se falliscono. I toggle nella pagina controllano layout delle miniature e visibilità della lista video. La cancellazione web è definitiva e richiede conferma.

Sotto il player, **Rigenera anteprime smart** avvia un solo job Python in background, mostra l’avanzamento ed è annullabile. **Rigenera anteprime standard** ricrea le cinque anteprime ai timestamp standard. Il generatore standard usato dall’indicizzazione resta disponibile come fallback.

I parametri di analisi smart sono configurabili in `SmartThumbnailGenerator` in `smart_thumbnail_generator.py`. Il servizio combina HOG, foreground della camera fissa, compensazione luminosa e descrittori del torso; scene molto occluse vanno verificate sui video reali.


La modalità GPU compare solo quando OpenCV rileva un decoder CUDA disponibile; altrimenti l’indicizzazione usa CPU. Il backend web richiede OpenCV; Send2Trash è dipendenza esclusiva del launcher Windows.

## EXE Windows

La cartella `desktop/` contiene un launcher Tk leggero che avvia la webapp locale e abilita i selettori nativi delle cartelle. Sul PC Windows, con Python 3.12 x64, apri `desktop/` ed esegui `build_windows.bat`; il file prodotto sarà `desktop/dist/LumenVideoLite.exe`. Lo script crea un virtualenv dedicato e non modifica l’ambiente Python web. La build EXE non è stata eseguita in questo workspace Linux.

## APK Android autonomo

Il progetto nativo è in `android/`. Non avvia né richiede il server Python: seleziona input e destinazioni con il selettore documenti, genera anteprime sul telefono e riproduce con Media3. Input e output usano permessi URI persistenti; l’eliminazione è definitiva e chiede conferma.

Con Java 21 e Android SDK 36 installati, compila dalla root del repository:

```bash
ANDROID_HOME="$HOME/Android/Sdk" ANDROID_SDK_ROOT="$HOME/Android/Sdk" ./android/gradlew -p android assembleDebug
```

L’APK installabile è `android/app/build/outputs/apk/debug/app-debug.apk`. Richiede Android 8.0 (API 26) o successivo. Per l’installazione via ADB: `adb install -r android/app/build/outputs/apk/debug/app-debug.apk`.

## Struttura condivisa

Web e Windows riusano HTML, API e backend Python; il launcher Windows aggiunge solo picker nativi e cestino di sistema. Android resta un client nativo autonomo con Media3 e selettori SAF. Le build rimangono separate e si eseguono soltanto su richiesta: questo evita conversioni duplicate, mantiene dipendenze specifiche per target e non genera APK/EXE durante lo sviluppo web.
