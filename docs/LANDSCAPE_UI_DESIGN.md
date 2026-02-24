# 横画面のUI拡張 — 設計書

## 1. 概要

スマートフォンを横（ランドスケープ）にした際、縦方向のスペースが限られるため映像エリアが極端に小さくなる問題を解決する。横画面専用のレイアウトに切り替え、映像表示面積を最大化しつつ操作性を維持する。

### 1.1 現状の問題

```
横画面（現在の縦レイアウトをそのまま適用した場合）:
┌──────────────────────────────────────────────────────────────┐
│ 🐾 Pet Camera  [↻ 画面更新]          ● LIVE 00:03:42        │ ← ヘッダー（高さ ~40px）
├──────────────────────────────────────────────────────────────┤
│      ┌────────────────────┐                                  │
│      │   ライブ映像        │  ← 映像エリア（残り ~150px！）   │
│      └────────────────────┘                                  │
├──────────────────────────────────────────────────────────────┤
│ [▲]                                                          │ ← トグル
│ [🔊 聞く] [🎤 話す] [📹 顔を見せる]  音量 [━━━━]             │ ← コントロール行1（高さ ~35px）
│ [📷 スマホに画像保存] [📁 PCに画像保存] [⚙ 設定]             │ ← コントロール行2（高さ ~35px）
├──────────────────────────────────────────────────────────────┤
│ 15 fps  |  1280x720 (WebRTC)  |  マイク: OFF / リスナー: 0   │ ← フッター（高さ ~25px）
└──────────────────────────────────────────────────────────────┘
```

横画面の縦ピクセルは約 360px（一般的なスマホ）。ヘッダー(40px) + コントロール2段(70px) + フッター(25px) + トグル(15px) = **150px** がUI要素に取られ、映像エリアはわずか **~210px** しか残らない。

### 1.2 改善後のコンセプト

横幅を活用し、タイトル情報を左に、操作ボタンを右に配置。映像エリアを縦幅いっぱいに拡大する。

---

## 2. 横画面レイアウト設計

### 2.1 操作パネルを開いた状態

```
┌─────────┬──────────────────────────────────┬──┬───────────┐
│ 🐾      │                                  │  │ [🔊 聞く] │
│ Pet     │                                  │  │ [🎤 話す] │
│ Camera  │                                  │◀│ [📹 顔]   │
│         │        ライブ映像                 │  │ 音量 [━━] │
│ ● LIVE  │        (最大表示)                 │  │ [📷 スマホ]│
│ 00:03:42│                                  │  │ [📁 PC]   │
│         │                                  │  │ [⚙ 設定] │
│ [↻]     │                                  │  │───────────│
│         │                                  │  │ 15fps     │
│         │                                  │  │ 1280x720  │
└─────────┴──────────────────────────────────┴──┴───────────┘
 ← 左サイド  ← 映像エリア（flex:1）       →  右トグル+パネル
   (~70px)                                (~20px)(~120px)
   常時表示                                トグルで開閉
```

### 2.2 操作パネルを閉じた状態（映像最大化）

```
┌─────────┬─────────────────────────────────────────────┬──┐
│ 🐾      │                                             │  │
│ Pet     │                                             │  │
│ Camera  │                                             │▶│
│         │        ライブ映像                            │  │
│ ● LIVE  │        (最大表示 — 横幅をフル活用)            │  │
│ 00:03:42│                                             │  │
│         │                                             │  │
│ [↻]     │                                             │  │
│         │                                             │  │
│         │                                             │  │
└─────────┴─────────────────────────────────────────────┴──┘
 ← 左サイド  ← 映像エリア（最大）                     → トグル
   (~70px)                                          (~20px)
```

### 2.3 左サイドバー詳細レイアウト

```
┌─────────┐
│ 🐾      │  ← ロゴ（1行に短縮 or アイコン化）
│ PetCam  │
│         │
│ ● LIVE  │  ← ライブバッジ
│ 00:03:42│  ← 経過時間
│         │
│  [↻]    │  ← 画面更新ボタン（アイコンのみ）
│         │
└─────────┘
  幅: ~70px
  背景: var(--surface)
  右ボーダー: 1px solid var(--border)
```

