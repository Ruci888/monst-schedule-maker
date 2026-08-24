# v1.1.0-beta.9.9 更新内容

スクリーンショットから降臨候補を取得する処理を改善しました。

## 主な変更

- カードの画像内位置を保持し、前後カードの日時から誤読した日付を補正
- 範囲内だが誤っている日付も、複数画像の周辺情報が一致すれば補正
- キャラ名をカード全体OCRと専用領域OCRの両方から比較
- `U-20日本代表`、`TOP3`、`殺し屋`、`チームY`などの接頭辞を保持
- 属性をキャラ名の文字色から独立判定
- 難易度ラベルを拡大して独立OCRし、複数結果の多数決を使用
- `超絶・廻`を`超絶`と区別
- `コラボ期間限定`を含むカードを「コラボ」に分類

## 更新するファイル

実行処理の変更対象は次の2ファイルです。

1. `app.py`
2. `video_schedule_extractor.py`

ZIPには、動作確認や既存構成との整合のため次の6ファイルを収録しています。

1. `app.py`
2. `admin_app.py`
3. `schedule_utils.py`
4. `video_schedule_extractor.py`
5. `test_video_schedule_extractor.py`
6. `UPDATE_v1.1.0-beta.9.9.md`

## 確認結果

- Python構文チェック：成功
- 単体テスト：28件すべて成功

実際のOCR精度はStreamlit Cloud上のTesseract環境にも左右されます。同じ10枚のスクリーンショットで再抽出し、日付・名前・属性・難易度を確認してください。

## GitHubコミットメッセージ例

`fix: improve screenshot OCR accuracy and date assignment (beta 9.9)`
