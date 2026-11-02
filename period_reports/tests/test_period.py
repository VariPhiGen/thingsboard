"""python3 -m unittest discover -s period_reports/tests -t ."""
import unittest
from datetime import date, datetime

from infra_reports.config import REPORT_TZ
from period_reports import rollup
from period_reports.period import PeriodError, build_period, period_label, resolve_period
from period_reports.render_pdf import render_html


def dg_day(day, run_hours, energy, fuel, alarms=(), maint=(), final=True):
    start = int(datetime.fromisoformat(day).replace(tzinfo=REPORT_TZ).timestamp() * 1000)
    return {"date": day, "final": final, "start_ts": start, "end_ts": start + 86400000, "devices": [{
        "id": "dg1", "name": "DG SET1", "type": "woodward_kg1500", "category": "dg", "online": True,
        "availability_pct": 100.0, "alarms": list(alarms), "alarms_excluded": {}, "operational_events": {},
        "maintenance": list(maint), "pm": {"health_avg": 90, "health_min": 70, "worst": "WARNING", "warning_min": 15,
                                          "critical_min": 0, "top_issues": ["Battery low on standby: 24.1 V"]},
        "series": {}, "runs": 1, "run_hours": run_hours, "energy_kwh": energy, "energy_coverage": 1.0,
        "fuel": fuel, "fuel_events": [{"ts": start + 3600000, "value": "Refuel >= +10% (90% to FULL)"}],
        "run_hours_total": 100 + run_hours,
        "stats": {"battery_voltage": {"avg": 26.5, "min": 24.1, "max": 27.0, "count": 100},
                  "coolant_temp": {"avg": 70, "min": 50, "max": 88, "count": 10},
                  "oil_pressure": None, "power_kw": {"avg": 100, "min": 0, "max": 400, "count": 10}},
    }, {
        "id": "ro1", "name": "RO Plant", "type": "RO System Profile", "category": "ro", "online": True,
        "availability_pct": 50.0, "alarms": [], "alarms_excluded": {"duplicate": 2}, "operational_events": {},
        "maintenance": [], "pm": None, "series": {},
        "stats": {"tds_ppm": {"avg": 60, "min": 40, "max": 80, "count": 50}},
    }]}


class ResolvePeriod(unittest.TestCase):
    TODAY = date(2026, 11, 1)

    def test_limits(self):
        self.assertEqual(resolve_period("2026-10-01", "2026-10-31", self.TODAY), (date(2026, 10, 1), date(2026, 10, 31)))
        with self.assertRaises(PeriodError):
            resolve_period("2026-09-01", "2026-10-31", self.TODAY)          # 61 days
        with self.assertRaises(PeriodError):
            resolve_period("2026-10-31", "2026-11-02", self.TODAY)          # future
        with self.assertRaises(PeriodError):
            resolve_period("2026-10-05", "2026-10-01", self.TODAY)          # reversed
        with self.assertRaises(PeriodError):
            resolve_period("2026-10-5", "x", self.TODAY)

    def test_labels(self):
        self.assertEqual(period_label(date(2026, 10, 30), date(2026, 10, 30)), "Daily")
        self.assertEqual(period_label(date(2026, 10, 25), date(2026, 10, 31)), "Weekly")
        self.assertEqual(period_label(date(2026, 10, 1), date(2026, 10, 31)), "Monthly")
        self.assertEqual(period_label(date(2026, 2, 1), date(2026, 2, 28)), "Monthly")
        self.assertEqual(period_label(date(2026, 10, 3), date(2026, 10, 20)), "Custom")