### 2.4 右パネル詳細レイアウト（展開時）

```
┌───────────┐
│ [🔊 聞く] │  ← 各ボタンは横幅いっぱい
│ [🎤 話す] │    縦に1つずつ積む
│ [📹 顔]   │
│           │
│ 音量      │  ← 音量スライダー（横向き、幅100%）
│ [━━━━━━] │
│           │
│ [📷 スマホ]│  ← 保存・設定ボタン
│ [📁 PC]   │
│ [⚙ 設定] │
│───────────│
│ 15fps     │  ← ステータス情報（footerの内容をここに表示）
│ 1280x720  │
│ マイク:OFF │
└───────────┘
  幅: ~120px
  背景: var(--surface)
  左ボーダー: 1px solid var(--border)
```

---

## 3. 実装ロジック

### 3.1 横画面検出

CSS media query で横画面かつスマホサイズを検出する。

```css
@media (orientation: landscape) and (max-height: 500px) {
  /* 横画面レイアウト */
}
```

**条件の根拠:**
- `orientation: landscape`: 横画面を検出
- `max-height: 500px`: スマホの横画面のみを対象とし、タブレットやデスクトップは除外
  - 一般的なスマホの横画面高さ: 320px〜450px
  - タブレットの横画面高さ: 700px以上

### 3.2 DOM構造（変更なし）

既存のHTML構造を変更せず、CSSのみでレイアウトを切り替える。

```html
<!-- 現在のDOM構造（変更不要） -->
<body>
  <header id="header">
    <div class="header-left"><span class="logo">Pet Camera</span></div>
    <div class="header-center"><button id="btn-reload">...</button></div>
    <div class="header-right">
      <span id="live-badge" class="badge">LIVE</span>
      <span id="uptime">00:00:00</span>
    </div>
  </header>

  <main>
    <div class="video-container">...</div>
    <div id="exclusive-banner">...</div>
    <button id="controls-toggle">...</button>
    <div id="controls-panel">
      <div class="controls">Row 1: 聞く, 話す, 顔を見せる, 音量</div>
      <div class="controls">Row 2: スマホ保存, PC保存, 設定</div>
    </div>
  </main>

  <footer id="status-bar">...</footer>
</body>
```

### 3.3 CSSレイアウト切り替え（核心部分）

```css
@media (orientation: landscape) and (max-height: 500px) {

  /* --- 全体: 縦配列 → 横配列 --- */
  body {
    flex-direction: row;        /* 縦→横に変更 */
    height: var(--app-height, 100dvh);
  }

  /* --- main を「透過」して子要素をbodyのflex itemに --- */
  main {
    display: contents;
  }

  /* --- 左サイドバー: headerを縦配置に --- */
  header {
    flex-direction: column;     /* 横並び→縦並びに変更 */
    justify-content: center;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem;
    width: 70px;
    border-bottom: none;
    border-right: 1px solid var(--border);
    flex-shrink: 0;
  }

  /* header内の各ブロックを縦配置に合わせる */
  .header-left, .header-center, .header-right {
    flex-direction: column;
    align-items: center;
    text-align: center;
  }

  .header-right { gap: 0.25rem; }

  /* 「画面更新」テキストを隠してアイコンのみにする */
  .btn-reload {
    font-size: 0;                /* テキストを隠す */
    padding: 0.4rem;
  }
  .btn-reload svg {
    font-size: initial;          /* SVGアイコンは維持 */
  }

  /* --- 映像エリア: 残りスペースを全て使う --- */
  .video-container {
    flex: 1;
    min-width: 0;
    order: 0;                    /* 左サイドの隣 */
  }

  /* --- 排他バナー: 映像の上にオーバーレイ --- */
  #exclusive-banner:not([hidden]) {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    z-index: 5;
  }

  /* --- トグルボタン: 横方向（右端）に配置 --- */
  #controls-toggle {
    writing-mode: vertical-rl;   /* 縦書きにして高さ方向に伸ばす */
    border-top: none;
    border-left: 1px solid var(--border);
    padding: 0 0.15rem;
    width: 20px;
    flex-shrink: 0;
    order: 1;
  }

  /* --- 右パネル: 縦に積むコントロール --- */
  #controls-panel {
    flex-direction: column;
    width: 120px;
    border-top: none;
    border-left: 1px solid var(--border);
    overflow-y: auto;
    flex-shrink: 0;
    order: 2;
  }

  #controls-panel .controls {
    flex-direction: column;      /* 横並び→縦並びに変更 */
    border-top: none;
    padding: 0.3rem;
    overflow-x: visible;         /* 横スクロール不要 */
  }

  #controls-panel .btn {
    width: 100%;
    justify-content: center;
  }

  .volume-control {
    flex-direction: column;
    margin-left: 0;
    width: 100%;
  }

  .volume-control input[type="range"] {
    width: 100%;
  }

  /* --- フッター: 横画面では非表示（右パネルにステータス表示） --- */
  footer {
    display: none;
  }
}
```

