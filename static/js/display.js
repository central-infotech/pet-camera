/**
 * DNG Camera — Display page (Phase 2)
 * Receives video frames from smartphone via Socket.IO and renders them.
 * Includes auto-reconnect, Wake Lock re-acquisition, and visibility recovery.
 */
(() => {
  const img = document.getElementById('display-video');
  const statusEl = document.getElementById('display-status');
  const noSignalEl = document.getElementById('no-signal');

  let socket = null;
  let currentBlobUrl = null;
  let hideStatusTimer = null;
  let wakeLock = null;
  let heartbeatInterval = null;

  // ---- Clear video (show black screen) ----
  function clearVideo() {
    if (currentBlobUrl) {
      URL.revokeObjectURL(currentBlobUrl);
      currentBlobUrl = null;
    }
    img.removeAttribute('src');
    noSignalEl.classList.remove('hidden');
    clearTimeout(hideStatusTimer);
    hideStatusTimer = null;
  }

  // ---- Socket.IO connection with resilience ----
  function connect() {
    socket = io('/video', {
      transports: ['websocket'],
      auth: { role: 'display' },
      reconnection: true,
      reconnectionAttempts: Infinity,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 30000,
      randomizationFactor: 0.3,
      timeout: 20000,
    });

    socket.on('connect', () => {
      console.log('[Display] Connected');
      statusEl.textContent = '接続完了 — 映像待機中...';
      socket.emit('display_join');

      // Session TTL heartbeat: extend display session every 6 hours
      if (heartbeatInterval) clearInterval(heartbeatInterval);
      heartbeatInterval = setInterval(() => {
        if (socket && socket.connected) {
          socket.emit('display_heartbeat');
        }
      }, 6 * 60 * 60 * 1000);
    });

    socket.on('connect_error', (err) => {
      console.error('[Display] Connection error:', err.message);
      clearVideo();
      statusEl.textContent = '接続エラー — 再接続中...';
      statusEl.classList.remove('hidden');
    });

    socket.io.on('reconnect_attempt', (attempt) => {
      console.log('[Display] Reconnect attempt:', attempt);
      statusEl.textContent = `再接続中...（${attempt}回目）`;
      statusEl.classList.remove('hidden');
    });

    socket.io.on('reconnect', (attempt) => {
      console.log('[Display] Reconnected after', attempt, 'attempts');
    });

    socket.io.on('reconnect_failed', () => {
      console.error('[Display] Reconnect failed');
      statusEl.textContent = '接続に失敗しました。ページを再読み込みしてください。';
      statusEl.classList.remove('hidden');
    });

    socket.on('video_frame', (data) => {
      try {
        // Revoke previous blob URL to prevent memory leak
        if (currentBlobUrl) {
          URL.revokeObjectURL(currentBlobUrl);
        }

        const blob = new Blob([data], { type: 'image/jpeg' });
        currentBlobUrl = URL.createObjectURL(blob);
        img.src = currentBlobUrl;

        // Hide status text and no-signal when receiving frames
        statusEl.classList.add('hidden');
        noSignalEl.classList.add('hidden');

        // Reset the hide timer — clear video if frames stop
        clearTimeout(hideStatusTimer);
        hideStatusTimer = setTimeout(() => {
          clearVideo();
          statusEl.textContent = '映像が途切れました';
          statusEl.classList.remove('hidden');
        }, 3000);
      } catch (err) {
        console.error('[Display] Frame processing error:', err);
      }
    });

    socket.on('video_status', (status) => {
      console.log('[Display] Status:', status);
      if (!status.sending) {
        clearVideo();
        statusEl.textContent = '映像待機中...';
        statusEl.classList.remove('hidden');
      }
    });

    socket.on('disconnect', (reason) => {
      console.log('[Display] Disconnected:', reason);
      clearVideo();
      statusEl.textContent = '切断されました — 再接続中...';
      statusEl.classList.remove('hidden');
    });
  }

  // ---- Wake Lock with re-acquisition ----
  async function requestWakeLock() {
    if (!('wakeLock' in navigator)) return;
    try {
      wakeLock = await navigator.wakeLock.request('screen');
      console.log('[Display] Screen Wake Lock acquired');
      wakeLock.addEventListener('release', () => {
        console.log('[Display] Wake Lock released');
        wakeLock = null;
      });
    } catch (err) {
      console.log('[Display] Wake Lock not available:', err.message);
    }
  }

  // ---- Visibility change: re-acquire Wake Lock + check socket ----
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      // Re-acquire Wake Lock
      if (!wakeLock) {
        requestWakeLock();
      }
      // Ensure Socket.IO is connected
      if (socket && !socket.connected) {
        console.log('[Display] Page visible, reconnecting...');
        socket.connect();
      }
    }
  });

  // ---- Network recovery ----
  window.addEventListener('online', () => {
    console.log('[Display] Network online');
    if (socket && !socket.connected) {
      socket.connect();
    }
  });

  window.addEventListener('offline', () => {
    console.log('[Display] Network offline');
    statusEl.textContent = 'ネットワーク切断 — 復帰待ち...';
    statusEl.classList.remove('hidden');
  });

  // ---- Settings panel ----
  const btnSettings = document.getElementById('btn-display-settings');
  const settingsPanel = document.getElementById('display-settings-panel');
  const btnSettingsClose = document.getElementById('btn-display-settings-close');

  btnSettings.addEventListener('click', () => {
    settingsPanel.hidden = !settingsPanel.hidden;
  });

  btnSettingsClose.addEventListener('click', () => {
    settingsPanel.hidden = true;
  });

  // ---- Passkey (WebAuthn) registration ----
  const passkeySection = document.getElementById('display-passkey-section');
  const passkeyStatus = document.getElementById('display-passkey-status');
  const btnPasskeyRegister = document.getElementById('btn-display-passkey-register');

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

  connect();
  requestWakeLock();
})();
