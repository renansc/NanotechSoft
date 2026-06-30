import os, json, re, sqlite3, subprocess, glob, threading, time, shutil
from flask import Flask, request, jsonify, send_from_directory

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
STATE_DIR = os.path.abspath(os.environ.get("DATA_DIR", BASE_DIR))
DATA_FILE = os.path.join(STATE_DIR, "cams.json")
DB_FILE = os.path.join(STATE_DIR, "cameras.db")
CAMS_DIR  = os.path.join(STATE_DIR, "cams")
LEGACY_DATA_FILE = os.path.join(BASE_DIR, "cams.json")
LEGACY_DB_FILE = os.path.join(BASE_DIR, "cameras.db")
os.makedirs(STATE_DIR, exist_ok=True)
os.makedirs(CAMS_DIR, exist_ok=True)

app = Flask(__name__, static_folder=BASE_DIR, static_url_path="")

# Mantém PIDs dos ffmpegs que o server iniciou (em memória)
PROCS = {}
HLS_TIME = "1"
HLS_LIST_SIZE = "2"
HLS_DELETE_THRESHOLD = "1"
HLS_KEEP_MAX_FILES = 6
JANITOR_INTERVAL_SEC = 20

def migrate_legacy_state():
    """Copy old files from the repository root into the configured state dir."""
    for src, dst in (
        (LEGACY_DATA_FILE, DATA_FILE),
        (LEGACY_DB_FILE, DB_FILE),
    ):
        if os.path.abspath(src) == os.path.abspath(dst):
            continue
        if os.path.exists(src) and not os.path.exists(dst):
            try:
                shutil.copy2(src, dst)
            except Exception:
                pass

def ffmpeg_disponivel() -> bool:
    try:
        r = subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return r.returncode == 0
    except Exception:
        return False

def _db_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def _write_json_snapshot(data):
    tmp_file = DATA_FILE + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, DATA_FILE)

def init_db():
    with _db_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cameras (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                mode TEXT NOT NULL,
                hls TEXT,
                rtsp TEXT,
                transport TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        count = conn.execute("SELECT COUNT(*) AS n FROM cameras").fetchone()["n"]
        if count == 0 and os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                cams = raw.get("cams") or []
                for c in cams:
                    conn.execute(
                        "INSERT OR REPLACE INTO cameras (id, name, mode, hls, rtsp, transport) VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            (c.get("id") or "").strip(),
                            (c.get("name") or "").strip(),
                            (c.get("mode") or "").strip(),
                            (c.get("hls") or "").strip() or None,
                            (c.get("rtsp") or "").strip() or None,
                            (c.get("transport") or "").strip() or None,
                        ),
                    )
                conn.commit()
            except Exception:
                pass

        if not os.path.exists(DATA_FILE):
            try:
                rows = conn.execute(
                    "SELECT id, name, mode, hls, rtsp, transport FROM cameras ORDER BY created_at, id"
                ).fetchall()
                cams = []
                for r in rows:
                    cams.append({
                        "id": r["id"],
                        "name": r["name"],
                        "mode": r["mode"],
                        "hls": r["hls"],
                        "rtsp": r["rtsp"],
                        "transport": r["transport"],
                    })
                _write_json_snapshot({"cams": cams})
            except Exception:
                pass

def load_data():
    with _db_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, mode, hls, rtsp, transport FROM cameras ORDER BY created_at, id"
        ).fetchall()

    cams = []
    for r in rows:
        cams.append({
            "id": r["id"],
            "name": r["name"],
            "mode": r["mode"],
            "hls": r["hls"],
            "rtsp": r["rtsp"],
            "transport": r["transport"],
        })
    return {"cams": cams}

