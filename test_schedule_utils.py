import unittest
from datetime import date, datetime

from schedule_utils import (
    AVAILABILITY_PERIOD,
    AVAILABILITY_SCHEDULED,
    schedule_active_on_game_day,
    schedule_end_datetime,
    schedule_game_day,
    schedule_overlaps_game_days,
    schedule_time_text_for_day,
)


def make_schedule(**overrides):
    schedule = {
        "year": 2026,
        "date": "8/18",
        "start_time": "19:00",
        "end_time": "11:59",
        "name": "テスト降臨",
        "attribute": "光",
        "difficulty": "超究極",
        "category": "コラボ",
        "availability_type": AVAILABILITY_PERIOD,
        "period_end_date": "2026-08-22",
    }
    schedule.update(overrides)
    return schedule


class ScheduleUtilsTest(unittest.TestCase):
    def test_period_schedule_is_active_on_each_overlapping_game_day(self):
        schedule = make_schedule()

        self.assertTrue(schedule_active_on_game_day(schedule, date(2026, 8, 18)))
        self.assertTrue(schedule_active_on_game_day(schedule, date(2026, 8, 21)))
        self.assertTrue(schedule_active_on_game_day(schedule, date(2026, 8, 22)))
        self.assertFalse(schedule_active_on_game_day(schedule, date(2026, 8, 23)))

    def test_period_schedule_overlaps_selected_week(self):
        schedule = make_schedule()

        self.assertTrue(
            schedule_overlaps_game_days(
                schedule,
                date(2026, 8, 19),
                date(2026, 8, 25),
            )
        )

    def test_period_time_text_only_keeps_a_nonstandard_first_start(self):
        schedule = make_schedule()

        self.assertEqual(
            schedule_time_text_for_day(schedule, date(2026, 8, 18)),
            "19:00～",
        )
        self.assertEqual(
            schedule_time_text_for_day(schedule, date(2026, 8, 19)),
            "",
        )
        self.assertEqual(
            schedule_time_text_for_day(schedule, date(2026, 8, 22)),
            "",
        )

    def test_period_starting_at_noon_has_no_time_text(self):
        schedule = make_schedule(start_time="12:00")

        self.assertEqual(
            schedule_time_text_for_day(schedule, date(2026, 8, 18)),
            "",
        )

    def test_before_noon_period_end_is_on_next_calendar_day(self):
        schedule = make_schedule(period_end_date="2026-08-19", end_time="11:59")

        self.assertEqual(
            schedule_end_datetime(schedule),
            datetime(2026, 8, 20, 11, 59),
        )

    def test_before_noon_schedule_belongs_to_previous_game_day(self):
        schedule = make_schedule(
            date="8/19",
            start_time="10:00",
            end_time="11:59",
            availability_type=AVAILABILITY_SCHEDULED,
            period_end_date="",
        )

        self.assertEqual(schedule_game_day(schedule), date(2026, 8, 18))

    def test_overnight_scheduled_end_moves_to_next_calendar_day(self):
        schedule = make_schedule(
            start_time="23:00",
            end_time="01:00",
            availability_type=AVAILABILITY_SCHEDULED,
            period_end_date="",
        )

        self.assertEqual(
            schedule_end_datetime(schedule),
            datetime(2026, 8, 19, 1, 0),
        )

    def test_master_reuse_can_force_1159_to_next_day(self):
        schedule = make_schedule(
            start_time="08:00",
            end_time="11:59",
            end_next_day=True,
            availability_type=AVAILABILITY_SCHEDULED,
            period_end_date="",
        )

        self.assertEqual(
            schedule_end_datetime(schedule),
            datetime(2026, 8, 19, 11, 59),
        )


if __name__ == "__main__":
    unittest.main()
