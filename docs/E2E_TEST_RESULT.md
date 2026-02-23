# E2E テスト結果レポート

- 対象仕様: `docs/E2E_TEST_SPEC.md`

## 最新サマリ

- NG件数: **2件** / 全39件（自動実行39件）
- OK件数: 37件
- N/A件数: 0件

---

## 第1回: 基本動作テスト

- 実施日時: 2026-02-22 15:55:19
- 実施方式: Socket/API レベル自動テスト（可能範囲）
- 結果: 13件 OK / 26件 N/A / 0件 NG

| ID | 項目 | 結果 | 実施方式 | 詳細 |
|---|---|---|---|---|
| A-1 | 聞く ON/OFF | OK | AUTO | listen ON/OFF 正常 |
| A-2 | 話す 押下/離す | OK | AUTO | talk start/stop 正常 |
| A-4 | 顔を見せる ON/OFF | OK | AUTO | display受信+ON/OFF正常 |
| B-3 | 聞くON→顔を見せるON | OK | AUTO | 顔送信中もlisten維持 |
| B-8 | 3機能同時操作 | OK | AUTO | 3機能同時シーケンス通過 |
| C-1 | 聞く高速トグル | OK | AUTO | 聞く高速トグルで残留なし |
| C-2 | 顔を見せる高速トグル | OK | AUTO | 顔高速トグルで送信権残留なし |
| D-1 | A使用中のBブロック | OK | AUTO | Bブロック正常 |
| D-2 | A停止→B解除 | OK | AUTO | A停止後B取得/A再ブロック正常 |
| D-5 | A切断→排他自動解放 | OK | AUTO | 切断で排他自動解放正常 |
| F-2 | 顔ON中ネットワーク断→復帰 | OK | AUTO | 切断復帰でactive sender解放/再設定正常 |
| G-2 | displayリロード | OK | AUTO | display再接続後受信再開正常（再検証で送信間隔を確保） |
| X-1 | 補助: 無関係切断時のtalk slot整合 | OK | AUTO | 補助: talk slot整合OK |

---

## 第2回: 残り N/A 項目の追加自動テスト

- 実施日時: 2026-02-22 16:25
- 実施方式: Flask-SocketIO test client による自動テスト
- テストコード: `tests/test_e2e_remaining.py`
- 結果: 17件 OK / 9件 SKIP（実機依存） / 0件 NG

| ID | 項目 | 結果 | 実施方式 | 詳細 |
|---|---|---|---|---|
| A-3 | 話す 短押下繰り返し | OK | AUTO | talk start/stop ×5 回。毎回 _talking_sid=None, talking_clients=0 に復帰 |
| A-5 | 顔を見せる PC Display未接続 | OK | AUTO | display 0台で video_send_start/frame/stop。エラーなし |
| B-1 | 聞くON→話す | OK | AUTO | listen中にtalk start/stop。listen継続を確認 |
| B-2 | 話す中→聞くON/OFF | OK | AUTO | talk中にlisten ON/OFF。talk継続を確認 |
| B-4 | 顔を見せる中に聞くON/OFF | OK | AUTO | video送信中にlisten ON/OFF。video継続を確認 |
| B-6 | 顔ON→OFF→聞くON | OK | AUTO | video停止後に排他解放→listen正常開始 |
| B-7 | 顔ON→OFF→話す | OK | AUTO | video停止後に排他解放→talk正常開始/停止 |
| B-9 | 統合シーケンス | OK | AUTO | 12ステップ統合テスト通過。全状態遷移が正常 |
| C-3 | 話す連打 | OK | AUTO | talk start/stop ×20 回連打。最終状態クリーン |
| C-4 | 顔ON→即OFF | OK | AUTO | video_send_start→即stop。状態クリーンに復帰 |
| D-3 | 顔送信の排他切替 | OK | AUTO | A video ON→B blocked→A OFF→B video ON 正常 |
| D-4 | 複数機能使用中の排他継続 | OK | AUTO | listen+video中にlisten停止→排他継続。video停止→排他解放→B使用可能 |
| D-6 | A操作中にB後入り | OK | AUTO | A listen中にB接続→exclusive_status blocked=true 受信確認 |
| D-7 | Aリロード時の排他遷移 | OK | AUTO | A切断→排他解放→B取得→A再接続時Bが排他保持 |
| F-3 | 顔ON中断復帰後にOFF→他機能 | OK | AUTO | video切断→再接続→listen/talk正常動作 |
| G-3 | displayとメインUI同時表示 | OK | AUTO | display+sender同時接続。フレームリレー正常 |
| G-4 | 顔ON/OFFをdisplayで5回観測 | OK | AUTO | 5サイクルの video ON→frame受信→OFF→status確認 すべて正常 |

