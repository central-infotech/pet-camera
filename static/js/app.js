/**
 * Pet Camera — Main UI logic
 */
(() => {
  // ---- Elements ----
  const btnListen = document.getElementById('btn-listen');
  const btnTalk = document.getElementById('btn-talk');
  const volumeSlider = document.getElementById('volume-slider');
  const btnSnapshot = document.getElementById('btn-snapshot');
  const btnSave = document.getElementById('btn-save');
  const btnSettings = document.getElementById('btn-settings');
  const btnSettingsClose = document.getElementById('btn-settings-close');
  const settingsPanel = document.getElementById('settings-panel');
  const btnApply = document.getElementById('btn-apply');
  const btnReset = document.getElementById('btn-reset');
  const uptimeEl = document.getElementById('uptime');
  const statusFps = document.getElementById('status-fps');
  const statusRes = document.getElementById('status-res');
  const statusAudio = document.getElementById('status-audio');

  // Settings inputs
  const settingRes = document.getElementById('setting-resolution');
  const settingFps = document.getElementById('setting-fps');
  const settingBrightness = document.getElementById('setting-brightness');
  const settingContrast = document.getElementById('setting-contrast');
  const brightnessVal = document.getElementById('brightness-val');
  const contrastVal = document.getElementById('contrast-val');

  // ---- Controls panel toggle ----
  const controlsPanel = document.getElementById('controls-panel');
  const controlsToggle = document.getElementById('controls-toggle');
  const controlsToggleIcon = document.getElementById('controls-toggle-icon');

  // Landscape detection for toggle icon direction
  const landscapeMQ = window.matchMedia('(orientation: landscape) and (max-height: 500px)');

  function updateToggleIcon() {
    const isHidden = controlsPanel.classList.contains('hidden');
    if (landscapeMQ.matches) {
      controlsToggleIcon.textContent = isHidden ? '\u25B6' : '\u25C0'; // ▶ / ◀
    } else {
      controlsToggleIcon.textContent = isHidden ? '\u25BC' : '\u25B2'; // ▼ / ▲
    }
  }

  controlsToggle.addEventListener('click', () => {
    controlsPanel.classList.toggle('hidden');
    updateToggleIcon();
  });

  landscapeMQ.addEventListener('change', updateToggleIcon);

  // ---- Exclusive session banner ----
  const exclusiveBanner = document.getElementById('exclusive-banner');

  // Connect audio socket eagerly to receive exclusive status
  PetAudio.connect();
  PetAudio.onBlockedChange = (blocked) => {
    if (exclusiveBanner) exclusiveBanner.hidden = !blocked;
    btnListen.disabled = blocked;
    btnTalk.disabled = blocked;
    if (btnShowFace) btnShowFace.disabled = blocked;
  };

  // ---- Video: WebRTC with MJPEG fallback ----
  const videoWebRTC = document.getElementById('video-stream-webrtc');
  const videoMJPEG = document.getElementById('video-stream-mjpeg');
  const videoOverlay = document.getElementById('video-overlay');

  function checkVideoLoaded() {
    if (videoMJPEG.naturalWidth > 0) {
      videoOverlay.hidden = true;
    } else {
      videoOverlay.hidden = false;
      requestAnimationFrame(checkVideoLoaded);
    }
  }

  function showWebRTC() {
    videoWebRTC.hidden = false;
    videoMJPEG.hidden = true;
    // Stop MJPEG stream to save bandwidth
    videoMJPEG.src = '';
    videoOverlay.hidden = true;
  }

  function showMJPEG() {
    videoWebRTC.hidden = true;
    videoMJPEG.hidden = false;
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

  // Initial connection
  videoOverlay.hidden = false;
  PetWebRTC.connect(videoWebRTC).then((ok) => {
    if (!ok) showMJPEG();
  });

  // ---- Audio: Listen toggle ----
  btnListen.addEventListener('click', () => {
    if (PetAudio.isListening) {
      PetAudio.stopListening();
      btnListen.classList.remove('active');
    } else {
      PetAudio.startListening();
      btnListen.classList.add('active');
    }
  });

  // ---- Audio: Push-to-talk ----
  function talkStart(e) {
    e.preventDefault();
    PetAudio.startTalking();
    btnTalk.classList.add('active');
  }
  function talkEnd(e) {
    e.preventDefault();
    PetAudio.stopTalking();
    btnTalk.classList.remove('active');
  }

  btnTalk.addEventListener('mousedown', talkStart);
  btnTalk.addEventListener('mouseup', talkEnd);
  btnTalk.addEventListener('mouseleave', talkEnd);
  btnTalk.addEventListener('touchstart', talkStart);
  btnTalk.addEventListener('touchend', talkEnd);
  btnTalk.addEventListener('touchcancel', talkEnd);

  // ---- Volume ----
  volumeSlider.addEventListener('input', () => {
    PetAudio.setVolume(parseInt(volumeSlider.value) / 100);
  });

  // ---- Snapshot download ----
  btnSnapshot.addEventListener('click', async () => {
    try {
      if (PetWebRTC.isConnected()) {
        // WebRTC: capture from video element via canvas
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
        // MJPEG: fetch from server
        const res = await fetch('/snapshot');
        if (!res.ok) throw new Error('Failed');
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `snapshot_${new Date().toISOString().replace(/[:.]/g, '-')}.jpg`;
        a.click();
        URL.revokeObjectURL(url);
      }
    } catch (err) {
      alert('スナップショットの取得に失敗しました');
    }
  });

  // ---- Snapshot save to server ----
  btnSave.addEventListener('click', async () => {
    btnSave.disabled = true;
    try {
      const res = await fetch('/api/snapshots', { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        btnSave.textContent = '保存しました';
        setTimeout(() => { btnSave.innerHTML = '<span class="icon">&#x1F4C1;</span> PCに画像保存'; }, 2000);
      } else {
        alert(data.error?.message || '保存に失敗しました');
      }
    } catch (err) {
      alert('保存に失敗しました');
    } finally {
      btnSave.disabled = false;
    }
  });

  // ---- Settings panel ----
  btnSettings.addEventListener('click', () => {
    settingsPanel.hidden = !settingsPanel.hidden;
    if (!settingsPanel.hidden) loadSettings();
  });

  btnSettingsClose.addEventListener('click', () => {
    settingsPanel.hidden = true;
  });

  settingBrightness.addEventListener('input', () => {
    brightnessVal.textContent = settingBrightness.value;
  });

  settingContrast.addEventListener('input', () => {
    contrastVal.textContent = settingContrast.value;
  });

  async function loadSettings() {
    try {
      const res = await fetch('/api/settings');
      const s = await res.json();
      settingRes.value = `${s.resolution.width}x${s.resolution.height}`;
      settingFps.value = s.fps;
      settingBrightness.value = s.brightness;
      settingContrast.value = s.contrast;
      brightnessVal.textContent = s.brightness;
      contrastVal.textContent = s.contrast;
    } catch (err) {
      console.error('Failed to load settings', err);
    }
  }

  btnApply.addEventListener('click', async () => {
    const [w, h] = settingRes.value.split('x').map(Number);
    const body = {
      resolution: { width: w, height: h },
      fps: parseInt(settingFps.value),
      brightness: parseInt(settingBrightness.value),
      contrast: parseInt(settingContrast.value),
    };
    try {
      const res = await fetch('/api/settings', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        settingsPanel.hidden = true;
        // Reconnect WebRTC with new camera settings
        if (PetWebRTC.isConnected()) {
          PetWebRTC.close();
          videoOverlay.hidden = false;
          PetWebRTC.connect(videoWebRTC).then((ok) => {
            if (!ok) showMJPEG();
          });
        } else {
          // MJPEG fallback: reload stream
          videoOverlay.hidden = false;
          videoMJPEG.src = '/video_feed?' + Date.now();
          checkVideoLoaded();
        }
      } else {
        const data = await res.json();
        alert(data.error?.message || '設定の適用に失敗しました');
      }
    } catch (err) {
      alert('設定の適用に失敗しました');
    }
  });

  btnReset.addEventListener('click', () => {
    settingRes.value = '1280x720';
    settingFps.value = '15';
    settingBrightness.value = '50';
    settingContrast.value = '50';
    brightnessVal.textContent = '50';
    contrastVal.textContent = '50';
  });

  // ---- Status polling ----
  const lsFps = document.getElementById('ls-fps');
  const lsRes = document.getElementById('ls-res');
  const lsAudio = document.getElementById('ls-audio');

  function formatUptime(seconds) {
    const h = Math.floor(seconds / 3600).toString().padStart(2, '0');
    const m = Math.floor((seconds % 3600) / 60).toString().padStart(2, '0');
    const s = (seconds % 60).toString().padStart(2, '0');
    return `${h}:${m}:${s}`;
  }

  async function pollStatus() {
    try {
      const res = await fetch('/api/status');
      if (!res.ok) return;
      const data = await res.json();
      uptimeEl.textContent = formatUptime(data.uptime_seconds);
      const mode = PetWebRTC.isConnected() ? 'WebRTC' : 'MJPEG';
      statusFps.textContent = `${data.fps} fps`;
      statusRes.textContent = `${data.resolution} (${mode})`;
      const mic = data.audio.microphone_active ? 'ON' : 'OFF';
      const listeners = data.audio.listening_clients;
      statusAudio.textContent = `マイク: ${mic} / リスナー: ${listeners}`;
      // Sync to landscape status panel (use line break instead of slash)
      if (lsFps) {
        lsFps.textContent = statusFps.textContent;
        lsRes.textContent = statusRes.textContent;
        lsAudio.innerHTML = `マイク: ${mic}<br>リスナー: ${listeners}`;
      }
    } catch (err) {
      // ignore
    }
  }

  setInterval(pollStatus, 3000);
  pollStatus();

  // ---- Passkey (WebAuthn) registration ----
  const passkeySection = document.getElementById('passkey-register-section');
  const passkeyStatus = document.getElementById('passkey-status');
  const btnPasskeyRegister = document.getElementById('btn-passkey-register');

  function b64urlToBytes(b64url) {
    const b64 = b64url.replace(/-/g, '+').replace(/_/g, '/');
    const pad = (4 - b64.length % 4) % 4;
    const raw = atob(b64 + '='.repeat(pad));
    return Uint8Array.from(raw, c => c.charCodeAt(0));
  }
  function bytesToB64url(bytes) {
    const arr = new Uint8Array(bytes);
    let binary = '';
    for (let i = 0; i < arr.length; i++) binary += String.fromCharCode(arr[i]);
    return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  async function checkPasskeySupport() {
    if (!window.PublicKeyCredential) return;
    passkeySection.hidden = false;
    try {
      const res = await fetch('/api/webauthn/credentials');
      if (res.ok) {
        const data = await res.json();
        passkeyStatus.textContent = data.count > 0
          ? `${data.count} 件のパスキーが登録済み`
          : '未登録（次回からパスキーでログインできます）';
      }
    } catch (e) {
      passkeyStatus.textContent = '状態を取得できません';
    }
  }
  checkPasskeySupport();

  // ---- Phase 2: Owner Video (Show Face) ----
  const btnShowFace = document.getElementById('btn-show-face');
  const ownerVideoStatus = document.getElementById('owner-video-status');
  const ownerPip = document.getElementById('owner-pip');
  const ownerPipVideo = document.getElementById('owner-pip-video');
  let videoSocket = null;
  let ownerVideoStream = null;
  let ownerVideoElement = null;
  let ownerCanvas = null;
  let ownerCanvasCtx = null;
  let captureInterval = null;
  let isSendingVideo = false;

  if (btnShowFace) {
    btnShowFace.addEventListener('click', () => {
      if (isSendingVideo) {
        stopOwnerVideo();
      } else {
        startOwnerVideo();
      }
    });
  }

  async function startOwnerVideo() {
    try {
      ownerVideoStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'user', width: 640, height: 480 },
      });
    } catch (err) {
      console.error('[OwnerVideo] Camera access denied:', err);
      alert('カメラへのアクセスが拒否されました。ブラウザの設定を確認してください。');
      return;
    }

    // Create hidden video element for canvas capture
    ownerVideoElement = document.createElement('video');
    ownerVideoElement.srcObject = ownerVideoStream;
    ownerVideoElement.setAttribute('playsinline', '');
    ownerVideoElement.muted = true;
    await ownerVideoElement.play();

    // Show PiP self-preview
    ownerPipVideo.srcObject = ownerVideoStream;
    ownerPipVideo.play();
    ownerPip.hidden = false;

    // Create canvas for JPEG encoding
    ownerCanvas = document.createElement('canvas');
    ownerCanvas.width = 640;
    ownerCanvas.height = 480;
    ownerCanvasCtx = ownerCanvas.getContext('2d');

    // Connect to /video namespace as sender with auto-reconnect
    videoSocket = io('/video', {
      transports: ['websocket'],
      auth: { role: 'sender' },
      reconnection: true,
      reconnectionAttempts: Infinity,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 30000,
      randomizationFactor: 0.3,
      timeout: 20000,
    });

    videoSocket.on('connect', () => {
      console.log('[OwnerVideo] Socket connected');
      videoSocket.emit('video_send_start', { width: 640, height: 480, fps: 10 });

      if (!isSendingVideo) {
        isSendingVideo = true;
        btnShowFace.classList.add('active');
      }

      ownerVideoStatus.textContent = '送信中: 640x480 / 10fps';

      // Start frame capture (clear existing interval to avoid duplicates)
      if (captureInterval) clearInterval(captureInterval);
      captureInterval = setInterval(captureAndSend, 100); // 10fps
    });

    videoSocket.io.on('reconnect_attempt', (attempt) => {
      console.log('[OwnerVideo] Reconnect attempt:', attempt);
      ownerVideoStatus.textContent = `再接続中...（${attempt}回目）`;
    });

    videoSocket.on('video_error', (err) => {
      console.error('[OwnerVideo] Error:', err);
      if (err.code === 'SENDER_BUSY' || err.code === 'EXCLUSIVE_BLOCKED') {
        alert('別のデバイスが操作中です');
        stopOwnerVideo();
      }
    });

    videoSocket.on('video_status', (status) => {
      console.log('[OwnerVideo] Status:', status);
      if (status.display_clients !== undefined) {
        ownerVideoStatus.textContent = isSendingVideo
          ? `送信中: 640x480 / 10fps / 接続PC: ${status.display_clients}台`
          : '';
      }
    });

    videoSocket.on('disconnect', (reason) => {
      console.log('[OwnerVideo] Socket disconnected:', reason);
      // Don't stop — let auto-reconnect handle it
      if (captureInterval) {
        clearInterval(captureInterval);
        captureInterval = null;
      }
      if (isSendingVideo) {
        ownerVideoStatus.textContent = '切断 — 再接続中...';
      }
    });
  }

  function captureAndSend() {
    if (!ownerVideoElement || !ownerCanvasCtx || !videoSocket || !videoSocket.connected) return;

    ownerCanvasCtx.drawImage(ownerVideoElement, 0, 0, 640, 480);
    ownerCanvas.toBlob((blob) => {
      if (blob && videoSocket && videoSocket.connected) {
        blob.arrayBuffer().then((buf) => {
          videoSocket.emit('video_frame', buf);
        });
      }
    }, 'image/jpeg', 0.6);
  }

  function stopOwnerVideo() {
    isSendingVideo = false;

    if (captureInterval) {
      clearInterval(captureInterval);
      captureInterval = null;
    }

    if (videoSocket) {
      videoSocket.emit('video_send_stop');
      videoSocket.disconnect();
      videoSocket = null;
    }

    // Hide PiP self-preview
    ownerPip.hidden = true;
    ownerPipVideo.srcObject = null;

    if (ownerVideoStream) {
      ownerVideoStream.getTracks().forEach(t => t.stop());
      ownerVideoStream = null;
    }
    ownerVideoElement = null;
    ownerCanvas = null;
    ownerCanvasCtx = null;

    btnShowFace.classList.remove('active');
    ownerVideoStatus.textContent = '';
  }

  if (btnPasskeyRegister) {
    btnPasskeyRegister.addEventListener('click', async () => {
      btnPasskeyRegister.disabled = true;
      btnPasskeyRegister.textContent = '登録中...';
      try {
        // Get registration options
        const optRes = await fetch('/api/webauthn/register/options', { method: 'POST' });
        if (!optRes.ok) throw new Error('登録オプションの取得に失敗');
        const options = await optRes.json();

        // Decode for browser API
        options.challenge = b64urlToBytes(options.challenge);
        options.user.id = b64urlToBytes(options.user.id);
        if (options.excludeCredentials) {
          options.excludeCredentials = options.excludeCredentials.map(c => ({
            ...c, id: b64urlToBytes(c.id),
          }));
        }

        // Invoke browser authenticator
        const credential = await navigator.credentials.create({ publicKey: options });

        // Encode response
        const body = {
          id: credential.id,
          rawId: bytesToB64url(credential.rawId),
          type: credential.type,
          response: {
            attestationObject: bytesToB64url(credential.response.attestationObject),
            clientDataJSON: bytesToB64url(credential.response.clientDataJSON),
          },
        };

        // Verify on server
        const verifyRes = await fetch('/api/webauthn/register', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (verifyRes.ok) {
          passkeyStatus.textContent = 'パスキーを登録しました！';
          checkPasskeySupport();
        } else {
          const data = await verifyRes.json();
          alert(data.error?.message || '登録に失敗しました');
        }
      } catch (err) {
        if (err.name !== 'NotAllowedError') {
          alert(err.message || '登録に失敗しました');
        }
      } finally {
        btnPasskeyRegister.disabled = false;
        btnPasskeyRegister.textContent = '\u{1F511} このデバイスを登録';
      }
    });
  }

  // ---- Visibility change: recover connections after background ----
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      // WebRTC video reconnect
      if (!PetWebRTC.isConnected()) {
        PetWebRTC.connect(videoWebRTC);
      }
      // Owner video reconnect
      if (isSendingVideo && videoSocket && !videoSocket.connected) {
        console.log('[OwnerVideo] Page visible, reconnecting video socket...');
        videoSocket.connect();
      }
      // Check if MediaStream tracks are still live
      if (isSendingVideo && ownerVideoStream) {
        const videoTrack = ownerVideoStream.getVideoTracks()[0];
        if (videoTrack && videoTrack.readyState === 'ended') {
          console.log('[OwnerVideo] Video track ended, restarting...');
          stopOwnerVideo();
          ownerVideoStatus.textContent = 'カメラが停止しました。再度「顔を見せる」を押してください。';
        }
      }
    }
  });

  // ---- Network recovery ----
  window.addEventListener('online', () => {
    console.log('[App] Network online');
    // WebRTC video reconnect
    if (!PetWebRTC.isConnected()) {
      PetWebRTC.connect(videoWebRTC);
    }
    // Owner video reconnect
    if (isSendingVideo && videoSocket && !videoSocket.connected) {
      videoSocket.connect();
    }
  });

  // ---- Page unload: clean up WebRTC ----
  window.addEventListener('pagehide', () => {
    PetWebRTC.close();
  });
})();
