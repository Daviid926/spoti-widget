import asyncio
import io
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, colorchooser
from datetime import datetime, timezone
from PIL import Image, ImageTk
from winsdk.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as MediaManager,
    GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
)
from winsdk.windows.storage.streams import Buffer, DataReader, InputStreamOptions

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(HERE, "nowplaying_config.json")
POLL_S = 1.0

THEMES = {
    "Oscuro":    {"bg": "#1e1e1e", "fg": "#ffffff", "sub": "#b3b3b3", "accent": "#1db954", "trough": "#3a3a3a"},
    "Claro":     {"bg": "#f2f2f2", "fg": "#111111", "sub": "#555555", "accent": "#1db954", "trough": "#cccccc"},
    "Morado":    {"bg": "#2b1b4a", "fg": "#ffffff", "sub": "#c9b6ef", "accent": "#b57bff", "trough": "#4a3875"},
    "Rojo neón": {"bg": "#120808", "fg": "#ffffff", "sub": "#ff9a9a", "accent": "#ff2e4d", "trough": "#3b1a1a"},
}

DEFAULTS = {
    "theme": "Oscuro",
    "custom": {"bg": "#222831", "fg": "#eeeeee", "accent": "#00adb5"},
    "layout": "Vertical",
    "cover_size": 200,
    "font": "Segoe UI",
    "title_size": 13,
    "show_cover": True,
    "show_artist": True,
    "show_progress": True,
    "show_time": True,
    "show_status": True,
    "borderless": False,
    "topmost": False,
    "opacity": 100,
    "skip_menu": False,
}


# ---------------- Configuración ----------------
def load_config():
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def get_colors(cfg):
    if cfg["theme"] in THEMES:
        return THEMES[cfg["theme"]]
    c = cfg["custom"]
    return {"bg": c["bg"], "fg": c["fg"], "sub": c["fg"], "accent": c["accent"], "trough": "#808080"}


