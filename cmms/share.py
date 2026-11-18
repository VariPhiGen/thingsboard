"""Give a ThingsBoard customer's users access to maintenance management (run once per customer, idempotent).

  python3 -m cmms.share --customer "Developer" --dry-run
  python3 -m cmms.share --customer "Developer"

1. Assigns the dashboards "Reports & Maintenance" and "Predictive Maintenance" to the customer (its users then see
   them in ThingsBoard and in the mobile app). The equipment devices must already be assigned to the customer: they are
   what its users see and work on; the script lists the configured equipment that is not.
2. Checks that no maintenance record (work orders, plans, settings, document library) is assigned to any customer:
   customer users change those only through the CMMS API, which checks their role. Assigned ones are reported, and
   unassigned with --fix.

Users are created in ThingsBoard (Customers > <customer> > Users); their maintenance role is given on the dashboard
(Maintenance Management > Settings > Users and roles). A user without a role has no access.
"""
import argparse
import logging
import sys

from infra_reports.config import load_settings
from infra_reports.tb_client import ThingsBoardClient

from . import model as m
from .store import LIBRARY_TYPE, PLAN_TYPE, SETTINGS_TYPE, WO_TYPE, Store

PUBLIC_CUSTOMER = "Public"
DASHBOARDS = ["Reports & Maintenance", "Predictive Maintenance"]   # titles set by the deploy scripts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--customer", required=True, help="ThingsBoard customer title")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fix", action="store_true", help="unassign maintenance records that are assigned to a customer")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    st = Store(ThingsBoardClient.connect(load_settings()))
    customers = st._pages("/api/customers")
    cust = next((c for c in customers if c.get("title") == a.customer), None)
    if not cust:
        print(f"Customer '{a.customer}' not found. Customers: {', '.join(c['title'] for c in customers)}")
        return 2
    if cust.get("title") == PUBLIC_CUSTOMER or (cust.get("additionalInfo") or {}).get("isPublic"):
        print("Refusing to share maintenance management with the public customer")
        return 2
    cid = cust["id"]["id"]

    dashes = st._pages("/api/tenant/dashboards")
    for title in DASHBOARDS:
        d = next((x for x in dashes if x["title"] == title), None)
        if not d:
            print(f"dashboard '{title}': not deployed yet, skipped")
            continue
        assigned = {c["customerId"]["id"] for c in (d.get("assignedCustomers") or [])}
        if cid in assigned:
            print(f"dashboard '{title}': already assigned")
        elif a.dry_run:
            print(f"dashboard '{title}': would assign")
        else:
            st._req("POST", f"/api/customer/{cid}/dashboard/{d['id']['id']}")
            print(f"dashboard '{title}': assigned")

    settings = m.Settings(st.settings())
    mine = {e["id"] for e in st.equipment(settings, cid)}
    missing = [e["name"] for e in st.equipment(settings) if e["id"] not in mine]
    print(f"equipment assigned to the customer: {len(mine)}" + (f"; not assigned: {', '.join(missing)}" if missing else " (all configured equipment)"))

    leaks = []
    for t in (WO_TYPE, PLAN_TYPE, SETTINGS_TYPE, LIBRARY_TYPE):
        for asset in st._pages("/api/tenant/assets", {"type": t}):
            owner = (asset.get("customerId") or {}).get("id")
            if owner and owner != "13814000-1dd2-11b2-8080-808080808080":
                leaks.append(asset)
    for asset in leaks:
        if a.fix and not a.dry_run:
            st._req("DELETE", f"/api/customer/asset/{asset['id']['id']}")
            print(f"unassigned {asset['type']} {asset['name']} from its customer")
        else:
            print(f"WARNING: {asset['type']} {asset['name']} is assigned to a customer; its users could change it directly (run with --fix)")
    if not leaks:
        print("maintenance records: none assigned to a customer (changes only through the CMMS API)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
