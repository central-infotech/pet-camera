# ストリーミング方式の改善案

現在の MJPEG 方式はフレーム間圧縮がなく、H.264 比で 2〜5 倍の帯域を消費する。
モバイル回線で長時間視聴するユースケースに対応するため、ストリーミング方式の改善を検討する。

---

## 現状の構成

| 要素 | 現在の実装 |
|------|-----------|
| 映像キャプチャ | OpenCV `VideoCapture` (DirectShow) |
| 映像コーデック | MJPEG（毎フレーム独立 JPEG） |
| 映像配信 | Flask `multipart/x-mixed-replace` (HTTP) |
| 音声コーデック | 生 PCM 16kHz/16bit mono |
| 音声配信 | Socket.IO (WebSocket) |
| 飼い主映像 | Socket.IO で JPEG バイナリ送信 |
| サーバー | Python Flask + Flask-SocketIO (threading) |
| 依存関係 | opencv-python, flask, flask-socketio, sounddevice, numpy |
| PC GPU | AMD Radeon（`h264_amf` 利用可能）※ログの "AMD HD Audio DP" より推定 |

**帯域の目安（現在）:**
- 720p/10fps MJPEG: ~40 KB/frame × 10fps ≈ **3.2 Mbps（~1.4 GB/h）**
- 720p/15fps MJPEG: ~40 KB/frame × 15fps ≈ **4.8 Mbps（~2.2 GB/h）**

**目標:** 同等画質で **0.5〜1.5 Mbps（~0.2〜0.7 GB/h）** に削減

---

## ストリーミング方式の一覧

### 1. MJPEG（現状維持）

HTTP の `multipart/x-mixed-replace` で毎フレーム独立 JPEG を送信。

| 項目 | 評価 |
|------|------|
| 遅延 | 100〜300ms（優秀） |
| 帯域効率 | 悪い（H.264 の 2〜5 倍） |
| ブラウザ互換 | 全ブラウザ対応（`<img>` タグで表示可能） |
| 実装の複雑さ | 最も単純 |
| 追加依存 | なし |

**まとめ:** 帯域効率以外は優秀。Wi-Fi 専用なら十分。

---

### 2. HLS（HTTP Live Streaming）

Apple 開発。H.264 エンコードした映像を 2〜6 秒のセグメント（`.ts` / `.m4s`）に分割し、`.m3u8` プレイリストで配信。LL-HLS（Low-Latency HLS）ではパーシャルセグメント（~200ms）を使い遅延を短縮。

| 項目 | 評価 |
|------|------|
| 遅延 | 通常 HLS: 6〜30 秒、LL-HLS: **2〜5 秒** |
| 帯域効率 | 優秀（H.264 フレーム間圧縮） |
| ブラウザ互換 | iOS Safari: ネイティブ対応、その他: hls.js ライブラリ経由 |
| 実装の複雑さ | 中 |
| 追加依存 | ffmpeg（外部バイナリ）、hls.js（クライアント） |

**サーバー側の実装:**
```
OpenCV フレーム取得
  → ffmpeg subprocess の stdin にパイプ (rawvideo BGR24)
  → ffmpeg が H.264 エンコード + HLS セグメント生成
  → Flask がセグメントファイルを HTTP 配信
```

**ffmpeg コマンド例:**
```bash
ffmpeg -f rawvideo -pix_fmt bgr24 -s 1280x720 -r 10 -i pipe:0 \
  -c:v libx264 -preset ultrafast -tune zerolatency \
  -g 20 -sc_threshold 0 \
  -f hls -hls_time 2 -hls_list_size 3 \
  -hls_flags delete_segments+append_list \
  /path/to/stream.m3u8
```

**AMD GPU ハードウェアエンコード:**
```bash
ffmpeg ... -c:v h264_amf -quality speed -rc cqp -qp_i 26 -qp_p 28 ...
```

