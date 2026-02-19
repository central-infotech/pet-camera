"""Pet Camera streaming server — Flask + Flask-SocketIO."""

import glob
import logging
import os
import time
from datetime import datetime, timezone

from flask import Flask, Response, jsonify, render_template, request, send_from_directory, session
from flask_socketio import SocketIO, disconnect, emit

from . import config
from .auth import (
    handle_auth_request,
    handle_logout,
    is_authenticated,
    login_required,
    setup_access_log,
    validate_socketio_auth,
)
from .camera import Camera
from .audio import AudioCapture, AudioPlayer
from . import webauthn_auth

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"),
    static_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "static"),
)
app.secret_key = config.SECRET_KEY
app.config["SESSION_COOKIE_NAME"] = "pet_camera_session"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = not config.IS_DEV
app.config["SESSION_COOKIE_SAMESITE"] = "Strict"

socketio = SocketIO(app, cors_allowed_origins=None, async_mode="threading")

# ---------------------------------------------------------------------------
# Subsystems
# ---------------------------------------------------------------------------
camera = Camera()
audio_capture = AudioCapture()
audio_player = AudioPlayer()

# Server start time for uptime calculation
_start_time = time.time()

# Track connected clients
_connected_clients: set[str] = set()

# Track audio listeners: {sid: queue}
_audio_listeners: dict = {}

