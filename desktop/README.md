# Lumen Video Lite per Windows

Il launcher Tk avvia il server locale, apre la webapp nel browser predefinito e fornisce i selettori nativi per le cartelle input/output. Solo questa modalità usa Send2Trash per il cestino di Windows.

## Build EXE

La build va eseguita su Windows x64 con Python 3.12 installato. Dalla cartella `desktop/` avvia `build_windows.bat`; il file risultante sarà `desktop/dist/LumenVideoLite.exe`. Lo script crea un virtualenv dedicato e non modifica le dipendenze o l'ambiente delle versioni web/Android.

La build non è stata eseguita in questo workspace Linux. Per ridurre tempo, spazio e dipendenze condivise, la versione desktop riusa la webapp Python esistente; non converte il player né duplica il backend.
