"""CMMS scheduler: run every 10 minutes (systemd timer cmms-scheduler.timer).

  python3 -m cmms.scheduler            # one pass
  python3 -m cmms.scheduler --dry-run  # log what would be created/sent, change nothing

Each pass is idempotent:
1. Preventive work orders: every active plan whose next occurrence is inside its lead time gets one work order
   (none is created while an earlier work order of the plan is still active).
2. Condition-based work orders: every active CRITICAL alarm "Predictive Maintenance - Critical" or
   "Fire Cylinder N Low Pressure" on monitored equipment gets one P1 corrective work order (keyed by the alarm id).
3. Overdue P1/P2 work orders are alerted once (Telegram + email).
4. Daily digest at 08:00 IST (once per day): overdue, due in 7 days, awaiting verification, documents expiring in 30 days.
"""
import argparse
import logging
import re
import sys
import time
from datetime import datetime, timedelta

from infra_reports.config import load_settings
from infra_reports.tb_client import ThingsBoardClient

from . import model as m
from .notify import Notifier
from .store import DG_TYPE, Store

log = logging.getLogger("cmms.scheduler")
ALARM_TYPES = re.compile(r"^(Predictive Maintenance - Critical|Fire Cylinder \d+ Low Pressure)$")
DIGEST_HOUR = 8


def history(action, note="", frm=None, to=None):
    return {"ts": int(time.time() * 1000), "user": "system", "name": "CMMS scheduler", "action": action,
            "from": frm, "to": to, "note": note}


def wo_from_plan(plan, created_ts):
    d = plan.get("detail") or {}
    meter = plan.get("strategy") == "meter"
    fields = {"title": plan["title"], "type": plan.get("type") or "Preventive", "priority": plan.get("priority") or "P3",
              "status": m.SCHEDULED, "source": "plan", "plan_id": plan["id"], "alarm_id": "",
              "equipment_id": plan["equipment_id"], "equipment_name": plan["equipment_name"],
              "due_date": "" if meter else plan.get("next_due_date") or "",
              "due_rh": plan.get("next_due_rh") if meter else None,
              "interval_rh": plan.get("interval_rh") if meter else None,
              "assignee": d.get("assignee") or "", "created_ts": created_ts, "completed_ts": None, "closed_ts": None}
    detail = {"description": d.get("notes") or "", "checklist": d.get("checklist") or [], "docs": d.get("docs") or [],
              "est_hours": d.get("est_hours"), "plan_number": plan.get("number"),
              "history": [history("created", f"Generated from plan {plan.get('number')}", to=m.SCHEDULED)]}
    return fields, detail


def wo_from_alarm(alarm, equipment_name, created_ts):
    det = alarm.get("details") or {}
    text = det.get("message") or det.get("data") or det.get("description") or alarm["type"]
    action = det.get("recommendation") or det.get("recommended_action") or ""
    fields = {"title": alarm["type"], "type": "Condition-based", "priority": "P1", "status": m.SCHEDULED,
              "source": "alarm", "plan_id": "", "alarm_id": alarm["id"]["id"],
              "equipment_id": alarm["originator"]["id"], "equipment_name": equipment_name,
              "due_date": m.due_date_for_priority("P1"), "due_rh": None, "interval_rh": None, "assignee": "",
              "created_ts": created_ts, "completed_ts": None, "closed_ts": None}
    detail = {"description": (text + (" Recommended: " + action if action else "")).strip(), "checklist": [], "docs": [],
              "alarm_type": alarm["type"], "alarm_start_ts": alarm.get("startTs"),
              "history": [history("created", f"Raised by alarm '{alarm['type']}'", to=m.SCHEDULED)]}
    return fields, detail


def fmt_due(w):
    if w.get("due_rh") not in (None, ""):
        return f"at {w['due_rh']} run-h"
    d = m.parse_date(w.get("due_date"))
    return d.strftime("%d %b %Y") if d else "-"


