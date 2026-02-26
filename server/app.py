"""Pet Camera streaming server — Flask + Flask-SocketIO."""

import glob
import logging
import os
import time
from datetime import datetime, timezone

from flask import Flask, Response, jsonify, render_template, request, send_from_directory, session
from flask_socketio import SocketIO, disconnect, emit, join_room, leave_room

from . import config
from .auth import (
    extend_session,
    handle_auth_request,
    handle_logout,
    is_authenticated,
    login_required,
    setup_access_log,
    validate_socketio_auth,
)
from .camera import Camera, enumerate_cameras, find_best_camera_index
from .audio import AudioCapture, AudioPlayer
from . import webauthn_auth
from . import webrtc

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

socketio = SocketIO(app, cors_allowed_origins=None, async_mode="threading",
                    manage_session=False)

# ---------------------------------------------------------------------------
# Subsystems
# ---------------------------------------------------------------------------
_camera_index = (
    config.CAMERA_INDEX
    if config.CAMERA_INDEX is not None
    else find_best_camera_index()
)
camera = Camera(camera_index=_camera_index)
logger.info("Camera: using index %d (config=%s)", _camera_index,
            "env" if config.CAMERA_INDEX is not None else "auto-detect")
audio_capture = AudioCapture()
audio_player = AudioPlayer()

# Server start time for uptime calculation
_start_time = time.time()

# Track connected clients
_connected_clients: set[str] = set()

# Track audio listeners: {sid: queue}
_audio_listeners: dict = {}

# Phase 2: Video relay state
_active_sender_sid: str | None = None  # SID of the client currently sending video
_display_clients: set[str] = set()  # SIDs of display clients
_video_client_roles: dict[str, str] = {}  # {sid: 'sender' | 'display'}
_last_frame_time: float = 0.0  # Rate limiting for incoming frames

# Exclusive session control: only one phone can use audio/video features at a time
_exclusive_ip: str | None = None  # IP that currently holds exclusive access
_sid_to_ip: dict[str, str] = {}  # socket sid → client IP (across both namespaces)
_talking_sid: str | None = None  # audio sid currently talking

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


@app.route("/sw.js")
def service_worker():
    """Serve service worker from root scope."""
    return send_from_directory(app.static_folder, "sw.js",
                               mimetype="application/javascript",
                               max_age=0)


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
        "camera_active": camera.is_active,
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

    # Reset WebRTC source track so next connection uses new camera settings
    webrtc.reset_source_track()

    return jsonify(result)


# --- Camera device selection ---

@app.route("/api/cameras", methods=["GET"])
@login_required
def list_cameras():
    """List available camera devices."""
    cameras = enumerate_cameras()
    return jsonify({
        "cameras": cameras,
        "current_index": camera.camera_index,
    })


@app.route("/api/cameras/current", methods=["PATCH"])
@login_required
def switch_camera_endpoint():
    """Switch to a different camera device."""
    data = request.get_json(silent=True)
    if not data or "index" not in data:
        return jsonify({"error": {"code": "INVALID_PARAMETER",
                                  "message": "index is required"}}), 400
    idx = data["index"]
    if not isinstance(idx, int) or idx < 0:
        return jsonify({"error": {"code": "INVALID_PARAMETER",
                                  "message": "index must be a non-negative integer"}}), 400

    camera.switch_camera(idx)
    webrtc.reset_source_track()

    return jsonify({"current_index": camera.camera_index})


# --- WebRTC ---

@app.route("/api/webrtc/offer", methods=["POST"])
@login_required
def webrtc_offer():
    """Accept a WebRTC SDP offer and return an answer."""
    data = request.get_json(silent=True)
    if not data or "sdp" not in data:
        return jsonify({"error": {"code": "INVALID_PARAMETER",
                                  "message": "SDP offer required"}}), 400

    import uuid
    pc_id = str(uuid.uuid4())[:8]
    session_id = session.get("sid", "")

    try:
        answer_sdp = webrtc.handle_offer(
            camera, data["sdp"], pc_id, session_id, config.WEBRTC_MAX_PEERS
        )
    except ValueError as e:
        if "TOO_MANY_PEERS" in str(e):
            return jsonify({"error": {"code": "TOO_MANY_PEERS",
                                      "message": "Maximum connections reached"}}), 429
        return jsonify({"error": {"code": "WEBRTC_ERROR",
                                  "message": str(e)}}), 500
    except Exception as e:
        logger.exception("WebRTC: offer handling failed")
        return jsonify({"error": {"code": "WEBRTC_ERROR",
                                  "message": str(e)}}), 500

    return jsonify({"sdp": answer_sdp, "type": "answer", "pc_id": pc_id})


