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

  connect();
  requestWakeLock();
})();
