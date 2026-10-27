# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

os.environ.setdefault("VIGILIAE_DATA_DIR", tempfile.mkdtemp(prefix="vigiliae-test-"))
os.environ.setdefault("VIGILIAE_HOLIDAYS", "2026-10-01")

from vigiliae.price_slot import is_peak, next_offpeak, price_slot  # noqa: E402

TZ = timezone(timedelta(hours=8))


def at(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


class PriceSlotTest(unittest.TestCase):
    def test_weekday_peak_windows(self):
        # 2026-10-27 is a Tuesday.
        self.assertTrue(is_peak(at(2026, 10, 27, 9, 0)))
        self.assertTrue(is_peak(at(2026, 10, 27, 11, 59)))
        self.assertFalse(is_peak(at(2026, 10, 27, 12, 0)))
        self.assertFalse(is_peak(at(2026, 10, 27, 13, 59)))
        self.assertTrue(is_peak(at(2026, 10, 27, 14, 0)))
        self.assertTrue(is_peak(at(2026, 10, 27, 17, 59)))
        self.assertFalse(is_peak(at(2026, 10, 27, 18, 0)))

    def test_weekend_is_offpeak(self):
        # 2026-10-25 is a Sunday.
        self.assertFalse(is_peak(at(2026, 10, 25, 10, 0)))
        self.assertFalse(is_peak(at(2026, 10, 25, 15, 0)))

    def test_holiday_is_offpeak(self):
        self.assertFalse(is_peak(at(2026, 10, 1, 10, 0)))

    def test_next_offpeak_from_morning_peak(self):
        self.assertEqual(next_offpeak(at(2026, 10, 27, 10, 30)), at(2026, 10, 27, 12, 0))

    def test_next_offpeak_from_afternoon_peak(self):
        self.assertEqual(next_offpeak(at(2026, 10, 27, 15, 30)), at(2026, 10, 27, 18, 0))

    def test_next_offpeak_inside_offpeak_is_identity(self):
        dt = at(2026, 10, 27, 13, 0)
        self.assertEqual(next_offpeak(dt), dt)

    def test_price_slot_returns_ratio_semantics(self):
        peak, label, seconds = price_slot(at(2026, 10, 27, 10, 0))
        self.assertTrue(peak)
        self.assertIn("peak", label)
        self.assertGreater(seconds, 0)

        peak, label, seconds = price_slot(at(2026, 10, 27, 19, 0))
        self.assertFalse(peak)
        self.assertIn("off-peak", label)
        self.assertEqual(seconds, 14 * 60 * 60)  # until 09:00 next day


if __name__ == "__main__":
    unittest.main()