@app.route("/api/webrtc/<pc_id>", methods=["DELETE"])
@login_required
def webrtc_close(pc_id):
    """Close a WebRTC connection (owner only)."""
    session_id = session.get("sid", "")
    ok = webrtc.close_peer(pc_id, session_id)
    if not ok:
        return jsonify({"error": {"code": "FORBIDDEN",
                                  "message": "Not the owner of this connection"}}), 403
    return jsonify({"closed": True})


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


# --- Phase 2: Display route ---

@app.route("/display")
def display():
    if is_authenticated():
        # Upgrade to display session (30-day TTL) if not already
        from .auth import create_session as _create_session, _session_store
        sid = session.get("sid")
        entry = _session_store.get(sid) if sid else None
        if entry and not entry.get("is_display"):
            new_sid = _create_session(is_display=True)
            session["sid"] = new_sid
        return render_template("display.html")
    return render_template("login.html")


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
# Exclusive session control helpers
# ===========================================================================

def _check_and_claim_exclusive(client_ip: str) -> bool:
    """Check if this IP can use features, and claim exclusive if not yet held."""
    global _exclusive_ip
    if client_ip is None:
        return False
    if _exclusive_ip is None:
        _exclusive_ip = client_ip
        logger.info("Exclusive: claimed by %s", client_ip)
        _broadcast_exclusive_status()
        return True
    return _exclusive_ip == client_ip


def _is_feature_active_for_ip(ip: str) -> bool:
    """Check if any feature (listen/talk/video) is active for the given IP."""
    for sid in _audio_listeners:
        if _sid_to_ip.get(sid) == ip:
            return True
    if _talking_sid is not None and _sid_to_ip.get(_talking_sid) == ip:
        return True
    if _active_sender_sid is not None and _sid_to_ip.get(_active_sender_sid) == ip:
        return True
    return False


def _maybe_release_exclusive():
    """Release exclusive access if the holding IP has no active features."""
    global _exclusive_ip
    if _exclusive_ip is None:
        return
    if not _is_feature_active_for_ip(_exclusive_ip):
        logger.info("Exclusive: released by %s", _exclusive_ip)
        _exclusive_ip = None
        _broadcast_exclusive_status()


def _broadcast_exclusive_status():
    """Notify all audio-connected clients about their blocked/unblocked status."""
    for sid in list(_connected_clients):
        client_ip = _sid_to_ip.get(sid)
        is_blocked = _exclusive_ip is not None and client_ip != _exclusive_ip
        try:
            socketio.emit("exclusive_status", {"blocked": is_blocked},
                          namespace="/audio", to=sid)
        except Exception:
            pass


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
    _sid_to_ip[sid] = request.remote_addr
    logger.info("Audio WS: client connected (sid=%s, ip=%s, total=%d)",
                sid, request.remote_addr, len(_connected_clients))

    # Send initial exclusive status
    client_ip = request.remote_addr
    is_blocked = _exclusive_ip is not None and client_ip != _exclusive_ip
    emit("exclusive_status", {"blocked": is_blocked})


@socketio.on("disconnect", namespace="/audio")
def audio_disconnect():
    global _talking_sid
    sid = request.sid
    _connected_clients.discard(sid)

    # Clean up listener if active
    q = _audio_listeners.pop(sid, None)
    if q:
        audio_capture.remove_listener(q)

    # Release talk slot only if this client held it
    if _talking_sid == sid:
        _talking_sid = None
        audio_player.release_talk()

    # Clean up IP tracking
    _sid_to_ip.pop(sid, None)
    logger.info("Audio WS: client disconnected (sid=%s)", sid)

    _maybe_release_exclusive()


@socketio.on("audio_listen_start", namespace="/audio")
def audio_listen_start():
    try:
        sid = request.sid
        client_ip = _sid_to_ip.get(sid)

        # Exclusive session check
        if not _check_and_claim_exclusive(client_ip):
            emit("audio_status", {"listening": False, "error": "exclusive_blocked"})
            return

        if sid in _audio_listeners:
            return  # Already listening

        if not audio_capture.is_active:
            audio_capture.start()

        q = audio_capture.add_listener()
        _audio_listeners[sid] = q

        # Start a background task to stream audio to this client
        socketio.start_background_task(_stream_audio_to_client, sid, q)

        emit("audio_status", {"listening": True, "talking_clients": audio_player.talking_clients})
    except Exception:
        logger.exception("audio_listen_start handler error")


