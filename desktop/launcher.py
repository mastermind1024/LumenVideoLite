import os
import sys
import threading
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))
os.environ["LUMEN_DESKTOP"] = "1"

from video_search_lite import LocalWebApp, LocalWebServer


def main() -> None:
    app = LocalWebApp()
    server = None
    last_error = None
    for port in range(8000, 8021):
        try:
            server = LocalWebServer(("127.0.0.1", port), app)
            break
        except OSError as error:
            last_error = error
    if server is None:
        raise RuntimeError(f"Nessuna porta locale disponibile: {last_error}")

    address = f"http://127.0.0.1:{server.server_address[1]}"
    threading.Thread(target=server.serve_forever, daemon=True, name="lumen-http").start()

    window = tk.Tk()
    window.title("Lumen Video Lite")
    window.geometry("360x150")
    window.resizable(False, False)
    tk.Label(window, text="Lumen Video Lite è in esecuzione", font=("Segoe UI", 12, "bold")).pack(pady=(20, 8))
    tk.Label(window, text=address, font=("Segoe UI", 10)).pack(pady=2)
    actions = tk.Frame(window)
    actions.pack(pady=14)
    tk.Button(actions, text="Apri applicazione", command=lambda: webbrowser.open(address)).pack(side=tk.LEFT, padx=5)

    def pick_folder(kind: str, current: str) -> str:
        selected = []
        completed = threading.Event()

        def show_dialog() -> None:
            chosen = filedialog.askdirectory(
                parent=window,
                title="Seleziona cartella video" if kind == "input" else "Seleziona cartella di destinazione",
                initialdir=current if Path(current).is_dir() else str(Path.home()),
                mustexist=True,
            )
            selected.append(chosen)
            completed.set()

        window.after(0, show_dialog)
        completed.wait()
        return selected[0]

    app.folder_picker = pick_folder

    def close() -> None:
        if messagebox.askyesno("Chiudi Lumen Video Lite", "Arrestare il server locale?"):
            server.shutdown()
            server.server_close()
            window.destroy()

    tk.Button(actions, text="Esci", command=close).pack(side=tk.LEFT, padx=5)
    window.protocol("WM_DELETE_WINDOW", close)
    window.after(500, lambda: webbrowser.open(address))
    window.mainloop()


if __name__ == "__main__":
    main()
