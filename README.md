# モンスト スケジュールメーカー Ver1.1

降臨予定とイベント予定を選択し、スマホ向けPNG画像を生成するStreamlitアプリです。

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
