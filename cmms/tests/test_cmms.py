"""python3 -m unittest discover -s cmms/tests -t ."""
import unittest
from datetime import date, datetime

from cmms import model as m
from cmms import scheduler as sch

NOW = datetime(2026, 11, 2, 9, 0, tzinfo=m.IST)
TODAY = date(2026, 11, 2)
MS = int(NOW.timestamp() * 1000)
DAY = 86400000


class Lifecycle(unittest.TestCase):
    def test_allowed_and_blocked_transitions(self):
        m.check_transition(m.SCHEDULED, m.IN_PROGRESS)
        m.check_transition(m.IN_PROGRESS, m.COMPLETED)
        m.check_transition(m.COMPLETED, m.IN_PROGRESS)        # rejected by verifier
        for cur, tgt in [(m.CLOSED, m.IN_PROGRESS), (m.CANCELLED, m.SCHEDULED), (m.ON_HOLD, m.COMPLETED), (m.SCHEDULED, m.CLOSED)]:
            with self.assertRaises(m.TransitionError):
                m.check_transition(cur, tgt)

    def test_completer_cannot_verify_own_work(self):
        wo = {"detail": {"completed_by": {"user": "tech@x"}}}
        with self.assertRaises(m.TransitionError):
            m.check_transition(m.COMPLETED, m.CLOSED, wo, "tech@x")
        m.check_transition(m.COMPLETED, m.CLOSED, wo, "supervisor@x")


class DueLogic(unittest.TestCase):
    def test_time_based_states(self):
        self.assertEqual(m.due_state({"status": m.SCHEDULED, "due_date": "2026-11-01"}, today=TODAY), "overdue")
        self.assertEqual(m.due_state({"status": m.SCHEDULED, "due_date": "2026-11-09"}, today=TODAY), "due")
        self.assertEqual(m.due_state({"status": m.SCHEDULED, "due_date": "2026-11-10"}, today=TODAY), "upcoming")
        self.assertEqual(m.due_state({"status": m.COMPLETED, "due_date": "2026-10-01"}, today=TODAY), "done")
        self.assertEqual(m.due_state({"status": m.CANCELLED, "due_date": "2026-10-01"}, today=TODAY), "closed")

    def test_meter_based_states_use_live_run_hours(self):
        wo = {"status": m.SCHEDULED, "due_rh": 250, "interval_rh": 250}
        self.assertEqual(m.due_state(wo, 200, TODAY), "upcoming")   # 50 h left, window 25 h
        self.assertEqual(m.due_state(wo, 230, TODAY), "due")
        self.assertEqual(m.due_state(wo, 251, TODAY), "overdue")
        self.assertEqual(m.due_state(wo, None, TODAY), "unknown")    # no reading: never guess

    def test_plan_generation_and_next_due(self):
        p = {"strategy": "time", "next_due_date": "2026-11-09", "lead_days": 7, "interval_days": 30, "active": True}
        self.assertTrue(m.plan_generation_due(p, today=TODAY))
        self.assertFalse(m.plan_generation_due(dict(p, next_due_date="2026-11-10"), today=TODAY))
        self.assertFalse(m.plan_generation_due(dict(p, active=False), today=TODAY))
        self.assertEqual(m.next_due_after_completion(p, "2026-11-05"), {"next_due_date": "2026-12-05"})
        mp = {"strategy": "meter", "next_due_rh": 250, "interval_rh": 250}
        self.assertTrue(m.plan_generation_due(mp, 240, TODAY))
        self.assertFalse(m.plan_generation_due(mp, 200, TODAY))
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
            {"type": "Preventive", "status": m.CLOSED, "due_date": "2026-10-10", "created_ts": MS - 30 * DAY, "completed_ts": MS - 24 * DAY},  # on time
            {"type": "Preventive", "status": m.CLOSED, "due_date": "2026-10-05", "created_ts": MS - 40 * DAY, "completed_ts": MS - 25 * DAY},  # late
            {"type": "Preventive", "status": m.SCHEDULED, "due_date": "2026-10-20"},                                                           # missed, overdue
            {"type": "Corrective", "status": m.CLOSED, "due_date": "2026-10-15", "created_ts": MS - 10 * DAY, "completed_ts": MS - 10 * DAY + 6 * 3600000,
             "detail": {"labour_hours": 4, "cost_total": 1200}},
            {"type": "Preventive", "status": m.CANCELLED, "due_date": "2026-10-12"},
        ]
        k = m.kpis(wos, date(2026, 10, 1), date(2026, 10, 31), TODAY)
        self.assertEqual((k["pm_due"], k["pm_on_time"], k["pm_compliance_pct"]), (3, 1, 33.3))
        self.assertEqual(k["mttr_h"], 6.0)
        self.assertEqual((k["backlog"], k["overdue"]), (1, 1))
        self.assertEqual(k["planned_pct"], 66.7)
        self.assertEqual((k["labour_hours"], k["cost_total"]), (4.0, 1200.0))

    def test_no_data_gives_none_not_zero(self):
        k = m.kpis([], date(2026, 10, 1), date(2026, 10, 31), TODAY)
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
        self.wos = []
        self.saved = []
        self.alarms = [{"id": {"id": "a1"}, "type": "Fire Cylinder 9 Low Pressure", "originator": {"entityType": "DEVICE", "id": "fire"},
                        "details": {"data": "Cylinder 9 pressure LOW"}, "startTs": MS - DAY},
                       {"id": {"id": "a2"}, "type": "Transformer 1 Overcurrent", "originator": {"entityType": "DEVICE", "id": "fire"}, "details": {}}]
        self.lib_attrs = {}
        self.rh = {"dg1": 245.0}

    def equipment(self): return self.eq
    def run_hours(self, i): return self.rh.get(i)
    def plans(self): return self.plans_
    def work_orders(self): return list(self.wos)
    def active_alarms(self, sev): return self.alarms
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

    def create_work_order(self, fields, detail):
        n = f"WO-2026-{len(self.wos) + 1:05d}"
        self.wos.append(dict(fields, id="w" + n, number=n, detail=detail, rev=1))
        return n, "w" + n


