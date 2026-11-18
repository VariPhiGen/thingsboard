# Maintenance management (CMMS) on ThingsBoard

Work requests, work orders, preventive maintenance plans, technical documents and maintenance KPIs for the monitored
equipment (DG sets, LT panels, RO plant, fire suppression). UI: widget **Maintenance Management** on the dashboard
**Reports & Maintenance** (`period_reports/widgets/maintenance_planner.js`). Server side: `cmms/` (this package): the
CMMS API (`api.py`, `service.py`), roles (`roles.py`), rules (`model.py`), scheduler (`scheduler.py`).

## Users and roles

| Role | May |
|---|---|
| Viewer | see work orders, requests, plans, documents, KPIs; print job cards |
| Requester | + raise work requests (fault reports, with photos); withdraw own requests not yet approved |
| Technician | + start / hold / resume / complete work orders assigned to them or unassigned (starting an unassigned one assigns it to them); record work done without a work order; attach photos and reports |
| Supervisor / planner | + approve (type, priority, due date, assignee) or reject requests; create / edit / assign / cancel work orders; verify and close or reject completed work; maintenance plans; technical documents |
| Maintenance administrator | + maintenance and predictive-maintenance settings; user roles; documents for all equipment. Only ThingsBoard tenant administrators (settings, templates, the user list and the general library are shared by all customers of the tenant) |

Each role includes the rights of the roles above it. A ThingsBoard **tenant administrator** is always maintenance
administrator. A **customer user** gets one of the first four roles from an administrator in **Maintenance Management > Settings >
Users and roles** (stored as `cmms_roles` on the asset *Maintenance Settings*); without a role it has no access. A
customer user sees only the equipment (devices) assigned to its customer, and the work orders, plans and documents of
that equipment. The person who recorded work cannot verify it (setting `verification.different_user`).

Giving a customer's users access (once per customer):
1. ThingsBoard: assign the customer's equipment devices to the customer (Devices > Assign to customer).
2. `python3 -m cmms.share --customer "<customer title>"`: assigns the dashboards *Reports & Maintenance* and
   *Predictive Maintenance* to the customer and checks that no maintenance record is assigned to a customer.
3. ThingsBoard: create the users (Customers > <customer> > Users; they set their password from the activation email).
4. Dashboard: give each user a role (Settings > Users and roles).

## CMMS API (`api.py`, `service.py`)

The widget never writes to ThingsBoard itself. It reads everything and sends every change as a command to
`https://viot.virtuosonetsoft.com/report-api/cmms/v1/...` (same origin; nginx -> `report_api_server.py` on
127.0.0.1:5055, systemd unit `virtuoso-report-api`) with the signed-in user's ThingsBoard JWT. The API accepts the token
only when ThingsBoard confirms it and the user belongs to the service account's tenant, then checks on the server: the
role, the equipment the user may see, the lifecycle, segregation of duties, the configured values (types, priorities,
failure codes, categories, meter range), the record revision and the input. Changes are made with the service account
of `thingsboard/.env`. History entries carry the verified user (id, email, name), never a name sent by the browser.
Work orders, plans, settings and roles are tenant assets that are not assigned to customers, so customer users cannot
change them through the ThingsBoard REST API either. Uploaded files are kept only when they are attached to a record by
the user who uploaded them (unused uploads are deleted after a day); downloads are allowed only for documents of
equipment the user may see.

Limit of ThingsBoard CE: a customer user may write attributes and telemetry of the devices assigned to its customer
through the ThingsBoard REST API (CE has no fine-grained permissions). This covers device attributes such as
`pm_config` and `maint_docs`; such changes are recorded in the ThingsBoard audit log under the user's name.

## Configuration (nothing hardcoded)

Every business value lives in ThingsBoard, on the asset **Maintenance Settings**, and is edited on the dashboard
(**Maintenance Management > Settings**):

- `cmms_settings` - equipment profiles in scope, meter key / unit / valid range, priorities with response days,
  work-order types (planned, allowed in plans, failure codes required, restarts the PM service countdown), "due soon"
  days, meter due window, failure codes, document categories, attachment categories, document expiry alert days, upload
  limit, verification rule, condition-based alarm severities and type patterns, alert priorities, digest hour, KPI
  periods, site time zone. `cmms_settings_rev` guards concurrent edits.
- `pm_templates` - the predictive-maintenance template (`predictive_maintenance/pm_seed.json`) used to configure new
  equipment.

