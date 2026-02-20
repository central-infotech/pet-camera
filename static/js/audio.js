/**
 * Pet Camera — Audio module
 * Handles microphone capture (getUserMedia) and speaker playback (Web Audio API)
 * via Socket.IO WebSocket connection.
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

  // Continuous talk mode (Phase 2)
  let isContinuousTalking = false;

  function connect() {
    if (socket && socket.connected) return;

    socket = io('/audio', {
      transports: ['websocket'],
    });

    socket.on('connect', () => {
      console.log('[Audio] WebSocket connected');
    });

    socket.on('connect_error', (err) => {
      console.error('[Audio] Connection error:', err.message);
    });

    socket.on('audio_stream', (data) => {
      if (isListening && audioCtx) {
        playPCM(data);
      }
    });

    socket.on('audio_status', (status) => {
      console.log('[Audio] Status:', status);
    });

    socket.on('disconnect', () => {
      console.log('[Audio] Disconnected');
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
  }

  function startListening() {
    if (isListening) return;
    connect();
    ensureAudioContext();
    isListening = true;
    nextPlayTime = 0;
    socket.emit('audio_listen_start');
  }

  function stopListening() {
    if (!isListening) return;
    isListening = false;
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

  /**
   * Start continuous talk using an existing MediaStream (Phase 2).
   * Used by "Show Face" feature — reuses the audio track from getUserMedia({video, audio}).
   */
  function startContinuousTalk(existingStream) {
    if (isContinuousTalking) return;
    connect();
    ensureAudioContext();

    // Extract audio tracks from the existing stream
    const audioTracks = existingStream.getAudioTracks();
    if (audioTracks.length === 0) {
      console.warn('[Audio] No audio tracks in stream for continuous talk');
      return;
    }

    const audioStream = new MediaStream(audioTracks);

    isContinuousTalking = true;
    isTalking = true;
    socket.emit('audio_talk_start');

    const source = audioCtx.createMediaStreamSource(audioStream);
    const processor = audioCtx.createScriptProcessor(4096, 1, 1);
    const ctxRate = audioCtx.sampleRate;

    processor.onaudioprocess = (e) => {
      if (!isContinuousTalking || !socket) return;
      const float32 = e.inputBuffer.getChannelData(0);
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
    // Note: We don't store mediaStream here — it's owned by the caller (app.js)
  }

  function stopContinuousTalk() {
    if (!isContinuousTalking) return;
    isContinuousTalking = false;
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
    // Don't stop mediaStream tracks — owned by caller
  }

  return {
    connect,
    startListening,
    stopListening,
    startTalking,
    stopTalking,
    startContinuousTalk,
    stopContinuousTalk,
    setVolume,
    get isListening() { return isListening; },
    get isTalking() { return isTalking; },
  };
})();
