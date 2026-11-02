"""CMMS scheduler: run every 10 minutes (systemd timer cmms-scheduler.timer).

  python3 -m cmms.scheduler            # one pass
  python3 -m cmms.scheduler --dry-run  # log what would be created/sent, change nothing

All rules come from the ThingsBoard configuration (asset "Maintenance Settings", attribute cmms_settings); when it is
missing or incomplete the pass stops with an error instead of assuming values. Each pass is idempotent:
1. Preventive work orders: every active plan whose next occurrence is inside its lead time gets one work order
   (none while an earlier work order of the plan is still active).
2. Condition-based work orders: every active alarm matching condition_based (severities + alarm type patterns) on
   configured equipment gets one work order (keyed by the alarm id), announced immediately.
3. Overdue work orders with a priority listed in alerts.overdue_priorities are alerted once.
4. Daily digest at alerts.digest_hour (local time zone of the settings), once per day: overdue, due soon,
   awaiting verification, documents expiring within doc_expiry_alert_days.
"""
import argparse
import logging
import sys
import time
from datetime import datetime, timedelta

from infra_reports.config import load_settings
from infra_reports.tb_client import ThingsBoardClient

from . import model as m
from .notify import Notifier
from .store import Store

log = logging.getLogger("cmms.scheduler")


def history(action, note="", frm=None, to=None):
    return {"ts": int(time.time() * 1000), "user": "system", "name": "CMMS scheduler", "action": action,
            "from": frm, "to": to, "note": note}


