/**
 * DNG Camera — WebRTC video module
 * Receives WebRTC video from the server with MJPEG fallback.
 *
 * State transitions:
 *   IDLE -> CONNECTING -> CONNECTED -> (DISCONNECTED -> CONNECTING | IDLE)
 *                     \-> RETRYING -> CONNECTING
 *                     \-> FALLBACK (MJPEG) -> periodic CONNECTING retry
 */
const PetWebRTC = (() => {
  let pc = null;
  let pcId = null;
  let _videoEl = null;

  // ── State ──
  let _isClosing = false;
  let _retryTimer = null;
  let _fallbackTimer = null;
  let retryCount = 0;

  const MAX_RETRIES = 5;
  const RETRY_BASE_DELAY = 2000;
  const FALLBACK_RETRY_INTERVAL = 60000;

  // ── Callbacks ──
  let _onConnected = null;
  let _onDisconnected = null;
  let _onFallback = null;

  /**
   * Start a WebRTC connection.
   * @param {HTMLVideoElement} videoEl
   * @returns {Promise<boolean>}
   */
  async function connect(videoEl) {
    _isClosing = false;
    _videoEl = videoEl;

    // Clean up any existing connection (without triggering reconnect)
    _internalClose();

    try {
      pc = new RTCPeerConnection({ iceServers: [] });

      pc.ontrack = (event) => {
        console.log('[WebRTC] Track received:', event.track.kind);
        videoEl.srcObject = event.streams[0];
        videoEl.play().catch(e => console.warn('[WebRTC] Autoplay blocked:', e));
      };

      // ── Connection state monitoring ──
      pc.onconnectionstatechange = () => {
        if (_isClosing) return;

        const state = pc.connectionState;
        console.log('[WebRTC] Connection state:', state);

        if (state === 'connected') {
          retryCount = 0;
          _cancelFallbackTimer();
          if (_onConnected) _onConnected();
        } else if (state === 'disconnected') {
          _scheduleRetry(5000);
        } else if (state === 'failed') {
          if (_onDisconnected) _onDisconnected();
          _scheduleRetry(0);
        }
        // 'closed' results from intentional close() — do not reconnect
      };

      // ICE connection state (early failure detection)
      pc.oniceconnectionstatechange = () => {
        if (_isClosing) return;
        const state = pc.iceConnectionState;
        console.log('[WebRTC] ICE connection state:', state);
        if (state === 'failed') {
          if (_onDisconnected) _onDisconnected();
          _scheduleRetry(0);
        }
      };

      // Receive-only video
      pc.addTransceiver('video', { direction: 'recvonly' });

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      // Wait for ICE gathering to complete (Vanilla ICE)
      await _waitIceGathering(pc);

      const res = await fetch('/api/webrtc/offer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sdp: pc.localDescription.sdp,
          type: 'offer',
        }),
      });

      if (!res.ok) {
        throw new Error('Server returned ' + res.status);
      }

      const answer = await res.json();
      pcId = answer.pc_id;

      await pc.setRemoteDescription(
        new RTCSessionDescription({ sdp: answer.sdp, type: answer.type })
      );

      console.log('[WebRTC] Connection established (pc_id=' + pcId + ')');
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

      // Timeout (5s) — should be instant on Tailscale
      setTimeout(() => {
        peerConnection.removeEventListener('icegatheringstatechange', check);
        resolve();
      }, 5000);
    });
  }

  function _scheduleRetry(initialDelay) {
    if (_isClosing) return;
    _cancelRetryTimer();

    if (retryCount >= MAX_RETRIES) {
      console.warn('[WebRTC] Max retries reached, falling back to MJPEG');
      if (_onFallback) _onFallback();
      _startFallbackTimer();
      return;
    }

    retryCount++;
    const delay = initialDelay > 0
      ? initialDelay
      : RETRY_BASE_DELAY * Math.pow(2, retryCount - 1);
    console.log('[WebRTC] Retry ' + retryCount + '/' + MAX_RETRIES + ' in ' + delay + 'ms');

    _retryTimer = setTimeout(() => {
      _retryTimer = null;
      if (!_isClosing && _videoEl) {
        connect(_videoEl);
      }
    }, delay);
  }

  function _startFallbackTimer() {
    _cancelFallbackTimer();
    _fallbackTimer = setInterval(() => {
      if (_isClosing) {
        _cancelFallbackTimer();
        return;
      }
      console.log('[WebRTC] Periodic retry from MJPEG fallback');
      retryCount = 0;
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

  function _internalClose() {
    if (pcId) {
      // Notify server (best-effort, keepalive survives pagehide)
      fetch('/api/webrtc/' + pcId, { method: 'DELETE', keepalive: true }).catch(() => {});
      pcId = null;
    }
    if (pc) {
      // Remove handlers before close to prevent reconnect triggers
      pc.onconnectionstatechange = null;
      pc.oniceconnectionstatechange = null;
      pc.ontrack = null;
      pc.close();
      pc = null;
    }
  }

  /**
   * Intentionally disconnect (no reconnect).
   */
  function close() {
    _isClosing = true;
    _cancelRetryTimer();
    _cancelFallbackTimer();
    _internalClose();
  }

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
