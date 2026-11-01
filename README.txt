イベントリンク機能・最新版コード基準の差分パッチ

基準: 2026-11-01にアップロードされた monst-schedule-maker-main(2).zip (commit d84db6da...)
更新ファイル: app.py / event_image_generator.py のみ

画像生成ロジック、カレンダーのレイアウト、ダウンロードPNGは変更なし。
既存の source_url があるイベント名にクリック領域を付加します。
source_url に #:~:text= が含まれる場合、対応ブラウザで該当見出しに移動します。

重要: このZIPはアップロード時点の復旧済み main を基準にしています。
GitHub main がその後更新されていれば、直接上書きせず差分を確認してください。
反映前に main からバックアップブランチを作成してください。
Streamlit Community Cloudでの実機動作は未確認です。