class FakeNotifier:
    def __init__(self): self.msgs = []
    def both(self, subject, lines): self.msgs.append((subject, lines)); return True


class Scheduler(unittest.TestCase):
    def test_pass_creates_pm_and_cbm_work_orders_once_and_digest_once(self):
        st, nt = FakeStore(), FakeNotifier()
        s1 = sch.run(st, nt, NOW)
        self.assertEqual(s1["created_pm"], ["WO-2026-00001"])            # DG at 245 run-h, due at 250 (window 25 h)
        self.assertEqual(s1["created_cbm"], ["WO-2026-00002"])           # fire cylinder alarm; overcurrent ignored
        pm, cbm = st.wos
        self.assertEqual((pm["type"], pm["due_rh"], pm["assignee"], pm["detail"]["checklist"]), ("Preventive", 250, "Ravi", ["Change oil"]))
        self.assertEqual((cbm["priority"], cbm["type"], cbm["alarm_id"]), ("P1", "Condition-based", "a1"))
        self.assertTrue(s1["digest"])
        subjects = [s for s, _ in nt.msgs]
        self.assertTrue(any(s.startswith("New P1 work order WO-2026-00002") for s in subjects))
        digest = [l for s, l in nt.msgs if s.startswith("Maintenance digest")][0]
        self.assertTrue(any("Fire NOC" in x and "expires 20 Nov 2026" in x for x in digest))
        # second pass: nothing new
        nt2 = FakeNotifier()
        s2 = sch.run(st, nt2, NOW)
        self.assertEqual((s2["created_pm"], s2["created_cbm"], s2["digest"]), ([], [], False))
        self.assertEqual(nt2.msgs, [])

    def test_overdue_p1_alerted_once(self):
        st, nt = FakeStore(), FakeNotifier()
        st.alarms = []
        st.plans_ = []
        st.lib_attrs["cmms_last_digest"] = TODAY.isoformat()
        st.wos = [{"id": "w1", "number": "WO-2026-00009", "title": "Fix leak", "priority": "P1", "status": m.IN_PROGRESS,
                   "due_date": "2026-11-01", "equipment_id": "fire", "equipment_name": "Fire Suppression", "overdue_alerted": False}]
        self.assertEqual(sch.run(st, nt, NOW)["overdue_alerts"], ["WO-2026-00009"])
        self.assertEqual(sch.run(st, FakeNotifier(), NOW)["overdue_alerts"], [])

    def test_no_pm_work_order_while_previous_one_is_active(self):
        st, nt = FakeStore(), FakeNotifier()
        st.alarms = []
        st.wos = [{"id": "w1", "number": "WO-2026-00001", "plan_id": "p1", "status": m.COMPLETED}]
        self.assertEqual(sch.run(st, nt, NOW)["created_pm"], [])

    def test_meter_plan_without_reading_is_not_generated(self):
        st, nt = FakeStore(), FakeNotifier()
        st.alarms, st.rh = [], {}
        self.assertEqual(sch.run(st, nt, NOW)["created_pm"], [])

    def test_dry_run_changes_nothing(self):
        st, nt = FakeStore(), FakeNotifier()
        s = sch.run(st, nt, NOW, dry_run=True)
        self.assertEqual((st.wos, st.saved, nt.msgs), ([], [], []))
        self.assertTrue(s["digest"])


if __name__ == "__main__":
    unittest.main()
