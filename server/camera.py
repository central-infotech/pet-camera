"""Camera control module: OpenCV webcam capture and settings management."""

import logging
import threading
import time

import cv2
import numpy as np

from . import config

logger = logging.getLogger(__name__)


def enumerate_cameras(max_index: int = 10) -> list[dict]:
    """Probe camera indices and return list of available cameras.

    Each entry contains:
      - index: int
      - name: str (backend-reported name, or fallback)
      - width, height: native resolution reported by the device
      - is_ir: bool heuristic — True if the device looks like an IR camera
    """
    cameras: list[dict] = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            continue

        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        backend = cap.getBackendName()

        # Read a test frame to detect IR camera (very dark / grayscale)
        is_ir = False
        ret, frame = cap.read()
        if ret and frame is not None:
            # IR cameras produce very dark frames or single-channel-like output
            mean_val = float(np.mean(frame))
            # Check if the image is effectively grayscale (R≈G≈B)
            if len(frame.shape) == 3 and frame.shape[2] == 3:
                b, g, r = cv2.split(frame)
                diff_rg = float(np.mean(np.abs(r.astype(int) - g.astype(int))))
                diff_rb = float(np.mean(np.abs(r.astype(int) - b.astype(int))))
                # IR cameras tend to produce near-grayscale with very low brightness
                if mean_val < 5 or (mean_val < 30 and diff_rg < 3 and diff_rb < 3):
                    is_ir = True
            elif mean_val < 5:
                is_ir = True

        cap.release()

        name = f"Camera {i} ({backend})"
        cameras.append({
            "index": i,
            "name": name,
            "width": w,
            "height": h,
            "is_ir": is_ir,
        })

    return cameras


def find_best_camera_index() -> int:
    """Auto-detect the best (non-IR) camera index."""
    cameras = enumerate_cameras()
    if not cameras:
        return 0
    # Prefer non-IR cameras
    for cam in cameras:
        if not cam["is_ir"]:
            return cam["index"]
    # Fallback to first camera
    return cameras[0]["index"]


