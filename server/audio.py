"""Audio module: microphone capture and speaker playback using sounddevice."""

import logging
import queue
import threading

import numpy as np
import sounddevice as sd

from . import config

logger = logging.getLogger(__name__)


class AudioCapture:
    """Captures audio from microphone and distributes PCM chunks to listeners."""

    def __init__(self):
        self._listeners: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._stream: sd.InputStream | None = None
        self._running = False

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info, status):
        if status:
            logger.warning("AudioCapture: %s", status)
        pcm_bytes = indata.tobytes()
        with self._lock:
            dead = []
            for q in self._listeners:
                try:
                    q.put_nowait(pcm_bytes)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._listeners.remove(q)

    def start(self):
        if self._running:
            return
        try:
            devices = sd.query_devices()
            default_in = sd.default.device[0]
            logger.info("AudioCapture: available devices:\n%s", devices)
            logger.info("AudioCapture: using default input device: %s", default_in)
            self._stream = sd.InputStream(
                samplerate=config.AUDIO_SAMPLE_RATE,
                channels=config.AUDIO_CHANNELS,
                dtype="int16",
                blocksize=config.AUDIO_CHUNK_SIZE,
                callback=self._audio_callback,
            )
            self._stream.start()
            self._running = True
            logger.info("AudioCapture: microphone stream started (rate=%d, ch=%d, chunk=%d)",
                        config.AUDIO_SAMPLE_RATE, config.AUDIO_CHANNELS, config.AUDIO_CHUNK_SIZE)
        except Exception:
            logger.exception("AudioCapture: failed to start microphone")

    def stop(self):
        self._running = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        logger.info("AudioCapture: stopped")

    def add_listener(self) -> queue.Queue:
        q = queue.Queue(maxsize=50)
        with self._lock:
            self._listeners.append(q)
        logger.info("AudioCapture: listener added (total=%d)", len(self._listeners))
        return q

    def remove_listener(self, q: queue.Queue):
        with self._lock:
            if q in self._listeners:
                self._listeners.remove(q)
        logger.info("AudioCapture: listener removed (total=%d)", len(self._listeners))

    @property
    def is_active(self) -> bool:
        return self._running and self._stream is not None

    @property
    def listener_count(self) -> int:
        with self._lock:
            return len(self._listeners)


class AudioPlayer:
    """Plays received PCM audio through the speaker."""

    def __init__(self):
        self._stream: sd.OutputStream | None = None
        self._lock = threading.Lock()
        self._running = False
        self._talking_clients = 0

    def start(self):
        if self._running:
            return
        try:
            default_out = sd.default.device[1]
            logger.info("AudioPlayer: using default output device: %s", default_out)
            self._stream = sd.OutputStream(
                samplerate=config.AUDIO_SAMPLE_RATE,
                channels=config.AUDIO_CHANNELS,
                dtype="int16",
                blocksize=config.AUDIO_CHUNK_SIZE,
            )
            self._stream.start()
            self._running = True
            logger.info("AudioPlayer: speaker stream started (rate=%d, ch=%d, chunk=%d)",
                        config.AUDIO_SAMPLE_RATE, config.AUDIO_CHANNELS, config.AUDIO_CHUNK_SIZE)
        except Exception:
            logger.exception("AudioPlayer: failed to start speaker")

    def stop(self):
        self._running = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        logger.info("AudioPlayer: stopped")

    def play(self, pcm_data: bytes):
        if not self._running or not self._stream:
            return
        try:
            samples = np.frombuffer(pcm_data, dtype=np.int16)
            samples = samples.reshape(-1, config.AUDIO_CHANNELS)
            self._stream.write(samples)
        except Exception:
            logger.exception("AudioPlayer: playback error")

    def acquire_talk(self) -> bool:
        """Try to acquire talk slot (only 1 client can talk at a time)."""
        with self._lock:
            if self._talking_clients > 0:
                return False
            self._talking_clients = 1
            return True

    def release_talk(self):
        with self._lock:
            self._talking_clients = max(0, self._talking_clients - 1)

    @property
    def is_active(self) -> bool:
        return self._running and self._stream is not None

    @property
    def talking_clients(self) -> int:
        with self._lock:
            return self._talking_clients