`cmms/settings_seed.json` is written once by `period_reports/deploy_dashboard.py` when no settings exist yet. The
scheduler and the widget refuse to run with missing or incomplete settings instead of assuming values. Forms have no
pre-filled values: the user enters every value (the due date of a manual work order is calculated from the configured
response days of the chosen priority; the meter field shows the equipment's latest valid reading).

## Data model

| Record | Stored as | Number |
|---|---|---|
| Maintenance plan | ThingsBoard asset, type `Maintenance Plan`, server attributes `plan_*` | `PL-0001` |
| Work order / work request | ThingsBoard asset, type `Work Order`, server attributes `wo_*` (`wo_detail` = JSON: checklist + results, parts, failure codes, labour, downtime, attachments, requested / approved / completed / verified by, history); `wo_assignee_id` = the assigned user (empty for a vendor typed as text) | `WO-2026-00001` |
| Technical document | ThingsBoard GENERAL resource; metadata list `maint_docs` on the equipment device, or on the asset `Maintenance Document Library` (all equipment) | - |
| Work done | also telemetry `maintenance_record` on the equipment (period reports) | - |

Plans and work orders are related to their equipment device with relation type `Maintenance`.
The asset name is the record number: ThingsBoard rejects duplicate asset names, so two creators can never get the
same number (the loser retries with the next one). `wo_rev` / `plan_rev` are checked before every update so a change
made meanwhile by another user is reported instead of overwritten. Every change is also in the ThingsBoard audit log.
ThingsBoard rejects null attribute values, so empty fields are stored as `""`.

## Work done tab

Lists every completed / verified work order, newest first (equipment filter, search, verification status). **+ Record
work done** enters work that was carried out without a work order: step 1 equipment, type, title (priority optional;
for corrective types the time the problem was reported), step 2 the normal completion form. The work order (source
`direct`) is created only when the work is saved, so an abandoned form leaves nothing behind. It has no due date, so it
is not counted in PM compliance; a corrective one counts in MTTR only when its reported time was entered. It is then
verified by another user like any other work order.

## Recording work done

The completion form (on a work order, or *Work done > + Record work done* without one) asks for: work started and
finished at (elapsed time shown; labour hours = person-hours of everyone, entered separately), technician / vendor
(the signed-in user is filled in and can be changed), meter reading, labour and downtime hours, work done, checklist
results, failure codes (corrective types), parts with qty and rate, attachments, and the **equipment condition after
the work** (EN 13306 operating state: *In service* / *In service with limitations* / *Out of service*; the last two need
the limitation or reason). **Further work needed** raises a work request (status Requested) for the supervisor, linked
both ways (`follow_up` / `follow_up_of`); it is ticked automatically when the equipment is out of service. Condition
and follow-up are stored on the work order and in `maintenance_record`, so they appear in the period reports.

## Lifecycle (EN 13306 terms)

```
Requested -> Scheduled                       work request approved by a supervisor (type, priority, due, assignee)
Requested -> Cancelled                       rejected by a supervisor / withdrawn by the requester (reason)
Scheduled -> In Progress <-> On Hold        (hold needs a reason)
Scheduled / In Progress -> Completed        (work done, labour h, checklist results; corrective: ISO 14224 failure
                                             problem / cause / action)
Completed -> Closed                          verified by ANOTHER user (segregation of duties)
Completed -> In Progress                     rejected for rework (reason)
Scheduled / In Progress / On Hold -> Cancelled  (reason; a plan occurrence is skipped, the plan moves one interval)
```
Priorities: P1 emergency (24 h), P2 urgent (3 d), P3 normal (7 d), P4 low (30 d).
Due state: overdue / due (time: within 7 days; run-hours: within 10 % of the interval, min 10 h) / upcoming.

Completing a work order of a plan moves the plan to its next due point (time: interval after the work date;
run-hours: interval after the run hours at the work). A DG *Preventive* work order can restart the Predictive
Maintenance service countdown (`pm_config.last_service_run_hours`, `service_interval_h`).

## Scheduler (`python3 -m cmms.scheduler`, every 10 min)

1. **Preventive work orders**: one per active plan whose next occurrence is inside its lead time (time plans: lead
   days, default 7; run-hour plans: 10 % of the interval). Never a second one while the previous is not closed.
2. **Condition-based work orders**: one P1 work order per active CRITICAL alarm `Predictive Maintenance - Critical`
   or `Fire Cylinder N Low Pressure` (keyed by alarm id), announced on Telegram + email.
3. **Overdue P1/P2** work orders: alerted once on Telegram + email.
4. **Daily digest 08:00 IST** (Telegram + email to `REPORT_RECIPIENTS`): work requests awaiting approval, overdue,
   due within 7 days, awaiting verification, documents expiring within 30 days.

Each pass is idempotent; `--dry-run` logs what would happen and changes nothing. Credentials, SMTP and Telegram come
from `thingsboard/.env` (same settings as the infra reports).

Install / update the timer (once, as a sudo user):
```bash
sudo cp /home/ubuntu/thingsboard/cmms/systemd/cmms-scheduler.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now cmms-scheduler.timer
systemctl list-timers cmms-scheduler.timer; journalctl -u cmms-scheduler -n 50
```

## KPIs (widget tab "KPIs", from recorded work orders only; "--" = no data)

- **PM compliance %** = planned work orders (preventive, inspection, statutory, calibration) due in the period and
  completed on or before their due date / planned work orders due in the period (cancelled excluded).
- **Backlog / overdue** = open work orders now / of which past due.
- **Mean time to repair** = average raised -> completed time of corrective and condition-based work orders completed in
  the period.
- **Planned work %** = share of planned work among work orders completed in the period.
- Labour hours, downtime hours and cost (parts qty x rate) of the work orders completed in the period.

## Tests

```bash
python3 -m unittest discover -s cmms/tests -t .        # rules, KPIs, scheduler, API: roles, scoping, workflow (47)
NODE_PATH=<node_modules with jsdom> node period_reports/tests/test_maintenance_planner.js
                                                       # widget end-to-end against the real API on an in-memory ThingsBoard (28)
```
