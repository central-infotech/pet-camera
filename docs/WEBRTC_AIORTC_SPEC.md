# WebRTC（aiortc）ストリーミング改修仕様書

## 1. 概要

現在の MJPEG ストリーミングを WebRTC（aiortc）に置き換え、帯域効率を大幅に改善する。
aiortc は Python で完結する WebRTC ライブラリであり、Flask プロセス内で動作するため外部プロセス（ffmpeg, go2rtc 等）が不要。

**改修対象:** ペットカメラ映像の配信経路（サーバー → スマートフォン）

**改修対象外:**
- 音声ストリーミング（Socket.IO PCM を維持）
- 飼い主映像リレー（Socket.IO JPEG リレーを維持）
- Display ページ（変更なし）

---

## 2. 改修の目的

| 指標 | 現状（MJPEG） | 目標（WebRTC） |
|------|---------------|----------------|
| 帯域（720p/10fps） | ~3.2 Mbps（~1.4 GB/h） | ~0.5〜1.5 Mbps（~0.2〜0.7 GB/h） |
| 遅延 | 100〜300ms | 50〜300ms |
| コーデック | JPEG（フレーム独立） | H.264（フレーム間圧縮） |
| 帯域適応 | なし（固定品質） | あり（ネットワーク状況に自動適応） |

モバイル回線での長時間視聴で通信量を 1/3〜1/5 に削減することが主目的。

---

## 3. 技術選定: aiortc

### 選定理由

1. **Flask プロセス内で完結** — 外部プロセス（ffmpeg, go2rtc, MediaMTX）不要
2. **低遅延** — WebRTC は 50〜300ms（HLS の 2〜5 秒と比較して圧倒的に低い）
3. **帯域適応** — ネットワーク状況に応じてビットレート自動調整
4. **ブラウザ互換** — 全モダンブラウザ対応（iOS Safari PWA 含む）
5. **Python 完結** — 既存の threading ベースアーキテクチャと統合可能

### aiortc の概要

- Python 製 WebRTC ライブラリ（asyncio ベース）
- H.264 エンコード: 内部で PyAV（FFmpeg バインディング）を使用
- ICE/DTLS/SRTP: 標準 WebRTC スタックを実装
- Windows 対応: pip wheel 提供済み（v1.14.0+, Python 3.10〜3.13）

### 制約事項

| 制約 | 影響 | 対策 |
|------|------|------|
| ソフトウェアエンコード | h264_amf（AMD GPU）利用不可、CPU 負荷あり | 720p/10fps ならソフトウェアで十分 |
| asyncio ベース | 現在の Flask は threading モード | asyncio イベントループを別スレッドで実行 |
| 遅延蓄積の既知問題 | recv() が遅いとフレームが溜まり遅延が増大 | 常に最新フレームを返す設計で回避 |

---

## 4. アーキテクチャ概要

### 現状

```
Camera (OpenCV)
  → camera.get_frame_jpeg()
  → Flask /video_feed (multipart/x-mixed-replace)
  → ブラウザ <img src="/video_feed">
```

### 改修後

```
Camera (OpenCV)
  → camera.get_frame_raw() → CameraVideoTrack.recv()
  → aiortc H.264 エンコード → RTP/UDP
  → ブラウザ RTCPeerConnection → <video> 要素

  フォールバック: MJPEG（/video_feed は維持）
```

### スレッド構成

```
メインスレッド: Flask + Flask-SocketIO (threading mode)
  ↓ webrtc モジュールの公開 API 経由
  ↓ 内部で asyncio.run_coroutine_threadsafe()
asyncio スレッド: aiortc イベントループ
  ├─ RTCPeerConnection #1 (viewer 1)
  ├─ RTCPeerConnection #2 (viewer 2)
  └─ CameraVideoTrack（Camera から最新フレーム取得）

カメラスレッド: Camera._capture_loop() (既存、変更なし)
```

### スレッド境界のルール

- **Flask スレッド → asyncio ループ**: `webrtc` モジュールの公開 API のみ経由（内部で `run_coroutine_threadsafe` を使用）
- **asyncio ループ → カメラスレッド**: `camera.get_frame_raw()` のみ（`threading.Lock` で保護済み）
- **Flask スレッドから `webrtc` の私有メンバ（`_loop`, `_peer_connections` 等）への直接アクセス禁止**

---

## 5. シグナリング設計

### フロー

WebRTC 接続確立にはシグナリング（SDP offer/answer 交換）が必要。
既存の Flask REST API を使い、**Vanilla ICE**（ICE 候補を全て収集してから送信）を採用する。

```
ブラウザ                                    サーバー
  │                                           │
  ├─ RTCPeerConnection 作成                    │
  ├─ addTransceiver('video', recvonly)         │
  ├─ createOffer()                            │
  ├─ setLocalDescription(offer)               │
  ├─ ICE 候補収集完了を待つ                     │
  │                                           │
  ├──── POST /api/webrtc/offer ───────────────→│
  │     { sdp: offer.sdp, type: "offer" }     │
  │                                           ├─ RTCPeerConnection 作成
  │                                           ├─ CameraVideoTrack 追加
  │                                           ├─ setRemoteDescription(offer)
  │                                           ├─ createAnswer()
  │                                           ├─ setLocalDescription(answer)
  │                                           │
  │←── 200 { sdp: answer.sdp, type:"answer" }─┤
  │                                           │
  ├─ setRemoteDescription(answer)             │
  │                                           │
  │◄════════ WebRTC 映像配信開始 ═══════════════►│
```

### Vanilla ICE を選択する理由

- Tailscale VPN 環境のため NAT 越えの問題なし
- ICE 候補収集は即時完了（ホスト候補のみ）
- Trickle ICE より実装がシンプル（ICE candidate の個別交換不要）

### STUN/TURN サーバー

- **不要**: Tailscale は直接 IP 接続を提供するため STUN/TURN は不要
- クライアント側の `iceServers` は空配列 `[]`

---

## 6. サーバー側の改修

### 6.1 新規モジュール: `server/webrtc.py`

aiortc の接続管理を担当するモジュール。
**Flask スレッドからは公開 API のみ使用する**（私有メンバへの直接アクセス禁止）。

```python
"""WebRTC streaming module using aiortc."""

import asyncio
import fractions
import logging
import threading
import time

from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
from aiortc.contrib.media import MediaRelay
from av import VideoFrame

logger = logging.getLogger(__name__)

# ─── 私有状態（asyncio ループ内でのみ参照・更新） ───

_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None
_peer_connections: dict[str, RTCPeerConnection] = {}  # {pc_id: pc}
_pc_sessions: dict[str, str] = {}  # {pc_id: session_id} — 所有者追跡
_relay: MediaRelay | None = None
_source_track: "CameraVideoTrack | None" = None
_disconnect_timers: dict[str, asyncio.TimerHandle] = {}  # {pc_id: timer}

# ─── 定数 ───

DISCONNECTED_TIMEOUT = 30  # disconnected 状態のタイムアウト（秒）
```

### 6.2 公開 API（Flask スレッドから呼び出し可能）

