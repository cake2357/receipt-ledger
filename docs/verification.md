# 検証記録

## 2026-10-04 OpenAI OCRの実接続診断

- 設定済みモデル `gpt-5.6-luna` のモデル取得APIはHTTP 200。
- 生成したテスト画像を既存の `extract()` 経由でResponses APIへ送信し、HTTP 429を再現。修正後の確認で `code=credit_balance_exhausted` を識別。OCR停止の原因はAPIのプリペイド残高切れ。残高の追加が必要で、有料OCRの成功は未確認。
- `credit_balance_exhausted` と `organization_spend_limit_exceeded` を安全な診断コードに追加し、残高・各上限に応じた具体的な案内を表示。任意の上流本文・APIキーは表示しない。課金エラーの再試行は復旧手段にしない。
- 設定画面の「利用可能」を「設定済み（接続・API残高は未確認）」へ変更。
- `.venv/bin/python -m pytest -q`：117 passed in 25.00s（localhost待受を許可した環境）。`node --check static/app.js` と `python -m compileall -q providers.py` も成功。
- 本番DBとレシート画像は読取確認のみ。実レシートの外部送信、残高追加、上限変更、モデル変更は行っていない。

## 無料Apple Vision OCRの追加検証

- `uv run --frozen pytest -q`：**77 passed in 9.39s**。`node --check static/app.js`、Python compileall、`zsh -n run.command` は終了コード0。
- RED→GREENを実測：ローカルOCRモジュール欠落→実装、保守的パーサ欠落→実装、ローカルOCR endpointの404→200、無料ボタン不存在→Chromium成功、同一行の金額未解析→解析、複数税区分で最後の税額を誤採用→null保持、OCR後の一覧カード未更新→即時再読込。
- macOS 26.6.2 / arm64、Swift 6.3.3で同梱Swiftを実コンパイル。Apple Visionの日本語対応を確認し、提供された2枚とも実認識＋API下書き保存＋GET読戻し200。推測や外部モデルによる代替結果ではない。
- 実画像1：22明細・25点、日付/店名/割引前/割引/小計/税を抽出。合計は原文が `¥5.449` のため空欄（カンマに勝手に直さない）。低信頼の明細価格1行もnull。
- 実画像2：17明細・20点、日付/店名/印字総額を抽出。薄い価格を含む5行の明細額をnull保持。単価・総額から埋めない。両画像とも税込明細額と税率は未確定、分類はルールのない全行未分類。精度保証ではない。
- 私的結果：`artifacts/private-local-ocr-verification.json`、原文 `artifacts/private-local-ocr-raw.json`（600、Git対象外）。検証スクリプト `artifacts/verify_private_local_ocr.py` は一時DBで実画像をアップロードし、外部adapterを禁止、同意false・キー空でローカルOCRを実行。確定拒否422、月次0、本番DBの前後ハッシュ一致、一時DB削除を確認。写真は成果物へコピーしていない。
- `tests/test_local_ocr.py`：パス逸脱/symlink拒否、shell未使用と60秒上限、120秒コンパイル失敗の安全なエラー、未対応Mac以外の案内、行傾き、低信頼価格、原文保存・完全一致分類・draft-only・Origin保護・確定済み/画像なし拒否。
- `tests/test_local_ocr_browser.py`：生成した日本語画像を実uvicorn/Chromiumからアップロード→実Apple Vision→無料OCR原文→編集保存→再読込。キー/モデルを明示空文字、同意false、外部URLリクエスト0、JSエラー0、有料ボタン無効。`artifacts/local-ocr-browser.png` と `artifacts/local-ocr-review.png` を目視し、無料/有料の区別・先頭の無料ボタン・原文表示を確認。390px幅も横overflowなし（`artifacts/local-ocr-mobile.png`）。
- 検証中、既存8888サーバーは同一PIDで稼働を維持し、`.env`/本番画像/取引を書き換えていない。Pythonコードの更新をその既存プロセスへ反映するには利用者/親担当による通常の再起動が必要。起動は従来の `./run.command`、ポート設定は保持する。

## 初期実装時の実行結果

プロジェクト: `/Users/yoshiki2357/receipt-ledger`

```text
$ .venv/bin/pytest -q
.................................                                        [100%]
33 passed in 5.23s

$ node --check static/app.js
(exit 0)

$ zsh -n run.command
(exit 0)

$ .venv/bin/python -m compileall -q ledger.py media.py providers.py server.py oauth_setup.py
(exit 0)
```

初期のStarlette TestClient deprecation warningはdev依存 `httpx2` の追加により解消。最終pytestは警告なし。

## 実際に確認したこと

