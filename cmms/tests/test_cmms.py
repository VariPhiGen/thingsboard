"""python3 -m unittest discover -s cmms/tests -t ."""
import copy
import json
import os
import unittest
from datetime import date, datetime

from cmms import model as m
from cmms import scheduler as sch

SEED = json.load(open(os.path.join(os.path.dirname(__file__), "..", "settings_seed.json")))
CFG = m.Settings(SEED)
NOW = datetime(2026, 11, 2, 9, 0, tzinfo=CFG.tz)
TODAY = date(2026, 11, 2)
MS = int(NOW.timestamp() * 1000)
DAY = 86400000


def cfg(**changes):
    raw = copy.deepcopy(SEED)
    raw.update(changes)
    return m.Settings(raw)


class SettingsValidation(unittest.TestCase):
    def test_missing_or_incomplete_settings_are_rejected(self):
        with self.assertRaises(m.SettingsError):
            m.Settings(None)
        raw = copy.deepcopy(SEED)
        del raw["priorities"]
        with self.assertRaisesRegex(m.SettingsError, "priorities"):
            m.Settings(raw)
        with self.assertRaisesRegex(m.SettingsError, "P9"):
            CFG.response_days("P9")

    def test_values_come_from_settings(self):
        self.assertEqual(CFG.response_days("P2"), 3)
        self.assertEqual(cfg(priorities=[{"code": "P2", "label": "Urgent", "response_days": 2}]).response_days("P2"), 2)
        self.assertEqual(CFG.meter_window(250), 25.0)
        self.assertEqual(cfg(meter_due_window={"pct_of_interval": 5, "min_units": 20}).meter_window(250), 20.0)
        self.assertTrue(CFG.valid_meter(166.2)); self.assertFalse(CFG.valid_meter(32767))

    def test_condition_based_alarm_filter(self):
        self.assertTrue(CFG.cbm_alarm({"type": "Fire Cylinder 9 Low Pressure", "severity": "CRITICAL"}))
        self.assertTrue(CFG.cbm_alarm({"type": "Predictive Maintenance - Critical", "severity": "CRITICAL"}))
        self.assertFalse(CFG.cbm_alarm({"type": "Fire Cylinder 9 Low Pressure", "severity": "MAJOR"}))
        self.assertFalse(CFG.cbm_alarm({"type": "Transformer 1 Overcurrent", "severity": "CRITICAL"}))
        off = cfg(condition_based=dict(SEED["condition_based"], enabled=False))
        self.assertFalse(off.cbm_alarm({"type": "Fire Cylinder 9 Low Pressure", "severity": "CRITICAL"}))


class Lifecycle(unittest.TestCase):
    def test_allowed_and_blocked_transitions(self):
        m.check_transition(m.SCHEDULED, m.IN_PROGRESS)
        m.check_transition(m.IN_PROGRESS, m.COMPLETED)
        m.check_transition(m.COMPLETED, m.IN_PROGRESS)
        for cur, tgt in [(m.CLOSED, m.IN_PROGRESS), (m.CANCELLED, m.SCHEDULED), (m.ON_HOLD, m.COMPLETED), (m.SCHEDULED, m.CLOSED)]:
            with self.assertRaises(m.TransitionError):
                m.check_transition(cur, tgt)

    def test_segregation_of_duties_follows_settings(self):
        wo = {"detail": {"completed_by": {"user": "tech@x"}}}
        with self.assertRaises(m.TransitionError):
            m.check_transition(m.COMPLETED, m.CLOSED, wo, "tech@x", CFG)
        m.check_transition(m.COMPLETED, m.CLOSED, wo, "supervisor@x", CFG)
        m.check_transition(m.COMPLETED, m.CLOSED, wo, "tech@x", cfg(verification={"different_user": False}))


