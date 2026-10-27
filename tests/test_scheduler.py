# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
from datetime import datetime, timezone, timedelta

os.environ.setdefault("VIGILIAE_DATA_DIR", tempfile.mkdtemp(prefix="vigiliae-test-"))

from vigiliae.scheduler import cron_match, parse_schedule  # noqa: E402

TZ = timezone(timedelta(hours=8))


class ScheduleTest(unittest.TestCase):
    def test_parse_empty_is_manual(self):
        self.assertEqual(parse_schedule(""), (None, None))

    def test_parse_interval(self):
        self.assertEqual(parse_schedule("every:3600"), ("interval", 3600))

    def test_parse_cron(self):
        self.assertEqual(parse_schedule("cron:0 8 * * *"),
                         ("cron", ["0", "8", "*", "*", "*"]))

    def test_parse_invalid(self):
        self.assertEqual(parse_schedule("tomorrow"), (None, None))

    def test_cron_daily_at_8(self):
        fields = ["0", "8", "*", "*", "*"]
        self.assertTrue(cron_match(fields, datetime(2026, 10, 27, 8, 0, tzinfo=TZ)))
        self.assertFalse(cron_match(fields, datetime(2026, 10, 27, 9, 0, tzinfo=TZ)))

    def test_cron_step_and_range(self):
        every_15 = ["*/15", "*", "*", "*", "*"]
        self.assertTrue(cron_match(every_15, datetime(2026, 10, 27, 8, 45, tzinfo=TZ)))
        self.assertFalse(cron_match(every_15, datetime(2026, 10, 27, 8, 46, tzinfo=TZ)))

        workdays = ["0", "9", "*", "*", "1-5"]
        self.assertTrue(cron_match(workdays, datetime(2026, 10, 27, 9, 0, tzinfo=TZ)))
        self.assertFalse(cron_match(workdays, datetime(2026, 10, 25, 9, 0, tzinfo=TZ)))

    def test_cron_sunday_is_zero(self):
        sunday = ["0", "9", "*", "*", "0"]
        self.assertTrue(cron_match(sunday, datetime(2026, 10, 25, 9, 0, tzinfo=TZ)))

    def test_cron_list(self):
        fields = ["0", "8,20", "*", "*", "*"]
        self.assertTrue(cron_match(fields, datetime(2026, 10, 27, 8, 0, tzinfo=TZ)))
        self.assertTrue(cron_match(fields, datetime(2026, 10, 27, 20, 0, tzinfo=TZ)))
        self.assertFalse(cron_match(fields, datetime(2026, 10, 27, 12, 0, tzinfo=TZ)))

    def test_bad_field_count(self):
        self.assertFalse(cron_match(["*"], datetime(2026, 10, 27, 8, 0, tzinfo=TZ)))


if __name__ == "__main__":
    unittest.main()
