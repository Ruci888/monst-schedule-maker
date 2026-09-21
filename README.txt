モンストスケジュールメーカー data_manager 互換性修正版

目的
- 公開メーカー: GitHub上の schedules.json / events.json / quest_master.json を読み込む
- 管理画面: admin_app.py が従来 import している save_json / save_schedules /
  save_events / save_quest_master を復元し、ImportErrorを解消する
- UI・画像生成処理には変更を加えない

重要
1. data_manager.py を置き換える前に、現在正常表示できている data_manager.py の
   GITHUB_OWNER の値を確認してください。
2. この修正版の
       GITHUB_OWNER = "YOUR_GITHUB_OWNER"
   を、その現在動作している値に変更してください。
3. GitHubへ commit してください。
4. 公開メーカーと管理画面の両方が起動することを確認してください。
5. 管理画面でテスト更新し、公開メーカーへ反映されることを確認してください。

想定コミットメッセージ:
Fix data manager compatibility for admin app