**クライアント側:**
```javascript
// hls.js (iOS Safari 以外)
if (Hls.isSupported()) {
  const hls = new Hls({ lowLatencyMode: true });
  hls.loadSource('/stream/stream.m3u8');
  hls.attachMedia(videoElement);
}
// iOS Safari はネイティブ対応
else if (videoElement.canPlayType('application/vnd.apple.mpegurl')) {
  videoElement.src = '/stream/stream.m3u8';
}
```

**メリット:**
- iOS Safari ネイティブ対応（PWA で最も安定）
- 帯域効率が大幅に改善（720p/10fps で ~0.5〜1.0 Mbps）
- セグメントファイルは標準 HTTP で配信（CDN 対応可能）
- MJPEG との並行運用が容易（別エンドポイントで提供）

**デメリット:**
- 最低 2〜5 秒の遅延（LL-HLS でも）
- ffmpeg プロセスの管理が必要
- セグメントファイルのディスク書き込み（tmpfs/RAM disk 推奨）

---

### 3. WebRTC

ブラウザ標準のリアルタイム通信プロトコル。H.264 + Opus を DTLS-SRTP で暗号化し、RTP/UDP で送信。シグナリング（SDP 交換）は任意の経路で行い、ICE で NAT 越えを処理。

#### 3a. aiortc（Python WebRTC ライブラリ）

| 項目 | 評価 |
|------|------|
| 遅延 | 50〜300ms（最低遅延） |
| 帯域効率 | 優秀（H.264、帯域適応あり） |
| ブラウザ互換 | 全モダンブラウザ対応（iOS Safari 含む） |
| 実装の複雑さ | 高い |
| 追加依存 | aiortc, av (PyAV/FFmpeg バインディング), cryptography, pylibsrtp |

**サーバー側の実装:**
```
OpenCV フレーム取得（スレッド）
  → collections.deque(maxlen=1) に最新フレーム格納
  → CustomVideoTrack.recv() で取り出し
  → aiortc が H.264 エンコード + WebRTC 送信
```

**シグナリングフロー:**
```
1. ブラウザが SDP offer を生成 → Flask API にPOST
2. サーバーが aiortc で SDP answer を生成 → レスポンスで返却
3. ICE candidate 交換（Socket.IO or API 経由）
4. WebRTC 接続確立 → 映像・音声配信開始
```

**既知の問題:**
- aiortc の `VideoStreamTrack` で OpenCV 処理すると **遅延が蓄積** する（4〜5秒 → 30秒以上に増加）。`deque(maxlen=1)` + 別スレッドの回避策が必須。
- ソフトウェアエンコード（ハードウェアアクセラレーション非対応）
- Windows での動作は pip wheel で対応済み（v1.14.0, Python 3.12/3.13）

**メリット:**
- 最低遅延（50〜300ms）
- 帯域効率優秀 + 自動帯域適応
- 全ブラウザ対応
- Flask プロセス内で完結（外部プロセス不要）

**デメリット:**
- 実装が複雑（async/threading の設計が重要）
- 遅延蓄積問題の回避策が必要
- ソフトウェアエンコードで CPU 負荷がやや高い
- ICE/STUN/TURN の考慮（Tailscale 環境なら NAT 問題なし）

#### 3b. 外部リレーサーバー（go2rtc / MediaMTX）

| 項目 | 評価 |
|------|------|
| 遅延 | 50〜300ms |
| 帯域効率 | 優秀 |
| ブラウザ互換 | 全モダンブラウザ |
| 実装の複雑さ | 中（設定ベース） |
| 追加依存 | go2rtc or MediaMTX（Go バイナリ）、ffmpeg |

**構成:**
```
OpenCV → ffmpeg subprocess → RTSP ストリーム → go2rtc / MediaMTX → WebRTC (WHEP)
                                                                    → HLS (フォールバック)
Flask は認証・設定・スナップショット・UIを担当
ブラウザは go2rtc / MediaMTX に直接接続して映像受信
```

**go2rtc:**
- Go 製シングルバイナリ（~15MB、依存なし）
- RTSP / RTMP / WebRTC / MJPEG / HLS 対応
- WHEP（WebRTC HTTP Egress Protocol）対応
- Frigate / Home Assistant で採用実績あり
- 設定例:
  ```yaml
  streams:
    petcam:
      - rtsp://127.0.0.1:8554/live
  ```

