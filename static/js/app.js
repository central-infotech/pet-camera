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

  // ---- Video overlay (hide once first frame arrives) ----
  const videoStream = document.getElementById('video-stream');
  const videoOverlay = document.getElementById('video-overlay');

  function checkVideoLoaded() {
    if (videoStream.naturalWidth > 0) {
      videoOverlay.hidden = true;
    } else {
      videoOverlay.hidden = false;
      requestAnimationFrame(checkVideoLoaded);
    }
  }
  videoOverlay.hidden = false;
  checkVideoLoaded();

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
      const res = await fetch('/snapshot');
      if (!res.ok) throw new Error('Failed');
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `snapshot_${new Date().toISOString().replace(/[:.]/g, '-')}.jpg`;
      a.click();
      URL.revokeObjectURL(url);
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
        setTimeout(() => { btnSave.innerHTML = '<span class="icon">&#x1F4BE;</span> 保存'; }, 2000);
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
        // Reload video stream with new settings
        videoOverlay.hidden = false;
        videoStream.src = '/video_feed?' + Date.now();
        checkVideoLoaded();
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
      statusFps.textContent = `${data.fps} fps`;
      statusRes.textContent = data.resolution;
      const mic = data.audio.microphone_active ? 'ON' : 'OFF';
      const listeners = data.audio.listening_clients;
      statusAudio.textContent = `マイク: ${mic} / リスナー: ${listeners}`;
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
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
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

    // Create canvas for JPEG encoding
    ownerCanvas = document.createElement('canvas');
    ownerCanvas.width = 640;
    ownerCanvas.height = 480;
    ownerCanvasCtx = ownerCanvas.getContext('2d');

    // Connect to /video namespace as sender
    videoSocket = io('/video', {
      transports: ['websocket'],
      auth: { role: 'sender' },
    });

    videoSocket.on('connect', () => {
      console.log('[OwnerVideo] Socket connected');
      videoSocket.emit('video_send_start', { width: 640, height: 480, fps: 10 });
      isSendingVideo = true;
      btnShowFace.classList.add('active');
      ownerVideoStatus.textContent = '送信中: 640x480 / 10fps';

      // Start audio talk (continuous mode)
      PetAudio.startContinuousTalk(ownerVideoStream);

      // Disable listen and talk buttons during owner video
      btnListen.disabled = true;
      btnTalk.disabled = true;
      if (PetAudio.isListening) {
        PetAudio.stopListening();
        btnListen.classList.remove('active');
      }

      // Start frame capture
      captureInterval = setInterval(captureAndSend, 100); // 10fps
    });

    videoSocket.on('video_error', (err) => {
      console.error('[OwnerVideo] Error:', err);
      if (err.code === 'SENDER_BUSY') {
        alert('別のデバイスが既に映像を送信中です');
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

    videoSocket.on('disconnect', () => {
      console.log('[OwnerVideo] Socket disconnected');
      if (isSendingVideo) stopOwnerVideo();
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

    // Stop continuous talk
    PetAudio.stopContinuousTalk();

    // Re-enable listen and talk buttons
    btnListen.disabled = false;
    btnTalk.disabled = false;

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
})();