```python
def start():
    """asyncio イベントループを別スレッドで起動。app.py の main() から呼ぶ。"""
    global _loop, _loop_thread, _relay
    _loop = asyncio.new_event_loop()
    _relay = MediaRelay()
    _loop_thread = threading.Thread(target=_loop.run_forever, daemon=True)
    _loop_thread.start()
    logger.info("WebRTC: asyncio event loop started")


def stop():
    """シャットダウン時に全接続を閉じてイベントループを停止。"""
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
    """現在のアクティブ接続数を返す（Flask スレッドから安全に呼べる）。"""
    # dict の len() は GIL により安全
    return len(_peer_connections)


def handle_offer(camera, offer_sdp: str, pc_id: str, session_id: str,
                  max_peers: int) -> str:
    """SDP offer を処理し answer SDP を返す。Flask スレッドから呼ぶ同期 API。

    接続上限チェックは asyncio ループ内で原子的に実行される（TOCTOU 防止）。

    Args:
        camera: Camera インスタンス
        offer_sdp: クライアントの SDP offer
        pc_id: 一意な接続 ID
        session_id: Flask セッション ID（所有者追跡用）
        max_peers: 同時接続数の上限
    Returns:
        SDP answer 文字列
    Raises:
        RuntimeError: イベントループ未起動
        ValueError: 接続数上限超過（"TOO_MANY_PEERS"）
        Exception: offer 処理の失敗
    """
    if _loop is None:
        raise RuntimeError("WebRTC event loop not started")
    future = asyncio.run_coroutine_threadsafe(
        _create_peer_connection(camera, offer_sdp, pc_id, session_id, max_peers),
        _loop,
    )
    return future.result(timeout=10)


def reset_source_track():
    """カメラ設定変更時に呼ぶ。次の offer で新しいトラックが作成される。"""
    if _loop is None:
        return
    asyncio.run_coroutine_threadsafe(_reset_source(), _loop)


async def _reset_source():
    global _source_track
    if _source_track:
        _source_track.stop()
    _source_track = None


def close_peer(pc_id: str, session_id: str | None = None) -> bool:
    """PeerConnection を閉じる。Flask スレッドから呼ぶ同期 API。

    session_id が指定された場合、所有者が一致する場合のみ閉じる。
    Returns:
        True: 閉じた or 存在しなかった, False: 所有者不一致
    """
    if _loop is None:
        return True
    future = asyncio.run_coroutine_threadsafe(
        _cleanup_pc(pc_id, session_id), _loop
    )
    return future.result(timeout=5)
```

### 6.3 CameraVideoTrack

カメラの最新フレームを WebRTC トラックとして配信するクラス。

```python
class CameraVideoTrack(MediaStreamTrack):
    """Camera → WebRTC video track.

    常に Camera から最新フレームを取得し、遅延蓄積を防ぐ。
    """
    kind = "video"

    def __init__(self, camera, fps: int = 10):
        super().__init__()
        self._camera = camera
        self._fps = fps
        self._start = None
        self._count = 0

    async def recv(self) -> VideoFrame:
        # タイムスタンプ管理
        if self._start is None:
            self._start = time.time()

        # 目標 FPS でペーシング
        target_time = self._count / self._fps
        elapsed = time.time() - self._start
        wait = target_time - elapsed
        if wait > 0:
            await asyncio.sleep(wait)

        # Camera から最新の生フレームを取得（スレッドセーフ）
        raw = self._camera.get_frame_raw()
        if raw is None:
            # カメラ未準備時は黒フレーム
            import numpy as np
            raw = np.zeros((720, 1280, 3), dtype=np.uint8)

        # numpy BGR → av.VideoFrame
        frame = VideoFrame.from_ndarray(raw, format="bgr24")

        # PTS（Presentation Timestamp）設定: 90kHz タイムベース
        frame.pts = int((time.time() - self._start) * 90000)
        frame.time_base = fractions.Fraction(1, 90000)

        self._count += 1
        return frame
```

**遅延蓄積の回避策:**

- `camera.get_frame_raw()` は常に最新の 1 フレームを返す（Camera クラスの `_lock` で保護された `_frame` を参照）
- `recv()` は過去のフレームをキューイングせず、呼び出し時点の最新フレームを返す
- H.264 エンコーダが同一フレームを受け取った場合、P フレームのサイズは極小（差分がないため）

### 6.4 offer ハンドラ（asyncio 内部実装）

```python
async def _create_peer_connection(camera, offer_sdp: str, pc_id: str,
                                   session_id: str, max_peers: int) -> str:
    """PeerConnection を作成して answer SDP を返す（asyncio ループ内で実行）。

    接続上限チェックと登録を原子的に実行（TOCTOU 防止）。
    """
    global _source_track

    # ── 接続上限チェック（asyncio ループ内で原子的に実行） ──
    if len(_peer_connections) >= max_peers:
        raise ValueError("TOO_MANY_PEERS")

    pc = RTCPeerConnection()
    _peer_connections[pc_id] = pc
    _pc_sessions[pc_id] = session_id

    # ── 接続状態の監視 ──

    @pc.on("connectionstatechange")
    async def on_connection_state_change():
        state = pc.connectionState
        logger.info("WebRTC [%s]: connectionState → %s", pc_id, state)

        if state == "connected":
            # disconnected タイマーがあればキャンセル
            _cancel_disconnect_timer(pc_id)

        elif state == "disconnected":
            # 一時切断の可能性があるため、タイムアウト後にクリーンアップ
            _start_disconnect_timer(pc_id)

        elif state in ("failed", "closed"):
            _cancel_disconnect_timer(pc_id)
            await _cleanup_pc(pc_id)

    @pc.on("iceconnectionstatechange")
    async def on_ice_state_change():
        state = pc.iceConnectionState
        logger.info("WebRTC [%s]: iceConnectionState → %s", pc_id, state)
        # ICE 層での片系切断を早期検知
        if state == "failed":
            _cancel_disconnect_timer(pc_id)
            await _cleanup_pc(pc_id)

    # ── トラック追加 ──

    # 元トラックがなければ作成（全 PeerConnection で共有）
    if _source_track is None:
        _source_track = CameraVideoTrack(camera, fps=10)

    # MediaRelay で複製して追加
    relayed = _relay.subscribe(_source_track)
    pc.addTrack(relayed)

    # ── SDP 処理 ──

    offer = RTCSessionDescription(sdp=offer_sdp, type="offer")
    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    logger.info("WebRTC [%s]: peer connection created (session=%s, total=%d)",
                pc_id, session_id[:8] if session_id else "?", len(_peer_connections))
    return pc.localDescription.sdp
```

### 6.5 disconnected タイムアウト管理

`disconnected` 状態が `DISCONNECTED_TIMEOUT` 秒以上続いた場合、ゾンビ接続として強制クリーンアップする。