**MediaMTX（旧 rtsp-simple-server）:**
- Go 製シングルバイナリ（~15MB、依存なし）
- RTSP / RTMP / HLS / LL-HLS / WebRTC (WHEP/WHIP) / SRT 対応
- 設定例:
  ```yaml
  paths:
    live:
      source: publisher
  ```

**Flask → RTSP パイプライン（ffmpeg）:**
```bash
ffmpeg -f rawvideo -pix_fmt bgr24 -s 1280x720 -r 10 -i pipe:0 \
  -c:v libx264 -preset ultrafast -tune zerolatency \
  -f rtsp rtsp://127.0.0.1:8554/live
```

**AMD GPU 利用:**
```bash
ffmpeg ... -c:v h264_amf -quality speed ...
```

**メリット:**
- 低遅延 + 高帯域効率
- プロダクション品質のプロトコル変換
- aiortc の遅延蓄積問題を回避
- HLS フォールバック自動提供

**デメリット:**
- 外部プロセス（go2rtc / MediaMTX + ffmpeg）の管理
- NSSM サービスとの統合が必要
- ブラウザが Flask とリレーサーバーの 2 箇所に接続
- 認証の二重化（Flask 認証 + リレーサーバーへのアクセス制御）

---

### 4. MSE + fMP4（WebSocket 経由）

H.264 エンコードした映像を fragmented MP4（fMP4）形式で WebSocket 経由で配信。ブラウザの Media Source Extensions（MSE）API で `<video>` タグに流し込む。

| 項目 | 評価 |
|------|------|
| 遅延 | 0.5〜2 秒 |
| 帯域効率 | 優秀（H.264） |
| ブラウザ互換 | Chrome/Firefox/Edge: MSE 対応、**iOS Safari: ManagedMediaSource（17.1+）** |
| 実装の複雑さ | 中〜高 |
| 追加依存 | ffmpeg |

**サーバー側の実装:**
```
OpenCV フレーム取得
  → ffmpeg subprocess stdin にパイプ (rawvideo)
  → ffmpeg が H.264 → fMP4 出力 (stdout)
  → Flask/Socket.IO が fMP4 チャンクを WebSocket で配信
```

**ffmpeg コマンド例（fMP4 出力）:**
```bash
ffmpeg -f rawvideo -pix_fmt bgr24 -s 1280x720 -r 10 -i pipe:0 \
  -c:v libx264 -preset ultrafast -tune zerolatency \
  -g 20 -sc_threshold 0 \
  -f mp4 -movflags frag_keyframe+empty_moov+default_base_moof \
  pipe:1
```

**クライアント側:**
```javascript
// iOS Safari 17.1+ は ManagedMediaSource を使用
const MSE = window.ManagedMediaSource || window.MediaSource;
const ms = new MSE();
video.src = URL.createObjectURL(ms);

ms.addEventListener('sourceopen', () => {
  const sb = ms.addSourceBuffer('video/mp4; codecs="avc1.42E01E"');
  socket.on('video_fmp4', (chunk) => {
    sb.appendBuffer(new Uint8Array(chunk));
  });
});
```

**iOS Safari の互換性:**
- iPhone: MSE 非対応 → **ManagedMediaSource (MMS)** が iOS 17.1（2023年後半）から利用可能
- MMS は MSE と API 互換だが、`window.ManagedMediaSource` の Feature Detection が必要
- iOS 17.1 以上であれば動作する（2026年時点で大多数の iPhone が対応）

**メリット:**
- 既存の Socket.IO インフラを活用可能
- Flask プロセス内で完結
- 帯域効率優秀
- 遅延は WebRTC ほど低くないが HLS より低い

**デメリット:**
- iOS Safari で ManagedMediaSource の対応が必要（コード分岐）
- ffmpeg プロセスの管理
- SourceBuffer 管理（バッファ肥大化防止）が必要
- 音声の同期は別途考慮（既存 Socket.IO PCM と並行可能）

---

