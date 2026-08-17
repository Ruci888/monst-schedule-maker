import unittest
from datetime import date, datetime

from event_image_generator import (
    event_daily_labels,
    event_datetimes,
    generate_event_image,
)


class EventImageGeneratorTest(unittest.TestCase):
    def test_event_times_are_kept_as_datetime(self):
        event = {
            "start_date": "2026-08-17",
            "end_date": "2026-08-18",
            "start_time": "12:00",
            "end_time": "11:59",
        }

        start, end = event_datetimes(event)

        self.assertEqual(start, datetime(2026, 8, 17, 12, 0))
        self.assertEqual(end, datetime(2026, 8, 18, 11, 59))

    def test_date_only_event_uses_full_end_date(self):
        event = {
            "start_date": "2026-08-17",
            "end_date": "2026-08-18",
        }

        start, end = event_datetimes(event)

        self.assertEqual(start, datetime(2026, 8, 17, 0, 0))
        self.assertEqual(end, datetime(2026, 8, 19, 0, 0))

    def test_library_attributes_are_assigned_to_each_day(self):
        event = {
            "start_date": "2026-08-25",
            "end_date": "2026-08-29",
            "daily_labels": "闇・木・光・水・火",
        }

        labels = event_daily_labels(event)

        self.assertEqual(labels[date(2026, 8, 25)], "闇")
        self.assertEqual(labels[date(2026, 8, 29)], "火")

    def test_event_image_is_generated_with_time_and_daily_labels(self):
        events = [{
            "name": "追憶の書庫 金卵排出率2倍",
            "short_name": "書庫卵2倍CP(闇・木・光・水・火)",
            "category": "育成キャンペーン",
            "start_date": "2026-08-25",
            "end_date": "2026-08-29",
            "start_time": "00:00",
            "end_time": "23:59",
            "daily_labels": "闇・木・光・水・火",
        }]

        image = generate_event_image(events, "ブルー", date(2026, 8, 24))

        self.assertGreater(len(image.getvalue()), 1000)


if __name__ == "__main__":
    unittest.main()