```python
def _start_disconnect_timer(pc_id: str):
    """disconnected タイムアウトタイマーを開始する。"""
    _cancel_disconnect_timer(pc_id)  # 既存タイマーがあればキャンセル

    async def _on_timeout():
        pc = _peer_connections.get(pc_id)
        if pc and pc.connectionState == "disconnected":
            logger.warning("WebRTC [%s]: disconnected timeout (%ds), forcing cleanup",
                           pc_id, DISCONNECTED_TIMEOUT)
            await _cleanup_pc(pc_id)

    handle = _loop.call_later(DISCONNECTED_TIMEOUT, lambda: asyncio.ensure_future(_on_timeout()))
    _disconnect_timers[pc_id] = handle
    logger.info("WebRTC [%s]: disconnect timer started (%ds)", pc_id, DISCONNECTED_TIMEOUT)


def _cancel_disconnect_timer(pc_id: str):
    """disconnected タイムアウトタイマーをキャンセルする。"""
    handle = _disconnect_timers.pop(pc_id, None)
    if handle:
        handle.cancel()
```

### 6.6 クリーンアップ

```python
async def _cleanup_pc(pc_id: str, required_session: str | None = None) -> bool:
    """PeerConnection をクリーンアップする。

    required_session が指定された場合、所有者が一致する場合のみ閉じる。
    Returns: True=閉じた/存在しなかった, False=所有者不一致
    """
    # 所有者チェック
    if required_session is not None:
        owner = _pc_sessions.get(pc_id)
        if owner is not None and owner != required_session:
            logger.warning("WebRTC [%s]: close rejected (session mismatch)", pc_id)
            return False

    _cancel_disconnect_timer(pc_id)
    _pc_sessions.pop(pc_id, None)
    pc = _peer_connections.pop(pc_id, None)
    if pc:
        await pc.close()
        logger.info("WebRTC [%s]: cleaned up (remaining=%d)", pc_id, len(_peer_connections))
    return True


async def _close_all():
    """全 PeerConnection を閉じる（シャットダウン用）。"""
    for pc_id in list(_disconnect_timers):
        _cancel_disconnect_timer(pc_id)
    coros = [pc.close() for pc in _peer_connections.values()]
    if coros:
        await asyncio.gather(*coros, return_exceptions=True)
    _peer_connections.clear()
    _pc_sessions.clear()
```

### 6.7 MediaRelay による複数視聴者対応

同時視聴者が複数いる場合（例: 夫婦で同時視聴）、各 PeerConnection に独立した CameraVideoTrack を持たせると重複してフレームを取得する。`_source_track` を 1 つだけ作成し、MediaRelay で複製して各 PeerConnection に配布する（6.4 のコード参照）。

**注意:** MediaRelay はフレームオブジェクト（VideoFrame）を複製する。H.264 エンコードは各 PeerConnection が独立して行う。1〜2 名の同時視聴（想定ユースケース）なら CPU 負荷は問題ない。

### 6.8 `server/app.py` の変更

#### 新規 API エンドポイント

```python
from . import webrtc

# POST /api/webrtc/offer
@app.route("/api/webrtc/offer", methods=["POST"])
@login_required
def webrtc_offer():
    """WebRTC SDP offer を受け取り、answer を返す。"""
    data = request.get_json(silent=True)
    if not data or "sdp" not in data:
        return jsonify({"error": {"code": "INVALID_PARAMETER",
                                  "message": "SDP offer required"}}), 400

    import uuid
    pc_id = str(uuid.uuid4())[:8]
    session_id = session.get("sid", "")

    try:
        # 接続上限チェックは handle_offer 内（asyncio ループ内）で原子的に実行
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


# DELETE /api/webrtc/<pc_id>
@app.route("/api/webrtc/<pc_id>", methods=["DELETE"])
@login_required
def webrtc_close(pc_id):
    """WebRTC 接続を明示的に切断する（所有者のみ）。"""
    session_id = session.get("sid", "")
    ok = webrtc.close_peer(pc_id, session_id)
    if not ok:
        return jsonify({"error": {"code": "FORBIDDEN",
                                  "message": "Not the owner of this connection"}}), 403
    return jsonify({"closed": True})
```

#### `PATCH /api/settings` の変更

```python
@app.route("/api/settings", methods=["PATCH"])
@login_required
def patch_settings():
    # ... 既存の設定更新処理 ...
    result, error = camera.update_settings(data)
    if error:
        # ... エラー処理 ...

    # 解像度/FPS 変更時に WebRTC ソーストラックをリセット
    webrtc.reset_source_track()
    return jsonify(result)
```

#### `main()` 関数の変更

```python
def main():
    # ... 既存のバリデーション ...

    # Start subsystems
    webrtc.start()  # ← 最初に起動（Bug 1 対策: asyncio ループを先に初期化）
    camera.start()
    audio_capture.start()
    audio_player.start()

    # ... 既存の TLS/起動処理 ...

    try:
        socketio.run(...)
    finally:
        camera.stop()
        audio_capture.stop()
        audio_player.stop()
        webrtc.stop()  # ← 追加
```

### 6.9 `server/config.py` の変更

```python
# WebRTC
WEBRTC_DEFAULT_FPS = 10  # WebRTC 配信時のデフォルト FPS
WEBRTC_MAX_PEERS = 3     # 同時接続数の上限
```

---

## 7. クライアント側の改修

### 7.1 新規モジュール: `static/js/webrtc.js`