def run(store, notifier, now=None, dry_run=False):
    now = now or datetime.now(m.IST)
    today = m.today_ist(now)
    now_ms = int(now.timestamp() * 1000)
    equipment = {e["id"]: e for e in store.equipment()}
    rh = {i: store.run_hours(i) for i, e in equipment.items() if e["type"] == DG_TYPE}
    plans, wos = store.plans(), store.work_orders()
    summary = {"created_pm": [], "created_cbm": [], "overdue_alerts": [], "digest": False}

    # 1. preventive work orders from plans
    for p in plans:
        if p.get("equipment_id") not in equipment or not m.plan_generation_due(p, rh.get(p["equipment_id"]), today):
            continue
        if any(w.get("plan_id") == p["id"] and w.get("status") in m.ACTIVE for w in wos):
            continue
        fields, detail = wo_from_plan(p, now_ms)
        if dry_run:
            log.info("[dry-run] would create PM work order for plan %s %s", p.get("number"), p.get("title"))
        else:
            number, aid = store.create_work_order(fields, detail)
            wos.append(dict(fields, id=aid, number=number, detail=detail, rev=1))
            summary["created_pm"].append(number)

    # 2. condition-based work orders from critical alarms
    for a in store.active_alarms("CRITICAL"):
        if a.get("originator", {}).get("entityType") != "DEVICE" or a["originator"]["id"] not in equipment:
            continue
        if not ALARM_TYPES.match(a.get("type") or ""):
            continue
        if any(w.get("alarm_id") == a["id"]["id"] for w in wos):
            continue
        fields, detail = wo_from_alarm(a, equipment[a["originator"]["id"]]["name"], now_ms)
        if dry_run:
            log.info("[dry-run] would create P1 work order for alarm %s on %s", a["type"], fields["equipment_name"])
            continue
        number, aid = store.create_work_order(fields, detail)
        wos.append(dict(fields, id=aid, number=number, detail=detail, rev=1))
        summary["created_cbm"].append(number)
        notifier.both(f"New P1 work order {number}: {fields['title']}",
                      [f"Equipment: {fields['equipment_name']}", detail["description"], f"Due: {fmt_due(fields)}",
                       "Open Reports & Maintenance > Maintenance Planner to assign and start the work."])

    # 3. overdue P1/P2 alerts (once per work order)
    for w in wos:
        if w.get("status") not in m.OPEN or w.get("priority") not in ("P1", "P2") or w.get("overdue_alerted"):
            continue
        if m.due_state(w, rh.get(w.get("equipment_id")), today) != "overdue":
            continue
        if dry_run:
            log.info("[dry-run] would alert overdue %s", w.get("number"))
            continue
        notifier.both(f"OVERDUE {w['priority']} work order {w['number']}: {w.get('title')}",
                      [f"Equipment: {w.get('equipment_name')}", f"Due: {fmt_due(w)}", f"Status: {w.get('status')}",
                       f"Assigned to: {w.get('assignee') or 'not assigned'}"])
        store.save_attrs("ASSET", w["id"], {"wo_overdue_alerted": True})
        summary["overdue_alerts"].append(w["number"])

    # 4. daily digest
    lib = store.library()
    if lib and now.hour >= DIGEST_HOUR:
        last = store.attrs("ASSET", lib, ["cmms_last_digest"]).get("cmms_last_digest")
        if str(last) != today.isoformat():
            lines = digest_lines(wos, store.documents(list(equipment.values())), rh, today)
            if dry_run:
                log.info("[dry-run] digest:\n%s", "\n".join(lines))
            else:
                notifier.both(f"Maintenance digest {today.strftime('%d %b %Y')}", lines)
                store.save_attrs("ASSET", lib, {"cmms_last_digest": today.isoformat()})
            summary["digest"] = True
    return summary


def digest_lines(wos, docs, rh, today):
    def state(w):
        return m.due_state(w, rh.get(w.get("equipment_id")), today)
    open_wos = sorted((w for w in wos if w.get("status") in m.OPEN), key=lambda w: (w.get("priority") or "P9", w.get("number")))
    overdue = [w for w in open_wos if state(w) == "overdue"]
    due = [w for w in open_wos if state(w) == "due"]
    verify = [w for w in wos if w.get("status") == m.COMPLETED]
    expiring = []
    for d in docs:
        exp = m.parse_date(d.get("expiry"))
        if exp and exp <= today + timedelta(days=30):
            expiring.append((exp, d))
    expiring.sort(key=lambda x: x[0])

    def line(w):
        return f"- {w['number']} [{w.get('priority')}] {w.get('title')} - {w.get('equipment_name')} (due {fmt_due(w)}, {w.get('status')}, {w.get('assignee') or 'unassigned'})"
    lines = [f"Open work orders: {len(open_wos)} | Overdue: {len(overdue)} | Due within 7 days: {len(due)} | Awaiting verification: {len(verify)}", ""]
    lines += ["OVERDUE:"] + ([line(w) for w in overdue] or ["- none"]) + [""]
    lines += ["DUE WITHIN 7 DAYS:"] + ([line(w) for w in due] or ["- none"]) + [""]
    lines += ["COMPLETED, AWAITING VERIFICATION:"] + ([f"- {w['number']} {w.get('title')} - {w.get('equipment_name')}" for w in verify] or ["- none"]) + [""]
    lines += ["DOCUMENTS EXPIRING WITHIN 30 DAYS:"] + (
        [f"- {d.get('title')} ({d.get('category')}, {d.get('owner')}) - {'EXPIRED' if exp < today else 'expires'} {exp.strftime('%d %b %Y')}"
         for exp, d in expiring] or ["- none"])
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    store = Store(ThingsBoardClient.connect(settings))
    summary = run(store, Notifier(settings, args.dry_run), dry_run=args.dry_run)
    log.info("pass done: %s", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