class DueLogic(unittest.TestCase):
    def test_time_based_states(self):
        st = lambda d, s=m.SCHEDULED, c=CFG: m.due_state({"status": s, "due_date": d}, None, TODAY, c)
        self.assertEqual(st("2026-11-01"), "overdue")
        self.assertEqual(st("2026-11-09"), "due")
        self.assertEqual(st("2026-11-10"), "upcoming")
        self.assertEqual(st("2026-11-10", c=cfg(due_soon_days=10)), "due")
        self.assertEqual(st("2026-10-01", m.COMPLETED), "done")
        self.assertEqual(st("2026-10-01", m.CANCELLED), "closed")

    def test_meter_based_states_use_live_reading(self):
        wo = {"status": m.SCHEDULED, "due_rh": 250, "interval_rh": 250}
        self.assertEqual(m.due_state(wo, 200, TODAY, CFG), "upcoming")
        self.assertEqual(m.due_state(wo, 230, TODAY, CFG), "due")
        self.assertEqual(m.due_state(wo, 251, TODAY, CFG), "overdue")
        self.assertEqual(m.due_state(wo, None, TODAY, CFG), "unknown")     # no reading: never guess

    def test_plan_generation_and_next_due(self):
        p = {"strategy": "time", "next_due_date": "2026-11-09", "lead_days": 7, "interval_days": 30, "active": True}
        self.assertTrue(m.plan_generation_due(p, None, TODAY, CFG))
        self.assertFalse(m.plan_generation_due(dict(p, next_due_date="2026-11-10"), None, TODAY, CFG))
        self.assertFalse(m.plan_generation_due(dict(p, active=False), None, TODAY, CFG))
        self.assertFalse(m.plan_generation_due(dict(p, lead_days=None), None, TODAY, CFG))   # not configured: nothing raised
        self.assertEqual(m.next_due_after_completion(p, "2026-11-05"), {"next_due_date": "2026-12-05"})
        mp = {"strategy": "meter", "next_due_rh": 250, "interval_rh": 250}
        self.assertTrue(m.plan_generation_due(mp, 240, TODAY, CFG))
        self.assertFalse(m.plan_generation_due(mp, 200, TODAY, CFG))
        self.assertEqual(m.next_due_after_completion(mp, "2026-11-05", 252.4), {"next_due_rh": 502.4})
        with self.assertRaises(ValueError):
            m.next_due_after_completion(mp, "2026-11-05", None)

    def test_cancel_skips_the_occurrence(self):
        p = {"strategy": "time", "next_due_date": "2026-11-09", "interval_days": 30}
        self.assertEqual(m.next_due_after_skip(p, {"due_date": "2026-11-09"}), {"next_due_date": "2026-12-09"})
        mp = {"strategy": "meter", "next_due_rh": 250, "interval_rh": 250}
        self.assertEqual(m.next_due_after_skip(mp, {"due_rh": 250}), {"next_due_rh": 500.0})


class Kpis(unittest.TestCase):
    def test_pm_compliance_mttr_backlog(self):
        wos = [
            {"type": "Preventive", "status": m.CLOSED, "due_date": "2026-10-10", "created_ts": MS - 30 * DAY, "completed_ts": MS - 24 * DAY},
            {"type": "Preventive", "status": m.CLOSED, "due_date": "2026-10-05", "created_ts": MS - 40 * DAY, "completed_ts": MS - 25 * DAY},
            {"type": "Preventive", "status": m.SCHEDULED, "due_date": "2026-10-20"},
            {"type": "Corrective", "status": m.CLOSED, "due_date": "2026-10-15", "created_ts": MS - 10 * DAY, "completed_ts": MS - 10 * DAY + 6 * 3600000,
             "detail": {"labour_hours": 4, "cost_total": 1200}},
            {"type": "Preventive", "status": m.CANCELLED, "due_date": "2026-10-12"},
        ]
        k = m.kpis(wos, date(2026, 10, 1), date(2026, 10, 31), TODAY, CFG)
        self.assertEqual((k["pm_due"], k["pm_on_time"], k["pm_compliance_pct"]), (3, 1, 33.3))
        self.assertEqual(k["mttr_h"], 6.0)
        self.assertEqual((k["backlog"], k["overdue"]), (1, 1))
        self.assertEqual(k["planned_pct"], 66.7)
        self.assertEqual((k["labour_hours"], k["cost_total"]), (4.0, 1200.0))

    def test_work_recorded_afterwards(self):
        # recorded as work done: no due date (not in PM compliance); MTTR only from the reported time
        ts = lambda d, h: int(datetime(2026, 10, d, h, tzinfo=CFG.tz).timestamp() * 1000)
        wos = [
            {"type": "Preventive", "status": m.COMPLETED, "source": "direct", "due_date": "", "created_ts": ts(20, 12), "completed_ts": ts(20, 10)},
            {"type": "Corrective", "status": m.COMPLETED, "source": "direct", "due_date": "", "created_ts": ts(21, 12), "completed_ts": ts(21, 10)},
            {"type": "Corrective", "status": m.CLOSED, "source": "direct", "due_date": "", "created_ts": ts(22, 12), "completed_ts": ts(22, 10),
             "detail": {"reported_ts": ts(22, 6)}},
        ]
        k = m.kpis(wos, date(2026, 10, 1), date(2026, 10, 31), TODAY, CFG)
        self.assertEqual(k["pm_due"], 0)
        self.assertIsNone(k["pm_compliance_pct"])
        self.assertEqual(k["mttr_h"], 4.0)

    def test_no_data_gives_none_not_zero(self):
        k = m.kpis([], date(2026, 10, 1), date(2026, 10, 31), TODAY, CFG)
        self.assertIsNone(k["pm_compliance_pct"]); self.assertIsNone(k["mttr_h"]); self.assertIsNone(k["planned_pct"])


