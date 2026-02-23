"""WebRTC streaming module using aiortc.

Flask threads call only the public API (start, stop, peer_count, handle_offer,
close_peer, reset_source_track).  All shared state lives inside the asyncio
event loop to avoid TOCTOU and thread-safety issues.
"""

import asyncio
import fractions
import logging
import threading
import time

from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
from aiortc.contrib.media import MediaRelay
from av import VideoFrame

from . import config

logger = logging.getLogger(__name__)

# ─── Private state (only accessed inside the asyncio loop) ───────────────

_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None
_peer_connections: dict[str, RTCPeerConnection] = {}  # {pc_id: pc}
_pc_sessions: dict[str, str] = {}  # {pc_id: session_id} — owner tracking
_relay: MediaRelay | None = None
_source_track: "CameraVideoTrack | None" = None
_disconnect_timers: dict[str, asyncio.TimerHandle] = {}  # {pc_id: timer}

DISCONNECTED_TIMEOUT = 30  # seconds


# ─── CameraVideoTrack ───────────────────────────────────────────────────


class CameraVideoTrack(MediaStreamTrack):
    """Camera -> WebRTC video track.

    Always returns the latest frame from Camera to prevent latency build-up.
    """

    kind = "video"

    def __init__(self, camera, fps: int = 10):
        super().__init__()
        self._camera = camera
        self._fps = fps
        self._start: float | None = None
        self._count = 0

    async def recv(self) -> VideoFrame:
        if self._start is None:
            self._start = time.time()

        # Pacing to target FPS
        target_time = self._count / self._fps
        elapsed = time.time() - self._start
        wait = target_time - elapsed
        if wait > 0:
            await asyncio.sleep(wait)

        # Grab latest raw frame (thread-safe via Camera._lock)
        raw = self._camera.get_frame_raw()
        if raw is None:
            # Camera not ready — throttle to 1fps to save CPU
            await asyncio.sleep(1)
            import numpy as np
            raw = np.zeros((720, 1280, 3), dtype=np.uint8)

        frame = VideoFrame.from_ndarray(raw, format="bgr24")

        # Stable PTS based on frame count (avoids asyncio.sleep jitter)
        frame.pts = int(self._count * 90000 / self._fps)
        frame.time_base = fractions.Fraction(1, 90000)

        self._count += 1
        return frame


# ─── Public API (callable from Flask threads) ───────────────────────────


def start():
    """Start the asyncio event loop in a daemon thread."""
    global _loop, _loop_thread, _relay
    _loop = asyncio.new_event_loop()
    _relay = MediaRelay()
    _loop_thread = threading.Thread(target=_loop.run_forever, daemon=True)
    _loop_thread.start()
    logger.info("WebRTC: asyncio event loop started")


def stop():
    """Shut down: close all connections and stop the event loop."""
    global _loop, _loop_thread
    if _loop is None:
        return
    future = asyncio.run_coroutine_threadsafe(_close_all(), _loop)
    try:
        future.result(timeout=5)
    except Exception:
        logger.exception("WebRTC: error closing connections")
    _loop.call_soon_threadsafe(_loop.stop)
    if _loop_thread:
        _loop_thread.join(timeout=5)
    _loop = None
    _loop_thread = None
    logger.info("WebRTC: stopped")


def peer_count() -> int:
    """Return the number of active peer connections (safe to call from any thread)."""
    return len(_peer_connections)


def handle_offer(camera, offer_sdp: str, pc_id: str, session_id: str,
                 max_peers: int) -> str:
    """Process an SDP offer and return the answer SDP.

    The peer-count check and registration happen atomically inside the asyncio
    loop to prevent TOCTOU races.

    Raises:
        RuntimeError: event loop not started
        ValueError: TOO_MANY_PEERS
    """
    if _loop is None:
        raise RuntimeError("WebRTC event loop not started")
    future = asyncio.run_coroutine_threadsafe(
        _create_peer_connection(camera, offer_sdp, pc_id, session_id, max_peers),
        _loop,
    )
    return future.result(timeout=10)


def close_peer(pc_id: str, session_id: str | None = None) -> bool:
    """Close a PeerConnection.  Returns False if session mismatch."""
    if _loop is None:
        return True
    future = asyncio.run_coroutine_threadsafe(
        _cleanup_pc(pc_id, session_id), _loop
    )
    return future.result(timeout=5)


def reset_source_track():
    """Reset the shared source track (call after camera settings change)."""
    if _loop is None:
        return
    asyncio.run_coroutine_threadsafe(_reset_source(), _loop)


