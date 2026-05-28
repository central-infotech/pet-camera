"""Audio module: microphone capture and speaker playback using sounddevice."""

import logging
import queue
import threading
import time

import numpy as np
import sounddevice as sd

from . import config

# Retry settings for audio device initialization
DEVICE_RETRY_INTERVAL = 10  # seconds between retries
DEVICE_MAX_RETRIES = 6      # max retries (60 seconds total)

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
        for attempt in range(1, DEVICE_MAX_RETRIES + 1):
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
                return
            except Exception:
                logger.exception("AudioCapture: failed to start microphone (attempt %d/%d)",
                                 attempt, DEVICE_MAX_RETRIES)
                if attempt < DEVICE_MAX_RETRIES:
                    logger.info("AudioCapture: retrying in %d seconds...", DEVICE_RETRY_INTERVAL)
                    time.sleep(DEVICE_RETRY_INTERVAL)
        logger.error("AudioCapture: all %d attempts exhausted, microphone unavailable",
                      DEVICE_MAX_RETRIES)

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
    """Plays received PCM audio through the speaker.

    play() is non-blocking: PCM is enqueued and written to the OutputStream by
    a dedicated worker thread. This keeps Socket.IO event handlers off the
    audio device, so a transient PortAudio stall cannot freeze the websocket
    connection. The queue is bounded; on overflow the oldest chunk is dropped
    to prevent latency build-up.
    """

    # Bounded playback queue. 16 chunks ≈ 1 s of audio at 1024 samples / 16 kHz.
    _PLAY_QUEUE_MAX = 16

    def __init__(self):
        self._stream: sd.OutputStream | None = None
        self._lock = threading.Lock()
        self._running = False
        self._talking_clients = 0
        self._play_queue: queue.Queue[bytes] = queue.Queue(maxsize=self._PLAY_QUEUE_MAX)
        self._writer_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self):
        if self._running:
            return
        for attempt in range(1, DEVICE_MAX_RETRIES + 1):
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
                self._stop_event.clear()
                self._writer_thread = threading.Thread(
                    target=self._writer_loop,
                    name="audio-player-writer",
                    daemon=True,
                )
                self._writer_thread.start()
                logger.info("AudioPlayer: speaker stream started (rate=%d, ch=%d, chunk=%d)",
                            config.AUDIO_SAMPLE_RATE, config.AUDIO_CHANNELS, config.AUDIO_CHUNK_SIZE)
                return
            except Exception:
                logger.exception("AudioPlayer: failed to start speaker (attempt %d/%d)",
                                 attempt, DEVICE_MAX_RETRIES)
                if attempt < DEVICE_MAX_RETRIES:
                    logger.info("AudioPlayer: retrying in %d seconds...", DEVICE_RETRY_INTERVAL)
                    time.sleep(DEVICE_RETRY_INTERVAL)
        logger.error("AudioPlayer: all %d attempts exhausted, speaker unavailable",
                      DEVICE_MAX_RETRIES)

    def stop(self):
        self._running = False
        self._stop_event.set()
        # Drain queue so the writer thread exits its blocking get() promptly.
        while True:
            try:
                self._play_queue.get_nowait()
            except queue.Empty:
                break
        if self._writer_thread and self._writer_thread.is_alive():
            self._writer_thread.join(timeout=2)
        self._writer_thread = None
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                logger.exception("AudioPlayer: error closing stream")
            self._stream = None
        logger.info("AudioPlayer: stopped")

    def play(self, pcm_data: bytes):
        """Enqueue PCM for asynchronous playback. Non-blocking.

        On overflow drops the oldest queued chunk so playback stays close to
        real time even if the device temporarily slows down.
        """
        if not self._running:
            return
        try:
            self._play_queue.put_nowait(pcm_data)
        except queue.Full:
            try:
                self._play_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._play_queue.put_nowait(pcm_data)
            except queue.Full:
                pass

    def _writer_loop(self):
        """Background worker: drain the queue into the OutputStream."""
        while not self._stop_event.is_set():
            try:
                pcm_data = self._play_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            stream = self._stream
            if stream is None:
                continue
            try:
                samples = np.frombuffer(pcm_data, dtype=np.int16)
                samples = samples.reshape(-1, config.AUDIO_CHANNELS)
                stream.write(samples)
            except sd.PortAudioError:
                logger.exception("AudioPlayer: PortAudio error, attempting stream reopen")
                self._reopen_stream()
            except Exception:
                logger.exception("AudioPlayer: playback error")

    def _reopen_stream(self):
        """Re-open the OutputStream after a device error. Called from the writer thread."""
        try:
            if self._stream:
                try:
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            self._stream = sd.OutputStream(
                samplerate=config.AUDIO_SAMPLE_RATE,
                channels=config.AUDIO_CHANNELS,
                dtype="int16",
                blocksize=config.AUDIO_CHUNK_SIZE,
            )
            self._stream.start()
            logger.info("AudioPlayer: stream re-opened after error")
        except Exception:
            logger.exception("AudioPlayer: stream re-open failed")

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
