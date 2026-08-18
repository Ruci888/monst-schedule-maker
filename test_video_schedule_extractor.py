import unittest

from video_schedule_extractor import (
    candidate_from_card_text,
    deduplicate_video_candidates,
    filter_existing_candidates,
    find_date_time,
    find_difficulty,
    normalize_identity_name,
)


class VideoScheduleExtractorTests(unittest.TestCase):
    def test_parses_app_card_text(self):
        text = """
        8/21(金) 12:00 ～ 8/22(土) 11:59
        難易度「爆絶」を3種類以上クリア　轟絶・究極
        アンコルウ
        """
        candidate = candidate_from_card_text(text, 2026, "闇", 88.2)
        self.assertEqual(candidate["date"], "8/21")
        self.assertEqual(candidate["start_time"], "12:00")
        self.assertEqual(candidate["end_time"], "11:59")
        self.assertEqual(candidate["name"], "アンコルウ")
        self.assertEqual(candidate["difficulty"], "轟絶")
        self.assertEqual(candidate["attribute"], "闇")
        self.assertFalse(candidate["published"])

    def test_normalizes_full_width_identity(self):
        self.assertEqual(normalize_identity_name("獅子吼・廻"), "獅子吼廻")
        self.assertEqual(normalize_identity_name(" 獅子吼 ･ 廻 "), "獅子吼廻")

    def test_finds_date_and_difficulty(self):
        parsed = find_date_time("8/25(火)12:00〜8/26(水)11:59")
        self.assertEqual(parsed["date"], "8/25")
        self.assertEqual(find_difficulty("超絶・廻"), "超絶")
        self.assertEqual(find_difficulty("轟絶・究極"), "轟絶")

    def test_deduplicates_overlapping_video_frames(self):
        base = {
            "year": 2026,
            "date": "8/25",
            "start_time": "12:00",
            "end_time": "11:59",
            "name": "レース",
            "difficulty": "爆絶",
            "ocr_confidence": 70,
        }
        better = {**base, "ocr_confidence": 92}
        unique, duplicate_count = deduplicate_video_candidates([base, better])
        self.assertEqual(len(unique), 1)
        self.assertEqual(duplicate_count, 1)
        self.assertEqual(unique[0]["ocr_confidence"], 92)

    def test_filters_published_and_pending_duplicates(self):
        candidates = [
            {"year": 2026, "date": "8/19", "start_time": "12:00", "name": "ドライ", "difficulty": "超絶"},
            {"year": 2026, "date": "8/20", "start_time": "12:00", "name": "ディスモルフォ", "difficulty": "黎絶"},
            {"year": 2026, "date": "8/21", "start_time": "12:00", "name": "アンコルウ", "difficulty": "轟絶"},
        ]
        new, published_count, pending_count = filter_existing_candidates(
            candidates,
            [candidates[0]],
            [candidates[1]],
        )
        self.assertEqual(new, [candidates[2]])
        self.assertEqual(published_count, 1)
        self.assertEqual(pending_count, 1)


if __name__ == "__main__":
    unittest.main()