@socketio.on("audio_listen_stop", namespace="/audio")
def audio_listen_stop():
    try:
        sid = request.sid
        q = _audio_listeners.pop(sid, None)
        if q:
            audio_capture.remove_listener(q)
        emit("audio_status", {"listening": False, "talking_clients": audio_player.talking_clients})
        _maybe_release_exclusive()
    except Exception:
        logger.exception("audio_listen_stop handler error")


@socketio.on("audio_talk_start", namespace="/audio")
def audio_talk_start():
    global _talking_sid
    try:
        sid = request.sid
        client_ip = _sid_to_ip.get(sid)

        # Exclusive session check
        if not _check_and_claim_exclusive(client_ip):
            emit("audio_status", {"talking": False, "error": "exclusive_blocked"})
            return

        if audio_player.acquire_talk():
            _talking_sid = sid
            logger.info("Audio WS: talk started (sid=%s)", sid)
            if not audio_player.is_active:
                audio_player.start()
            emit("audio_status", {"listening": sid in _audio_listeners, "talking": True})
        else:
            emit("audio_status", {"listening": sid in _audio_listeners, "talking": False, "error": "talk_slot_busy"})
    except Exception:
        logger.exception("audio_talk_start handler error")


@socketio.on("audio_talk_stop", namespace="/audio")
def audio_talk_stop():
    global _talking_sid
    try:
        sid = request.sid
        if _talking_sid == sid:
            _talking_sid = None
        audio_player.release_talk()
        logger.info("Audio WS: talk stopped (sid=%s)", sid)
        emit("audio_status", {"listening": sid in _audio_listeners, "talking": False})
        _maybe_release_exclusive()
    except Exception:
        logger.exception("audio_talk_stop handler error")


@socketio.on("audio_talk", namespace="/audio")
def audio_talk(data):
    """Receive audio data from client and play through speaker."""
    try:
        sid = request.sid

        # Only accept audio from the client that holds the talk slot
        if _talking_sid != sid:
            return

        if not audio_player.is_active:
            audio_player.start()

        if isinstance(data, (bytes, bytearray)):
            audio_player.play(bytes(data))
    except Exception:
        logger.exception("audio_talk handler error")


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
# Socket.IO — Video namespace (Phase 2)
# ===========================================================================

@socketio.on("connect", namespace="/video")
def video_connect(auth_data=None):
    if not validate_socketio_auth(auth_data):
        logger.warning("Video WS: rejected unauthenticated connection from %s", request.remote_addr)
        disconnect()
        return False

    # Validate role
    role = (auth_data or {}).get("role") if auth_data else None
    if role not in ("sender", "display"):
        logger.warning("Video WS: rejected connection without valid role from %s", request.remote_addr)
        disconnect()
        return False

    sid = request.sid
    _video_client_roles[sid] = role
    _sid_to_ip[sid] = request.remote_addr
    logger.info("Video WS: %s connected (sid=%s, role=%s)", request.remote_addr, sid, role)


@socketio.on("disconnect", namespace="/video")
def video_disconnect():
    global _active_sender_sid
    try:
        sid = request.sid
        role = _video_client_roles.pop(sid, None)

        if role == "sender" and _active_sender_sid == sid:
            _active_sender_sid = None
            logger.info("Video WS: sender disconnected, releasing send slot (sid=%s)", sid)
            socketio.emit("video_status", _build_video_status(), namespace="/video")

        if role == "display":
            _display_clients.discard(sid)
            logger.info("Video WS: display client left (sid=%s, remaining=%d)", sid, len(_display_clients))
            socketio.emit("video_status", _build_video_status(), namespace="/video")

        _sid_to_ip.pop(sid, None)
        _maybe_release_exclusive()
    except Exception:
        logger.exception("video_disconnect handler error")