### 5. WebCodecs API（将来候補）

ブラウザの低レベル映像デコーダに直接 H.264 NAL ユニットを渡す。コンテナ不要で最小オーバーヘッド。

| 項目 | 評価 |
|------|------|
| 遅延 | < 100ms（理論上最低） |
| 帯域効率 | 優秀（H.264） |
| ブラウザ互換 | Chrome: 対応、Safari: 部分対応（16.4+）、**Firefox Android: 非対応** |
| 実装の複雑さ | 高い |
| 追加依存 | ffmpeg |

**サーバー側:** ffmpeg で H.264 NAL ユニットを生成 → WebSocket で送信
**クライアント側:** `VideoDecoder` API でデコード → Canvas に描画

**メリット:**
- 理論上最低の遅延とオーバーヘッド
- コンテナ解析不要

**デメリット:**
- Firefox Android 非対応（現時点）
- iOS Safari は部分対応（AudioDecoder 未対応）
- クライアント側のコードが複雑（手動デコーダ管理、フレームタイミング）
- まだ成熟していない API

**結論:** 現時点では見送り。2027年以降にブラウザ対応が安定してから再検討。

---

### 6. WebTransport（将来候補）

HTTP/3 (QUIC) ベースのトランスポート。UDP ライクな unreliable datagram をサポートし、遅延フレームの破棄が可能。

| 項目 | 評価 |
|------|------|
| 遅延 | < 100ms |
| 帯域効率 | 優秀 |
| ブラウザ互換 | Chrome/Firefox: 対応、**Safari/iOS: 非対応**（Interop 2026 注力領域） |
| 実装の複雑さ | 高い |
| 追加依存 | aioquic（実験的） |

**結論:** Safari/iOS 非対応のため現時点では見送り。2027年以降に再検討。

---

## 比較まとめ

| 方式 | 遅延 | 帯域 720p/10fps | iOS Safari | 実装量 | 外部依存 |
|------|------|----------------|------------|--------|---------|
| **MJPEG**（現状） | 100〜300ms | ~3.2 Mbps | ネイティブ | なし | なし |
| **HLS / LL-HLS** | 2〜5 秒 | ~0.5〜1.0 Mbps | ネイティブ | 中 | ffmpeg, hls.js |
| **WebRTC (aiortc)** | 50〜300ms | ~0.5〜1.5 Mbps | 対応 | 大 | aiortc, av |
| **WebRTC (リレー)** | 50〜300ms | ~0.5〜1.5 Mbps | 対応 | 中 | go2rtc + ffmpeg |
| **MSE + fMP4** | 0.5〜2 秒 | ~0.5〜1.0 Mbps | MMS (17.1+) | 中〜大 | ffmpeg |
| **WebCodecs** | < 100ms | ~0.5〜1.0 Mbps | 部分的 | 大 | ffmpeg |
| **WebTransport** | < 100ms | ~0.5〜1.0 Mbps | **非対応** | 大 | aioquic |

---

## 推奨案（優先順）

### 案 A: HLS / LL-HLS（推奨 — 最も実用的）

**理由:**
1. iOS Safari ネイティブ対応 — PWA 運用で最も安定
2. 実装が比較的シンプル（ffmpeg subprocess + ファイル配信）
3. 帯域を 1/3〜1/5 に削減（~1.0 Mbps 以下）
4. MJPEG と並行運用可能（Wi-Fi 時は低遅延 MJPEG、モバイル時は省帯域 HLS を選択）
5. ffmpeg のみが追加依存（Windows バイナリは簡単に入手可能）

**遅延 2〜5 秒の許容性:**
ペットカメラの用途では「今この瞬間のペットの様子を見る」のが目的であり、数秒の遅延は実用上問題ない。音声通話（話す・聞く）は既存の Socket.IO リアルタイム経路を維持するため、対話性は損なわれない。