class FakeStore:
    def __init__(self):
        self.eq = [{"id": "dg1", "name": "DG SET1", "type": "woodward_kg1500"}, {"id": "fire", "name": "Fire Suppression", "type": "LT Panel Fire Profile"}]
        self.plans_ = [{"id": "p1", "number": "PL-0001", "title": "250 h service", "type": "Preventive", "priority": "P2", "strategy": "meter",
                        "interval_rh": 250, "next_due_rh": 250, "active": True, "equipment_id": "dg1", "equipment_name": "DG SET1",
                        "detail": {"checklist": ["Change oil"], "assignee": "Ravi"}},
                       {"id": "p2", "number": "PL-0002", "title": "Cylinder inspection", "type": "Inspection", "priority": "P3", "strategy": "time",
                        "interval_days": 90, "next_due_date": "2026-12-30", "lead_days": 7, "active": True, "equipment_id": "fire",
                        "equipment_name": "Fire Suppression", "detail": {}}]
        self.wos, self.saved, self.lib_attrs = [], [], {}
        self.alarms = [{"id": {"id": "a1"}, "type": "Fire Cylinder 9 Low Pressure", "severity": "CRITICAL", "originator": {"entityType": "DEVICE", "id": "fire"},
                        "details": {"data": "Cylinder 9 pressure LOW"}, "startTs": MS - DAY},
                       {"id": {"id": "a2"}, "type": "Transformer 1 Overcurrent", "severity": "CRITICAL", "originator": {"entityType": "DEVICE", "id": "fire"}, "details": {}},
                       {"id": {"id": "a3"}, "type": "Fire Cylinder 3 Low Pressure", "severity": "MAJOR", "originator": {"entityType": "DEVICE", "id": "fire"}, "details": {}}]
        self.meter = {"dg1": 245.0}
        self.years = []

    def equipment(self, settings): return [e for e in self.eq if e["type"] in settings.raw["equipment_profiles"]]
    def meter_reading(self, i, settings): return self.meter.get(i)
    def plans(self): return self.plans_
    def work_orders(self): return list(self.wos)
    def active_alarms(self): return self.alarms
    def library(self): return "lib"
    def documents(self, eq): return [{"title": "Fire NOC", "category": "Certificate", "owner": "Fire Suppression", "expiry": "2026-11-20"}]
    def attrs(self, t, i, keys): return {k: self.lib_attrs.get(k) for k in keys}

    def save_attrs(self, t, i, v):
        self.saved.append((i, v))
        if i == "lib":
            self.lib_attrs.update(v)
        for w in self.wos:
            if w["id"] == i:
                w.update({k[3:]: val for k, val in v.items() if k.startswith("wo_")})

    def create_work_order(self, fields, detail, year):
        self.years.append(year)
        n = f"WO-{year}-{len(self.wos) + 1:05d}"
        self.wos.append(dict(fields, id="w" + n, number=n, detail=detail, rev=1))
        return n, "w" + n


