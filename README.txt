v1.1.0-beta.9.24h — イベントカレンダー下の空白解消（再修正版）

変更対象: app.py のみ（ZIP内の app.py を GitHub リポジトリ直下に上書き）
ベース: ユーザーがアップロードした v1.1.0-beta.9.24e の app.py

変更: リンク付きイベント画像を固定高さ iframe (components.html) ではなく、
Streamlit 本体の自動高さ HTML (st.html) で表示。画像の描画・リンク位置・
ニュースURL生成・保存機能は変更なし。

注意: Streamlit が st.html に対応している必要があります。
構文チェック済み。iPhone/Streamlit Cloud 実機テストは未実施。
問題があれば v1.1.0-beta.9.24e の app.py に戻してください。

コミット: v1.1.0-beta.9.24h Render linked event image without iframe gap