```javascript
/**
 * Pet Camera — WebRTC video module
 * サーバーからの WebRTC 映像受信を管理する。
 * MJPEG フォールバック付き。
 *
 * 状態遷移:
 *   IDLE → CONNECTING → CONNECTED → (DISCONNECTED → CONNECTING | IDLE)
 *                   └→ RETRYING → CONNECTING
 *                   └→ FALLBACK (MJPEG) → 定期的に CONNECTING を再試行
 */
const PetWebRTC = (() => {
  let pc = null;
  let pcId = null;
  let _videoEl = null;     // 接続先の video 要素（再接続で使い回す）

  // ── 状態管理 ──
  let _isClosing = false;  // 意図的切断中フラグ（再接続を抑止）
  let _retryTimer = null;  // 再接続タイマー ID
  let _fallbackTimer = null; // フォールバック後の定期再試行タイマー ID
  let retryCount = 0;

  const MAX_RETRIES = 5;
  const RETRY_BASE_DELAY = 2000;       // 指数バックオフの基底（ms）
  const FALLBACK_RETRY_INTERVAL = 60000; // MJPEG フォールバック後の再試行間隔（ms）

  // ── コールバック ──
  let _onConnected = null;
  let _onDisconnected = null;
  let _onFallback = null;

  /**
   * WebRTC 接続を開始する。
   * @param {HTMLVideoElement} videoEl - 映像を表示する video 要素
   * @returns {Promise<boolean>} 接続成功なら true
   */
  async function connect(videoEl) {
    // 意図的切断状態をリセット
    _isClosing = false;
    _videoEl = videoEl;

    // 既存接続があれば内部クリーンアップ（再接続抑止なし）
    _internalClose();

    try {
      pc = new RTCPeerConnection({ iceServers: [] });

      // 映像トラック受信時のハンドラ
      pc.ontrack = (event) => {
        console.log('[WebRTC] Track received:', event.track.kind);
        videoEl.srcObject = event.streams[0];
        videoEl.play().catch(e => console.warn('[WebRTC] Autoplay blocked:', e));
      };

      // ── 接続状態の監視 ──
      pc.onconnectionstatechange = () => {
        if (_isClosing) return;  // 意図的切断中は無視

        const state = pc.connectionState;
        console.log('[WebRTC] Connection state:', state);

        if (state === 'connected') {
          retryCount = 0;
          _cancelFallbackTimer();
          if (_onConnected) _onConnected();
        } else if (state === 'disconnected') {
          // 一時的な場合があるので少し待つ（サーバー側も 30s タイムアウト）
          _scheduleRetry(5000);
        } else if (state === 'failed') {
          if (_onDisconnected) _onDisconnected();
          _scheduleRetry(0);
        }
        // 'closed' は意図的 close() の結果なので再接続しない
      };

      // ICE 接続状態の監視（片系切断の早期検知）
      pc.oniceconnectionstatechange = () => {
        if (_isClosing) return;

        const state = pc.iceConnectionState;
        console.log('[WebRTC] ICE connection state:', state);

        if (state === 'failed') {
          if (_onDisconnected) _onDisconnected();
          _scheduleRetry(0);
        }
      };

      // 映像を受信のみ（recvonly）
      pc.addTransceiver('video', { direction: 'recvonly' });

      // SDP offer 生成
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      // ICE 候補収集完了を待つ（Vanilla ICE）
      await _waitIceGathering(pc);

      // サーバーに offer 送信、answer 受信
      const res = await fetch('/api/webrtc/offer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sdp: pc.localDescription.sdp,
          type: 'offer',
        }),
      });

      if (!res.ok) {
        throw new Error(`Server returned ${res.status}`);
      }

      const answer = await res.json();
      pcId = answer.pc_id;

      await pc.setRemoteDescription(
        new RTCSessionDescription({ sdp: answer.sdp, type: answer.type })
      );

      console.log('[WebRTC] Connection established (pc_id=%s)', pcId);
      return true;

    } catch (err) {
      console.error('[WebRTC] Connection failed:', err);
      _internalClose();
      if (!_isClosing) {
        _scheduleRetry(0);
      }
      return false;
    }
  }

  /**
   * ICE 候補収集完了を待つ。
   */
  function _waitIceGathering(peerConnection) {
    return new Promise((resolve) => {
      if (peerConnection.iceGatheringState === 'complete') {
        resolve();
        return;
      }
      const check = () => {
        if (peerConnection.iceGatheringState === 'complete') {
          peerConnection.removeEventListener('icegatheringstatechange', check);
          resolve();
        }
      };
      peerConnection.addEventListener('icegatheringstatechange', check);

      // タイムアウト（5 秒）— Tailscale 環境なら即完了するはず
      setTimeout(() => {
        peerConnection.removeEventListener('icegatheringstatechange', check);
        resolve();
      }, 5000);
    });
  }

  /**
   * 再接続のスケジュール。
   * @param {number} initialDelay - 初回遅延（0 なら指数バックオフを使用）
   */
  function _scheduleRetry(initialDelay) {
    if (_isClosing) return;

    // 既存のリトライタイマーをキャンセル
    _cancelRetryTimer();

    if (retryCount >= MAX_RETRIES) {
      console.warn('[WebRTC] Max retries reached, falling back to MJPEG');
      if (_onFallback) _onFallback();
      // MJPEG フォールバック後も定期的に WebRTC を再試行
      _startFallbackTimer();
      return;
    }

    retryCount++;
    const delay = initialDelay > 0
      ? initialDelay
      : RETRY_BASE_DELAY * Math.pow(2, retryCount - 1);
    console.log('[WebRTC] Retry %d/%d in %dms', retryCount, MAX_RETRIES, delay);

    _retryTimer = setTimeout(() => {
      _retryTimer = null;
      if (!_isClosing && _videoEl) {
        connect(_videoEl);
      }
    }, delay);
  }

  /**
   * MJPEG フォールバック後の定期再試行。
   */
  function _startFallbackTimer() {
    _cancelFallbackTimer();
    _fallbackTimer = setInterval(() => {
      if (_isClosing) {
        _cancelFallbackTimer();
        return;
      }
      console.log('[WebRTC] Periodic retry from MJPEG fallback');
      retryCount = 0;  // リトライカウントをリセット
      if (_videoEl) connect(_videoEl);
    }, FALLBACK_RETRY_INTERVAL);
  }

  function _cancelRetryTimer() {
    if (_retryTimer) {
      clearTimeout(_retryTimer);
      _retryTimer = null;
    }
  }

  function _cancelFallbackTimer() {
    if (_fallbackTimer) {
      clearInterval(_fallbackTimer);
      _fallbackTimer = null;
    }
  }

  /**
   * 内部クリーンアップ（再接続フラグを変更しない）。
   */
  function _internalClose() {
    if (pcId) {
      // サーバーに切断を通知（ベストエフォート、keepalive で pagehide 後も送信）
      fetch(`/api/webrtc/${pcId}`, { method: 'DELETE', keepalive: true }).catch(() => {});
      pcId = null;
    }
    if (pc) {
      // イベントハンドラを除去してから close（再接続の発火を防止）
      pc.onconnectionstatechange = null;
      pc.oniceconnectionstatechange = null;
      pc.ontrack = null;
      pc.close();
      pc = null;
    }
  }

  /**
   * 意図的に接続を切断する（再接続しない）。
   */
  function close() {
    _isClosing = true;
    _cancelRetryTimer();
    _cancelFallbackTimer();
    _internalClose();
  }

  /**
   * 接続中かどうか。
   */
  function isConnected() {
    return pc !== null && pc.connectionState === 'connected';
  }

  return {
    connect,
    close,
    isConnected,
    set onConnected(fn) { _onConnected = fn; },
    set onDisconnected(fn) { _onDisconnected = fn; },
    set onFallback(fn) { _onFallback = fn; },
  };
})();
```

### 7.2 `templates/index.html` の変更

```html
<!-- 変更前 -->
<img id="video-stream" src="/video_feed" alt="Live Feed">

<!-- 変更後 -->
<video id="video-stream-webrtc" autoplay playsinline muted
       style="width:100%; height:100%; object-fit:contain; display:none;"></video>
<img id="video-stream-mjpeg" src="/video_feed" alt="Live Feed">
```

- `<video>` 要素を追加（WebRTC 用）
- `<img>` 要素は MJPEG フォールバック用に維持
- WebRTC 接続成功時は `<video>` を表示、`<img>` を非表示
- WebRTC 失敗時は `<img>` にフォールバック

スクリプトの追加:
```html
<script src="/static/js/webrtc.js"></script>  <!-- audio.js の前 -->
<script src="/static/js/audio.js"></script>
<script src="/static/js/app.js"></script>
```

### 7.3 `static/js/app.js` の変更

