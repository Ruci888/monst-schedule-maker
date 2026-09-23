モンストスケジュールメーカー 公開β版アップデート
Version: v1.1.0-beta.9.21

主な変更
- イベント画像タイトル直下に7カテゴリ凡例を追加
- カレンダー左列をカテゴリ文字から縦カラーバーへ変更
- イベント名領域を拡大し、文字サイズを拡大
- 開始/終了時刻はバー左右・白文字・黒縁なしを維持
- 書庫卵2倍CPの日別属性カラーを維持
- デザイン選択を廃止し、見やすいブルーデザインに固定
- イベント表示項目に「すべて」を追加
- 初期は全選択。最初の個別操作でその項目だけに絞り込み、その後は複数選択可能
- イベントタブを初期表示
- β版/非公式ツール注意書きを追加
- フィードバックフォームを追加
- NGワード、5文字未満、同一セッション60秒以内の連投を拒否
- Firebase Cloud Firestoreへ非公開保存
- 管理画面にフィードバックタブを追加
- 日時順表示、カテゴリ分け、非表示/再表示、CSV全件ダウンロードに対応
- 「非表示」は論理削除で、Firestoreの元データは削除しない

Firebase設定
1. Firebaseプロジェクトを作成し Cloud Firestore を有効化
2. サービスアカウントJSONを取得
3. MakerとAdminのStreamlit Secretsに以下を設定
   [firebase.service_account]
   type = "service_account"
   project_id = "..."
   private_key_id = "..."
   private_key = """-----BEGIN PRIVATE KEY-----
   ...
   -----END PRIVATE KEY-----
   """
   client_email = "..."
   client_id = "..."
   auth_uri = "https://accounts.google.com/o/oauth2/auth"
   token_uri = "https://oauth2.googleapis.com/token"
   auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
   client_x509_cert_url = "..."

注意
- サービスアカウントJSON/秘密鍵をGitHubへコミットしないでください。
- feedback_storage.py と firebase-admin が追加されています。
- Firebase未設定でもアプリ本体は動作しますが、フィードバック送信は利用できません。
- 既存の data_manager.py / github_storage.py / JSONデータは変更しません。

推奨Commit:
Prepare public beta UI and feedback

## v1.1.0-beta.9.22
- イベントカテゴリを「定期 / コラボ / ガチャ / ゲーム内CP / イベント / その他」に整理。
- ユーザー側のみ「定期コンテンツ」を「定期」と短縮表示。
- 廃止カテゴリは公開側の表示対象から除外。旧「コラボ・期間限定」は公開側で「コラボ」として互換表示。
- イベント表示項目を降臨側と同系統の pills ボタンへ変更し、「すべて」を含め横一列表示。
- 画像上部の凡例を6カテゴリ一列表示へ変更。
- 左端カテゴリカラーバーを行間で途切れない連続表示へ変更。
- フィードバック入力を st.form + form_submit_button に変更し、送信後クリア時の widget state 競合を回避。
- requirements に pyotp を復元し、firebase-admin を維持。