@socketio.on("video_send_start", namespace="/video")
def video_send_start(data=None):
    global _active_sender_sid
    try:
        sid = request.sid
        client_ip = _sid_to_ip.get(sid)

        if _video_client_roles.get(sid) != "sender":
            return

        # Exclusive session check
        if not _check_and_claim_exclusive(client_ip):
            emit("video_error", {"code": "EXCLUSIVE_BLOCKED",
                                 "message": "Another device is currently using the system"})
            return

        if _active_sender_sid is not None and _active_sender_sid != sid:
            emit("video_error", {"code": "SENDER_BUSY", "message": "Another device is already sending"})
            return

        _active_sender_sid = sid
        info = data if isinstance(data, dict) else {}
        logger.info("Video WS: send started (sid=%s, %s)", sid,
                    f"{info.get('width', '?')}x{info.get('height', '?')}@{info.get('fps', '?')}fps")
        socketio.emit("video_status", _build_video_status(), namespace="/video")
    except Exception:
        logger.exception("video_send_start handler error")


@socketio.on("video_send_stop", namespace="/video")
def video_send_stop():
    global _active_sender_sid
    try:
        sid = request.sid

        if _active_sender_sid == sid:
            _active_sender_sid = None
            logger.info("Video WS: send stopped (sid=%s)", sid)
            socketio.emit("video_status", _build_video_status(), namespace="/video")
            _maybe_release_exclusive()
    except Exception:
        logger.exception("video_send_stop handler error")


@socketio.on("video_frame", namespace="/video")
def video_frame(data):
    global _last_frame_time
    try:
        sid = request.sid

        # Only accept from active sender
        if _video_client_roles.get(sid) != "sender" or _active_sender_sid != sid:
            return

        if not isinstance(data, (bytes, bytearray)):
            return

        # Frame size limit
        if len(data) > config.VIDEO_FRAME_MAX_BYTES:
            return

        # Rate limit
        now = time.time()
        min_interval = 1.0 / config.VIDEO_MAX_FPS
        if now - _last_frame_time < min_interval:
            return
        _last_frame_time = now

        # Relay to all display clients
        for display_sid in list(_display_clients):
            socketio.emit("video_frame", data, namespace="/video", to=display_sid)
    except Exception:
        logger.exception("video_frame handler error")


@socketio.on("display_join", namespace="/video")
def display_join():
    try:
        sid = request.sid
        if _video_client_roles.get(sid) != "display":
            return

        _display_clients.add(sid)
        join_room("display", sid=sid, namespace="/video")
        logger.info("Video WS: display client joined (sid=%s, total=%d)", sid, len(_display_clients))
        emit("video_status", _build_video_status())
    except Exception:
        logger.exception("display_join handler error")


@socketio.on("display_leave", namespace="/video")
def display_leave():
    try:
        sid = request.sid
        _display_clients.discard(sid)
        leave_room("display", sid=sid, namespace="/video")
        logger.info("Video WS: display client left (sid=%s, total=%d)", sid, len(_display_clients))
        socketio.emit("video_status", _build_video_status(), namespace="/video")
    except Exception:
        logger.exception("display_leave handler error")


@socketio.on("display_heartbeat", namespace="/video")
def display_heartbeat():
    """Extend display session TTL on periodic heartbeat."""
    try:
        sid_cookie = session.get("sid") if session else None
        if sid_cookie:
            extend_session(sid_cookie)
    except Exception:
        logger.exception("display_heartbeat handler error")


def _build_video_status() -> dict:
    return {
        "sending": _active_sender_sid is not None,
        "display_clients": len(_display_clients),
    }


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

    # Production: require explicit HOST (Tailscale IP)
    if not config.IS_DEV and not config.HOST:
        logger.error("PET_CAMERA_HOST environment variable is not set. In production, bind address must be explicit.")
        print("\n[ERROR] Set PET_CAMERA_HOST to your Tailscale IP (e.g. 100.x.x.x).\n")
        print("  Windows:  set PET_CAMERA_HOST=100.x.x.x")
        print("  PowerShell: $env:PET_CAMERA_HOST='100.x.x.x'\n")
        return

    # Start subsystems (webrtc first so asyncio loop is ready before requests)
    webrtc.start()
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
            logger.error("TLS: No certificates found in %s — HTTPS is required in production", config.CERT_DIR)
            print("\n[ERROR] HTTPS is required in production mode.")
            print("  Place certificate (.crt) and key (.key) files in the 'certs/' directory.")
            print("  Use 'tailscale cert <hostname>' to generate them.")
            print("  To run without HTTPS, set PET_CAMERA_ENV=development\n")
            return

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
        webrtc.stop()


if __name__ == "__main__":
    main()