# ---------------- Menú de configuración ----------------
def run_menu(cfg):
    win = tk.Tk()
    win.title("NowPlaying · Configuración")
    win.resizable(False, False)
    out = {}

    v_theme = tk.StringVar(value=cfg["theme"])
    v_layout = tk.StringVar(value=cfg["layout"])
    v_font = tk.StringVar(value=cfg["font"])
    v_tsize = tk.IntVar(value=cfg["title_size"])
    v_cover = tk.IntVar(value=cfg["cover_size"])
    v_opacity = tk.IntVar(value=cfg["opacity"])
    flags = {k: tk.BooleanVar(value=cfg[k]) for k in
             ("show_cover", "show_artist", "show_progress", "show_time", "show_status",
              "borderless", "topmost", "skip_menu")}
    custom = dict(cfg["custom"])

    # --- Estilo ---
    f1 = ttk.LabelFrame(win, text="Estilo")
    f1.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))

    ttk.Label(f1, text="Tema").grid(row=0, column=0, sticky="w", padx=8, pady=4)
    ttk.Combobox(f1, textvariable=v_theme, state="readonly", width=16,
                 values=list(THEMES) + ["Personalizado"]).grid(row=0, column=1, sticky="w")

    ttk.Label(f1, text="Colores propios").grid(row=1, column=0, sticky="w", padx=8, pady=4)
    row_colors = ttk.Frame(f1)
    row_colors.grid(row=1, column=1, sticky="w")

    def pick(key, btn):
        res = colorchooser.askcolor(initialcolor=custom[key], parent=win)[1]
        if res:
            custom[key] = res
            btn.config(bg=res)
            v_theme.set("Personalizado")

    for key, label in (("bg", "Fondo"), ("fg", "Texto"), ("accent", "Acento")):
        b = tk.Button(row_colors, text=label, width=7, bg=custom[key], relief="groove")
        b.config(command=lambda k=key, bb=b: pick(k, bb))
        b.pack(side="left", padx=2)

    ttk.Label(f1, text="Diseño").grid(row=2, column=0, sticky="w", padx=8, pady=4)
    row_l = ttk.Frame(f1)
    row_l.grid(row=2, column=1, sticky="w")
    for name in ("Vertical", "Horizontal"):
        ttk.Radiobutton(row_l, text=name, value=name, variable=v_layout).pack(side="left", padx=4)

    ttk.Label(f1, text="Fuente").grid(row=3, column=0, sticky="w", padx=8, pady=4)
    ttk.Combobox(f1, textvariable=v_font, state="readonly", width=16,
                 values=["Segoe UI", "Arial", "Consolas", "Georgia", "Impact", "Comic Sans MS"]
                 ).grid(row=3, column=1, sticky="w")

    ttk.Label(f1, text="Tamaño del título").grid(row=4, column=0, sticky="w", padx=8, pady=4)
    ttk.Spinbox(f1, from_=9, to=28, textvariable=v_tsize, width=5).grid(row=4, column=1, sticky="w")

    ttk.Label(f1, text="Tamaño portada").grid(row=5, column=0, sticky="w", padx=8, pady=4)
    tk.Scale(f1, from_=60, to=300, orient="horizontal", variable=v_cover, length=160
             ).grid(row=5, column=1, sticky="w")

    # --- Mostrar ---
    f2 = ttk.LabelFrame(win, text="Mostrar")
    f2.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
    opciones = (("show_cover", "Portada"), ("show_artist", "Artista"),
                ("show_progress", "Barra de progreso"), ("show_time", "Tiempo (1:23 / 3:45)"),
                ("show_status", "Estado y app"))
    for i, (k, t) in enumerate(opciones):
        ttk.Checkbutton(f2, text=t, variable=flags[k]).grid(row=i // 2, column=i % 2, sticky="w", padx=8, pady=2)

    # --- Ventana ---
    f3 = ttk.LabelFrame(win, text="Ventana")
    f3.grid(row=2, column=0, sticky="ew", padx=10, pady=5)
    ttk.Checkbutton(f3, text="Sin bordes (arrastrable)", variable=flags["borderless"]
                    ).grid(row=0, column=0, sticky="w", padx=8, pady=2)
    ttk.Checkbutton(f3, text="Siempre encima", variable=flags["topmost"]
                    ).grid(row=0, column=1, sticky="w", padx=8, pady=2)
    ttk.Label(f3, text="Opacidad %").grid(row=1, column=0, sticky="w", padx=8)
    tk.Scale(f3, from_=40, to=100, orient="horizontal", variable=v_opacity, length=160
             ).grid(row=1, column=1, sticky="w")

    ttk.Checkbutton(win, text="No mostrar este menú al iniciar (clic derecho en el widget → Configurar)",
                    variable=flags["skip_menu"]).grid(row=3, column=0, sticky="w", padx=12, pady=4)

    def start():
        new = dict(cfg)
        new.update(theme=v_theme.get(), layout=v_layout.get(), font=v_font.get(),
                   title_size=int(v_tsize.get()), cover_size=int(v_cover.get()),
                   opacity=int(v_opacity.get()), custom=custom)
        for k, v in flags.items():
            new[k] = bool(v.get())
        out["cfg"] = new
        win.destroy()

    bar = ttk.Frame(win)
    bar.grid(row=4, column=0, pady=(5, 10))
    ttk.Button(bar, text="▶ Iniciar", command=start).pack(side="left", padx=6)
    ttk.Button(bar, text="Salir", command=win.destroy).pack(side="left", padx=6)

    win.mainloop()
    return out.get("cfg")


# ---------------- Hilo de fondo: habla con Windows ----------------
async def read_cover(props):
    if not props.thumbnail:
        return None
    stream = await props.thumbnail.open_read_async()
    buf = Buffer(stream.size)
    await stream.read_async(buf, stream.size, InputStreamOptions.READ_AHEAD)
    reader = DataReader.from_buffer(buf)
    data = bytearray(buf.length)
    reader.read_bytes(data)
    return bytes(data)


def get_progress(current):
    tl = current.get_timeline_properties()
    pos = tl.position.total_seconds()
    dur = (tl.end_time - tl.start_time).total_seconds()
    playing = current.get_playback_info().playback_status == PlaybackStatus.PLAYING
    if playing:
        try:
            elapsed = (datetime.now(timezone.utc) - tl.last_updated_time).total_seconds()
            pos += max(0, elapsed)
        except Exception:
            pass
    if dur > 0:
        pos = min(pos, dur)
    return pos, dur, playing


async def check_song(last_key, results):
    sessions = await MediaManager.request_async()
    current = sessions.get_current_session()
    if not current:
        return None
    props = await current.try_get_media_properties_async()
    key = (props.title, props.artist)
    if key != last_key:
        cover = await read_cover(props)
        results.put(("song", props.title, props.artist, cover))
    pos, dur, playing = get_progress(current)
    results.put(("progress", pos, dur, playing, current.source_app_user_model_id))
    return key


def worker(results):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    last_key = None
    while True:
        try:
            key = loop.run_until_complete(check_song(last_key, results))
            if key is None and last_key is not None:
                results.put(("none",))
            last_key = key
        except Exception as e:
            print("Error:", e)
        time.sleep(POLL_S)


# ---------------- Widget ----------------
def fmt(seconds):
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def run_widget(cfg):
    c = get_colors(cfg)
    results = queue.Queue()
    threading.Thread(target=worker, args=(results,), daemon=True).start()

    root = tk.Tk()
    root.title("Reproduciendo ahora")
    root.configure(bg=c["bg"])
    root.resizable(False, False)
    root.attributes("-topmost", cfg["topmost"])
    root.attributes("-alpha", cfg["opacity"] / 100)
    if cfg["borderless"]:
        root.overrideredirect(True)

    horizontal = cfg["layout"] == "Horizontal"
    cs = cfg["cover_size"]
    text_w = 240 if horizontal else max(cs, 240)
    anchor = "w" if horizontal else "center"
    font = cfg["font"]
    tsize = cfg["title_size"]

    main = tk.Frame(root, bg=c["bg"], padx=14, pady=14)
    main.pack()
    info = tk.Frame(main, bg=c["bg"])

    cover_label = None
    if cfg["show_cover"]:
        cover_label = tk.Label(main, bg=c["bg"], width=cs, height=cs)
        cover_label.config(image="")
    if horizontal:
        if cover_label:
            cover_label.pack(side="left", padx=(0, 14))
        info.pack(side="left")
    else:
        if cover_label:
            cover_label.pack(pady=(0, 10))
        info.pack()

    title_label = tk.Label(info, text="Nada en reproducción", fg=c["fg"], bg=c["bg"],
                           font=(font, tsize, "bold"), wraplength=text_w,
                           justify="left" if horizontal else "center")
    title_label.pack(anchor=anchor)

    artist_label = None
    if cfg["show_artist"]:
        artist_label = tk.Label(info, text="", fg=c["sub"], bg=c["bg"],
                                font=(font, max(8, tsize - 3)))
        artist_label.pack(anchor=anchor)

    progress = None
    if cfg["show_progress"]:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("NP.Horizontal.TProgressbar", troughcolor=c["trough"],
                        background=c["accent"], bordercolor=c["bg"],
                        lightcolor=c["accent"], darkcolor=c["accent"])
        progress = ttk.Progressbar(info, style="NP.Horizontal.TProgressbar",
                                   orient="horizontal", mode="determinate",
                                   maximum=1000, length=text_w)
        progress.pack(pady=(12, 4), anchor=anchor)

    time_label = None
    if cfg["show_time"]:
        time_label = tk.Label(info, text="--:-- / --:--", fg=c["fg"], bg=c["bg"], font=(font, 10))
        time_label.pack(anchor=anchor)

    status_label = None
    if cfg["show_status"]:
        status_label = tk.Label(info, text="", fg=c["sub"], bg=c["bg"], font=(font, 9))
        status_label.pack(anchor=anchor, pady=(4, 0))

    # --- Menú clic derecho + arrastrar ---
    def open_config():
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "--config"])
        root.destroy()

    menu = tk.Menu(root, tearoff=0)
    menu.add_command(label="Configurar…", command=open_config)
    menu.add_command(label="Cerrar", command=root.destroy)

    drag = {"x": 0, "y": 0}

    def start_drag(e):
        drag["x"], drag["y"] = e.x_root - root.winfo_x(), e.y_root - root.winfo_y()

    def do_drag(e):
        root.geometry(f"+{e.x_root - drag['x']}+{e.y_root - drag['y']}")

    def bind_recursive(w):
        w.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))
        if cfg["borderless"]:
            w.bind("<Button-1>", start_drag)
            w.bind("<B1-Motion>", do_drag)
        for child in w.winfo_children():
            bind_recursive(child)

    bind_recursive(root)

    # --- Actualizaciones ---
    def update_song(title, artist, cover):
        title_label.config(text=title or "Sin título")
        if artist_label:
            artist_label.config(text=artist or "")
        if cover_label:
            if cover:
                img = Image.open(io.BytesIO(cover)).resize((cs, cs))
                cover_label.photo = ImageTk.PhotoImage(img)
                cover_label.config(image=cover_label.photo, width=cs, height=cs)
            else:
                cover_label.photo = None
                cover_label.config(image="")

    def update_progress(pos, dur, playing, app):
        if progress:
            progress["value"] = pos / dur * 1000 if dur > 0 else 0
        if time_label:
            time_label.config(text=f"{fmt(pos)} / {fmt(dur)}" if dur > 0 else f"{fmt(pos)} / --:--")
        if status_label:
            app_name = (app or "").replace(".exe", "")
            estado = "▶ Reproduciendo" if playing else "⏸ En pausa"
            status_label.config(text=f"{estado}  ·  {app_name}" if app_name else estado)

    def reset_ui():
        update_song("Nada en reproducción", "", None)
        if progress:
            progress["value"] = 0
        if time_label:
            time_label.config(text="--:-- / --:--")
        if status_label:
            status_label.config(text="")

    def check_queue():
        try:
            while True:
                msg = results.get_nowait()
                if msg[0] == "song":
                    update_song(msg[1], msg[2], msg[3])
                elif msg[0] == "progress":
                    update_progress(msg[1], msg[2], msg[3], msg[4])
                else:
                    reset_ui()
        except queue.Empty:
            pass
        root.after(200, check_queue)

    check_queue()
    root.mainloop()


# ---------------- Inicio ----------------
if __name__ == "__main__":
    cfg = load_config()
    force_menu = "--config" in sys.argv
    if cfg["skip_menu"] and not force_menu:
        run_widget(cfg)
    else:
        new_cfg = run_menu(cfg)
        if new_cfg:
            save_config(new_cfg)
            run_widget(new_cfg)