**実装の概要:**
1. `server/hls_encoder.py` — ffmpeg subprocess でフレームを H.264 HLS に変換
2. `server/app.py` — `/stream/` エンドポイントで .m3u8 と .ts ファイルを配信
3. `static/js/app.js` — hls.js を使った `<video>` 再生、iOS Safari は `<video src>` 直接
4. 設定画面 — ストリーミング方式の切り替え（MJPEG / HLS）
5. `config.py` — HLS 関連設定（セグメント長、リスト長、tmpdir）

**追加依存:**
- サーバー: ffmpeg バイナリ（PATH に配置 or 設定で指定）
- クライアント: hls.js（CDN or 静的ファイル、~60KB gzip）

---

### 案 B: MSE + fMP4 over Socket.IO

**理由:**
1. 既存 Socket.IO インフラを再利用
2. HLS より低遅延（0.5〜2 秒）
3. 外部プロセスは ffmpeg のみ

**懸念:**
- iOS Safari で `ManagedMediaSource` の Feature Detection とコード分岐が必要
- SourceBuffer のバッファ管理が必要
- HLS より実装が複雑

---

### 案 C: WebRTC（go2rtc リレー）

**理由:**
1. 最低遅延（50〜300ms）
2. 帯域効率優秀 + 自動帯域適応
3. go2rtc がプロトコル変換を全自動化

**懸念:**
- 外部プロセスが 2 つ（ffmpeg + go2rtc）
- NSSM サービス管理の追加
- 認証の二重化問題（Flask 認証とリレーサーバーへのアクセス制御）
- Tailscale 環境では NAT 問題はないが、構成の複雑さが増す

---

## ハードウェアエンコード

ログに `AMD HD Audio DP out #0` があり、AMD GPU 搭載と推定。

| エンコーダ | ffmpeg オプション | CPU 使用率 | 遅延 |
|-----------|-----------------|-----------|------|
| libx264 (CPU) | `-c:v libx264 -preset ultrafast -tune zerolatency` | 40〜80% | 5〜15ms |
| h264_amf (AMD GPU) | `-c:v h264_amf -quality speed` | 2〜5% | 2〜5ms |

`h264_amf` が利用可能なら CPU 負荷を大幅に削減できる。ffmpeg 起動時にハードウェアエンコーダの有無を検出し、利用可能なら優先する設計が望ましい。

```python
# エンコーダ自動検出の擬似コード
def detect_encoder():
    for enc in ['h264_amf', 'h264_nvenc', 'h264_qsv']:
        if ffmpeg_supports(enc):
            return enc
    return 'libx264'
```

---

## 音声コーデックの改善（付随検討）

現在の音声は生 PCM 16kHz/16bit（~256 kbps）を Socket.IO で送信している。
映像と同時に音声コーデックも改善すれば更に帯域を削減できる。

| 方式 | ビットレート | 品質 | 実装の容易さ |
|------|-----------|------|------------|
| 生 PCM（現状） | ~256 kbps | 無劣化 | 最も簡単 |
| Opus（WebSocket 経由） | ~32〜64 kbps | 高品質 | 中（Python で opuslib 等） |
| Opus（WebRTC 経由） | ~32〜64 kbps | 高品質 | WebRTC 採用時は自動 |

映像の改善が優先だが、将来的に Opus エンコードも検討の価値がある。

---

## 段階的な導入ステップ（案 A: HLS の場合）

### Phase 1: ffmpeg パイプラインの構築
- ffmpeg subprocess で OpenCV フレームを H.264 HLS セグメントに変換
- ハードウェアエンコーダ（h264_amf）の自動検出
- セグメントファイルの一時ディレクトリ管理

### Phase 2: HLS 配信エンドポイント
- Flask に `/stream/stream.m3u8` と `/stream/*.ts` エンドポイント追加
- CORS / 認証ヘッダーの設定

### Phase 3: クライアント側の切り替え
- hls.js の組み込み（CDN or 静的ファイル）
- iOS Safari 用ネイティブ HLS 再生
- 設定画面でのストリーミング方式切り替え UI

### Phase 4: 自動帯域検出（将来）
- ネットワーク状態に応じて MJPEG ↔ HLS を自動切り替え
- Wi-Fi 時は低遅延 MJPEG、モバイル時は省帯域 HLS
