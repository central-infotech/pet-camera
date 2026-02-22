"""Authentication middleware: token verification, session management, rate limiting, access logging."""

import functools
import hashlib
import logging
import os
import secrets
import time
from datetime import datetime, timezone

from flask import request, session, jsonify, redirect, url_for

from . import config

logger = logging.getLogger(__name__)

# In-memory rate limiting store: {ip: {"attempts": int, "blocked_until": float}}
_rate_limit_store: dict[str, dict] = {}

# In-memory session store: {session_id: {"created_at": float, "ip": str}}
_session_store: dict[str, dict] = {}


def _constant_time_compare(a: str, b: str) -> bool:
    return hashlib.sha256(a.encode()).hexdigest() == hashlib.sha256(b.encode()).hexdigest()


def _check_rate_limit(ip: str) -> tuple[bool, int]:
    """Check if IP is rate limited. Returns (is_blocked, retry_after_seconds)."""
    now = time.time()
    entry = _rate_limit_store.get(ip)

    if entry is None:
        return False, 0

    if entry.get("blocked_until", 0) > now:
        retry_after = int(entry["blocked_until"] - now) + 1
        return True, retry_after

    # Clean up expired window
    if now - entry.get("window_start", 0) > config.RATE_LIMIT_WINDOW_SECONDS:
        _rate_limit_store.pop(ip, None)
        return False, 0

    return False, 0


def _record_failed_attempt(ip: str):
    """Record a failed authentication attempt for rate limiting."""
    now = time.time()
    entry = _rate_limit_store.get(ip)

    if entry is None or now - entry.get("window_start", 0) > config.RATE_LIMIT_WINDOW_SECONDS:
        entry = {"attempts": 0, "window_start": now}
        _rate_limit_store[ip] = entry

    entry["attempts"] += 1

    if entry["attempts"] >= 3:
        logger.warning("Auth: %d consecutive failed attempts from %s", entry["attempts"], ip)

    if entry["attempts"] >= config.RATE_LIMIT_MAX_ATTEMPTS:
        entry["blocked_until"] = now + config.RATE_LIMIT_WINDOW_SECONDS
        logger.error("Auth: Rate limit triggered for %s — blocked for %ds", ip, config.RATE_LIMIT_WINDOW_SECONDS)


def _clear_rate_limit(ip: str):
    _rate_limit_store.pop(ip, None)


def verify_token(token: str) -> bool:
    if not config.AUTH_TOKEN:
        logger.warning("Auth: PET_CAMERA_TOKEN is not set — all tokens rejected")
        return False
    return _constant_time_compare(token, config.AUTH_TOKEN)


def create_session(is_display: bool = False) -> str:
    session_id = secrets.token_urlsafe(32)
    _session_store[session_id] = {
        "created_at": time.time(),
        "ip": request.remote_addr,
        "is_display": is_display,
    }
    return session_id


def validate_session(session_id: str) -> bool:
    entry = _session_store.get(session_id)
    if entry is None:
        return False
    ttl = config.DISPLAY_SESSION_TTL_SECONDS if entry.get("is_display") else config.SESSION_TTL_SECONDS
    if time.time() - entry["created_at"] > ttl:
        _session_store.pop(session_id, None)
        return False
    return True


def extend_session(session_id: str):
    """Extend the TTL of a display session (called on heartbeat)."""
    entry = _session_store.get(session_id)
    if entry and entry.get("is_display"):
        entry["created_at"] = time.time()


def invalidate_session(session_id: str):
    _session_store.pop(session_id, None)


def is_authenticated() -> bool:
    # Check session cookie
    sid = session.get("sid")
    if sid and validate_session(sid):
        return True

    # Check Bearer token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        return verify_token(token)

    return False


def login_required(f):
    """Decorator to require authentication for a route."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not is_authenticated():
            code = "AUTH_REQUIRED" if not request.headers.get("Authorization") and not session.get("sid") else "AUTH_INVALID"
            return jsonify({"error": {"code": code, "message": "Authentication required"}}), 401
        return f(*args, **kwargs)
    return decorated


def handle_auth_request():
    """Handle POST /api/auth — token verification with rate limiting."""
    ip = request.remote_addr

    # Check rate limit
    blocked, retry_after = _check_rate_limit(ip)
    if blocked:
        return jsonify({
            "error": {
                "code": "RATE_LIMITED",
                "message": f"Too many authentication attempts. Try again in {retry_after} seconds.",
                "retry_after_seconds": retry_after,
            }
        }), 429

    data = request.get_json(silent=True) or {}
    token = data.get("token", "")

    if verify_token(token):
        _clear_rate_limit(ip)
        sid = create_session()
        session["sid"] = sid
        resp = jsonify({"authenticated": True})
        return resp, 200
    else:
        _record_failed_attempt(ip)
        return jsonify({"error": {"code": "AUTH_INVALID", "message": "Invalid token"}}), 401


def handle_logout():
    """Handle POST /api/logout — invalidate session."""
    sid = session.pop("sid", None)
    if sid:
        invalidate_session(sid)
    return jsonify({"logged_out": True}), 200


def validate_socketio_auth(auth_data: dict | None) -> bool:
    """Validate Socket.IO handshake authentication."""
    # Check session cookie (Flask session is available during handshake)
    sid = session.get("sid") if session else None
    if sid and validate_session(sid):
        return True

    # Check auth parameter
    if auth_data and "token" in auth_data:
        return verify_token(auth_data["token"])

    return False


def setup_access_log(app):
    """Set up access logging middleware."""
    os.makedirs(config.LOG_DIR, exist_ok=True)
    access_log_path = os.path.join(config.LOG_DIR, "access.log")

    access_logger = logging.getLogger("access")
    access_logger.setLevel(logging.INFO)
    access_logger.propagate = False

    handler = logging.handlers.TimedRotatingFileHandler(
        access_log_path, when="midnight", backupCount=7, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    access_logger.addHandler(handler)

    @app.after_request
    def log_request(response):
        now = datetime.now(timezone.utc).astimezone().isoformat()
        ip = request.remote_addr
        method = request.method
        path = request.path
        status = response.status_code
        access_logger.info("%s | %s | %s %s | %s", now, ip, method, path, status)
        return response


import logging.handlers