### 3.4 JavaScript の変更

orientation media query をリッスンし、トグルアイコンの方向を切り替える。

```javascript
// ---- Landscape toggle icon direction ----
const landscapeMQ = window.matchMedia('(orientation: landscape) and (max-height: 500px)');

function updateToggleIcon() {
  const isLandscape = landscapeMQ.matches;
  const isHidden = controlsPanel.classList.contains('hidden');

  if (isLandscape) {
    controlsToggleIcon.textContent = isHidden ? '\u25B6' : '\u25C0'; // ▶ / ◀
  } else {
    controlsToggleIcon.textContent = isHidden ? '\u25BC' : '\u25B2'; // ▼ / ▲
  }
}

// 既存のトグル処理を修正
controlsToggle.addEventListener('click', () => {
  controlsPanel.classList.toggle('hidden');
  updateToggleIcon();
});

// orientation変化時にアイコンを更新
landscapeMQ.addEventListener('change', updateToggleIcon);
```

### 3.5 フッター情報の右パネル統合

横画面ではフッターを非表示にする代わりに、右パネル内にステータス情報を複製表示する。

**方法A: CSSのみ（フッターを右パネル内に移動）**

フッターに `order` を付けて右パネルの一部として見せる方法。ただし、フッターは `main` の外にあるため、`display: contents` 適用後もbody直下のflex itemとして扱われる。CSSだけでは右パネル「内部」に入れることが難しい。

**方法B: JS でステータス表示先を切り替え**

横画面時に右パネル下部にステータス領域を用意し、pollStatus の更新先を切り替える。

```html
<!-- controls-panel の末尾に追加 -->
<div id="landscape-status" class="landscape-status" hidden>
  <span id="ls-fps">-- fps</span>
  <span id="ls-res">--</span>
  <span id="ls-audio">音声: --</span>
</div>
```

```javascript
// pollStatus 関数内に追加
const lsFps = document.getElementById('ls-fps');
const lsRes = document.getElementById('ls-res');
const lsAudio = document.getElementById('ls-audio');

// ステータス更新時に両方に書き込む
if (lsFps) {
  lsFps.textContent = statusFps.textContent;
  lsRes.textContent = statusRes.textContent;
  lsAudio.textContent = statusAudio.textContent;
}
```

```css
/* 横画面時のみ表示 */
.landscape-status { display: none; }

@media (orientation: landscape) and (max-height: 500px) {
  .landscape-status {
    display: flex;
    flex-direction: column;
    padding: 0.3rem;
    font-size: 0.7rem;
    color: var(--text-muted);
    border-top: 1px solid var(--border);
    gap: 0.15rem;
  }
}
```

**推奨: 方法B** — HTMLに小さな要素を追加し、CSS + JS で横画面時のみ表示する。

---

## 4. 各コンポーネントの配置と動作まとめ