```javascript
// ---- Video: WebRTC with MJPEG fallback ----
const videoWebRTC = document.getElementById('video-stream-webrtc');
const videoMJPEG = document.getElementById('video-stream-mjpeg');

function showWebRTC() {
  videoWebRTC.style.display = '';
  videoMJPEG.style.display = 'none';
  // MJPEG ストリームを停止（帯域節約）
  videoMJPEG.src = '';
  videoOverlay.hidden = true;
}

function showMJPEG() {
  videoWebRTC.style.display = 'none';
  videoMJPEG.style.display = '';
  videoMJPEG.src = '/video_feed?' + Date.now();
  checkVideoLoaded();
}

PetWebRTC.onConnected = () => {
  console.log('[App] WebRTC connected');
  showWebRTC();
};

PetWebRTC.onDisconnected = () => {
  console.log('[App] WebRTC disconnected, waiting for reconnect...');
};

PetWebRTC.onFallback = () => {
  console.log('[App] Falling back to MJPEG');
  showMJPEG();
};

// 初回接続
PetWebRTC.connect(videoWebRTC).then((ok) => {
  if (!ok) showMJPEG();
});

// ページ可視性変更時の復帰
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') {
    if (!PetWebRTC.isConnected()) {
      PetWebRTC.connect(videoWebRTC);
    }
  }
});

// ネットワーク復帰
window.addEventListener('online', () => {
  if (!PetWebRTC.isConnected()) {
    PetWebRTC.connect(videoWebRTC);
  }
});

// ページ離脱時のクリーンアップ
// pagehide は beforeunload より iOS Safari で確実に発火する
window.addEventListener('pagehide', () => {
  PetWebRTC.close();
});
```

### 7.4 既存コードへの影響（変更対象チェックリスト）

`app.js` 内で `video-stream` (`videoStream`) に依存する全箇所を列挙する。

| # | ファイル | 対象 | 現在のコード | 変更内容 |
|---|---------|------|------------|---------|
| 1 | `app.js:42` | `videoStream` 変数宣言 | `document.getElementById('video-stream')` | `videoWebRTC` / `videoMJPEG` に分離 |
| 2 | `app.js:43` | `videoOverlay` 参照 | `document.getElementById('video-overlay')` | 変更なし（オーバーレイは共通） |
| 3 | `app.js:45-54` | `checkVideoLoaded()` | `videoStream.naturalWidth > 0` で判定 | MJPEG 時のみ実行（`videoMJPEG.naturalWidth`）。WebRTC 時はオーバーレイを即非表示 |
| 4 | `app.js:92-106` | スナップショット（ダウンロード） | `fetch('/snapshot')` | WebRTC 時は `<video>` からCanvas キャプチャ、MJPEG 時は従来通り |
| 5 | `app.js:160-187` | 設定適用後のリロード | `videoStream.src = '/video_feed?' + Date.now()` | WebRTC: `PetWebRTC.close()` → `PetWebRTC.connect()` で再接続。MJPEG: 従来通り |
| 6 | `app.js:198-223` | ステータスポーリング | ステータスバー表示 | `statusBar` に「WebRTC」/「MJPEG」のモード表示を追加 |
| 7 | `index.html:43` | `<img id="video-stream">` | MJPEG ストリーム表示 | `<video>` + `<img>` に分離（セクション 7.2 参照） |
| 8 | `index.html:148` | スクリプト読み込み | `audio.js`, `app.js` | `webrtc.js` を先頭に追加 |

### 7.5 スナップショットの対応

WebRTC 使用時は `<img>` ではなく `<video>` から JPEG を取得する必要がある。

```javascript
btnSnapshot.addEventListener('click', async () => {
  if (PetWebRTC.isConnected()) {
    // WebRTC: video 要素から Canvas 経由でキャプチャ
    const canvas = document.createElement('canvas');
    canvas.width = videoWebRTC.videoWidth;
    canvas.height = videoWebRTC.videoHeight;
    canvas.getContext('2d').drawImage(videoWebRTC, 0, 0);
    canvas.toBlob((blob) => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `snapshot_${new Date().toISOString().replace(/[:.]/g, '-')}.jpg`;
      a.click();
      URL.revokeObjectURL(url);
    }, 'image/jpeg', 0.95);
  } else {
    // MJPEG: 従来通りサーバーから取得
    // ... 既存コード ...
  }
});
```

サーバー保存（`btnSave`）はサーバー側で直接カメラからフレームを取得するため変更不要。

### 7.6 操作パネルのレイアウト変更

操作ボタンを2段構成に再編し、横スクロール対応と表示/非表示トグルを追加。

**レイアウト構成:**
```
[▲ トグルボタン]              ← タップで操作パネルの表示/非表示を切り替え
[段1] 🔊聞く | 🎤話す | 📹顔を見せる | (ステータス) | 音量スライダー
[段2] 📷スマホに画像保存 | 📁PCに画像保存 | ⚙設定
[footer] FPS | 解像度 | 音声状態
```

**横スクロール:**
- 各段は `flex-wrap: nowrap; overflow-x: auto` で横スクロール可能
- ボタン内で改行しない（`white-space: nowrap`）
- スクロールバーは非表示（`scrollbar-width: none`）

**操作パネルトグル:**
- トグルボタン（▲/▼）で `#controls-panel` の表示/非表示を切り替え
- 非表示時は映像エリアが拡大され、横向き時に大画面表示が可能
- ▲ = パネル表示中（タップで隠す）、▼ = パネル非表示（タップで表示）
- footer（FPS等）はトグル対象外で常時表示

---

## 8. MJPEG フォールバック

WebRTC が使えない場合に MJPEG にフォールバックする。

### クライアント状態遷移図

```
                 ページロード
                     │
                     ▼
              ┌─────────────┐
              │    IDLE      │
              └──────┬───────┘
                     │ connect()
                     ▼
              ┌─────────────┐
         ┌───→│ CONNECTING   │◄──────────────────┐
         │    └──────┬───────┘                    │
         │           │                            │
         │    成功 ──┤── 失敗                      │
         │           │      │                     │
         │           ▼      ▼                     │
         │    ┌────────┐  ┌─────────┐   retryCount │
         │    │CONNECTED│  │RETRYING │   < MAX     │
         │    └────┬───┘  └────┬────┘             │
         │         │           │ 指数バックオフ     │
         │  disconnected/      └──────────────────┘
         │  failed  │
         │         ▼          retryCount >= MAX
         │    ┌─────────┐         │
         │    │RETRYING  │────────▼
         │    └─────────┘  ┌──────────┐
         │                 │ FALLBACK │ MJPEG 表示
         │                 │ (MJPEG)  │
         │                 └────┬─────┘
         │                      │ 60秒ごとに再試行
         └──────────────────────┘

  close() はどの状態からも → IDLE に遷移（再接続しない）
```

### フォールバックの条件

1. WebRTC 接続が `MAX_RETRIES`（5）回連続で失敗
2. ブラウザが WebRTC 未対応（実質ありえないが安全策）
3. サーバー側 aiortc が起動失敗

### フォールバック時の動作

- `<video>` を非表示、`<img src="/video_feed">` を表示
- ステータスバーに「MJPEG」と表示
- **60 秒ごとに WebRTC 接続を再試行**（ネットワーク復旧を自動検知）
- 再試行成功時は自動で WebRTC に復帰（`onConnected` → `showWebRTC()`）

### `/video_feed` エンドポイント

**変更なし。** 既存の MJPEG ストリーミングエンドポイントはそのまま維持する。

---

## 9. 音声の取り扱い

### 方針: 変更なし（Socket.IO PCM を維持）

現在の音声設計は「デフォルト OFF、オンデマンド」であり、WebRTC の常時接続型とは設計思想が異なる。