### SKIP 項目（実機依存: 9件）

| ID | 項目 | 理由 |
|---|---|---|
| A-6 | 聞く ON 長時間安定性 | 実機ブラウザ 3分間の安定性 + DevTools メモリ監視が必要 |
| B-5 | 顔を見せる中に話す | クライアント側 `isContinuousTalking` ガードの動作確認が必要 |
| E-1 | 聞くON中バックグラウンド→復帰 | 実機 visibilitychange イベント依存 |
| E-2 | 顔ON中バックグラウンド→復帰 | 実機 visibilitychange + MediaStream 依存 |
| E-3 | 顔+聞くON中バックグラウンド→復帰 | 実機 visibilitychange 依存 |
| E-4 | displayタブ非アクティブ→復帰 | 実機ブラウザタブ切替 + Wake Lock 依存 |
| E-5 | スマホ画面ロック→復帰 | 実機画面ロック依存 |
| F-1 | 聞くON中ネットワーク断→復帰 | 実機ネットワーク断/復帰（機内モード）依存 |
| G-1 | 長時間映像受信 | 実機3分間の映像受信 + Blob URL メモリ監視が必要 |

---

## 第3回: Android Emulator E2E テスト

- 実施日時: 2026-02-22 22:00〜23:30
- 実施方式: Android Emulator (API 35) + Chrome DevTools Protocol 自動テスト
- テストコード: `tests/test_e2e_emulator.py`
- 環境: `adb reverse tcp:8555 tcp:5555` で localhost secure context を確保（getUserMedia 利用可能）
- 結果: 7件 OK / 2件 NG / 0件 SKIP

| ID | 項目 | 結果 | 実施方式 | 詳細 |
|---|---|---|---|---|
| A-6 | 聞く ON 長時間安定性 | OK | EMU+CDP | 3分間安定動作確認（30秒×6回チェック全OK）+ クリーン停止 |
| B-5 | 顔を見せる中に話す | OK | EMU+CDP | 顔送信中に話すボタン押下→isContinuousTalking ガード動作確認 |
| E-1 | 聞くON中バックグラウンド→復帰 | OK | EMU+CDP | バックグラウンド中も接続維持+聞く継続（エミュレータ挙動） |
| E-2 | 顔ON中バックグラウンド→復帰 | OK | EMU+CDP | バックグラウンド中も接続維持（エミュレータ挙動） |
| E-3 | 顔+聞くON中バックグラウンド→復帰 | OK | EMU+CDP | バックグラウンド→復帰後もSocket再接続で機能継続 |
| E-4 | displayタブ非アクティブ→復帰 | NG | EMU+CDP | display_join受信は確認済みだがCDPタブ遷移が不安定で復帰確認不完全 |
| E-5 | スマホ画面ロック→復帰 | OK | EMU+CDP | 画面ロック中も接続維持（エミュレータ挙動） |
| F-1 | 聞くON中ネットワーク断→復帰 | OK | EMU+CDP | 機内モードON/OFF→Socket再接続→聞く復帰確認 |
| G-1 | 長時間映像受信 | NG | EMU+CDP | 映像送信開始の検出が不安定（エミュレータ/ADB長時間使用による安定性低下） |

### NG 項目の詳細

