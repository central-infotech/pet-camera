# Pet Camera

自宅の PC に接続した Web カメラ・マイク・スピーカーを使って、外出先のスマホからペットの様子をリアルタイムで見守るシステム。

## 主な機能

- **ライブ映像** — MJPEG ストリーミングで低遅延のリアルタイム映像
- **双方向音声** — 家の音を聞く / スマホからペットに話しかける（プッシュトゥトーク）
- **スナップショット** — ワンタップで静止画を撮影・保存
- **カメラ設定** — 解像度・FPS・明るさ・コントラストをブラウザから調整
- **パスキー認証** — 初回トークン認証後、指紋/顔認証でログイン可能（WebAuthn）
- **常時稼働** — Windows サービスとして自動起動・自動復旧

## アーキテクチャ

```
スマホ (Tailscale VPN) ──HTTPS/WSS──> 自宅 PC:5555
                                        ├── Flask + Flask-SocketIO
                                        ├── OpenCV (カメラ制御)
                                        └── sounddevice (音声 I/O)
```

- **VPN**: Tailscale（WireGuard ベース）でインターネットに非公開
- **TLS**: Tailscale の HTTPS 証明書で暗号化
- **認証**: トークン + パスキー（WebAuthn）の二段構え

## 必要環境

| 項目 | 要件 |
|------|------|
| OS | Windows 10 / 11 |
| Git | [git-scm.com](https://git-scm.com/) |
| Python | 3.10 以上 |
| カメラ | USB または内蔵 Web カメラ |
| マイク・スピーカー | 内蔵または外部接続 |
| VPN | [Tailscale](https://tailscale.com/) (PC・スマホ両方) |

## セットアップ

### 1. Git・Tailscale の準備

**Git** がインストールされていない場合:

1. [git-scm.com](https://git-scm.com/) からダウンロードしてインストール
2. インストーラーの設定はすべてデフォルトのままで OK

**Tailscale** のアカウントがない場合:

1. [tailscale.com](https://tailscale.com/) でアカウントを作成（Google / Microsoft アカウントで登録可）
2. PC に Tailscale をインストールしてログイン
3. スマホにも Tailscale アプリをインストールして同じアカウントでログイン

> **家族で使う場合:** 家族それぞれが自分のアカウントで Tailscale に登録し、PC オーナーが Tailscale 管理画面からサーバー PC のノードを「Share」すれば、アカウントを共有せずにアクセスできます。

### 2. リポジトリのクローン

```batch
git clone https://github.com/central-infotech/pet-camera.git
cd pet-camera
```

### 3. 初期セットアップ

```batch
setup.bat
```

Python 仮想環境の作成、依存パッケージのインストール、ディレクトリの作成が行われます。

### 4. 環境変数の設定

管理者権限のコマンドプロンプトで:

```batch
setx /M PET_CAMERA_TOKEN "あなたの秘密のトークン"
setx /M PET_CAMERA_ENV "production"
```

### 5. TLS 証明書の取得

```batch
tailscale cert --cert-file "certs\マシン名.tailnet名.ts.net.crt" --key-file "certs\マシン名.tailnet名.ts.net.key" マシン名.tailnet名.ts.net
```

### 6. サーバーの起動

**手動起動 (テスト用):**

```batch
venv\Scripts\python.exe run.py
```

**Windows サービスとして登録 (推奨):**

```batch
install-service.bat    REM 管理者として実行
```

### 7. アクセス

**スマホ（外出先から見守り）:**

1. スマホで Tailscale に接続
2. ブラウザで `https://マシン名.tailnet名.ts.net:5555` にアクセス
3. トークンを入力してログイン

**PC ブラウザ（ペット映像の表示用）:**

- `https://マシン名.tailnet名.ts.net:5555/display` にアクセス

## ディレクトリ構成

```
pet-camera/
├── server/                  # Python バックエンド
│   ├── app.py               #   Flask アプリケーション
│   ├── camera.py            #   カメラ制御 (OpenCV)
│   ├── audio.py             #   音声 I/O (sounddevice)
│   ├── auth.py              #   認証・セッション管理
│   ├── webauthn_auth.py     #   パスキー認証 (WebAuthn)
│   ├── config.py            #   設定管理
│   └── requirements.txt     #   依存パッケージ
├── static/                  # フロントエンド静的ファイル
│   ├── css/style.css
│   └── js/
│       ├── app.js           #   UI ロジック
│       └── audio.js         #   音声制御 (Web Audio API)
├── templates/               # HTML テンプレート
│   ├── index.html           #   メインビューワー
│   └── login.html           #   認証画面
├── docs/                    # ドキュメント
│   ├── SPECIFICATION.md     #   仕様書
│   └── HOW_TO_USE.md        #   取扱説明書
├── setup.bat                # 初期セットアップ
├── install-service.bat      # サービス登録
├── renew-cert.bat           # 証明書更新
└── run.py                   # エントリーポイント
```

## 技術スタック

| コンポーネント | 技術 |
|--------------|------|
| カメラ制御 | OpenCV (cv2) |
| 音声 I/O | sounddevice + NumPy |
| Web サーバー | Flask |
| WebSocket | Flask-SocketIO |
| 映像配信 | MJPEG over HTTPS |
| 音声配信 | PCM 16kHz/16bit over WSS |
| パスキー認証 | WebAuthn (py-webauthn) |
| VPN | Tailscale (WireGuard) |
| サービス管理 | NSSM |

## ドキュメント

- [取扱説明書](docs/HOW_TO_USE.md) — セットアップから操作方法・トラブルシューティングまで
- [仕様書](docs/SPECIFICATION.md) — API 設計・セキュリティ設計・技術仕様の詳細

## ライセンス

[MIT License](LICENSE)