# ---------------------------------------------------------------------------
# Ensure directories
# ---------------------------------------------------------------------------
os.makedirs(config.SNAPSHOT_DIR, exist_ok=True)
os.makedirs(config.LOG_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Access logging
# ---------------------------------------------------------------------------
setup_access_log(app)

# ===========================================================================
# HTTP Routes
# ===========================================================================


@app.route("/")
def index():
    if is_authenticated():
        return render_template("index.html")
    return render_template("login.html")


@app.route("/video_feed")
@login_required
def video_feed():
    return Response(
        camera.generate_mjpeg(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/snapshot")
@login_required
def snapshot():
    jpeg = camera.get_frame_jpeg(quality=95)
    if jpeg is None:
        return jsonify({"error": {"code": "CAMERA_ERROR", "message": "No frame available"}}), 500
    return Response(jpeg, mimetype="image/jpeg",
                    headers={"Content-Disposition": "attachment; filename=snapshot.jpg"})


# --- Snapshots CRUD ---

@app.route("/api/snapshots", methods=["POST"])
@login_required
def save_snapshot():
    jpeg = camera.get_frame_jpeg(quality=95)
    if jpeg is None:
        return jsonify({"error": {"code": "CAMERA_ERROR", "message": "No frame available"}}), 500

    # Enforce storage limit (FIFO)
    _enforce_snapshot_limit(len(jpeg))

    now = datetime.now()
    filename = now.strftime("snapshot_%Y%m%d_%H%M%S") + f"_{now.microsecond // 1000:03d}.jpg"
    filepath = os.path.join(config.SNAPSHOT_DIR, filename)

    try:
        with open(filepath, "wb") as f:
            f.write(jpeg)
    except OSError as e:
        return jsonify({"error": {"code": "STORAGE_ERROR", "message": str(e)}}), 500

    used = _get_storage_used()
    return jsonify({
        "filename": filename,
        "size_bytes": len(jpeg),
        "timestamp": now.astimezone(timezone.utc).isoformat(),
        "storage_used_bytes": used,
        "storage_limit_bytes": config.SNAPSHOT_MAX_BYTES,
    })


@app.route("/api/snapshots", methods=["GET"])
@login_required
def list_snapshots():
    files = sorted(glob.glob(os.path.join(config.SNAPSHOT_DIR, "snapshot_*.jpg")))
    snapshots = []
    for fp in files:
        fname = os.path.basename(fp)
        stat = os.stat(fp)
        snapshots.append({
            "filename": fname,
            "size_bytes": stat.st_size,
            "timestamp": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        })
    used = sum(s["size_bytes"] for s in snapshots)
    return jsonify({
        "snapshots": snapshots,
        "total_count": len(snapshots),
        "storage_used_bytes": used,
        "storage_limit_bytes": config.SNAPSHOT_MAX_BYTES,
    })


@app.route("/api/snapshots/<filename>", methods=["GET"])
@login_required
def get_snapshot(filename):
    safe = os.path.basename(filename)
    if safe != filename or not safe.startswith("snapshot_"):
        return jsonify({"error": {"code": "NOT_FOUND", "message": "Snapshot not found"}}), 404
    filepath = os.path.join(config.SNAPSHOT_DIR, safe)
    if not os.path.isfile(filepath):
        return jsonify({"error": {"code": "NOT_FOUND", "message": "Snapshot not found"}}), 404
    return send_from_directory(config.SNAPSHOT_DIR, safe, mimetype="image/jpeg")


@app.route("/api/snapshots/<filename>", methods=["DELETE"])
@login_required
def delete_snapshot(filename):
    safe = os.path.basename(filename)
    if safe != filename or not safe.startswith("snapshot_"):
        return jsonify({"error": {"code": "NOT_FOUND", "message": "Snapshot not found"}}), 404
    filepath = os.path.join(config.SNAPSHOT_DIR, safe)
    if not os.path.isfile(filepath):
        return jsonify({"error": {"code": "NOT_FOUND", "message": "Snapshot not found"}}), 404
    os.remove(filepath)
    return jsonify({"deleted": True})


# --- Status & Settings ---

@app.route("/api/status")
@login_required
def status():
    return jsonify({
        "status": "running",
        "uptime_seconds": int(time.time() - _start_time),
        "fps": camera.fps_actual,
        "resolution": camera.resolution_str,
        "clients_connected": len(_connected_clients),
        "camera_index": camera.camera_index,
        "audio": {
            "microphone_active": audio_capture.is_active,
            "speaker_active": audio_player.is_active,
            "listening_clients": audio_capture.listener_count,
        },
    })


@app.route("/api/settings", methods=["GET"])
@login_required
def get_settings():
    return jsonify(camera.get_settings())


@app.route("/api/settings", methods=["PATCH"])
@login_required
def patch_settings():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": {"code": "INVALID_PARAMETER", "message": "Request body required"}}), 400

    result, error = camera.update_settings(data)
    if error:
        code = "UNKNOWN_PARAMETER" if "Unknown" in error else "INVALID_PARAMETER"
        return jsonify({"error": {"code": code, "message": error}}), 400

    return jsonify(result)


# --- Auth ---

@app.route("/api/auth", methods=["POST"])
def auth():
    return handle_auth_request()


@app.route("/api/logout", methods=["POST"])
@login_required
def logout():
    return handle_logout()


# --- WebAuthn ---

@app.route("/api/webauthn/register/options", methods=["POST"])
@login_required
def webauthn_register_options():
    options_json = webauthn_auth.get_registration_options_json()
    return Response(options_json, mimetype="application/json")


@app.route("/api/webauthn/register", methods=["POST"])
@login_required
def webauthn_register():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": {"code": "INVALID_PARAMETER", "message": "Request body required"}}), 400
    success, msg = webauthn_auth.verify_registration(body)
    if success:
        return jsonify({"registered": True})
    return jsonify({"error": {"code": "WEBAUTHN_ERROR", "message": msg}}), 400


@app.route("/api/webauthn/login/options", methods=["POST"])
def webauthn_login_options():
    if webauthn_auth.get_credential_count() == 0:
        return jsonify({"error": {"code": "NO_CREDENTIALS", "message": "No passkeys registered"}}), 404
    options_json = webauthn_auth.get_authentication_options_json()
    if not options_json:
        return jsonify({"error": {"code": "NO_CREDENTIALS", "message": "No passkeys registered"}}), 404
    return Response(options_json, mimetype="application/json")


@app.route("/api/webauthn/login", methods=["POST"])
def webauthn_login():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": {"code": "INVALID_PARAMETER", "message": "Request body required"}}), 400
    success, msg = webauthn_auth.verify_authentication(body)
    if success:
        from .auth import create_session
        sid = create_session()
        session["sid"] = sid
        return jsonify({"authenticated": True})
    return jsonify({"error": {"code": "AUTH_INVALID", "message": msg}}), 401


@app.route("/api/webauthn/credentials", methods=["GET"])
@login_required
def webauthn_credentials():
    return jsonify({"count": webauthn_auth.get_credential_count()})


# ===========================================================================
# Snapshot helpers
# ===========================================================================

def _get_storage_used() -> int:
    total = 0
    for fp in glob.glob(os.path.join(config.SNAPSHOT_DIR, "snapshot_*.jpg")):
        total += os.path.getsize(fp)
    return total


def _enforce_snapshot_limit(new_size: int):
    """Delete oldest snapshots until there is room for new_size bytes."""
    while True:
        used = _get_storage_used()
        if used + new_size <= config.SNAPSHOT_MAX_BYTES:
            break
        files = sorted(glob.glob(os.path.join(config.SNAPSHOT_DIR, "snapshot_*.jpg")))
        if not files:
            break
        oldest = files[0]
        logger.info("Snapshots: deleting oldest %s (FIFO)", os.path.basename(oldest))
        os.remove(oldest)


# ===========================================================================
# Socket.IO — Audio namespace
# ===========================================================================

@socketio.on("connect", namespace="/audio")
def audio_connect(auth_data=None):
    if not validate_socketio_auth(auth_data):
        logger.warning("Audio WS: rejected unauthenticated connection from %s", request.remote_addr)
        disconnect()
        return False
    sid = request.sid
    _connected_clients.add(sid)
    logger.info("Audio WS: client connected (sid=%s, total=%d)", sid, len(_connected_clients))


@socketio.on("disconnect", namespace="/audio")
def audio_disconnect():
    sid = request.sid
    _connected_clients.discard(sid)

    # Clean up listener if active
    q = _audio_listeners.pop(sid, None)
    if q:
        audio_capture.remove_listener(q)

    # Release talk slot if held
    audio_player.release_talk()
    logger.info("Audio WS: client disconnected (sid=%s)", sid)


@socketio.on("audio_listen_start", namespace="/audio")
def audio_listen_start():
    sid = request.sid
    if sid in _audio_listeners:
        return  # Already listening

    if not audio_capture.is_active:
        audio_capture.start()

    q = audio_capture.add_listener()
    _audio_listeners[sid] = q

    # Start a background task to stream audio to this client
    socketio.start_background_task(_stream_audio_to_client, sid, q)

    emit("audio_status", {"listening": True, "talking_clients": audio_player.talking_clients})


@socketio.on("audio_listen_stop", namespace="/audio")
def audio_listen_stop():
    sid = request.sid
    q = _audio_listeners.pop(sid, None)
    if q:
        audio_capture.remove_listener(q)
    emit("audio_status", {"listening": False, "talking_clients": audio_player.talking_clients})


@socketio.on("audio_talk_start", namespace="/audio")
def audio_talk_start():
    sid = request.sid
    if audio_player.acquire_talk():
        logger.info("Audio WS: talk started (sid=%s)", sid)
        if not audio_player.is_active:
            audio_player.start()
        emit("audio_status", {"listening": sid in _audio_listeners, "talking": True})
    else:
        emit("audio_status", {"listening": sid in _audio_listeners, "talking": False, "error": "talk_slot_busy"})


@socketio.on("audio_talk_stop", namespace="/audio")
def audio_talk_stop():
    sid = request.sid
    audio_player.release_talk()
    logger.info("Audio WS: talk stopped (sid=%s)", sid)
    emit("audio_status", {"listening": sid in _audio_listeners, "talking": False})


@socketio.on("audio_talk", namespace="/audio")
def audio_talk(data):
    """Receive audio data from client and play through speaker."""
    if not audio_player.is_active:
        audio_player.start()

    if isinstance(data, (bytes, bytearray)):
        audio_player.play(bytes(data))


def _stream_audio_to_client(sid: str, q):
    """Background task: read from queue and emit audio chunks to client."""
    import queue as queue_module
    while sid in _audio_listeners:
        try:
            pcm_data = q.get(timeout=0.5)
            socketio.emit("audio_stream", pcm_data, namespace="/audio", to=sid)
        except queue_module.Empty:
            continue
        except Exception:
            break


# ===========================================================================
# Main entry
# ===========================================================================

def main():
    if not config.AUTH_TOKEN:
        logger.error("PET_CAMERA_TOKEN environment variable is not set. Exiting.")
        print("\n[ERROR] Set the PET_CAMERA_TOKEN environment variable before starting.\n")
        print("  Windows:  set PET_CAMERA_TOKEN=your-secret-token")
        print("  PowerShell: $env:PET_CAMERA_TOKEN='your-secret-token'\n")
        return

    # Start subsystems
    camera.start()
    audio_capture.start()
    audio_player.start()

    # TLS setup
    ssl_ctx = None
    if not config.IS_DEV:
        crt_files = glob.glob(os.path.join(config.CERT_DIR, "*.crt"))
        key_files = glob.glob(os.path.join(config.CERT_DIR, "*.key"))
        if crt_files and key_files:
            ssl_ctx = (crt_files[0], key_files[0])
            logger.info("TLS: using certificate %s", os.path.basename(crt_files[0]))
        else:
            logger.warning("TLS: No certificates found in %s — running without HTTPS", config.CERT_DIR)
            logger.warning("TLS: Audio (microphone) features may not work on mobile browsers")

    proto = "https" if ssl_ctx else "http"
    logger.info("Starting Pet Camera server at %s://%s:%d", proto, config.HOST, config.PORT)

    try:
        socketio.run(
            app,
            host=config.HOST,
            port=config.PORT,
            ssl_context=ssl_ctx,
            allow_unsafe_werkzeug=True,
        )
    finally:
        camera.stop()
        audio_capture.stop()
        audio_player.stop()


if __name__ == "__main__":
    main()
