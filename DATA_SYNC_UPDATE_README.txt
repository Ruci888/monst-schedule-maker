モンスト スケジュールメーカー：GitHub共通JSON同期アップデート

目的
- GitHub上の schedules.json / events.json / quest_master.json を正本にする。
- 公開メーカーはGitHub Public RepositoryからREAD ONLYで取得する。
- 公開メーカーにはGitHub Tokenを置かない。
- 取得失敗時に古いローカルJSONへ黙ってフォールバックしない。

更新対象
1. data_manager.py を同梱版へ置き換える。
2. data_manager.py 冒頭の GITHUB_OWNER を実際のGitHubユーザー/Organization名へ変更する。
3. GITHUB_REPOSITORY が monst-schedule-maker、GITHUB_BRANCH が main で正しいことを確認する。
4. requirements.txt に requests が無ければ requests を追加する。

重要
- 管理画面側の github_storage.py / admin_app.py は今回変更不要。
- app.py の from data_manager import load_events, load_schedules も変更不要。
- schedules.json / events.json / quest_master.json のローカルコピーは開発・保守用として残せるが、公開メーカーの正本には使わない。
- GitHub取得エラー時は RemoteDataError を発生させる。現状の app.py に例外表示処理が無い場合、Streamlit上ではエラーになる。この挙動は「古い情報を最新として表示しない」ことを優先したもの。

動作確認
A. 管理画面でテスト用の降臨データを1件更新して保存。
B. GitHubの schedules.json に変更が反映されたことを確認。
C. 公開メーカーを再読込。
D. 更新した降臨が表示されることを確認。
E. イベントについても同様に events.json で確認。

次段階で推奨
- app.py側で RemoteDataError を捕捉し、利用者向けに「最新データを取得できませんでした」と簡潔に表示する。
- 必要になった段階で短いTTLキャッシュを検討する。
