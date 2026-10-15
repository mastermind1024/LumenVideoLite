# Lumen Video Lite per Android

APK nativo, autonomo e offline. Non richiede il backend Python.

## Build

Requisiti: Java 21 e Android SDK 36. Dalla root del repository:

```bash
ANDROID_HOME="$HOME/Android/Sdk" ANDROID_SDK_ROOT="$HOME/Android/Sdk" ./android/gradlew -p android assembleDebug
```

APK: `android/app/build/outputs/apk/debug/app-debug.apk`.

## Uso locale

Apri **Impostazioni** per scegliere una cartella dal selettore documenti Android, configurare i percorsi TOPLESS/NUDE/LINGERIE e svuotare la cache anteprime. L’app mantiene il permesso alla cartella sul dispositivo, crea cinque anteprime per video, riproduce con i controlli Media3 e usa il decoder hardware del telefono quando disponibile. Le cartelle output vengono create all’interno della cartella selezionata.

La cancellazione usa l’API del provider documenti. Quando il provider non espone un cestino, l’app avvisa che l’operazione è definitiva e chiede conferma prima di eliminare il file.