def save_data(data):
    cams = data.get("cams") or []
    with _db_conn() as conn:
        conn.execute("DELETE FROM cameras")
        for c in cams:
            conn.execute(
                "INSERT OR REPLACE INTO cameras (id, name, mode, hls, rtsp, transport) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    (c.get("id") or "").strip(),
                    (c.get("name") or "").strip(),
                    (c.get("mode") or "").strip(),
                    (c.get("hls") or "").strip() or None,
                    (c.get("rtsp") or "").strip() or None,
                    (c.get("transport") or "").strip() or None,
                ),
            )
        conn.commit()
    try:
        _write_json_snapshot({"cams": cams})
    except Exception:
        pass

def safe_slug(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9_-]+", "-", name)
    name = re.sub(r"-{2,}", "-", name).strip("-")
    return name or "cam"

def cleanup_cam_folder(cam_folder: str, keep_max_files: int = HLS_KEEP_MAX_FILES):
    """Evita acumulo de segmentos: mantem somente os mais recentes."""
    try:
        seg_files = sorted(
            glob.glob(os.path.join(cam_folder, "seg_*.ts")),
            key=lambda p: os.path.getmtime(p),
        )
        if len(seg_files) > keep_max_files:
            for p in seg_files[: len(seg_files) - keep_max_files]:
                try:
                    os.remove(p)
                except Exception:
                    pass

        # Remove arquivos temporarios deixados por escritas interrompidas.
        for p in glob.glob(os.path.join(cam_folder, "*.tmp")):
            try:
                os.remove(p)
            except Exception:
                pass
    except Exception:
        pass

def _hls_janitor_loop():
    while True:
        try:
            for d in os.listdir(CAMS_DIR):
                cam_folder = os.path.join(CAMS_DIR, d)
                if os.path.isdir(cam_folder):
                    cleanup_cam_folder(cam_folder)
        except Exception:
            pass
        time.sleep(JANITOR_INTERVAL_SEC)