def wo_from_plan(plan, created_ts):
    d = plan.get("detail") or {}
    meter = plan.get("strategy") == "meter"
    fields = {"title": plan["title"], "type": plan["type"], "priority": plan["priority"],
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


def wo_from_alarm(alarm, equipment_name, created_ts, today, settings):
    det = alarm.get("details") or {}
    text = det.get("message") or det.get("data") or det.get("description") or alarm["type"]
    action = det.get("recommendation") or det.get("recommended_action") or ""
    pri = settings.cbm["priority"]
    fields = {"title": alarm["type"], "type": settings.cbm["wo_type"], "priority": pri, "status": m.SCHEDULED,
              "source": "alarm", "plan_id": "", "alarm_id": alarm["id"]["id"],
              "equipment_id": alarm["originator"]["id"], "equipment_name": equipment_name,
              "due_date": m.due_date_for_priority(pri, today, settings), "due_rh": None, "interval_rh": None, "assignee": "",
              "created_ts": created_ts, "completed_ts": None, "closed_ts": None}
    detail = {"description": (text + (" Recommended: " + action if action else "")).strip(), "checklist": [], "docs": [],
              "alarm_type": alarm["type"], "alarm_start_ts": alarm.get("startTs"),
              "history": [history("created", f"Raised by alarm '{alarm['type']}' ({alarm.get('severity')})", to=m.SCHEDULED)]}
    return fields, detail


def fmt_due(w, settings):
    if w.get("due_rh") not in (None, ""):
        return f"at {w['due_rh']} {settings.raw['meter']['unit']}"
    d = m.parse_date(w.get("due_date"))
    return d.strftime("%d %b %Y") if d else "-"


def run(store, notifier, settings, now=None, dry_run=False):
    now = (now or datetime.now(settings.tz)).astimezone(settings.tz)
    today = m.today_local(settings, now)
    now_ms = int(now.timestamp() * 1000)
    equipment = {e["id"]: e for e in store.equipment(settings)}
    meter = {i: store.meter_reading(i, settings) for i in equipment}
    plans, wos = store.plans(), store.work_orders()
    summary = {"created_pm": [], "created_cbm": [], "overdue_alerts": [], "digest": False}

    # 1. preventive work orders from plans
    for p in plans:
        if p.get("equipment_id") not in equipment or not m.plan_generation_due(p, meter.get(p["equipment_id"]), today, settings):
            continue
        if any(w.get("plan_id") == p["id"] and w.get("status") in m.ACTIVE for w in wos):
            continue
        fields, detail = wo_from_plan(p, now_ms)
        if dry_run:
            log.info("[dry-run] would create work order for plan %s %s", p.get("number"), p.get("title"))
            continue
        number, aid = store.create_work_order(fields, detail, now.year)
        wos.append(dict(fields, id=aid, number=number, detail=detail, rev=1))
        summary["created_pm"].append(number)

    # 2. condition-based work orders from alarms
    for a in store.active_alarms():
        if a.get("originator", {}).get("entityType") != "DEVICE" or a["originator"]["id"] not in equipment:
            continue
        if not settings.cbm_alarm(a) or any(w.get("alarm_id") == a["id"]["id"] for w in wos):
            continue
        fields, detail = wo_from_alarm(a, equipment[a["originator"]["id"]]["name"], now_ms, today, settings)
        if dry_run:
            log.info("[dry-run] would create %s work order for alarm %s on %s", fields["priority"], a["type"], fields["equipment_name"])
            continue
        number, aid = store.create_work_order(fields, detail, now.year)
        wos.append(dict(fields, id=aid, number=number, detail=detail, rev=1))
        summary["created_cbm"].append(number)
        notifier.both(f"New {fields['priority']} work order {number}: {fields['title']}",
                      [f"Equipment: {fields['equipment_name']}", detail["description"], f"Due: {fmt_due(fields, settings)}",
                       "Open Reports & Maintenance > Maintenance Management to assign and start the work."])

    # 3. overdue alerts (once per work order)
    for w in wos:
        if w.get("status") not in m.OPEN or w.get("priority") not in settings.alerts["overdue_priorities"] or w.get("overdue_alerted"):
            continue
        if m.due_state(w, meter.get(w.get("equipment_id")), today, settings) != "overdue":
            continue
        if dry_run:
            log.info("[dry-run] would alert overdue %s", w.get("number"))
            continue
        notifier.both(f"OVERDUE {w['priority']} work order {w['number']}: {w.get('title')}",
                      [f"Equipment: {w.get('equipment_name')}", f"Due: {fmt_due(w, settings)}", f"Status: {w.get('status')}",
                       f"Assigned to: {w.get('assignee') or 'not assigned'}"])
        store.save_attrs("ASSET", w["id"], {"wo_overdue_alerted": True})
        summary["overdue_alerts"].append(w["number"])

    # 4. daily digest
    lib = store.library()
    if lib and settings.alerts.get("digest_enabled") and now.hour >= int(settings.alerts["digest_hour"]):
        last = store.attrs("ASSET", lib, ["cmms_last_digest"]).get("cmms_last_digest")
        if str(last) != today.isoformat():
            lines = digest_lines(wos, store.documents(list(equipment.values())), meter, today, settings)
            if dry_run:
                log.info("[dry-run] digest:\n%s", "\n".join(lines))
            else:
                notifier.both(f"Maintenance digest {today.strftime('%d %b %Y')}", lines)
                store.save_attrs("ASSET", lib, {"cmms_last_digest": today.isoformat()})
            summary["digest"] = True
    return summary


def digest_lines(wos, docs, meter, today, settings):
    def state(w):
        return m.due_state(w, meter.get(w.get("equipment_id")), today, settings)
    order = [p["code"] for p in settings.raw["priorities"]]
    open_wos = sorted((w for w in wos if w.get("status") in m.OPEN),
                      key=lambda w: (order.index(w.get("priority")) if w.get("priority") in order else len(order), w.get("number")))
    overdue = [w for w in open_wos if state(w) == "overdue"]
    due = [w for w in open_wos if state(w) == "due"]
    verify = [w for w in wos if w.get("status") == m.COMPLETED]
    horizon = today + timedelta(days=int(settings.raw["doc_expiry_alert_days"]))
    expiring = sorted(((m.parse_date(d.get("expiry")), d) for d in docs if m.parse_date(d.get("expiry")) and m.parse_date(d.get("expiry")) <= horizon),
                      key=lambda x: x[0])

    def line(w):
        return (f"- {w['number']} [{w.get('priority')}] {w.get('title')} - {w.get('equipment_name')} "
                f"(due {fmt_due(w, settings)}, {w.get('status')}, {w.get('assignee') or 'unassigned'})")
    soon = settings.raw["due_soon_days"]
    lines = [f"Open work orders: {len(open_wos)} | Overdue: {len(overdue)} | Due within {soon} days: {len(due)} | Awaiting verification: {len(verify)}", ""]
    lines += ["OVERDUE:"] + ([line(w) for w in overdue] or ["- none"]) + [""]
    lines += [f"DUE WITHIN {soon} DAYS:"] + ([line(w) for w in due] or ["- none"]) + [""]
    lines += ["COMPLETED, AWAITING VERIFICATION:"] + ([f"- {w['number']} {w.get('title')} - {w.get('equipment_name')}" for w in verify] or ["- none"]) + [""]
    lines += [f"DOCUMENTS EXPIRING WITHIN {settings.raw['doc_expiry_alert_days']} DAYS:"] + (
        [f"- {d.get('title')} ({d.get('category')}, {d.get('owner')}) - {'EXPIRED' if exp < today else 'expires'} {exp.strftime('%d %b %Y')}"
         for exp, d in expiring] or ["- none"])
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    env = load_settings()
    store = Store(ThingsBoardClient.connect(env))
    try:
        settings = m.Settings(store.settings())
    except m.SettingsError as exc:
        log.error("%s - nothing done", exc)
        return 2
    summary = run(store, Notifier(env, args.dry_run), settings, dry_run=args.dry_run)
    log.info("pass done: %s", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