| コンポーネント | 縦画面（現在） | 横画面 |
|---|---|---|
| **ヘッダー** | 画面上部に横並び（ロゴ・更新・LIVE） | 左サイドバーに縦並び（~70px幅、常時表示） |
| **映像エリア** | flex:1 で残りスペースを使う | flex:1 で中央の残りスペースを使う |
| **トグルボタン** | 映像下部に ▲/▼ | 映像右端に ▶/◀（縦書き、20px幅） |
| **操作パネル** | 2段の横並びボタン | 右サイドバーに縦並びボタン（~120px幅） |
| **音量スライダー** | Row1 の右端に横配置 | 右パネル内でフル幅横配置 |
| **フッター** | 画面最下部に横並び | 非表示（右パネル下部にステータス複製） |
| **排他バナー** | 映像下、トグル上 | 映像上にオーバーレイ表示 |
| **PiP（顔を見せる）** | 映像エリア左上 | 映像エリア左上（変更なし） |
| **設定パネル** | 中央固定オーバーレイ | 中央固定オーバーレイ（変更なし） |

---

## 5. トグルボタンの動作

### 5.1 縦画面（既存動作 — 変更なし）

| 状態 | アイコン | タップ後 |
|---|---|---|
| パネル表示中 | ▲ | パネルを隠す |
| パネル非表示 | ▼ | パネルを表示 |

### 5.2 横画面（新規）

| 状態 | アイコン | タップ後 |
|---|---|---|
| パネル表示中 | ◀ | パネルを隠す（映像エリア拡大） |
| パネル非表示 | ▶ | パネルを表示 |

トグルボタン自体は常に表示される（パネルの開閉に関わらず）。横画面では `writing-mode: vertical-rl` で縦方向に伸ばし、画面の高さいっぱいをタップ領域とする。

---

## 6. 技術的な注意点

### 6.1 `display: contents` の利用

`<main>` に `display: contents` を適用すると、`<main>` 自体はレイアウトツリーから消え、子要素（`.video-container`, `#controls-toggle`, `#controls-panel`）が `<body>` の直接のflex/gridアイテムとして扱われる。

**ブラウザサポート**: Chrome 65+、Firefox 62+、Safari 11.1+（Android PWA では問題なし）

### 6.2 `order` プロパティによる並べ替え

DOM の順序を変えずに、CSS の `order` で表示順を制御する。

```
body (flex-direction: row)
  header          → order: 0 (デフォルト) → 左端
  .video-container → order: 0 (デフォルト) → ヘッダーの隣
  #exclusive-banner → position: absolute → 映像上にオーバーレイ
  #controls-toggle  → order: 1 → 映像の右
  #controls-panel   → order: 2 → トグルの右
  #settings-panel   → position: fixed → 変更なし
  footer           → display: none → 非表示
```

### 6.3 横画面対象端末の検出精度

```css
@media (orientation: landscape) and (max-height: 500px)
```

| 端末カテゴリ | 横画面時の高さ | マッチ |
|---|---|---|
| 一般的なスマホ（16:9） | 320px〜400px | YES |
| 縦長スマホ（20:9） | 360px〜450px | YES |
| 小型タブレット（8インチ） | 600px〜800px | NO |
| iPad / 大型タブレット | 700px〜1000px | NO |
| デスクトップ | 700px以上 | NO |

### 6.4 Service Worker キャッシュ

CSS/JS を変更するため、Service Worker のキャッシュバージョンを v11 → v12 にインクリメントする必要がある。

### 6.5 既存の縦画面レイアウトへの影響

全ての変更は `@media (orientation: landscape) and (max-height: 500px)` 内に閉じるため、縦画面のレイアウトには一切影響しない。

---

## 7. 実装ファイル一覧

| ファイル | 変更内容 |
|---|---|
| `static/css/style.css` | `@media` ブロック追加（横画面レイアウト全体） |
| `static/js/app.js` | トグルアイコンの方向切り替え（▲▼ ⇔ ◀▶） |
| `templates/index.html` | `#landscape-status` 要素を `#controls-panel` 末尾に追加 |
| `static/sw.js` | キャッシュバージョン v11 → v12 |
| `docs/SPECIFICATION.md` | セクション 5.7 にランドスケープUI の記述を追加 |
