"""Ownership guard: keeps the devices behind the dashboards with the customers those dashboards are shared with.

A customer user can only read devices of its own customer. When a device is moved to the Public customer (this keeps
happening, silently and without an audit entry), every dashboard shared with the real customer shows "No data" for it.

Every GUARD_INTERVAL_S seconds (default 60) the guard

  1. reads the dashboards: the devices they use (entity aliases that name devices: single entity / entity list) and the
     customers they are shared with (the Public customer does not count);
  2. reads who owns those devices;
  3. gives a device that is owned by the Public customer back to the customer its dashboards are shared with:
       - the customer that owned it last time the guard saw it correctly owned (kept in the state file), or
       - the only customer the dashboards are shared with, when there is just one;
       - when there is no way to tell (several customers, nothing seen yet) it only logs a warning.

Nothing is hardcoded: customers, devices and dashboards all come from ThingsBoard. A device that is owned by some other
customer than the dashboards' is only reported, never moved. Dashboard aliases that do not name fixed devices (by type,
by name filter) are skipped and logged once.

Run:  python3 -m ownership_guard.guard            (loop)       GUARD_DRY_RUN=1 python3 -m ownership_guard.guard --once
"""
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import requests

from infra_reports.config import load_settings
from infra_reports.tb_client import ThingsBoardClient, ThingsBoardError

log = logging.getLogger("ownership_guard")

STATE_FILE = Path(os.environ.get("GUARD_STATE_FILE") or Path.home() / ".local/state/ownership_guard/state.json")
PAGE = 500


# ----------------------------------------------------------------------------- ThingsBoard access
class TB:
    """The few ThingsBoard calls the guard needs; logs in again when the token has expired."""

    def __init__(self, settings):
        self.settings = settings
        self.client = None

    def _connect(self):
        self.client = ThingsBoardClient.connect(self.settings)

    def request(self, method, path, params=None):
        if self.client is None:
            self._connect()
        for attempt in (1, 2):
            c = self.client
            try:
                res = c.session.request(method, f"{c.base_url}{path}", params=params, headers=c._headers, timeout=30)
            except requests.RequestException as exc:
                raise ThingsBoardError(f"{method} {path} failed: {exc}") from exc
            if res.status_code in (401, 403) and attempt == 1 and "expired" in res.text.lower():
                self._connect()
                continue
            if res.status_code != 200:
                raise ThingsBoardError(f"{method} {path} returned HTTP {res.status_code}: {res.text[:160]}")
            return res.json() if res.content else {}
        raise ThingsBoardError(f"{method} {path}: session could not be renewed")

    def paged(self, path):
        page = 0
        while True:
            data = self.request("GET", path, {"pageSize": PAGE, "page": page})
            yield from data.get("data", [])
            if not data.get("hasNext"):
                return
            page += 1

    # the inputs of the decision
    def customers(self):
        return {c["id"]["id"]: {"title": c.get("title") or "", "public": bool((c.get("additionalInfo") or {}).get("isPublic"))}
                for c in self.paged("/api/customers")}

    def dashboards(self):
        out = []
        for d in self.paged("/api/tenant/dashboards"):
            full = self.request("GET", f"/api/dashboard/{d['id']['id']}")
            out.append({"id": d["id"]["id"], "title": d.get("title") or "",
                        "customers": [a["customerId"]["id"] for a in (d.get("assignedCustomers") or [])],
                        "aliases": list(((full.get("configuration") or {}).get("entityAliases") or {}).values())})
        return out

    def owners(self):
        return {d["id"]["id"]: {"name": d.get("name") or "", "customer": (d.get("customerId") or {}).get("id") or ""}
                for d in self.paged("/api/tenant/deviceInfos")}

    def assign(self, device_id, customer_id):
        self.request("POST", f"/api/customer/{customer_id}/device/{device_id}")


