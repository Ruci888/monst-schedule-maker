import unittest
from datetime import date, datetime, timezone

from quest_master import (
    add_candidate_image_reference,
    card_reference_is_learnable,
    delete_quest_master,
    master_expired,
    parse_master_bulk_entries,
    parse_master_bulk_text,
    quest_master_kana_group,
    quest_master_key,
    schedule_from_master,
    search_quest_master,
    upsert_quest_master,
)


NOW = datetime(2026, 8, 27, 0, 0, tzinfo=timezone.utc)


class QuestMasterTests(unittest.TestCase):
    def test_adds_master_from_approved_schedule(self):
        master, added, updated, skipped = upsert_quest_master(
            [],
            [{
                "name": "ペグイル",
                "attribute": "闇",
                "difficulty": "黎絶",
                "category": "高難易度・注目",
            }],
            now=NOW,
        )
        self.assertEqual((added, updated, skipped), (1, 0, 0))
        self.assertEqual(master[0]["name"], "ペグイル")
        self.assertTrue(master[0]["quest_id"].startswith("quest_"))
        self.assertEqual(master[0]["created_at"], NOW.isoformat())

    def test_updates_same_name_and_difficulty_without_changing_id(self):
        first, *_ = upsert_quest_master(
            [],
            [{
                "name": "グノーシス",
                "attribute": "木",
                "difficulty": "超究極・兵",
                "category": "高難易度・注目",
            }],
            now=NOW,
        )
        quest_id = first[0]["quest_id"]
        second, added, updated, skipped = upsert_quest_master(
            first,
            [{
                "name": "グノーシス",
                "attribute": "水",
                "difficulty": "超究極・兵",
                "category": "高難易度・注目",
            }],
            now=datetime(2026, 8, 28, tzinfo=timezone.utc),
        )
        self.assertEqual((added, updated, skipped), (0, 1, 0))
        self.assertEqual(second[0]["quest_id"], quest_id)
        self.assertEqual(second[0]["attribute"], "水")

    def test_same_name_with_different_difficulty_has_separate_id(self):
        master, added, updated, skipped = upsert_quest_master(
            [],
            [
                {
                    "name": "同名キャラ",
                    "attribute": "火",
                    "difficulty": "究極",
                    "category": "通常降臨",
                },
                {
                    "name": "同名キャラ",
                    "attribute": "火",
                    "difficulty": "超究極",
                    "category": "高難易度・注目",
                },
            ],
            now=NOW,
        )
        self.assertEqual((added, updated, skipped), (2, 0, 0))
        self.assertNotEqual(master[0]["quest_id"], master[1]["quest_id"])

    def test_normal_master_never_expires(self):
        record = {
            "name": "通常キャラ",
            "difficulty": "究極",
            "category": "通常降臨",
            "period_end_date": "2026-08-01",
        }
        self.assertFalse(master_expired(record, today=date(2026, 8, 27)))

    def test_limited_master_expires_after_period_end(self):
        record = {
            "name": "期間限定キャラ",
            "difficulty": "究極",
            "category": "イベント・期間限定",
            "period_end_date": "2026-08-26",
        }
        self.assertTrue(master_expired(record, today=date(2026, 8, 27)))

    def test_search_hides_expired_master_by_default(self):
        records = [
            {
                "name": "通常キャラ",
                "attribute": "木",
                "difficulty": "究極",
                "category": "通常降臨",
            },
            {
                "name": "終了キャラ",
                "attribute": "光",
                "difficulty": "究極",
                "category": "コラボ",
                "period_end_date": "2026-08-20",
            },
        ]
        active = search_quest_master(
            records, include_expired=False, today=date(2026, 8, 27)
        )
        all_records = search_quest_master(
            records, include_expired=True, today=date(2026, 8, 27)
        )
        self.assertEqual([item["name"] for item in active], ["通常キャラ"])
        self.assertEqual(len(all_records), 2)

    def test_reuses_master_with_date_and_start_time_only(self):
        record = {
            "quest_id": "quest_test",
            "name": "ペグイル",
            "quest_name": "",
            "attribute": "闇",
            "difficulty": "黎絶",
            "category": "高難易度・注目",
        }
        schedule = schedule_from_master(
            record,
            date(2026, 8, 30),
            "20:00",
        )
        self.assertEqual(schedule["date"], "8/30")
        self.assertEqual(schedule["start_time"], "20:00")
        self.assertEqual(schedule["end_time"], "11:59")
        self.assertTrue(schedule["end_next_day"])
        self.assertEqual(schedule["quest_id"], "quest_test")

    def test_deletes_only_confirmed_master_id(self):
        records = [
            {
                "quest_id": "one",
                "name": "一",
                "difficulty": "究極",
                "category": "通常降臨",
            },
            {
                "quest_id": "two",
                "name": "二",
                "difficulty": "究極",
                "category": "通常降臨",
            },
        ]
        remaining = delete_quest_master(records, {"one"})
        self.assertEqual([item["quest_id"] for item in remaining], ["two"])
        self.assertEqual(quest_master_key(remaining[0]), ("二", "究極"))

    def test_parses_mobile_friendly_bulk_master_input(self):
        records, errors = parse_master_bulk_text(
            "スノーマン｜木｜究極\n"
            "ストラテジー,水,爆絶,す",
            "通常降臨",
        )
        self.assertEqual(errors, [])
        self.assertEqual(records[0], {
            "name": "スノーマン",
            "name_reading": "",
            "attribute": "木",
            "difficulty": "究極",
            "category": "通常降臨",
        })
        self.assertEqual(records[1]["category"], "通常降臨")
        self.assertEqual(records[1]["name_reading"], "す")

    def test_parses_optional_reading_for_kana_browse(self):
        records, errors = parse_master_bulk_text(
            "仙丹｜木｜超絶｜せ",
            "通常降臨",
        )
        self.assertEqual(errors, [])
        self.assertEqual(records[0]["name_reading"], "せ")

    def test_kana_group_uses_katakana_name_automatically(self):
        self.assertEqual(
            quest_master_kana_group({"name": "スノーマン"}),
            "さ行",
        )

    def test_kana_group_uses_registered_reading_for_kanji_name(self):
        self.assertEqual(
            quest_master_kana_group({"name": "仙丹"}),
            "未分類",
        )
        self.assertEqual(
            quest_master_kana_group({"name": "仙丹", "name_reading": "せ"}),
            "さ行",
        )

    def test_searches_master_by_registered_reading(self):
        records = [{
            "name": "仙丹",
            "name_reading": "せんたん",
            "attribute": "木",
            "difficulty": "超絶",
            "category": "通常降臨",
        }]
        matches = search_quest_master(records, query="せん")
        self.assertEqual([record["name"] for record in matches], ["仙丹"])

    def test_bulk_master_input_reports_invalid_line(self):
        records, errors = parse_master_bulk_text(
            "名前だけ",
            "通常降臨",
        )
        self.assertEqual(records, [])
        self.assertIn("1行目", errors[0])

    def test_bulk_master_rejects_per_line_category_columns(self):
        records, errors = parse_master_bulk_text(
            "仙丹｜木｜超絶｜通常降臨｜せ",
            "通常降臨",
        )
        self.assertEqual(records, [])
        self.assertIn("カテゴリは上部の選択", errors[0])

    def test_bulk_master_entries_keep_line_numbers_and_errors(self):
        entries = parse_master_bulk_entries(
            "スノーマン｜木｜究極\n名前だけ\n仙丹｜木｜超絶｜せ",
            "通常降臨",
        )
        self.assertEqual([entry["line_number"] for entry in entries], [1, 2, 3])
        self.assertEqual(entries[0]["record"]["category"], "通常降臨")
        self.assertIsNone(entries[1]["record"])
        self.assertIn("2行目", entries[1]["error"])
        self.assertEqual(entries[2]["record"]["name_reading"], "せ")

    def test_parses_all_unique_quests_from_reported_screenshot_batch(self):
        records, errors = parse_master_bulk_text(
            "U-20日本代表 士道龍聖｜光｜超究極\n"
            "TOP3 蟻生十兵衛｜木｜究極\n"
            "殺し屋 烏旅人｜水｜究極\n"
            "チームY 二子一揮｜闇｜極\n"
            "チームV 剣城斬鉄｜光｜極\n"
            "イゴーロナク｜光｜激究極\n"
            "スタバーン｜光｜轟絶\n"
            "ジョルノ・ロキア｜水｜激究極\n"
            "スノーマン｜木｜究極\n"
            "ドリルマックス｜闇｜究極\n"
            "ぶんぶく茶釜｜光｜極\n"
            "浄化の仏神 金剛夜叉明王廻｜光｜超絶・廻\n"
            "松永久秀｜火｜究極\n"
            "キャスパリーグ｜水｜極\n"
            "コポルネス｜火｜黎絶\n"
            "ストラテジー｜水｜爆絶\n"
            "仙丹｜木｜超絶",
            "通常降臨",
        )
        self.assertEqual(errors, [])
        self.assertEqual(len(records), 17)
        self.assertEqual(records[0]["name"], "U-20日本代表 士道龍聖")
        self.assertEqual(records[11]["difficulty"], "超絶・廻")

    def test_adds_only_complete_card_to_master_image_references(self):
        master, *_ = upsert_quest_master(
            [],
            [{
                "name": "スノーマン",
                "attribute": "木",
                "difficulty": "究極",
                "category": "通常降臨",
            }],
            now=NOW,
        )
        candidate = {
            "card_complete": True,
            "card_visible_ratio": 1.0,
            "card_sharpness": 80,
            "portrait_signature": "0" * 64,
            "visual_signature": "1" * 64,
            "card_signature": "2" * 64,
            "source_capture_type": "screenshot",
        }
        updated, added, message = add_candidate_image_reference(
            master,
            master[0]["quest_id"],
            candidate,
            now=NOW,
        )
        self.assertTrue(added)
        self.assertIn("登録", message)
        self.assertEqual(len(updated[0]["image_references"]), 1)
        self.assertNotIn("_preview_image", updated[0]["image_references"][0])

        updated_again, added_again, _ = add_candidate_image_reference(
            updated,
            master[0]["quest_id"],
            candidate,
            now=NOW,
        )
        self.assertFalse(added_again)
        self.assertEqual(len(updated_again[0]["image_references"]), 1)

    def test_rejects_clipped_card_from_master_learning(self):
        candidate = {
            "card_complete": False,
            "card_visible_ratio": 0.72,
            "card_sharpness": 90,
            "portrait_signature": "0" * 64,
            "card_completeness_reason": "下端またはメニュー被り",
        }
        learnable, reason = card_reference_is_learnable(candidate)
        self.assertFalse(learnable)
        self.assertIn("下端", reason)

    def test_partial_card_can_never_be_added_even_with_portrait(self):
        master, *_ = upsert_quest_master(
            [],
            [{
                "name": "仙丹",
                "attribute": "木",
                "difficulty": "超絶",
                "category": "通常降臨",
            }],
            now=NOW,
        )
        updated, added, _ = add_candidate_image_reference(
            master,
            master[0]["quest_id"],
            {
                "card_complete": False,
                "card_visible_ratio": 0.95,
                "card_sharpness": 100,
                "portrait_signature": "a" * 64,
            },
            now=NOW,
        )
        self.assertFalse(added)
        self.assertEqual(updated[0]["image_references"], [])


if __name__ == "__main__":
    unittest.main()
