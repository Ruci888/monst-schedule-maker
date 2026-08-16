# モンスト スケジュールメーカー（プロトタイプ）

降臨予定とイベント予定を選択し、スマホ向けPNG画像を生成するStreamlitアプリです。

## 起動

```powershell
pip install -r requirements.txt
streamlit run app.py
```

## データ更新

- 降臨：`schedules.json`
- イベント：`events.json`

現段階では管理者がJSONを更新する手動データ方式です。自動取得と管理画面は次期版で追加します。
