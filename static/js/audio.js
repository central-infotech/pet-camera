/**
 * DNG Camera — Audio module
 * Handles microphone capture (getUserMedia) and speaker playback (Web Audio API)
 * via Socket.IO WebSocket connection.
 * Includes auto-reconnect with state recovery and visibility change handling.
 */

const PetAudio = (() => {
  const SERVER_RATE = 16000;

  let socket = null;
  let audioCtx = null;
  let isListening = false;
  let isTalking = false;
  let mediaStream = null;
  let volume = 0.8;

  // Playback queue for incoming audio
  let nextPlayTime = 0;

  // Talk refs for cleanup
  let _talkSource = null;
  let _talkProcessor = null;

  // Exclusive session control
  let isBlocked = false;
  let _onBlockedChange = null;

  // State tracking for reconnect recovery
  let _wasListening = false;

  function connect() {
    if (socket && socket.connected) return;

    socket = io('/audio', {
      transports: ['websocket'],
      reconnection: true,
      reconnectionAttempts: Infinity,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 30000,
      randomizationFactor: 0.3,
      timeout: 20000,
    });

    socket.on('connect', () => {
      console.log('[Audio] WebSocket connected');
      // Recover listening state after reconnect
      if (_wasListening && !isListening) {
        isListening = true;
        nextPlayTime = 0;
        socket.emit('audio_listen_start');
        console.log('[Audio] Recovered listening state');
      }
    });

    socket.on('connect_error', (err) => {
      console.error('[Audio] Connection error:', err.message);
    });

    socket.io.on('reconnect_attempt', (attempt) => {
      console.log('[Audio] Reconnect attempt:', attempt);
    });

    socket.on('audio_stream', (data) => {
      if (isListening && audioCtx) {
        playPCM(data);
      }
    });

    socket.on('audio_status', (status) => {
      console.log('[Audio] Status:', status);
    });

    socket.on('exclusive_status', (status) => {
      console.log('[Audio] Exclusive status:', status);
      isBlocked = status.blocked;
      if (_onBlockedChange) _onBlockedChange(isBlocked);
    });

    socket.on('disconnect', (reason) => {
      console.log('[Audio] Disconnected:', reason);
      // Save state for recovery
      if (isListening) _wasListening = true;
    });
  }

  function ensureAudioContext() {
    if (!audioCtx) {
      // Use browser default sample rate for maximum compatibility
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      console.log('[Audio] AudioContext sampleRate:', audioCtx.sampleRate);
    }
    if (audioCtx.state === 'suspended') {
      audioCtx.resume();
    }
  }

  /**
   * Resample PCM from srcRate to dstRate using linear interpolation.
   */
  function resample(float32, srcRate, dstRate) {
    if (srcRate === dstRate) return float32;
    const ratio = srcRate / dstRate;
    const outLen = Math.round(float32.length / ratio);
    const out = new Float32Array(outLen);
    for (let i = 0; i < outLen; i++) {
      const srcIdx = i * ratio;
      const idx0 = Math.floor(srcIdx);
      const idx1 = Math.min(idx0 + 1, float32.length - 1);
      const frac = srcIdx - idx0;
      out[i] = float32[idx0] * (1 - frac) + float32[idx1] * frac;
    }
    return out;
  }

  function playPCM(pcmBytes) {
    if (!audioCtx) return;

    try {
      // Convert to ArrayBuffer regardless of incoming type
      let arrayBuf;
      if (pcmBytes instanceof ArrayBuffer) {
        arrayBuf = pcmBytes;
      } else if (pcmBytes.buffer instanceof ArrayBuffer) {
        arrayBuf = pcmBytes.buffer;
      } else {
        arrayBuf = new Uint8Array(pcmBytes).buffer;
      }

      const int16 = new Int16Array(arrayBuf);
      const float32 = new Float32Array(int16.length);
      for (let i = 0; i < int16.length; i++) {
        float32[i] = (int16[i] / 32768.0) * volume;
      }

      // Resample from 16kHz server rate to AudioContext rate
      const resampled = resample(float32, SERVER_RATE, audioCtx.sampleRate);

      const buffer = audioCtx.createBuffer(1, resampled.length, audioCtx.sampleRate);
      buffer.getChannelData(0).set(resampled);

      const source = audioCtx.createBufferSource();
      source.buffer = buffer;
      source.connect(audioCtx.destination);

      const now = audioCtx.currentTime;
      if (nextPlayTime < now) {
        nextPlayTime = now;
      }
      source.start(nextPlayTime);
      nextPlayTime += buffer.duration;
    } catch (err) {
      console.error('[Audio] Playback error:', err);
    }
  }

  function startListening() {
    if (isListening) return;
    connect();
    ensureAudioContext();
    isListening = true;
    _wasListening = true;
    nextPlayTime = 0;
    socket.emit('audio_listen_start');
  }

  function stopListening() {
    if (!isListening) return;
    isListening = false;
    _wasListening = false;
    nextPlayTime = 0;
    if (socket) socket.emit('audio_listen_stop');
  }

  async function startTalking() {
    if (isTalking) return;
    connect();
    ensureAudioContext();

    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        }
      });
    } catch (err) {
      console.error('[Audio] Microphone access denied:', err);
      alert('マイクへのアクセスが拒否されました。ブラウザの設定を確認してください。');
      return;
    }

    isTalking = true;
    socket.emit('audio_talk_start');

    const source = audioCtx.createMediaStreamSource(mediaStream);
    const processor = audioCtx.createScriptProcessor(4096, 1, 1);
    const ctxRate = audioCtx.sampleRate;

    processor.onaudioprocess = (e) => {
      if (!isTalking || !socket) return;
      const float32 = e.inputBuffer.getChannelData(0);

      // Downsample from AudioContext rate to 16kHz server rate
      const resampled = resample(float32, ctxRate, SERVER_RATE);

      const int16 = new Int16Array(resampled.length);
      for (let i = 0; i < resampled.length; i++) {
        const s = Math.max(-1, Math.min(1, resampled[i]));
        int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
      }
      socket.emit('audio_talk', int16.buffer);
    };

    source.connect(processor);
    processor.connect(audioCtx.destination);

    _talkSource = source;
    _talkProcessor = processor;
  }

  function stopTalking() {
    if (!isTalking) return;
    isTalking = false;

    if (socket) socket.emit('audio_talk_stop');

    if (_talkProcessor) {
      _talkProcessor.disconnect();
      _talkProcessor.onaudioprocess = null;
      _talkProcessor = null;
    }
    if (_talkSource) {
      _talkSource.disconnect();
      _talkSource = null;
    }
    if (mediaStream) {
      mediaStream.getTracks().forEach(t => t.stop());
      mediaStream = null;
    }
  }

  function setVolume(v) {
    volume = Math.max(0, Math.min(1, v));
  }

  // ---- Visibility change: resume AudioContext if suspended ----
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      if (audioCtx && audioCtx.state === 'suspended') {
        audioCtx.resume();
        console.log('[Audio] AudioContext resumed after visibility change');
      }
      // Ensure Socket.IO is connected
      if (socket && !socket.connected) {
        console.log('[Audio] Page visible, reconnecting...');
        socket.connect();
      }
    }
  });

  // ---- Network recovery ----
  window.addEventListener('online', () => {
    console.log('[Audio] Network online');
    if (socket && !socket.connected) {
      socket.connect();
    }
  });

  return {
    connect,
    startListening,
    stopListening,
    startTalking,
    stopTalking,
    setVolume,
    get isListening() { return isListening; },
    get isTalking() { return isTalking; },
    get isBlocked() { return isBlocked; },
    set onBlockedChange(fn) { _onBlockedChange = fn; },
  };
})();