- `uv sync` によりPython仮想環境を作成、依存取得成功。`uv.lock` 固定。
- RED/GREEN: 初回missing application、未実装カテゴリ/集計、未実装upload/provider/frontend/OAuth/server、INTEGER台帳欠落、非canonical日付の誤確定、OCR履歴欠落、chunked容量上限欠落、負数グラフscale欠落を失敗として観察した後に実装・再実行。
- 通常テストは生成fixture、追加の私的検証は提供された実画像2枚を一時DBへアップロード。手入力・未完成確定拒否・合計不一致拒否・確定・再編集をDBまで検証。実レシートは本番へ保存・確定していない。
- 整数円のSQLite `typeof(amount)='integer'`、float/bool/string拒否、下書きは集計除外、再編集で仕訳除外。
- 分類名と説明の編集/追加、2月28日分のゼロ埋め、カテゴリ別/日別/月次合計。
- PNG/JPEG経路とHEIC変換、バイト列重複、Drive ID重複、ZIPに入ったDBと画像の復元。
- CSV数式先頭文字の無害化。Originなし/異なるOrigin/null/不正Host拒否。非画像・容量超過・chunked容量超過拒否。
- 外部OCRリクエストはMockTransportで公式JSON schema/画像入力/store:false/分類説明を検証。DriveもMockTransportでページングと画像downloadを検証。
- 有料AI OCRは同意・キー・モデルがないと409。税別結果では明細額nullと警告、原文保持。不完全応答も保存。完全一致ルールがAI分類を上書き。
- Desktop OAuth設定はfake Flowで自身のファイルパス/read-only scope/PKCE/127.0.0.1動的ポート/秘密ファイル600権限を検証。
- Playwright Chromium＋実uvicornで入力→不一致→保存→ページ再読み込みで永続化→確定→月次120円→分類編集→再編集→月次0円。ブラウザJSエラーなし。
- 390×844のモバイルviewportでドキュメントの横方向overflowなし。グラフ/日次テーブルは内部横スクロール。1280pxと390pxスクリーンショットを保存・目視確認。
- 実行可能 `run.command` を `/tmp` から起動。`LEDGER_DATA_DIR` を一時領域にしてHTTP200、receipt_count=0、ocr_consent=falseを確認後、正常停止。Uvicornログ: `http://127.0.0.1:58285`（この検証時の動的ポート）。
- 初回検証時に本番 `data/` 不在を確認。今回の追加検証も一時データ領域だけを使用し、本番取引や秘密ファイルを作成していない。
- 静的走査で危険なeval/pickle/shell=True/os.system/SQL f-stringなし。JSはDOM textContent、innerHTML不使用。

## 実レシート配賦・追加検証

- RED→GREEN: 実画像アップロードの415を2件再現。PillowがiPhone HDR JPEGをMPOとして認識し、許可形式判定に落ちていた。MPOの主画像だけを既存のサイズ上限・EXIF補正・JPEG変換へ通して200を確認。
- 単一税率ガード欠落（混在/不明でも200）、小計保存欠落、配賦案APIの404、小計不一致の誤通過、UI税率選択欠落、provider schemaの小計/税率欠落を失敗として観察してから実装。
- `tests/test_allocation.py`: 最大剰余法の同順位、金額/割引/税合計保存、元税抜額、数量、承認前の確定拒否、配賦元変更検出、不明値、負数、割引超過、混在/不明税率、案の非書込を検証。
- Chromium実サーバーで税抜100・割引3・税7→案104を表示しても元の明細額120を保持→明示適用104→承認/確認→月次104を検証。JSエラーなし。
- `PYTHONPATH=. .venv/bin/python artifacts/validate_private_samples.py`：実画像2件アップロード200。1枚目は22行/25点、税抜5185−割引139＋税403＝5449へ配賦（下書きのみ）。2枚目は17行/20点、薄い価格2箇所をnullで保存、案/配賦422を確認。実レシートの商品名/分類はこの検証では未転記、確定しない。
- private reportは `artifacts/private-sample-verification.json`（600、gitignore対象、写真なし）。一時DB削除、両月の集計0、外部OCR無効を確認。写真を公開成果物にコピーしていない。
- 実画像テストは原本がある環境のみ実行し、ない環境ではskip。外部OCRの自動読み取り精度を証明する試験ではない。

## 証拠ファイル

- `tests/test_app.py`
- `tests/test_upload.py`
- `tests/test_providers.py`
- `tests/test_frontend.py`
- `tests/test_integrity.py`
- `tests/test_oauth.py`
- `tests/test_browser.py`
- `tests/test_hardening.py`
- `artifacts/desktop.png`、`artifacts/mobile.png`（テスト画面、.gitignore対象）

## 未検証/制約

Google OAuth実ログイン、実Driveフォルダ取り込み、OpenAI有料API送信は行っていない。外部の成功や実レシート精度は保証しない。実iPhone Safari・多量データ負荷・インターネット公開は未検証。テストは課金/外部書き込みを行わない。Hermes資格情報・プロファイルを変更していない。Git repository作成/commitは行っていない。独立レビューは親エージェントが別途実施する想定。