class FakeNotifier:
    def __init__(self): self.msgs = []
    def both(self, subject, lines): self.msgs.append((subject, lines)); return True


class Scheduler(unittest.TestCase):
    def test_pass_creates_pm_and_cbm_work_orders_once_and_digest_once(self):
        st, nt = FakeStore(), FakeNotifier()
        s1 = sch.run(st, nt, CFG, NOW)
        self.assertEqual(s1["created_pm"], ["WO-2026-00001"])        # meter 245, due 250, window 25
        self.assertEqual(s1["created_cbm"], ["WO-2026-00002"])       # only the CRITICAL fire-cylinder alarm matches
        pm, cbm = st.wos
        self.assertEqual((pm["type"], pm["priority"], pm["due_rh"], pm["assignee"]), ("Preventive", "P2", 250, "Ravi"))
        self.assertEqual((cbm["priority"], cbm["type"], cbm["alarm_id"], cbm["due_date"]), ("P1", "Condition-based", "a1", "2026-11-03"))
        self.assertTrue(s1["digest"])
        digest = [l for s, l in nt.msgs if s.startswith("Maintenance digest")][0]
        self.assertTrue(any("Fire NOC" in x and "expires 20 Nov 2026" in x for x in digest))
        nt2 = FakeNotifier()
        s2 = sch.run(st, nt2, CFG, NOW)
        self.assertEqual((s2["created_pm"], s2["created_cbm"], s2["digest"]), ([], [], False))
        self.assertEqual(nt2.msgs, [])

    def test_settings_drive_the_scheduler(self):
        st, nt = FakeStore(), FakeNotifier()
        c = cfg(condition_based=dict(SEED["condition_based"], priority="P2", severities=["CRITICAL", "MAJOR"]),
                alerts=dict(SEED["alerts"], digest_hour=10), equipment_profiles=["LT Panel Fire Profile"])
        s = sch.run(st, nt, c, NOW)
        self.assertEqual(s["created_pm"], [])                         # DG profile not configured -> its plan is ignored
        self.assertEqual(len(s["created_cbm"]), 2)                    # MAJOR alarm now matches too
        self.assertEqual({w["priority"] for w in st.wos}, {"P2"})
        self.assertFalse(s["digest"])                                 # 09:00 < configured 10:00

    def test_overdue_alerted_once_for_configured_priorities(self):
        st, nt = FakeStore(), FakeNotifier()
        st.alarms, st.plans_ = [], []
        st.lib_attrs["cmms_last_digest"] = TODAY.isoformat()
        st.wos = [{"id": "w1", "number": "WO-2026-00009", "title": "Fix leak", "priority": "P1", "status": m.IN_PROGRESS,
                   "due_date": "2026-11-01", "equipment_id": "fire", "equipment_name": "Fire Suppression", "overdue_alerted": False},
                  {"id": "w2", "number": "WO-2026-00010", "title": "Paint", "priority": "P4", "status": m.SCHEDULED,
                   "due_date": "2026-10-01", "equipment_id": "fire", "equipment_name": "Fire Suppression", "overdue_alerted": False}]
        self.assertEqual(sch.run(st, nt, CFG, NOW)["overdue_alerts"], ["WO-2026-00009"])
        self.assertEqual(sch.run(st, FakeNotifier(), CFG, NOW)["overdue_alerts"], [])

    def test_no_pm_work_order_while_previous_one_is_active(self):
        st = FakeStore(); st.alarms = []
        st.wos = [{"id": "w1", "number": "WO-2026-00001", "plan_id": "p1", "status": m.COMPLETED}]
        self.assertEqual(sch.run(st, FakeNotifier(), CFG, NOW)["created_pm"], [])

    def test_meter_plan_without_reading_is_not_generated(self):
        st = FakeStore(); st.alarms, st.meter = [], {}
        self.assertEqual(sch.run(st, FakeNotifier(), CFG, NOW)["created_pm"], [])

    def test_dry_run_changes_nothing(self):
        st, nt = FakeStore(), FakeNotifier()
        s = sch.run(st, nt, CFG, NOW, dry_run=True)
        self.assertEqual((st.wos, st.saved, nt.msgs), ([], [], []))
        self.assertTrue(s["digest"])


if __name__ == "__main__":
    unittest.main()
