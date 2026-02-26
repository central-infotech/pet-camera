"""Pet Camera configuration."""

import os

# Environment
ENV = os.environ.get("PET_CAMERA_ENV", "production")
IS_DEV = ENV == "development"

# Auth
AUTH_TOKEN = os.environ.get("PET_CAMERA_TOKEN", "")
SESSION_TTL_SECONDS = 24 * 60 * 60  # 24 hours
RATE_LIMIT_MAX_ATTEMPTS = 5
RATE_LIMIT_WINDOW_SECONDS = 300  # 5 minutes

# Server
# Production: PET_CAMERA_HOST must be explicitly set (e.g. Tailscale IP 100.x.x.x)
# Development: defaults to 0.0.0.0
HOST = os.environ.get("PET_CAMERA_HOST", "0.0.0.0" if IS_DEV else "")
PORT = 5555
SECRET_KEY = os.environ.get("PET_CAMERA_SECRET", os.urandom(32).hex())

# Camera defaults
# Set PET_CAMERA_INDEX to a specific device index, or leave unset for auto-detect
CAMERA_INDEX: int | None = (
    int(os.environ["PET_CAMERA_INDEX"])
    if os.environ.get("PET_CAMERA_INDEX", "").strip()
    else None  # None = auto-detect (skip IR cameras)
)
DEFAULT_RESOLUTION = (1280, 720)
DEFAULT_FPS = 15
DEFAULT_BRIGHTNESS = 50
DEFAULT_CONTRAST = 50
VALID_RESOLUTIONS = [(640, 480), (1280, 720), (1920, 1080)]
VALID_FPS = [5, 10, 15, 30]

# Audio
AUDIO_SAMPLE_RATE = 16000
AUDIO_CHANNELS = 1
AUDIO_CHUNK_SIZE = 1024  # samples per chunk (~64ms at 16kHz)

# Video relay (Phase 2)
VIDEO_FRAME_MAX_BYTES = 200 * 1024  # 200 KB max per frame
VIDEO_MAX_FPS = 15  # server-side rate limit

# Display session
DISPLAY_SESSION_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days

# Snapshots
SNAPSHOT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "snapshots")
SNAPSHOT_MAX_BYTES = 500 * 1024 * 1024  # 500 MB

# Logs
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")

# WebRTC
WEBRTC_DEFAULT_FPS = 10  # WebRTC 配信時のデフォルト FPS
WEBRTC_MAX_PEERS = 3     # 同時接続数の上限

# TLS
CERT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "certs")
