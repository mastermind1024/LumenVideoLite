# Lumen Video Lite per Android

APK nativo, autonomo e offline. Non richiede il backend Python.

## Build

Requisiti: Java 21 e Android SDK 36. Dalla root del repository:

```bash
ANDROID_HOME="$HOME/Android/Sdk" ANDROID_SDK_ROOT="$HOME/Android/Sdk" ./android/gradlew -p android assembleDebug
```

APK: `android/app/build/outputs/apk/debug/app-debug.apk`.

## Uso locale

Apri **Impostazioni** per scegliere input e cartelle di destinazione con il selettore documenti Android. I permessi alle cartelle selezionate vengono mantenuti sul dispositivo. Le destinazioni iniziali sono `1_Top`, `2_Main` e `3_Linger`; l’app genera cinque anteprime standard e riproduce con i controlli Media3, usando il decoder hardware quando disponibile.

L’eliminazione è sempre definitiva: l’app chiede conferma prima di rimuovere il video tramite il provider documenti. Non è previsto l’invio al cestino.