| 観点 | WebRTC 音声 | 現行 Socket.IO 音声 |
|------|------------|-------------------|
| 常時性 | トラック追加時から常時流れる | ユーザー操作時のみ |
| コーデック | Opus（~32-64 kbps） | PCM 16kHz（~256 kbps） |
| 帯域 | 常時消費（ミュート時も微量） | オンデマンドのみ |
| 実装の変更量 | 大（AudioStreamTrack、マイク入力、スピーカー出力の統合） | なし |

**理由:**
- 映像の帯域改善が最優先（3.2 Mbps → ~1.0 Mbps）
- 音声は使用時のみ ~256 kbps で、映像と比べて影響が小さい
- 聞く/話すのオンデマンド設計を WebRTC で再現するには実装量が大きい
- 将来的に WebRTC 音声に移行することは可能（Phase 2 候補）

---

## 10. 飼い主映像の取り扱い

### 方針: 変更なし（Socket.IO JPEG リレーを維持）

| 観点 | 現行の Socket.IO リレー | WebRTC に変更した場合 |
|------|----------------------|---------------------|
| 経路 | スマホ → Socket.IO → Flask → Socket.IO → Display | スマホ → WebRTC → Flask（aiortc） → WebRTC → Display |
| 帯域 | ~15 KB/frame × 10fps ≈ 1.2 Mbps | ~0.3 Mbps（H.264） |
| 実装量 | 変更なし | 大（ブラウザ → aiortc の受信 + aiortc → ブラウザの再配信） |

**理由:**
- 飼い主映像は「顔を見せる」ボタン押下時のみ使用（常時ではない）
- 帯域改善効果は映像ストリームに比べて小さい
- ブラウザからの WebRTC 受信 → サーバー → 別ブラウザへの WebRTC 送信は SFU 的な構成が必要で実装が複雑
- 今回のスコープ外とし、将来的な改善候補とする

### Display ページの映像クリア動作

飼い主映像の送信が終了した際、Display ページ（PC 側）では最後のフレームを残さず黒画面に戻す。

**クリアするタイミング:**
- `video_status` で `sending: false` を受信（送信側が「顔を見せる」を終了）
- フレーム受信が 3 秒間途切れた場合（タイムアウト）
- Socket.IO 切断時（`disconnect` イベント）
- 接続エラー時（`connect_error` イベント）

**実装:** `display.js` 内に `clearVideo()` ヘルパーを追加。Blob URL を解放し、`<img>` の `src` 属性を除去することでコンテナ背景色（黒）を表示する。

---

## 11. 依存関係の変更

### `server/requirements.txt`

```diff
 opencv-python>=4.8.0
 flask>=3.0.0
 flask-socketio>=5.3.0
 sounddevice>=0.4.6
 numpy>=1.24.0
 python-engineio>=4.8.0
 webauthn>=2.0.0
+aiortc>=1.9.0
```

### aiortc の依存ツリー

aiortc をインストールすると以下が自動的にインストールされる:

| パッケージ | 用途 |
|-----------|------|
| `av` (PyAV) | H.264 エンコード/デコード（FFmpeg バインディング） |
| `aioice` | ICE (Interactive Connectivity Establishment) |
| `cryptography` | DTLS/SRTP 暗号化 |
| `pylibsrtp` | SRTP (Secure RTP) |
| `pyee` | イベントエミッタ |
| `cffi` | C 拡張バインディング |

### インストール手順

```bash
# venv 内で
pip install aiortc
```

Windows では pip wheel が提供されており、C コンパイラは不要（aiortc v1.9.0+）。

---

## 12. H.264 エンコードパラメータ

aiortc は内部で PyAV（libx264）を使用し、H.264 エンコードを行う。

### デフォルト設定（aiortc 内部）

| パラメータ | 値 | 説明 |
|-----------|-----|------|
| Profile | Baseline | 最大互換性（iOS Safari 含む） |
| Preset | — | aiortc 内部で最適化済み |
| Bitrate | 自動（帯域推定に基づく） | WebRTC の帯域適応で動的調整 |
| GOP size | — | aiortc が管理 |

### カスタマイズ（必要に応じて）

aiortc ではコーデックパラメータを SDP レベルで制限できる:

```python
# トランシーバーのコーデック設定
for transceiver in pc.getTransceivers():
    codecs = [c for c in transceiver._codecs
              if c.mimeType == "video/H264"]
    transceiver._codecs = codecs  # H264 のみに制限
```

### CPU 負荷の見積もり

| 設定 | CPU 使用率（目安） |
|------|-------------------|
| 720p/10fps × 1 viewer | ~10〜20% |
| 720p/10fps × 2 viewers | ~20〜40% |
| 720p/15fps × 1 viewer | ~15〜30% |

※ ソフトウェアエンコード（libx264）。PC のスペックに依存。

---

## 13. 接続ライフサイクル管理

### サーバー側 PeerConnection 状態遷移

```
              new
               │
               ▼
          connecting
               │
        ┌──────┴──────┐
        ▼             ▼
   connected       failed ──→ _cleanup_pc()
        │
        ▼
   disconnected
        │
        ├── 30秒以内に connected に復帰 → タイマーキャンセル
        │
        └── 30秒経過 → _cleanup_pc()（強制クリーンアップ）

   closed ──→ _cleanup_pc()

   iceConnectionState === "failed" ──→ _cleanup_pc()（早期検知）
```

### クリーンアップトリガー一覧

| # | トリガー | 処理 |
|---|---------|------|
| 1 | `connectionstatechange → "failed"` | 即時 `_cleanup_pc()` |
| 2 | `connectionstatechange → "closed"` | 即時 `_cleanup_pc()` |
| 3 | `connectionstatechange → "disconnected"` | 30 秒タイマー開始 → タイムアウトで `_cleanup_pc()` |
| 4 | `iceconnectionstatechange → "failed"` | 即時 `_cleanup_pc()`（片系切断の早期検知） |
| 5 | `DELETE /api/webrtc/<pc_id>` | 所有者検証後に `close_peer()` |
| 6 | サーバーシャットダウン | `stop()` → `_close_all()` |

### クライアント側

```
接続トリガー:
  1. ページロード時（自動接続）
  2. visibilitychange → "visible"（復帰時）
  3. online イベント（ネットワーク復帰時）
  4. カメラ設定変更後（close → connect）
  5. MJPEG フォールバック中の定期再試行（60秒ごと）

切断トリガー:
  1. ページ離脱時（pagehide → close()、_isClosing=true）
  2. close() 明示呼び出し（_isClosing=true、タイマー全キャンセル）

自動再接続（_isClosing=false の場合のみ）:
  1. connectionstatechange → "disconnected"（5秒待機後）
  2. connectionstatechange → "failed"（指数バックオフ）
  3. 接続試行失敗（指数バックオフ）
```

### ページ離脱時のクリーンアップ

```javascript
// pagehide は beforeunload より iOS Safari で確実に発火する
window.addEventListener('pagehide', () => {
  PetWebRTC.close();
});
```

---

## 14. セキュリティ考慮

### 認証

- `/api/webrtc/offer` は `@login_required` で保護
- `/api/webrtc/<pc_id>` (DELETE) も `@login_required` で保護
- WebRTC の映像データは DTLS-SRTP で暗号化（aiortc が自動処理）
- SDP 自体には機密情報は含まれない（ICE 候補の IP アドレスのみ）