class BuildPeriod(unittest.TestCase):
    def setUp(self):
        fuel1 = {"consumed_pct": 20.0, "refuelled_pct": 10.0, "refuel_count": 1, "lower_bound": True, "min": 70.0}
        fuel2 = {"consumed_pct": 5.0, "refuelled_pct": 0.0, "refuel_count": 0, "lower_bound": False, "min": 85.0}
        alarm = {"type": "Low Oil Pressure", "severity": "CRITICAL", "status": "CLEARED_ACK",
                 "start_ts": 1793400000000, "clear_ts": 1793400600000}
        self.rollups = [dg_day("2026-10-30", 2.0, 800.0, fuel1, [alarm]),
                        dg_day("2026-10-31", 0.5, 100.0, fuel2, final=False)]

    def test_totals(self):
        p = build_period(self.rollups)
        dg = next(d for d in p["devices"] if d["category"] == "dg")
        t = dg["totals"]
        self.assertEqual(t["run_hours"], 2.5)
        self.assertEqual(t["energy_kwh"], 900.0)
        self.assertEqual(t["fuel_consumed_pct"], 25.0)
        self.assertTrue(t["fuel_lower_bound"])
        self.assertEqual(t["refuels"], 1)
        self.assertEqual(t["battery_voltage"]["min"], 24.1)
        self.assertEqual(t["coolant_temp"]["max"], 88)
        self.assertEqual(len(p["alarms"]), 1)
        self.assertEqual(p["partial_days"], ["2026-10-31"])
        self.assertEqual(p["label"], "Custom")
        self.assertEqual([d["category"] for d in p["devices"]], ["dg", "ro"])   # category order

    def test_category_filter_and_events(self):
        p = build_period(self.rollups, ["ro"])
        self.assertEqual([d["name"] for d in p["devices"]], ["RO Plant"])
        p = build_period(self.rollups)
        kinds = sorted({e["kind"] for e in p["events"]})
        self.assertEqual(kinds, ["Fuel", "Predictive"])
        self.assertIn("≥", next(e["text"] for e in p["events"] if e["kind"] == "Fuel"))

    def test_live_maintenance_replaces_rollup_copy(self):
        stale = {"ts": 1, "value": {"type": "Inspection", "description": "old copy"}}
        self.rollups[0]["devices"][0]["maintenance"] = [stale]
        live = {"dg1": [{"ts": 1793400000000, "value": {"type": "Preventive service", "description": "Oil changed"}}]}
        p = build_period(self.rollups, maintenance_live=live)
        self.assertEqual([m["description"] for m in p["maintenance"]], ["Oil changed"])
        p = build_period(self.rollups)
        self.assertEqual([m["description"] for m in p["maintenance"]], ["old copy"])

    def test_render_html(self):
        html = render_html(build_period(self.rollups, generated_by="Tester <x>"))
        self.assertIn("Equipment Performance &amp; Maintenance Report", html)
        self.assertIn("Tester &lt;x&gt;", html)            # escaped
        self.assertIn("Low Oil Pressure", html)
        self.assertIn("&ge; 25.0 %", html)                   # fuel lower bound
        self.assertIn("2026-10-31 is still in progress", html)


class RollupHelpers(unittest.TestCase):
    def test_refuelled_and_smoothing(self):
        events = [{"value": "Refuel >= +29.4% (70.6% to FULL)"}, {"value": "Refuel +7.9% (90.1% to 98%)"},
                  {"value": "Fuel drop -6% with DG stopped"}]
        self.assertEqual(rollup._refuelled(events), (29.4 + 7.9, 2))
        self.assertEqual(rollup._median_smooth([90, 90, 100, 90, 90]), [90, 90, 90, 90, 90])

    def test_dg_fuel_uses_filtered_level(self):
        hist = {"fuel_level_pct": [{"ts": 1, "value": "80"}, {"ts": 2, "value": "70"}],
                "fuel_level": [{"ts": 1, "value": "100"}]}
        f = rollup._dg_fuel(hist, [])
        self.assertEqual((f["source"], f["consumed_pct"], f["lower_bound"]), ("fuel_level_pct", 10.0, False))

    def test_availability_counts_elapsed_buckets_only(self):
        series = {"a": [1] * 10 + [None] * 38}
        self.assertEqual(rollup._availability(series), round(1000 / 48, 1))
        self.assertEqual(rollup._availability(series, 10), 100.0)

    def test_detect_refuels_from_level(self):
        m = 60000
        level = [(i * m, 67.0) for i in range(60)] + [(60 * m + i * m, 67.0 + i * 1.1) for i in range(31)] + \
                [(91 * m + i * m, 100.0) for i in range(60)]
        total, count = rollup._detect_refuels(level)
        self.assertEqual(count, 1)
        self.assertGreater(total, 25)
        slow = [(i * m, 90.0 - i * 0.2) for i in range(120)]           # running: only falls
        self.assertEqual(rollup._detect_refuels(slow), (0.0, 0))
        f = rollup._dg_fuel({"fuel_level": [{"ts": t, "value": v} for t, v in level]}, [])
        self.assertEqual((f["refuel_source"], f["refuel_count"]), ("level", 1))
        self.assertGreater(f["consumed_pct"], -0.01)

    def test_clean_samples_drops_offline_lt_meter_readings(self):
        s = [(1, 0.0), (2, 412.0), (3, 24.6)]
        self.assertEqual(rollup.clean_samples("lt", "UPS_Room_1_voltage", s), [(2, 412.0)])
        self.assertEqual(rollup.clean_samples("lt", "UPS_Room_1_frequency", [(1, 21.3), (2, 50.0), (3, 0)]), [(2, 50.0)])
        self.assertEqual(rollup.clean_samples("lt", "UPS_Room_1_current", s), s)     # 0 A is a real reading
        self.assertEqual(rollup.clean_samples("dg", "voltage", s), s)


if __name__ == "__main__":
    unittest.main()
