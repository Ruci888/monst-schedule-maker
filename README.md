# モンスト スケジュールメーカー Ver1.1

降臨予定とイベント予定を選択し、スマホ向けPNG画像を生成するStreamlitアプリです。

公開画面の降臨スケジュールは、次の2モードから選べます。

- 注目：コラボ・期間限定、黎絶、轟絶、超究極シリーズ
- 通常降臨・爆絶以下：爆絶、超絶、激究極／究極、極、星5制限

通常降臨版は各日12:00～翌11:59を共通時間として、7日分を2列で表示します。

## 起動

```powershell
pip install -r requirements.txt
streamlit run app.py
```

## データ更新

- 降臨：`schedules.json`
- イベント：`events.json`

## 管理画面

管理画面では、降臨とイベントの登録・修正・公開切替、
公式ニュースからの自動取得候補を確認できます。

```powershell
python -m pip install -r requirements.txt
python setup_admin_auth.py
streamlit run admin_app.py
```

`setup_admin_auth.py`が表示するパスワードハッシュとTOTP秘密鍵は、
`.streamlit/secrets.toml`またはStreamlit Community CloudのSecretsへ登録します。
秘密情報はGitHubへコミットしないでください。

設定項目の記入例は`.streamlit/secrets.example.toml`にあります。

オンライン管理画面では、GitHubのFine-grained personal access tokenを利用して
`schedules.json`と`events.json`を更新します。トークンは対象リポジトリを限定し、
`Contents: Read and write`以外の不要な権限を付与しないでください。

管理画面はユーザー向けアプリとは別のStreamlitアプリとしてデプロイし、
閲覧者を管理者本人だけに制限してください。
## 管理画面の動画取込

管理画面の「自動取得候補・失敗ログ」から、モンストアプリの
スケジュール画面録画（MP4・MOV）を降臨候補へ変換できます。

- 最大100MB、3分以内
- 日程の年を指定してから動画を選択
- 動画は処理中のみ一時保存し、処理後に削除
- 公開済み・承認待ち・動画内の重複を除外
- OCR結果は自動公開せず、必ず「降臨候補」で確認して承認
- 画面内のカード枠を画像として検出し、日時・名前・難易度・属性を別領域から読む
- 不確実な名前・属性・難易度は推測で埋めず、空欄の承認待ち候補として保存
- 未入力項目がある候補は、管理画面で修正するまで承認できない
- 誤認識候補は「削除」にチェックして承認待ち一覧から削除できる
- OCR内部評価は正答率ではないため、すべての動画候補を目視確認する

Cloudでは`packages.txt`からTesseract日本語データを導入します。
ローカル管理画面で使う場合も、Tesseract本体と日本語データが必要です。