def ffmpeg_start(cam_id: str, rtsp_url: str, transport: str = "udp"):
    cam_folder = os.path.join(CAMS_DIR, cam_id)
    os.makedirs(cam_folder, exist_ok=True)

    m3u8_path = os.path.join(cam_folder, "live.m3u8")
    seg_tmpl  = os.path.join(cam_folder, "seg_%03d.ts")
    cleanup_cam_folder(cam_folder)

    # Para Termux/Android: melhor tentar copy primeiro (baixo CPU)
    # -an para evitar dor de cabeça com áudio; depois você pode habilitar se precisar
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "warning",
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        "-probesize", "32",
        "-analyzeduration", "0",
        "-rtsp_transport", transport,
        "-i", rtsp_url,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-r", "15",
        "-pix_fmt", "yuv420p",
        "-g", "15",
        "-keyint_min", "15",
        "-sc_threshold", "0",
        "-an",
        "-f", "hls",
        "-hls_time", HLS_TIME,
        "-hls_list_size", HLS_LIST_SIZE,
        "-hls_delete_threshold", HLS_DELETE_THRESHOLD,
        "-hls_allow_cache", "0",
        "-hls_flags", "delete_segments+omit_endlist+temp_file",
        "-hls_segment_filename", seg_tmpl,
        m3u8_path
    ]

    # encerra instancia anterior (se existir)
    if cam_id in PROCS and PROCS[cam_id].poll() is None:
        try:
            PROCS[cam_id].terminate()
        except Exception:
            pass
    # Garante que nao exista ffmpeg antigo escrevendo no mesmo live.m3u8.
    try:
        subprocess.run(["pkill", "-f", m3u8_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    PROCS[cam_id] = p
    return m3u8_path

def start_saved_rtsp_streams():
    data = load_data()
    cams = data.get("cams") or []
    for c in cams:
        if (c.get("mode") or "").lower() != "rtsp":
            continue
        rtsp = (c.get("rtsp") or "").strip()
        cam_id = (c.get("id") or "").strip()
        if not rtsp or not cam_id:
            continue
        transport = (c.get("transport") or "tcp").strip().lower()
        if transport not in ("udp", "tcp"):
            transport = "tcp"
        try:
            if ffmpeg_disponivel():
                ffmpeg_start(cam_id, rtsp, transport)
        except Exception:
            pass

migrate_legacy_state()
init_db()

@app.get("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")

@app.get("/api/list")
def api_list():
    data = load_data()
    return jsonify(data)

@app.post("/api/add")
def api_add():
    body = request.get_json(force=True, silent=True) or {}
    name = (body.get("name") or "").strip()
    mode = (body.get("mode") or "").strip()  # "rtsp" | "hls"
    value = (body.get("value") or "").strip()
    transport = (body.get("transport") or "udp").strip().lower()

    if not name or not mode or not value:
        return jsonify({"ok": False, "error": "Preencha name/mode/value"}), 400

    data = load_data()

    cam_id = safe_slug(name)
    # garante id unico
    existing_ids = {c["id"] for c in data["cams"]}
    base = cam_id
    i = 2
    while cam_id in existing_ids:
        cam_id = f"{base}-{i}"
        i += 1

    cam = {"id": cam_id, "name": name, "mode": mode}

    if mode == "hls":
        cam["hls"] = value
    elif mode == "rtsp":
        # ONVIF nao é stream; se vier onvif:// ou http(s)://.../onvif, avisa
        if value.lower().startswith("rtsp://"):
            cam["rtsp"] = value
            cam["transport"] = transport if transport in ("udp", "tcp") else "udp"
            if not ffmpeg_disponivel():
                return jsonify({
                    "ok": False,
                    "error": "FFmpeg nao encontrado no servidor. Instale ffmpeg para usar modo RTSP, ou cadastre em modo HLS."
                }), 503
            try:
                ffmpeg_start(cam_id, value, cam["transport"])
            except FileNotFoundError:
                return jsonify({
                    "ok": False,
                    "error": "FFmpeg nao encontrado no servidor. Instale ffmpeg para usar modo RTSP."
                }), 503
            except Exception as e:
                return jsonify({
                    "ok": False,
                    "error": f"Falha ao iniciar conversao RTSP/HLS: {str(e)}"
                }), 500
            cam["hls"] = f"/cams/{cam_id}/live.m3u8"
        else:
            return jsonify({
                "ok": False,
                "error": "ONVIF nao é vídeo direto. Cole a URL RTSP (rtsp://...). Se você só tem ONVIF, precisa descobrir o RTSP via ONVIF."
            }), 400
    else:
        return jsonify({"ok": False, "error": "mode inválido (use rtsp ou hls)"}), 400

    data["cams"].append(cam)
    save_data(data)
    return jsonify({"ok": True, "cam": cam})

@app.post("/api/update")
def api_update():
    body = request.get_json(force=True, silent=True) or {}
    cam_id = (body.get("id") or "").strip()
    if not cam_id:
        return jsonify({"ok": False, "error": "id obrigatorio"}), 400

    data = load_data()
    cams = data.get("cams") or []
    cam = next((c for c in cams if (c.get("id") or "").strip() == cam_id), None)
    if not cam:
        return jsonify({"ok": False, "error": "camera nao encontrada"}), 404

    name = (body.get("name") or cam.get("name") or "").strip()
    mode = (body.get("mode") or cam.get("mode") or "").strip().lower()
    value = (body.get("value") or "").strip()
    transport = (body.get("transport") or cam.get("transport") or "tcp").strip().lower()
    if transport not in ("udp", "tcp"):
        transport = "tcp"

    if not name:
        return jsonify({"ok": False, "error": "nome obrigatorio"}), 400

    if mode == "hls":
        if not value:
            value = (cam.get("hls") or "").strip()
        if not value:
            return jsonify({"ok": False, "error": "url hls obrigatoria"}), 400
        cam["name"] = name
        cam["mode"] = "hls"
        cam["hls"] = value
        cam.pop("rtsp", None)
        cam.pop("transport", None)

        if cam_id in PROCS and PROCS[cam_id].poll() is None:
            try:
                PROCS[cam_id].terminate()
            except Exception:
                pass

    elif mode == "rtsp":
        if not value:
            value = (cam.get("rtsp") or "").strip()
        if not value.startswith("rtsp://"):
            return jsonify({"ok": False, "error": "url rtsp invalida"}), 400
        if not ffmpeg_disponivel():
            return jsonify({"ok": False, "error": "FFmpeg nao encontrado no servidor."}), 503

        cam["name"] = name
        cam["mode"] = "rtsp"
        cam["rtsp"] = value
        cam["transport"] = transport
        cam["hls"] = f"/cams/{cam_id}/live.m3u8"
        try:
            ffmpeg_start(cam_id, value, transport)
        except Exception as e:
            return jsonify({"ok": False, "error": f"falha ao reiniciar stream: {str(e)}"}), 500
    else:
        return jsonify({"ok": False, "error": "mode invalido (use rtsp ou hls)"}), 400

    save_data(data)
    return jsonify({"ok": True, "cam": cam})

@app.post("/api/remove")
def api_remove():
    body = request.get_json(force=True, silent=True) or {}
    cam_id = (body.get("id") or "").strip()
    if not cam_id:
        return jsonify({"ok": False, "error": "id obrigatório"}), 400

    data = load_data()
    data["cams"] = [c for c in data["cams"] if c.get("id") != cam_id]
    save_data(data)

    # mata ffmpeg se estiver rodando
    if cam_id in PROCS and PROCS[cam_id].poll() is None:
        try:
            PROCS[cam_id].terminate()
        except Exception:
            pass

    # Apaga residuos da camera removida para nao ocupar disco.
    cam_folder = os.path.join(CAMS_DIR, cam_id)
    try:
        if os.path.isdir(cam_folder):
            for p in glob.glob(os.path.join(cam_folder, "*")):
                try:
                    os.remove(p)
                except Exception:
                    pass
            try:
                os.rmdir(cam_folder)
            except Exception:
                pass
    except Exception:
        pass

    return jsonify({"ok": True})

@app.post("/api/restart")
def api_restart():
    body = request.get_json(force=True, silent=True) or {}
    cam_id = (body.get("id") or "").strip()
    transport = (body.get("transport") or "tcp").strip().lower()
    if transport not in ("udp", "tcp"):
        transport = "tcp"
    if not cam_id:
        return jsonify({"ok": False, "error": "id obrigatorio"}), 400

    data = load_data()
    cam = next((x for x in (data.get("cams") or []) if (x.get("id") or "").strip() == cam_id), None)
    if not cam:
        return jsonify({"ok": False, "error": "camera nao encontrada"}), 404
    if (cam.get("mode") or "").lower() != "rtsp":
        return jsonify({"ok": False, "error": "camera nao esta em modo rtsp"}), 400
    rtsp_url = (cam.get("rtsp") or "").strip()
    if not rtsp_url.startswith("rtsp://"):
        return jsonify({"ok": False, "error": "url rtsp invalida"}), 400
    if not ffmpeg_disponivel():
        return jsonify({"ok": False, "error": "FFmpeg nao encontrado no servidor."}), 503

    cam["transport"] = transport
    save_data(data)
    try:
        ffmpeg_start(cam_id, rtsp_url, transport)
    except Exception as e:
        return jsonify({"ok": False, "error": f"falha ao reiniciar stream: {str(e)}"}), 500
    return jsonify({"ok": True, "cam": cam})

@app.get("/cams/<path:filename>")
def cams_files(filename):
    resp = send_from_directory(CAMS_DIR, filename, conditional=False, max_age=0)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

if __name__ == "__main__":
    threading.Thread(target=_hls_janitor_loop, daemon=True).start()
    start_saved_rtsp_streams()
    # Acesse via: http://127.0.0.1:8080
    # ou de outro device: http://IP_DO_ANDROID:8080 (webcam pode exigir https)
    app.run(
        host=os.environ.get("APP_HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8889")),
        debug=False,
    )
