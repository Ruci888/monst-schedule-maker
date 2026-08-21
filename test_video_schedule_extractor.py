import unittest
from datetime import date

from video_schedule_extractor import (
    OCR_MODE_FAST,
    OCR_MODE_PRECISE,
    build_known_schedule_master,
    card_signatures_match,
    candidate_passes_quality_gate,
    candidate_identity,
    candidate_from_card_text,
    clean_ocr_character_name,
    deduplicate_video_candidates,
    filter_existing_candidates,
    find_date_time,
    find_difficulty,
    normalize_candidate_recording_date,
    normalize_identity_name,
    normalize_ocr_mode,
    postprocess_video_candidates,
    prepare_video_review_candidates,
    resolve_candidate_with_master,
)


class VideoScheduleExtractorTests(unittest.TestCase):
    def test_defaults_unknown_ocr_mode_to_fast(self):
        self.assertEqual(normalize_ocr_mode(""), OCR_MODE_FAST)
        self.assertEqual(normalize_ocr_mode("不明"), OCR_MODE_FAST)
        self.assertEqual(
            normalize_ocr_mode(OCR_MODE_PRECISE),
            OCR_MODE_PRECISE,
        )

    def test_matches_nearly_identical_card_signatures_before_ocr(self):
        base = "0" * 64
        near = "0" * 63 + "3"
        far = "f" * 64
        self.assertTrue(card_signatures_match(base, near))
        self.assertFalse(card_signatures_match(base, far))

    def test_parses_app_card_text(self):
        text = """
        8/21(金) 12:00 ～ 8/22(土) 11:59
        難易度「爆絶」を3種類以上クリア　轟絶・究極
        アンコルウ
        """
        candidate = candidate_from_card_text(text, 2026, "闇", 88.2)
        self.assertEqual(candidate["date"], "8/21")
        self.assertEqual(candidate["ocr_end_date"], "8/22")
        self.assertEqual(candidate["start_time"], "12:00")
        self.assertEqual(candidate["end_time"], "11:59")
        self.assertEqual(candidate["name"], "アンコルウ")
        self.assertEqual(candidate["difficulty"], "轟絶")
        self.assertEqual(candidate["attribute"], "闇")
        self.assertFalse(candidate["published"])

    def test_normalizes_full_width_identity(self):
        self.assertEqual(normalize_identity_name("獅子吼・廻"), "獅子吼廻")
        self.assertEqual(normalize_identity_name(" 獅子吼 ･ 廻 "), "獅子吼廻")

    def test_removes_english_noise_around_japanese_name(self):
        self.assertEqual(
            clean_ocr_character_name("w 竜 オーポレン BRE"),
            "オーポレン",
        )
        self.assertEqual(clean_ocr_character_name("x ew. AO"), "")

    def test_keeps_incomplete_candidate_for_manual_review(self):
        text = "8/21(金) 12:00 ～ 8/22(土) 11:59\n超絶\nソーマ"
        candidate = candidate_from_card_text(
            text,
            2026,
            recognized_name="x ew. AO",
            raw_name_text="x ew. AO",
            ocr_status="名前認識失敗",
        )
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["name"], "")
        self.assertIn("名前要入力", candidate["ocr_status"])
        self.assertFalse(candidate["published"])

    def test_uses_only_dedicated_difficulty_result(self):
        text = (
            "8/21(金) 12:00 ～ 8/22(土) 11:59\n"
            "難易度『爆絶』を3種類以上クリア"
        )
        candidate = candidate_from_card_text(
            text,
            2026,
            attribute="光",
            recognized_name="ソーマ",
            recognized_difficulty="超絶",
            raw_difficulty_text="超絶",
        )
        self.assertEqual(candidate["difficulty"], "超絶")

    def test_incomplete_candidates_have_separate_identities(self):
        first = {
            "year": 2026,
            "date": "8/21",
            "start_time": "12:00",
            "name": "",
            "attribute": "",
            "difficulty": "",
            "candidate_id": "first",
        }
        second = {**first, "candidate_id": "second"}
        self.assertNotEqual(candidate_identity(first), candidate_identity(second))

    def test_finds_date_and_difficulty(self):
        parsed = find_date_time("8/25(火)12:00〜8/26(水)11:59")
        self.assertEqual(parsed["date"], "8/25")
        self.assertEqual(parsed["end_date"], "8/26")
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

    def test_uses_multiple_frame_consensus_for_same_card(self):
        base = {
            "year": 2026,
            "date": "8/22",
            "start_time": "12:00",
            "end_time": "11:59",
            "difficulty": "超絶",
            "attribute": "火",
            "visual_signature": "0" * 64,
            "ocr_votes": 1,
        }
        candidates = [
            {
                **base,
                "name": "ソーレニにンスンス",
                "ocr_confidence": 75,
            },
            {
                **base,
                "name": "ソーマ",
                "ocr_confidence": 65,
                "visual_signature": "0" * 63 + "1",
            },
            {
                **base,
                "name": "ソーマ",
                "ocr_confidence": 70,
                "visual_signature": "0" * 63 + "2",
            },
        ]
        unique, duplicate_count = deduplicate_video_candidates(candidates)
        self.assertEqual(len(unique), 1)
        self.assertEqual(duplicate_count, 2)
        self.assertEqual(unique[0]["name"], "ソーマ")
        self.assertEqual(unique[0]["ocr_votes"], 3)

    def test_keeps_different_visual_cards_separate(self):
        base = {
            "year": 2026,
            "date": "8/22",
            "start_time": "12:00",
            "end_time": "11:59",
            "difficulty": "超絶",
            "attribute": "火",
            "ocr_confidence": 70,
        }
        candidates = [
            {**base, "name": "ソーマ", "visual_signature": "0" * 64},
            {**base, "name": "アラミタマ", "visual_signature": "f" * 64},
        ]
        unique, duplicate_count = deduplicate_video_candidates(candidates)
        self.assertEqual(len(unique), 2)
        self.assertEqual(duplicate_count, 0)

    def test_card_image_deduplicates_even_when_ocr_dates_differ(self):
        base = {
            "year": 2026,
            "start_time": "12:00",
            "end_time": "11:59",
            "name": "",
            "difficulty": "",
            "attribute": "",
            "card_signature": "0" * 64,
            "ocr_confidence": 0,
        }
        candidates = [
            {**base, "date": "3/20", "candidate_id": "first"},
            {**base, "date": "8/20", "candidate_id": "second"},
        ]
        unique, duplicate_count = deduplicate_video_candidates(candidates)
        self.assertEqual(len(unique), 1)
        self.assertEqual(duplicate_count, 1)

    def test_keeps_failed_ocr_as_image_review_candidate(self):
        candidate = {
            "candidate_id": "manual-card",
            "year": 2026,
            "date": "3/20",
            "ocr_end_date": "3/21",
            "start_time": "12:00",
            "end_time": "11:59",
            "name": "",
            "attribute": "",
            "difficulty": "",
            "category": "high_difficulty",
            "ocr_raw_name": "判読不能",
            "ocr_raw_date": "3/20 12:00",
            "ocr_raw_difficulty": "",
            "ocr_confidence": 0,
            "ocr_votes": 1,
            "_preview_image": b"jpeg-bytes",
        }
        (
            review,
            automatic_count,
            manual_count,
            rejected_count,
            duplicate_count,
        ) = prepare_video_review_candidates(
            [candidate],
            date(2026, 8, 20),
        )
        self.assertEqual(len(review), 1)
        self.assertEqual(review[0]["date"], "")
        self.assertEqual(review[0]["review_mode"], "画像確認")
        self.assertEqual(review[0]["_preview_image"], b"jpeg-bytes")
        self.assertEqual(automatic_count, 0)
        self.assertEqual(manual_count, 1)
        self.assertEqual(rejected_count, 0)
        self.assertEqual(duplicate_count, 0)

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

    def test_rejects_ocr_date_outside_recording_window(self):
        candidate = {
            "year": 2026,
            "date": "3/20",
            "ocr_end_date": "3/21",
            "start_time": "12:00",
            "end_time": "11:59",
        }
        result = normalize_candidate_recording_date(
            candidate,
            date(2026, 8, 20),
        )
        self.assertIsNone(result)

    def test_normalizes_valid_game_day_and_times(self):
        candidate = {
            "year": 2026,
            "date": "8/20",
            "ocr_end_date": "8/21",
            "start_time": "12:00",
            "end_time": "11:58",
        }
        result = normalize_candidate_recording_date(
            candidate,
            date(2026, 8, 20),
        )
        self.assertEqual(result["date"], "8/20")
        self.assertEqual(result["start_time"], "12:00")
        self.assertEqual(result["end_time"], "11:59")

    def test_rejects_non_consecutive_ocr_end_date(self):
        candidate = {
            "year": 2026,
            "date": "8/20",
            "ocr_end_date": "8/25",
            "start_time": "12:00",
            "end_time": "11:59",
        }
        result = normalize_candidate_recording_date(
            candidate,
            date(2026, 8, 20),
        )
        self.assertIsNone(result)

    def test_corrects_name_and_fields_from_known_master(self):
        known = [{
            "name": "ペグイル",
            "attribute": "闇",
            "difficulty": "黎絶",
            "category": "high_difficulty",
        }]
        master = build_known_schedule_master(known, [])
        candidate = {
            "name": "ペクイル",
            "ocr_raw_name": "ペクイル / ペグイル",
            "attribute": "光",
            "difficulty": "",
        }
        resolved, matched = resolve_candidate_with_master(candidate, master)
        self.assertTrue(matched)
        self.assertEqual(resolved["name"], "ペグイル")
        self.assertEqual(resolved["attribute"], "闇")
        self.assertEqual(resolved["difficulty"], "黎絶")
        self.assertEqual(resolved["category"], "高難易度・注目")

    def test_quality_gate_rejects_incomplete_one_frame_noise(self):
        candidate = {
            "name": "こに",
            "attribute": "光",
            "difficulty": "",
            "ocr_votes": 1,
            "ocr_confidence": 90,
        }
        self.assertFalse(candidate_passes_quality_gate(candidate))

    def test_postprocess_rejects_noise_and_deduplicates_corrected_names(self):
        base = {
            "year": 2026,
            "date": "8/20",
            "ocr_end_date": "8/21",
            "start_time": "12:00",
            "end_time": "11:59",
            "attribute": "光",
            "difficulty": "",
            "category": "high_difficulty",
            "ocr_votes": 1,
            "ocr_confidence": 60,
        }
        candidates = [
            {**base, "name": "ペクイル", "ocr_raw_name": "ペグイル"},
            {**base, "name": "ペグイル", "ocr_raw_name": "ペグイル"},
            {
                **base,
                "date": "3/20",
                "ocr_end_date": "3/21",
                "name": "こに",
                "ocr_raw_name": "こに",
            },
        ]
        published = [{
            "name": "ペグイル",
            "attribute": "闇",
            "difficulty": "黎絶",
            "category": "high_difficulty",
        }]
        accepted, rejected, duplicates = postprocess_video_candidates(
            candidates,
            date(2026, 8, 20),
            published_schedules=published,
        )
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]["name"], "ペグイル")
        self.assertEqual(rejected, 1)
        self.assertEqual(duplicates, 1)


if __name__ == "__main__":
    unittest.main()
