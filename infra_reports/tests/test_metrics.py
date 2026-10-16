import unittest
from datetime import datetime, timezone

from infra_reports.config import REPORT_TZ

from infra_reports.metrics import (
    BUCKET_MS, bucket_series, count_runs, integrate_energy_kwh, parse_value, report_window, resolve_report_date, sample_stats,
    valid_samples,
)

HOUR = 3_600_000


class ParseValueTest(unittest.TestCase):
    def test_numbers_and_booleans(self):
        self.assertEqual(parse_value("12.5"), 12.5)
        self.assertEqual(parse_value(7), 7.0)
        self.assertEqual(parse_value("true"), 1.0)
        self.assertEqual(parse_value("FALSE"), 0.0)
        self.assertEqual(parse_value(True), 1.0)

    def test_invalid_values_are_dropped(self):
        for value in ("error", "N/A", "", None, "--", "32767", 32767, "65535.0", "nan"):
            self.assertIsNone(parse_value(value), value)


class SamplesTest(unittest.TestCase):
    def test_valid_samples_sorted_and_filtered(self):
        points = [{"ts": 3, "value": "3"}, {"ts": 1, "value": "error"}, {"ts": 2, "value": "32767"}, {"ts": 0, "value": "1"}]
        self.assertEqual(valid_samples(points), [(0, 1.0), (3, 3.0)])

    def test_bucket_series_averages_and_gaps(self):
        start = 0
        samples = [(0, 10.0), (BUCKET_MS - 1, 20.0), (2 * BUCKET_MS, 5.0), (4 * BUCKET_MS, 99.0)]
        series = bucket_series(samples, start, start + 4 * BUCKET_MS)
        self.assertEqual(series, [15.0, None, 5.0, None])  # sample at the end boundary is outside the window

    def test_sample_stats(self):
        stats = sample_stats([(0, 5.0), (1, 1.0), (2, 9.0)])
        self.assertEqual(stats, {"avg": 5.0, "min": 1.0, "max": 9.0, "delta": 4.0, "count": 3})
        self.assertEqual(sample_stats([]), {})


class EnergyTest(unittest.TestCase):
    def test_constant_load_for_one_hour(self):
        samples = [(t * 10_000, 100.0) for t in range(361)]  # 100 kW every 10 s for 1 h
        energy, coverage = integrate_energy_kwh(samples, 0, HOUR + 1)  # window is [start, end)
        self.assertAlmostEqual(energy, 100.0, places=6)
        self.assertAlmostEqual(coverage, 1.0, places=3)

    def test_gaps_are_not_integrated(self):
        samples = [(0, 100.0), (60_000, 100.0), (60_000 + 30 * 60_000, 100.0)]  # 1 min, then a 30 min gap
        energy, coverage = integrate_energy_kwh(samples, 0, HOUR)
        self.assertAlmostEqual(energy, 100.0 / 60)
        self.assertAlmostEqual(coverage, 1 / 60)

    def test_trapezoid_and_negative_samples(self):
        energy, _ = integrate_energy_kwh([(0, 0.0), (60_000, 60.0), (90_000, -5.0)], 0, HOUR)
        self.assertAlmostEqual(energy, 0.5)  # (0+60)/2 kW for 1 min; negative sample ignored

    def test_count_runs(self):
        minute = 60_000
        kw = [0, 500, 520, 0, 3, 0, 450, 460, 0]
        samples = [(i * minute, v) for i, v in enumerate(kw)]
        self.assertEqual(count_runs(samples, 0, HOUR), 2)
        self.assertEqual(count_runs(samples, 2 * minute, HOUR), 2)    # a run already going at the start counts
        self.assertEqual(count_runs([(0, 500.0), (30 * minute, 500.0)], 0, HOUR), 1)  # a data gap does not split a run
        self.assertEqual(count_runs([], 0, HOUR), 0)

    def test_count_runs_without_load_and_read_errors(self):
        s = 10_000
        power = [(i * s, 0.0) for i in range(60)]
        # Engine idles (no load) from 10 to 40; one failed RPM read at 20 (power 0, no RPM sample)
        rpm = [(i * s, 1500.0 if 10 <= i < 40 else 0.0) for i in range(60) if i != 20]
        self.assertEqual(count_runs(power, 0, HOUR, rpm), 1)
        # Sensor-offline RPM code while stopped is not a run
        self.assertEqual(count_runs(power, 0, HOUR, [(i * s, 32767.0) for i in range(60)]), 0)
        # Two runs separated by a real stop longer than 2 minutes
        rpm2 = [(i * s, 1500.0 if i < 10 or i >= 40 else 0.0) for i in range(60)]
        self.assertEqual(count_runs(power, 0, HOUR, rpm2), 2)


class ReportWindowTest(unittest.TestCase):
    def test_past_day_is_the_ist_calendar_day(self):
        start, end = report_window("2026-10-03")
        self.assertEqual(datetime.fromtimestamp(start / 1000, timezone.utc).isoformat(), "2026-10-02T18:30:00+00:00")
        self.assertEqual(end - start, 24 * HOUR)

    def test_rolling_window(self):
        self.assertEqual(report_window(None, now_ms=100 * HOUR), (76 * HOUR, 100 * HOUR))

    def test_yesterday_is_resolved_in_ist(self):
        # 15 Oct 01:00 IST is still 14 Oct in UTC; "yesterday" must be 14 Oct (IST), not 13 Oct
        now = datetime(2026, 10, 15, 1, 0, tzinfo=REPORT_TZ)
        self.assertEqual(resolve_report_date("yesterday", now), "2026-10-14")
        self.assertEqual(resolve_report_date("2026-10-03"), "2026-10-03")
        self.assertIsNone(resolve_report_date(None))

    def test_bad_date(self):
        with self.assertRaises(ValueError):
            report_window("03-10-2026")


if __name__ == "__main__":
    unittest.main()