class Camera:
    def __init__(self, camera_index: int = 0):
        self._index = camera_index
        self._cap: cv2.VideoCapture | None = None
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._frame_count = 0
        self._fps_actual = 0.0
        self._fps_timer = time.time()
        self._running = False
        self._thread: threading.Thread | None = None

        # Current settings
        self._resolution = list(config.DEFAULT_RESOLUTION)
        self._fps = config.DEFAULT_FPS
        self._brightness = config.DEFAULT_BRIGHTNESS
        self._contrast = config.DEFAULT_CONTRAST

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        logger.info("Camera: capture thread started (index=%d)", self._index)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        if self._cap:
            self._cap.release()
            self._cap = None
        logger.info("Camera: stopped")

    def _open(self) -> bool:
        try:
            self._cap = cv2.VideoCapture(self._index, cv2.CAP_DSHOW)
            if not self._cap.isOpened():
                logger.error("Camera: failed to open camera index %d", self._index)
                return False
            self._apply_settings()
            logger.info("Camera: opened successfully (index=%d)", self._index)
            return True
        except Exception:
            logger.exception("Camera: error opening camera")
            return False

    def _apply_settings(self):
        if not self._cap:
            return
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._resolution[0])
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._resolution[1])
        self._cap.set(cv2.CAP_PROP_FPS, self._fps)
        self._cap.set(cv2.CAP_PROP_BRIGHTNESS, self._brightness / 100.0 * 255)
        self._cap.set(cv2.CAP_PROP_CONTRAST, self._contrast / 100.0 * 255)

    def _capture_loop(self):
        while self._running:
            if self._cap is None or not self._cap.isOpened():
                if not self._open():
                    logger.warning("Camera: retrying in 5 seconds...")
                    time.sleep(5)
                    continue

            ret, frame = self._cap.read()
            if not ret:
                logger.warning("Camera: frame read failed, reopening...")
                self._cap.release()
                self._cap = None
                time.sleep(1)
                continue

            with self._lock:
                self._frame = frame
                self._frame_count += 1

            # Calculate actual FPS every second
            now = time.time()
            elapsed = now - self._fps_timer
            if elapsed >= 1.0:
                self._fps_actual = self._frame_count / elapsed
                self._frame_count = 0
                self._fps_timer = now

            # Throttle to target FPS
            time.sleep(max(0, 1.0 / self._fps - 0.005))

    def get_frame_jpeg(self, quality: int = 85) -> bytes | None:
        with self._lock:
            if self._frame is None:
                return None
            _, buf = cv2.imencode(".jpg", self._frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
            return buf.tobytes()

    def get_frame_raw(self) -> np.ndarray | None:
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    def generate_mjpeg(self):
        """Generator yielding MJPEG frames for streaming."""
        while True:
            jpeg = self.get_frame_jpeg()
            if jpeg is None:
                time.sleep(0.1)
                continue
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n"
                b"\r\n" + jpeg + b"\r\n"
            )
            time.sleep(1.0 / self._fps)

    def get_settings(self) -> dict:
        return {
            "resolution": {"width": self._resolution[0], "height": self._resolution[1]},
            "fps": self._fps,
            "brightness": self._brightness,
            "contrast": self._contrast,
        }

    def update_settings(self, settings: dict) -> tuple[dict | None, str | None]:
        """Update camera settings. Returns (new_settings, error_message)."""
        known_keys = {"resolution", "fps", "brightness", "contrast"}
        unknown = set(settings.keys()) - known_keys
        if unknown:
            return None, f"Unknown parameters: {', '.join(unknown)}"

        new_res = self._resolution[:]
        new_fps = self._fps
        new_brightness = self._brightness
        new_contrast = self._contrast

        if "resolution" in settings:
            res = settings["resolution"]
            if not isinstance(res, dict) or "width" not in res or "height" not in res:
                return None, "resolution must contain width and height"
            w, h = res["width"], res["height"]
            if (w, h) not in config.VALID_RESOLUTIONS:
                valid = ", ".join(f"{r[0]}x{r[1]}" for r in config.VALID_RESOLUTIONS)
                return None, f"Invalid resolution. Valid: {valid}"
            new_res = [w, h]

        if "fps" in settings:
            fps = settings["fps"]
            if fps not in config.VALID_FPS:
                return None, f"Invalid fps. Valid: {config.VALID_FPS}"
            new_fps = fps

        if "brightness" in settings:
            b = settings["brightness"]
            if not isinstance(b, int) or not (0 <= b <= 100):
                return None, "brightness must be between 0 and 100"
            new_brightness = b

        if "contrast" in settings:
            c = settings["contrast"]
            if not isinstance(c, int) or not (0 <= c <= 100):
                return None, "contrast must be between 0 and 100"
            new_contrast = c

        self._resolution = new_res
        self._fps = new_fps
        self._brightness = new_brightness
        self._contrast = new_contrast
        self._apply_settings()

        logger.info("Camera: settings updated — %s", self.get_settings())
        return self.get_settings(), None

    @property
    def fps_actual(self) -> float:
        return round(self._fps_actual, 1)

    @property
    def resolution_str(self) -> str:
        return f"{self._resolution[0]}x{self._resolution[1]}"

    @property
    def camera_index(self) -> int:
        return self._index

    def switch_camera(self, new_index: int):
        """Switch to a different camera device by index."""
        if new_index == self._index:
            return
        logger.info("Camera: switching from index %d to %d", self._index, new_index)
        was_running = self._running
        if was_running:
            self.stop()
        self._index = new_index
        self._frame = None
        if was_running:
            self.start()

    @property
    def is_active(self) -> bool:
        return self._cap is not None and self._cap.isOpened()