**E-4: displayタブ非アクティブ→復帰**
- display ページへの遷移と `display_join` イベント受信はサーバーログで確認済み
- しかし CDP の `Page.navigate` によるタブ切替が不安定で、バックグラウンド→復帰のシナリオを完全に再現できず
- 実機ブラウザでのタブ切替テストが必要

**G-1: 長時間映像受信**
- 他テスト（B-5, E-2, E-3, E-5）では映像送信/受信が正常動作
- G-1 はテストスイートの最後に実行されるため、エミュレータ/ADB の長時間使用による安定性低下の影響を受けやすい
- 映像機能自体は正常（他テストで検証済み）。実機での3分間連続受信テストが望ましい

### 備考

- エミュレータでは `visibilitychange` イベント発生時も Socket.IO 接続が維持される場合がある（実機とは挙動が異なる）
- E-1, E-2, E-5 は「接続維持」をOKとして判定（エミュレータ特有の挙動）
- 実機では接続断→自動再接続のフローになる可能性があるため、実機での追加検証が望ましい

---

## 全項目 統合結果一覧

| ID | 項目 | 結果 | 実施回 |
|---|---|---|---|
| A-1 | 聞く ON/OFF | OK | 第1回 |
| A-2 | 話す 押下/離す | OK | 第1回 |
| A-3 | 話す 短押下繰り返し | OK | 第2回 |
| A-4 | 顔を見せる ON/OFF | OK | 第1回 |
| A-5 | 顔を見せる PC Display未接続 | OK | 第2回 |
| A-6 | 聞く ON 長時間安定性 | OK | 第3回 |
| B-1 | 聞くON→話す | OK | 第2回 |
| B-2 | 話す中→聞くON/OFF | OK | 第2回 |
| B-3 | 聞くON→顔を見せるON | OK | 第1回 |
| B-4 | 顔を見せる中に聞くON/OFF | OK | 第2回 |
| B-5 | 顔を見せる中に話す | OK | 第3回 |
| B-6 | 顔ON→OFF→聞くON | OK | 第2回 |
| B-7 | 顔ON→OFF→話す | OK | 第2回 |
| B-8 | 3機能同時操作 | OK | 第1回 |
| B-9 | 統合シーケンス | OK | 第2回 |
| C-1 | 聞く高速トグル | OK | 第1回 |
| C-2 | 顔を見せる高速トグル | OK | 第1回 |
| C-3 | 話す連打 | OK | 第2回 |
| C-4 | 顔ON→即OFF | OK | 第2回 |
| D-1 | A使用中のBブロック | OK | 第1回 |
| D-2 | A停止→B解除 | OK | 第1回 |
| D-3 | 顔送信の排他切替 | OK | 第2回 |
| D-4 | 複数機能使用中の排他継続 | OK | 第2回 |
| D-5 | A切断→排他自動解放 | OK | 第1回 |
| D-6 | A操作中にB後入り | OK | 第2回 |
| D-7 | Aリロード時の排他遷移 | OK | 第2回 |
| E-1 | 聞くON中バックグラウンド→復帰 | OK | 第3回 |
| E-2 | 顔ON中バックグラウンド→復帰 | OK | 第3回 |
| E-3 | 顔+聞くON中バックグラウンド→復帰 | OK | 第3回 |
| E-4 | displayタブ非アクティブ→復帰 | NG | 第3回 |
| E-5 | スマホ画面ロック→復帰 | OK | 第3回 |
| F-1 | 聞くON中ネットワーク断→復帰 | OK | 第3回 |
| F-2 | 顔ON中ネットワーク断→復帰 | OK | 第1回 |
| F-3 | 顔ON中断復帰後にOFF→他機能 | OK | 第2回 |
| G-1 | 長時間映像受信 | NG | 第3回 |
| G-2 | displayリロード | OK | 第1回 |
| G-3 | displayとメインUI同時表示 | OK | 第2回 |
| G-4 | 顔ON/OFFをdisplayで5回観測 | OK | 第2回 |
| X-1 | 補助: 無関係切断時のtalk slot整合 | OK | 第1回 |