# ----------------------------------------------------------------------------- the decision (no I/O)
def alias_devices(alias):
    """(device ids, resolvable): the devices an entity alias names, or ([], False) when it names them by a rule."""
    f = alias.get("filter") or {}
    if f.get("type") == "singleEntity":
        e = f.get("singleEntity") or {}
        return ([e["id"]] if e.get("entityType") == "DEVICE" and e.get("id") else []), True
    if f.get("type") == "entityList":
        return (list(f.get("entityList") or []) if f.get("entityType") == "DEVICE" else []), True
    return [], False


def plan(dashboards, customers, owners, state):
    """-> (actions, new_state, notes). An action is (device_id, device_name, target_customer_id, reason)."""
    allowed, used_by, notes = {}, {}, []
    for d in dashboards:
        shared = [c for c in d["customers"] if c in customers and not customers[c]["public"]]
        for alias in d["aliases"]:
            ids, ok = alias_devices(alias)
            if not ok:
                notes.append(("skip-alias", d["id"] + alias.get("alias", ""),
                              f"dashboard '{d['title']}': alias '{alias.get('alias')}' does not name fixed devices; skipped"))
            for dev in ids:
                used_by.setdefault(dev, []).append(d["title"])
                for c in shared:
                    if c not in allowed.setdefault(dev, []):
                        allowed[dev].append(c)
    actions, new_state = [], dict(state)
    for dev, ok_customers in allowed.items():
        o = owners.get(dev)
        if o is None or not ok_customers:
            continue
        if o["customer"] in ok_customers:
            new_state[dev] = o["customer"]                    # correctly owned: remember it
        elif o["customer"] in customers and customers[o["customer"]]["public"]:
            target = state.get(dev) if state.get(dev) in ok_customers else (ok_customers[0] if len(ok_customers) == 1 else None)
            if target:
                actions.append((dev, o["name"], target, f"owned by Public; dashboards {sorted(set(used_by[dev]))} are shared with "
                                f"{[customers[c]['title'] for c in ok_customers]}"))
            else:
                notes.append(("ambiguous", dev, f"{o['name']} is owned by Public and its dashboards are shared with several customers "
                              f"{[customers[c]['title'] for c in ok_customers]}; owner before unknown, not moved"))
        else:
            notes.append(("other-owner", dev, f"{o['name']} is owned by '{customers.get(o['customer'], {}).get('title', o['customer'])}', "
                          f"its dashboards are shared with {[customers[c]['title'] for c in ok_customers]}; not moved"))
    return actions, new_state, notes


# ----------------------------------------------------------------------------- loop
def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=1))
    except OSError as exc:
        log.warning("could not save the state file %s: %s", STATE_FILE, exc)


def run_once(tb, state, dry_run, seen_notes):
    customers, dashboards, owners = tb.customers(), tb.dashboards(), tb.owners()
    actions, new_state, notes = plan(dashboards, customers, owners, state)
    for kind, key, text in notes:
        if (kind, key, text) not in seen_notes:
            seen_notes.add((kind, key, text))
            log.warning("%s", text)
    for dev, name, target, why in actions:
        title = customers[target]["title"]
        if dry_run:
            log.warning("DRY RUN: would assign %s to %s (%s)", name, title, why)
            continue
        tb.assign(dev, target)
        new_state[dev] = target
        log.warning("FIXED: %s was %s; assigned back to %s", name, why, title)
    if new_state != state:
        save_state(new_state)
    return new_state


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--once", action="store_true", help="one pass, then exit")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    interval = float(os.environ.get("GUARD_INTERVAL_S") or 60)
    dry = os.environ.get("GUARD_DRY_RUN", "") not in ("", "0", "false")
    tb, state, seen = TB(load_settings()), load_state(), set()
    log.info("started: every %.0fs%s, state file %s", interval, " (DRY RUN)" if dry else "", STATE_FILE)
    while True:
        try:
            state = run_once(tb, state, dry, seen)
        except (ThingsBoardError, requests.RequestException) as exc:
            log.error("pass failed, will retry: %s", exc)
        if args.once:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
