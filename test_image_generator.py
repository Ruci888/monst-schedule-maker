import unittest
from datetime import date

from PIL import Image

from image_generator import generate_schedule_image, get_difficulty_color


def make_schedule(day, name, difficulty, attribute="火"):
    return {
        "year": 2026,
        "date": day,
        "start_time": "12:00",
        "end_time": "11:59",
        "name": name,
        "attribute": attribute,
        "difficulty": difficulty,
        "category": "高難易度・注目",
        "availability_type": "時間指定",
        "period_end_date": "",
    }


class ScheduleImageGeneratorTest(unittest.TestCase):
    def test_normal_mode_keeps_seven_days_and_generates_png(self):
        schedules = [
            make_schedule("8/18", "テスト爆絶", "爆絶"),
            make_schedule("8/18", "テスト超絶廻", "超絶・廻", "光"),
            make_schedule("8/18", "テスト超絶", "超絶", "水"),
            make_schedule("8/18", "テスト究極", "究極", "木"),
            make_schedule("8/19", "テスト星5", "星5制限", "光"),
        ]
        image_buffer = generate_schedule_image(
            schedules,
            "ダーク",
            date(2026, 8, 18),
            "通常降臨・爆絶以下",
        )
        image = Image.open(image_buffer)

        self.assertEqual(image.format, "PNG")
        self.assertEqual(image.width, 1080)
        self.assertGreaterEqual(image.height, 1350)
        self.assertEqual(
            get_difficulty_color("超絶・廻"),
            get_difficulty_color("超絶"),
        )


if __name__ == "__main__":
    unittest.main()