# ─── Internal async helpers (run inside the asyncio loop) ────────────────


async def _reset_source():
    global _source_track
    if _source_track:
        _source_track.stop()
    _source_track = None


async def _create_peer_connection(camera, offer_sdp: str, pc_id: str,
                                  session_id: str, max_peers: int) -> str:
    """Create a PeerConnection and return the answer SDP.

    Peer-count check + registration is atomic (runs in the single-threaded
    asyncio loop).
    """
    global _source_track

    # ── Atomic peer limit check ──
    if len(_peer_connections) >= max_peers:
        raise ValueError("TOO_MANY_PEERS")

    pc = RTCPeerConnection()
    _peer_connections[pc_id] = pc
    _pc_sessions[pc_id] = session_id

    # ── Connection-state monitoring ──

    @pc.on("connectionstatechange")
    async def on_connection_state_change():
        state = pc.connectionState
        logger.info("WebRTC [%s]: connectionState -> %s", pc_id, state)

        if state == "connected":
            _cancel_disconnect_timer(pc_id)
        elif state == "disconnected":
            _start_disconnect_timer(pc_id)
        elif state in ("failed", "closed"):
            _cancel_disconnect_timer(pc_id)
            await _cleanup_pc(pc_id)

    @pc.on("iceconnectionstatechange")
    async def on_ice_state_change():
        state = pc.iceConnectionState
        logger.info("WebRTC [%s]: iceConnectionState -> %s", pc_id, state)
        if state == "failed":
            _cancel_disconnect_timer(pc_id)
            await _cleanup_pc(pc_id)

    # ── Add video track ──

    if _source_track is None:
        _source_track = CameraVideoTrack(camera, fps=config.WEBRTC_DEFAULT_FPS)

    relayed = _relay.subscribe(_source_track)
    pc.addTrack(relayed)

    # ── SDP exchange ──

    offer = RTCSessionDescription(sdp=offer_sdp, type="offer")
    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    logger.info(
        "WebRTC [%s]: peer connection created (session=%s, total=%d)",
        pc_id,
        session_id[:8] if session_id else "?",
        len(_peer_connections),
    )
    return pc.localDescription.sdp


# ─── Disconnect timeout ─────────────────────────────────────────────────


def _start_disconnect_timer(pc_id: str):
    _cancel_disconnect_timer(pc_id)

    async def _on_timeout():
        pc = _peer_connections.get(pc_id)
        if pc and pc.connectionState == "disconnected":
            logger.warning(
                "WebRTC [%s]: disconnected timeout (%ds), forcing cleanup",
                pc_id, DISCONNECTED_TIMEOUT,
            )
            await _cleanup_pc(pc_id)

    handle = _loop.call_later(
        DISCONNECTED_TIMEOUT,
        lambda: asyncio.ensure_future(_on_timeout()),
    )
    _disconnect_timers[pc_id] = handle
    logger.info("WebRTC [%s]: disconnect timer started (%ds)", pc_id, DISCONNECTED_TIMEOUT)


def _cancel_disconnect_timer(pc_id: str):
    handle = _disconnect_timers.pop(pc_id, None)
    if handle:
        handle.cancel()


# ─── Cleanup ─────────────────────────────────────────────────────────────


async def _cleanup_pc(pc_id: str, required_session: str | None = None) -> bool:
    """Clean up a PeerConnection.

    If *required_session* is given, only close when the owner matches.
    Returns True if closed (or already gone), False on session mismatch.
    """
    if required_session is not None:
        owner = _pc_sessions.get(pc_id)
        if owner is not None and owner != required_session:
            logger.warning("WebRTC [%s]: close rejected (session mismatch)", pc_id)
            return False

    _cancel_disconnect_timer(pc_id)
    _pc_sessions.pop(pc_id, None)
    pc = _peer_connections.pop(pc_id, None)
    if pc:
        # Explicitly stop relayed tracks before closing
        for sender in pc.getSenders():
            if sender.track:
                sender.track.stop()
        await pc.close()
        logger.info("WebRTC [%s]: cleaned up (remaining=%d)", pc_id, len(_peer_connections))
    return True


async def _close_all():
    """Close every PeerConnection (shutdown helper)."""
    for pc_id in list(_disconnect_timers):
        _cancel_disconnect_timer(pc_id)
    coros = [pc.close() for pc in _peer_connections.values()]
    if coros:
        await asyncio.gather(*coros, return_exceptions=True)
    _peer_connections.clear()
    _pc_sessions.clear()