### pc_id の所有者検証

- `webrtc.py` 内部で `_pc_sessions[pc_id] = session_id` を保持
- `DELETE /api/webrtc/<pc_id>` は Flask セッション ID と照合し、所有者のみ切断を許可
- 他タブ・他端末の接続を誤って切断するリスクを防止

### DoS 対策

- 同時 PeerConnection 数を `WEBRTC_MAX_PEERS` で制限（デフォルト: 3）
- offer 上限超過時は 429 Too Many Requests を返す
- 接続上限チェックと接続登録は asyncio ループ内で原子的に実行（TOCTOU 防止）

### Tailscale 環境

- Tailscale VPN 内のみアクセス可能（既存のネットワーク制限を継承）
- STUN/TURN サーバー不要のため、外部との通信なし

---

## 15. テスト方針

### 手動テスト

| テスト項目 | 手順 | 期待結果 |
|-----------|------|---------|
| WebRTC 接続 | ページを開く | 映像が `<video>` で表示される |
| 映像品質 | 720p/10fps で配信 | 目視で画質確認、帯域 ~1.0 Mbps 以下 |
| 遅延確認 | 画面前で手を振る | 0.5 秒以内に反映 |
| MJPEG フォールバック | aiortc を停止 → ページリロード | `<img>` で MJPEG 表示 |
| フォールバック後復帰 | aiortc を再起動 → 60 秒待つ | 自動で WebRTC に復帰 |
| 複数視聴者 | 2 台のスマホから同時アクセス | 両方で映像表示 |
| 再接続（一時切断） | Wi-Fi OFF（5秒）→ ON | 自動復帰 |
| 再接続（長時間切断） | Wi-Fi OFF（60秒）→ ON | サーバー側クリーンアップ後に新規接続 |
| ページバックグラウンド | ホーム画面 → アプリ復帰 | 映像復帰 |
| ページ離脱 | タブを閉じる | サーバー側接続がクリーンアップされる |
| カメラ設定変更 | 解像度変更 | WebRTC 再接続して新解像度で表示 |
| スナップショット | WebRTC 中にスナップショット | Canvas 経由で JPEG 保存 |
| 音声同時使用 | WebRTC 映像 + Socket.IO 音声 | 両方正常に動作 |
| 接続数上限 | 4 台目から接続 | 429 エラー、MJPEG にフォールバック |
| 所有者検証 | 別セッションから DELETE | 403 エラー |

### 帯域測定

```bash
# Tailscale 上でのネットワークモニタリング
# Windows: タスクマネージャー → パフォーマンス → ネットワーク
# または: Resource Monitor (resmon.exe) → ネットワーク タブ
```

### ブラウザ互換テスト

| ブラウザ | プラットフォーム | 優先度 |
|---------|----------------|--------|
| Safari | iOS (PWA) | 最高 |
| Chrome | Android | 高 |
| Chrome | Windows/Mac | 中 |
| Firefox | Windows | 低 |

---

## 16. 段階的実装計画

### Step 1: aiortc 基盤

- `server/webrtc.py` 作成（asyncio ループ、CameraVideoTrack、公開 API）
- `server/config.py` に WebRTC 設定追加
- `server/requirements.txt` に aiortc 追加
- `pip install aiortc` の動作確認

### Step 2: シグナリング API

- `POST /api/webrtc/offer` エンドポイント追加
- `DELETE /api/webrtc/<pc_id>` エンドポイント追加（所有者検証付き）
- `main()` に `webrtc.start()` / `webrtc.stop()` 追加

### Step 3: クライアント WebRTC

- `static/js/webrtc.js` 作成（状態管理、`_isClosing` フラグ、タイマー管理）
- `templates/index.html` に `<video>` 要素追加、`webrtc.js` 読み込み
- `static/js/app.js` に WebRTC/MJPEG 切り替えロジック追加

### Step 4: フォールバックとリカバリ

- MJPEG フォールバック実装
- 再接続ロジック（指数バックオフ + 定期再試行）
- visibilitychange / online / pagehide イベント対応
- disconnected タイムアウト動作確認

### Step 5: スナップショット・UI 対応

- WebRTC 時の Canvas キャプチャ対応
- ステータスバーのモード表示
- 設定変更後の再接続
- 変更対象チェックリスト（7.4）の全項目確認

### Step 6: テストと調整

- 各ブラウザでの動作確認
- 帯域測定
- 遅延確認
- 長時間安定性テスト
- 接続枯渇テスト（disconnected タイムアウトの動作確認）

---

## 17. リスクと対策

| リスク | 影響度 | 発生確率 | 対策 |
|--------|--------|---------|------|
| aiortc の遅延蓄積 | 高 | 中 | 常に最新フレームを返す設計。監視して異常時は再接続 |
| CPU 負荷（ソフトウェアエンコード） | 中 | 低 | 720p/10fps なら問題なし。FPS を下げる設定も可 |
| aiortc Windows 互換性 | 高 | 低 | pip wheel 提供済み。インストール時に確認 |
| iOS Safari PWA での WebRTC | 高 | 低 | Safari は WebRTC 対応済み。実機テストで確認 |
| asyncio/threading の競合 | 中 | 中 | 公開 API 経由で `run_coroutine_threadsafe` を使用。私有メンバ直接アクセス禁止 |
| 同時視聴者増加時の CPU | 中 | 低 | `WEBRTC_MAX_PEERS` で上限制限 |
| ネットワーク断後の再接続失敗 | 中 | 中 | 指数バックオフ + MJPEG フォールバック + 60 秒ごとの定期再試行 |
| ゾンビ接続（disconnected 残留） | 高 | 中 | 30 秒タイムアウト + ICE 状態監視で強制クリーンアップ |
| close() 時の再接続ループ | 高 | 中 | `_isClosing` フラグ + イベントハンドラ除去 + タイマーキャンセル |

---

## 18. 実装によって起こりうるバグとその対策

### Bug 1: asyncio ループ未起動時の offer 受付

**症状:** サーバー起動直後に WebRTC 接続を試みると `RuntimeError: WebRTC event loop not started` が発生する。

**原因:** `main()` で `webrtc.start()` が `socketio.run()` の前に呼ばれるが、HTTPS 証明書チェック等で起動が遅延する場合にタイミングが合わない。

**対策:**
- `handle_offer()` 内で `_loop is None` チェック済み（RuntimeError を raise）
- クライアントは 500 エラーを受けてリトライするため、数秒後に自動回復
- 起動順序を `webrtc.start()` → `camera.start()` → 他サブシステム → `socketio.run()` とし、WebRTC が最初に初期化されるようにする（6.8 の `main()` と一致）

### Bug 2: Camera フレーム未取得時の黒フレーム無限送信

**症状:** カメラ接続前やカメラエラー時に黒フレームが連続送信され、無駄な H.264 エンコード CPU 負荷が発生する。

**原因:** `CameraVideoTrack.recv()` で `camera.get_frame_raw()` が `None` を返すと黒フレームにフォールバックする設計。

**対策:**
- 黒フレームは H.264 の P フレームとして極小サイズになるため、帯域への影響は軽微
- ただし CPU はエンコードに使われるため、連続 `None` が一定回数続いたらログ警告を出す
- カメラがまだ起動していない場合は、`recv()` で `await asyncio.sleep(1)` としてポーリング頻度を下げる

