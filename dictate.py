"""Diktierfunktion mit GUI-Dialog.

Ctrl+Alt+D startet/stoppt Aufnahme. Transkription wird in einem
editierbaren Dialog angezeigt und kann in die Zwischenablage kopiert werden.
Mehrere Aufnahmen werden im selben Dialog aneinandergehängt.

Funktioniert ohne Admin-Rechte.
"""

import os
import sys
import platform
import threading
import tempfile
from pathlib import Path

import tkinter as tk
import numpy as np
import sounddevice as sd
from scipy.io import wavfile
from pynput import keyboard

# -- Konfiguration --
HOTKEY_KEYS = keyboard.HotKey.parse("<ctrl>+<alt>+d")
HOTKEY_LABEL = "Ctrl+Alt+D"
MODEL_SIZE = "medium"  # tiny, base, small, medium, large-v3
LANGUAGE = "de"         # None für auto-detect
SAMPLE_RATE = 16000
DIALOG_WIDTH = 650
DIALOG_HEIGHT = 340

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"

# Plattformunabhängige Schriftarten
FONT_FAMILY = "Segoe UI" if IS_WINDOWS else "Sans"
FONT_NORMAL = (FONT_FAMILY, 11)
FONT_BTN = (FONT_FAMILY, 10)
FONT_BTN_BOLD = (FONT_FAMILY, 10, "bold")
FONT_STATUS = (FONT_FAMILY, 9)
FONT_STATUS_BOLD = (FONT_FAMILY, 9, "bold")


class DictateApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.withdraw()
        self.root.title("Whisper Dictate")

        self.recording = False
        self.transcribing = False
        self.audio_chunks: list = []
        self.stream = None
        self.model = None
        self.model_loaded = False
        self.dialog: tk.Toplevel | None = None
        self._pulse_step = 0

        # GUI-Widget-Referenzen
        self.result_text: tk.Text | None = None
        self.status_bar: tk.Label | None = None
        self.stop_btn: tk.Button | None = None
        self.record_btn: tk.Button | None = None
        self.copy_btn: tk.Button | None = None
        self.cancel_btn: tk.Button | None = None

        # Modell im Hintergrund laden
        threading.Thread(target=self._load_model, daemon=True).start()

        # Hotkey-Listener starten
        self._start_hotkey_listener()

    def _load_model(self):
        from faster_whisper import WhisperModel
        self.model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
        self.model_loaded = True

    def _start_hotkey_listener(self):
        hotkey = keyboard.HotKey(HOTKEY_KEYS, self._on_hotkey)

        def on_press(key):
            hotkey.press(self._listener.canonical(key))

        def on_release(key):
            hotkey.release(self._listener.canonical(key))

        self._listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._listener.daemon = True
        self._listener.start()

    def _on_hotkey(self):
        self.root.after(0, self._toggle_recording)

    def _toggle_recording(self):
        if self.transcribing:
            return  # Während Transkription keine Aktion
        if not self.recording:
            self._start_recording()
        else:
            self._stop_recording()

    # -- Dialog --

    def _ensure_dialog(self):
        """Dialog erstellen falls noch nicht offen."""
        if self.dialog and self.dialog.winfo_exists():
            return

        self.dialog = tk.Toplevel(self.root)
        self.dialog.title("Whisper Dictate")
        self.dialog.attributes("-topmost", True)
        self.dialog.resizable(True, True)
        self.dialog.protocol("WM_DELETE_WINDOW", self._close_dialog)
        self.dialog.minsize(DIALOG_WIDTH, DIALOG_HEIGHT)

        # Zentrieren
        screen_w = self.dialog.winfo_screenwidth()
        screen_h = self.dialog.winfo_screenheight()
        x = (screen_w - DIALOG_WIDTH) // 2
        y = (screen_h - DIALOG_HEIGHT) // 2
        self.dialog.geometry(f"{DIALOG_WIDTH}x{DIALOG_HEIGHT}+{x}+{y}")

        main_frame = tk.Frame(self.dialog, padx=15, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Grid-Layout: Textfeld expandiert, Buttons und Status bleiben sichtbar
        main_frame.rowconfigure(0, weight=1)  # Textfeld bekommt übrigen Platz
        main_frame.rowconfigure(1, weight=0)  # Buttons feste Höhe
        main_frame.rowconfigure(2, weight=0)  # Statusleiste feste Höhe
        main_frame.columnconfigure(0, weight=1)

        # Editierbares Textfeld
        self.result_text = tk.Text(
            main_frame, font=FONT_NORMAL, wrap=tk.WORD, padx=5, pady=5
        )
        self.result_text.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        self.result_text.mark_set(tk.INSERT, tk.END)

        # Button-Leiste
        btn_frame = tk.Frame(main_frame)
        btn_frame.grid(row=1, column=0, sticky="ew", pady=(0, 6))

        # Aufnahme stoppen (links)
        self.stop_btn = tk.Button(
            btn_frame,
            text="Aufnahme stoppen",
            command=self._stop_recording,
            font=FONT_BTN,
            bg="#f8d7da",
            fg="#721c24",
            disabledforeground="#bbb",
            padx=12,
            pady=5,
            cursor="hand2",
        )
        self.stop_btn.pack(side=tk.LEFT)

        # Neue Aufnahme
        self.record_btn = tk.Button(
            btn_frame,
            text="Neue Aufnahme",
            command=self._start_recording,
            font=FONT_BTN,
            bg="#d4edda",
            fg="#155724",
            padx=12,
            pady=5,
            cursor="hand2",
        )
        self.record_btn.pack(side=tk.LEFT, padx=(8, 0))

        # Kopieren & Schliessen (rechts)
        self.copy_btn = tk.Button(
            btn_frame,
            text="Kopieren & Schliessen",
            command=self._copy_and_close,
            font=FONT_BTN_BOLD,
            bg="#cce5ff",
            fg="#004085",
            padx=12,
            pady=5,
            cursor="hand2",
        )
        self.copy_btn.pack(side=tk.RIGHT)

        # Abbrechen
        self.cancel_btn = tk.Button(
            btn_frame,
            text="Abbrechen",
            command=self._close_dialog,
            font=FONT_BTN,
            padx=10,
            pady=5,
            cursor="hand2",
        )
        self.cancel_btn.pack(side=tk.RIGHT, padx=(0, 8))

        # Statusleiste (ganz unten)
        self.status_bar = tk.Label(
            main_frame,
            text="Bereit",
            font=FONT_STATUS,
            fg="#888",
            anchor=tk.W,
            relief=tk.SUNKEN,
            padx=6,
            pady=2,
        )
        self.status_bar.grid(row=2, column=0, sticky="ew")

        # Shortcuts
        self.dialog.bind("<Escape>", lambda e: self._close_dialog())
        self.dialog.bind("<Control-Return>", lambda e: self._copy_and_close())

    def _update_button_states(self):
        """Buttons je nach Zustand aktivieren/deaktivieren."""
        if not self.dialog or not self.dialog.winfo_exists():
            return

        if self.recording:
            self.stop_btn.config(state=tk.NORMAL)
            self.record_btn.config(state=tk.DISABLED)
            self.copy_btn.config(state=tk.DISABLED)
            self.cancel_btn.config(state=tk.NORMAL)
        elif self.transcribing:
            self.stop_btn.config(state=tk.DISABLED)
            self.record_btn.config(state=tk.DISABLED)
            self.copy_btn.config(state=tk.DISABLED)
            self.cancel_btn.config(state=tk.DISABLED)
        else:
            self.stop_btn.config(state=tk.DISABLED)
            self.record_btn.config(state=tk.NORMAL)
            self.copy_btn.config(state=tk.NORMAL)
            self.cancel_btn.config(state=tk.NORMAL)

    def _set_status(self, text: str, fg: str = "#888", bold: bool = False):
        """Statusleiste aktualisieren."""
        if not self.dialog or not self.dialog.winfo_exists():
            return
        font = FONT_STATUS_BOLD if bold else FONT_STATUS
        self.status_bar.config(text=text, fg=fg, font=font)

    # -- Recording --

    def _start_recording(self):
        if not self.model_loaded:
            self._ensure_dialog()
            self._set_status("Modell wird geladen, bitte warten...")
            self._update_button_states()
            self._wait_for_model()
            return

        self._ensure_dialog()

        self.audio_chunks = []
        self.recording = True
        self._pulse_step = 0

        self._record_thread = threading.Thread(target=self._record_loop, daemon=True)
        self._record_thread.start()

        self._set_status("Aufnahme...", fg="#cc0000", bold=True)
        self._update_button_states()
        self._pulse()
        self.dialog.focus_force()

    def _wait_for_model(self):
        if not self.dialog or not self.dialog.winfo_exists():
            return
        if self.model_loaded:
            self._start_recording()
        else:
            self.root.after(500, self._wait_for_model)

    def _record_loop(self):
        """Blockierende Aufnahme in eigenem Thread."""
        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32") as stream:
                while self.recording:
                    data, overflowed = stream.read(int(SAMPLE_RATE * 0.1))  # 100ms Blöcke
                    self.audio_chunks.append(data.copy())
        except Exception:
            pass

    def _stop_recording(self):
        if not self.recording:
            return
        self.recording = False
        # Warten bis Record-Thread fertig, dann transkribieren
        self._set_status("Aufnahme wird beendet...", fg="#e68a00")
        threading.Thread(target=self._finish_recording, daemon=True).start()

    def _finish_recording(self):
        # Warten bis der Record-Thread sich beendet hat
        if hasattr(self, '_record_thread') and self._record_thread.is_alive():
            self._record_thread.join(timeout=2.0)

        if not self.audio_chunks:
            self.root.after(0, self._no_audio)
            return

        self.root.after(0, self._start_transcription)

    def _no_audio(self):
        self.transcribing = False
        self._set_status("Keine Audiodaten.")
        self._update_button_states()

    def _start_transcription(self):
        self.transcribing = True
        self._set_status("Transkribiere...", fg="#e68a00", bold=True)
        self._update_button_states()
        threading.Thread(target=self._transcribe, daemon=True).start()

    def _transcribe(self):
        try:
            audio = np.concatenate(self.audio_chunks, axis=0)
            audio_int16 = (audio * 32767).astype(np.int16)

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_path = f.name
                wavfile.write(tmp_path, SAMPLE_RATE, audio_int16)

            segments, info = self.model.transcribe(
                tmp_path, language=LANGUAGE, beam_size=5
            )
            text = " ".join(seg.text.strip() for seg in segments)

            Path(tmp_path).unlink(missing_ok=True)

            self.root.after(0, self._append_result, text)
        except Exception as e:
            self.root.after(0, self._append_result, f"[Fehler: {e}]")

    def _append_result(self, text: str):
        self.transcribing = False

        if not self.dialog or not self.dialog.winfo_exists():
            return

        if text and text.strip():
            # Text an aktueller Cursor-Position einfügen
            cursor_pos = self.result_text.index(tk.INSERT)
            # Prüfen ob vor dem Cursor schon Text steht -> Leerzeichen einfügen
            if cursor_pos != "1.0":
                char_before = self.result_text.get(f"{cursor_pos} -1c", cursor_pos)
                if char_before and not char_before.isspace():
                    self.result_text.insert(tk.INSERT, " ")
            self.result_text.insert(tk.INSERT, text.strip())

        self._set_status(
            f"Fertig. {HOTKEY_LABEL} oder 'Neue Aufnahme' fuer weiteres Diktat.",
            fg="#228b22",
        )
        self._update_button_states()
        self.result_text.focus_set()

    # -- Pulse Animation --

    def _pulse(self):
        if not self.recording or not self.dialog or not self.dialog.winfo_exists():
            return
        dots = "." * ((self._pulse_step % 3) + 1)
        self._set_status(f"Aufnahme{dots}", fg="#cc0000", bold=True)
        self._pulse_step += 1
        self.dialog.after(500, self._pulse)

    # -- Actions --

    def _copy_and_close(self):
        if self.result_text:
            text = self.result_text.get("1.0", tk.END).strip()
            if text:
                self.root.clipboard_clear()
                self.root.clipboard_append(text)
        self._close_dialog()

    def _close_dialog(self):
        # Laufende Aufnahme stoppen
        self.recording = False
        self.audio_chunks = []
        if self.dialog:
            self.dialog.destroy()
            self.dialog = None


# -- Autostart --

def _get_autostart_path() -> Path:
    """Plattformspezifischen Autostart-Pfad ermitteln."""
    if IS_WINDOWS:
        return (
            Path(os.environ["APPDATA"])
            / r"Microsoft\Windows\Start Menu\Programs\Startup"
            / "whisper-dictate.vbs"
        )
    if IS_LINUX:
        return (
            Path.home() / ".config" / "autostart" / "whisper-dictate.desktop"
        )
    raise RuntimeError(f"Autostart nicht unterstützt auf {platform.system()}")


def install_autostart():
    script = Path(__file__).resolve()
    project_dir = script.parent
    target = _get_autostart_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    if IS_WINDOWS:
        content = (
            'Set WshShell = CreateObject("WScript.Shell")\n'
            f'WshShell.CurrentDirectory = "{project_dir}"\n'
            f'WshShell.Run "uv run pythonw ""{script}""", 0, False\n'
        )
    elif IS_LINUX:
        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=WhisperDictate\n"
            "Comment=Diktierfunktion mit Whisper\n"
            f"Exec=uv run {script}\n"
            f"Path={project_dir}\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n"
        )
    else:
        raise RuntimeError(f"Autostart nicht unterstützt auf {platform.system()}")

    target.write_text(content, encoding="utf-8")
    print(f"Autostart installiert: {target}")


def remove_autostart():
    target = _get_autostart_path()
    if target.exists():
        target.unlink()
        print(f"Autostart entfernt: {target}")
    else:
        print("Autostart war nicht installiert.")


def main():
    if "--install-autostart" in sys.argv:
        install_autostart()
        return
    if "--remove-autostart" in sys.argv:
        remove_autostart()
        return

    root = tk.Tk()
    DictateApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
