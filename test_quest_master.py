import unittest
from datetime import date, datetime, timezone

from quest_master import (
    delete_quest_master,
    master_expired,
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


if __name__ == "__main__":
    unittest.main()