```python
async def recv(self) -> VideoFrame:
    # ...
    raw = self._camera.get_frame_raw()
    if raw is None:
        await asyncio.sleep(1)  # カメラ未準備時は 1fps に落とす
        import numpy as np
        raw = np.zeros((720, 1280, 3), dtype=np.uint8)
    # ...
```

### Bug 3: 複数 close() 呼び出しによる二重解放

**症状:** `_cleanup_pc()` が connectionstatechange と DELETE API から同時に呼ばれ、`pc.close()` が二重実行される。

**原因:** asyncio ループ内でも非同期タスクが並行実行される可能性がある。

**対策:**
- `_cleanup_pc()` で `_peer_connections.pop(pc_id, None)` を使用し、存在しない場合は何もしない
- `pop` は asyncio シングルスレッド内ではアトミックに動作するため安全
- 既にクリーンアップ済みなら `pc` は `None` となり、`close()` はスキップされる

### Bug 4: ブラウザ autoplay ポリシーによる映像表示失敗

**症状:** WebRTC 接続は成功するが、映像が表示されない（特に iOS Safari）。

**原因:** ブラウザの autoplay ポリシーにより、ユーザー操作なしの動画再生がブロックされる。

**対策:**
- `<video>` に `muted` 属性を付与（muted の自動再生は全ブラウザで許可）
- `playsinline` 属性を付与（iOS Safari でインライン再生）
- `videoEl.play()` の Promise を catch してエラーをログ出力
- 万が一再生がブロックされた場合、ユーザーのタップで再生を試みる UI を表示

### Bug 5: MJPEG ストリームの帯域浪費

**症状:** WebRTC が接続中にもかかわらず MJPEG ストリームが裏で動き続け、帯域が二重消費される。

**原因:** `<img src="/video_feed">` を非表示にしても HTTP 接続は維持される。

**対策:**
- `showWebRTC()` で `videoMJPEG.src = ''` として明示的に MJPEG 接続を切断
- `showMJPEG()` で再度 `src` を設定してストリームを再開
- WebRTC 接続成功後に MJPEG の `<img>` から `src` を除去する順序を厳守

### Bug 6: Service Worker が WebRTC API レスポンスをキャッシュ

**症状:** SDP answer がキャッシュされ、古い接続情報で接続を試みて失敗する。

**原因:** Service Worker のキャッシュ戦略が `/api/webrtc/*` をキャッシュする可能性。

**対策:**
- 既存の `sw.js` は `/api/*` をスキップする設計（変更不要）
- 確認: `sw.js` の fetch ハンドラで `/api/` プレフィックスがキャッシュ対象外であることを実装時に検証

### Bug 7: カメラ解像度変更後に WebRTC 映像が乱れる

**症状:** カメラ設定で解像度を変更した後、WebRTC 映像にノイズが入る、またはフリーズする。

**原因:** `CameraVideoTrack` が前の解像度でエンコード中のところに、カメラが異なる解像度のフレームを返し始める。H.264 エンコーダが解像度変更を検知できない。

**対策:**
- 設定変更後にクライアントが `PetWebRTC.close()` → `PetWebRTC.connect()` で新規接続を行う
- サーバー側: 旧 PeerConnection は `close_peer()` でクリーンアップ → 新規接続で新しい `CameraVideoTrack` が作成される
- `_source_track` も解像度変更時にリセットが必要:

```python
# config 変更時に _source_track をリセット
def reset_source_track():
    """カメラ設定変更時に呼ぶ。次の offer で新しいトラックが作成される。"""
    global _source_track
    if _source_track:
        _source_track.stop()
    _source_track = None
```

### Bug 8: MediaRelay のサブスクリプションリーク

**症状:** PeerConnection が閉じられても MediaRelay のサブスクリプションが残り、メモリとCPUが漏洩する。

**原因:** `_relay.subscribe()` で作成されたリレートラックが、PeerConnection の close 時に適切に解放されない。

**対策:**
- aiortc の `RTCPeerConnection.close()` は内部でトラックの `stop()` を呼ぶ
- MediaRelay はトラックが stop されるとサブスクリプションを解除する
- 念のため `_cleanup_pc()` で明示的にトラックを stop:

```python
async def _cleanup_pc(pc_id: str, required_session: str | None = None) -> bool:
    # ... 所有者チェック ...
    pc = _peer_connections.pop(pc_id, None)
    if pc:
        # トラックを明示的に停止
        for sender in pc.getSenders():
            if sender.track:
                sender.track.stop()
        await pc.close()
    return True
```

### Bug 9: PTS 不連続によるブラウザ側の映像フリーズ

**症状:** WebRTC 映像が数秒ごとにカクつく、または一瞬フリーズする。

**原因:** `CameraVideoTrack.recv()` で `time.time()` ベースの PTS を設定しているが、`asyncio.sleep()` のジッターにより PTS が不連続になる可能性。

**対策:**
- `_count / _fps` ベースの理想的な PTS を使用（ジッター耐性が高い）:

```python
frame.pts = int(self._count * 90000 / self._fps)
```

- `time.time()` ベースの実時間 PTS は遅延蓄積の検出用に別途保持するが、フレームには `_count` ベースの安定した PTS を設定する

### Bug 10: `pagehide` でのネットワーク リクエスト失敗

**症状:** ページ離脱時の `DELETE /api/webrtc/<pc_id>` が送信されず、サーバー側でゾンビ接続が残る。

**原因:** `pagehide` イベント中は通常の `fetch()` がキャンセルされる可能性がある。

**対策:**
- `fetch()` に `keepalive: true` を指定（ページ離脱後もリクエストを維持）:

```javascript
fetch(`/api/webrtc/${pcId}`, { method: 'DELETE', keepalive: true }).catch(() => {});
```

- `keepalive` はペイロード 64KB 以下のリクエストでサポート（DELETE なら問題なし）
- 仮に `DELETE` が送れなくても、サーバー側の disconnected タイムアウト（30 秒）で自動クリーンアップされるため致命的ではない

---

## 19. ファイル変更一覧

| ファイル | 種別 | 変更内容 |
|---------|------|---------|
| `server/webrtc.py` | **新規** | WebRTC モジュール（asyncio ループ、CameraVideoTrack、公開 API、disconnected タイムアウト、所有者管理） |
| `server/app.py` | 変更 | WebRTC API エンドポイント追加（offer + close）、main() に start/stop 追加 |
| `server/config.py` | 変更 | WebRTC 設定値追加（WEBRTC_DEFAULT_FPS, WEBRTC_MAX_PEERS） |
| `server/requirements.txt` | 変更 | aiortc 追加 |
| `static/js/webrtc.js` | **新規** | WebRTC クライアントモジュール（状態管理、`_isClosing` フラグ、リトライ/フォールバック タイマー） |
| `static/js/app.js` | 変更 | WebRTC/MJPEG 切り替え、スナップショット対応、設定変更後再接続、ステータス表示（チェックリスト 7.4 参照） |
| `templates/index.html` | 変更 | `<video>` 要素追加、`webrtc.js` 読み込み追加 |
