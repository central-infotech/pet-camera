/**
 * Pet Camera — Display page (Phase 2)
 * Receives video frames from smartphone via Socket.IO and renders them.
 */
(() => {
  const img = document.getElementById('display-video');
  const statusEl = document.getElementById('display-status');

  let socket = null;
  let currentBlobUrl = null;
  let hideStatusTimer = null;

  function connect() {
    socket = io('/video', {
      transports: ['websocket'],
      auth: { role: 'display' },
    });

    socket.on('connect', () => {
      console.log('[Display] Connected');
      statusEl.textContent = '接続完了 — 映像待機中...';
      socket.emit('display_join');
    });

    socket.on('connect_error', (err) => {
      console.error('[Display] Connection error:', err.message);
      statusEl.textContent = '接続エラー';
      statusEl.classList.remove('hidden');
    });

    socket.on('video_frame', (data) => {
      // Revoke previous blob URL to prevent memory leak
      if (currentBlobUrl) {
        URL.revokeObjectURL(currentBlobUrl);
      }

      const blob = new Blob([data], { type: 'image/jpeg' });
      currentBlobUrl = URL.createObjectURL(blob);
      img.src = currentBlobUrl;

      // Hide status text when receiving frames
      statusEl.classList.add('hidden');

      // Reset the hide timer — show status again if frames stop
      clearTimeout(hideStatusTimer);
      hideStatusTimer = setTimeout(() => {
        statusEl.textContent = '映像が途切れました';
        statusEl.classList.remove('hidden');
      }, 3000);
    });

    socket.on('video_status', (status) => {
      console.log('[Display] Status:', status);
      if (!status.sending) {
        statusEl.textContent = '映像待機中...';
        statusEl.classList.remove('hidden');
      }
    });

    socket.on('disconnect', () => {
      console.log('[Display] Disconnected');
      statusEl.textContent = '切断されました — 再接続中...';
      statusEl.classList.remove('hidden');
    });
  }

  // Try to keep screen awake using Wake Lock API
  async function requestWakeLock() {
    if (!('wakeLock' in navigator)) return;
    try {
      await navigator.wakeLock.request('screen');
      console.log('[Display] Screen Wake Lock acquired');
    } catch (err) {
      console.log('[Display] Wake Lock not available:', err.message);
    }
  }

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
