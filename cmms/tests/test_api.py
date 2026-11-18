"""CMMS API: authentication, roles, customer scoping, workflow on the server. python3 -m unittest discover -s cmms/tests -t ."""
import copy
import json
import time
import unittest
from datetime import datetime, timedelta, timezone

from cmms import roles as R
from cmms.api import Api
from cmms.tests.fake_tb import SEED, FakeClient, site

IST = timezone(timedelta(minutes=SEED["timezone_offset_minutes"]))
YEAR = datetime.now(IST).year


def today(n=0):
    return (datetime.now(IST).date() + timedelta(days=n)).isoformat()


class Base(unittest.TestCase):
    def setUp(self):
        self.tb, self.ids, self.people, self.cust = site()
        self.api = Api(lambda: FakeClient(self.tb))

    def call(self, who, method, path, body=None, raw=None, ctype=None, expect=200):
        headers = {"X-Authorization": f"Bearer tok-{who}"} if who else {}
        if ctype:
            headers["Content-Type"] = ctype
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")

        def read(limit):
            if len(data) > limit:
                from cmms.api import HttpError
                raise HttpError(413, "too large")
            return data
        status, hdrs, out = self.api.handle(method, "/cmms/v1" + path, headers, read)
        res = json.loads(out) if hdrs.get("Content-Type") == "application/json" else out
        self.assertEqual(status, expect, res)
        return res

    def act(self, who, action, body, expect=200):
        return self.call(who, "POST", "/action/" + action, body, expect=expect)

    def state(self, who):
        return self.call(who, "GET", "/state")

    def wo(self, who, number):
        return next(w for w in self.state(who)["work_orders"] if w["number"] == number)

    def upload(self, who, name, purpose="attachment", expect=200):
        return self.call(who, "POST", f"/upload?purpose={purpose}&name={name}", raw=b"\x89PNGdata", ctype="image/png", expect=expect)

    def done(self, **kw):
        body = {"started_ts": int(time.time() * 1000) - 7200000, "finished_ts": int(time.time() * 1000) - 3600000,
                "condition": "In service", "technician": "Ravi", "work_done": "Replaced filter",
                "labour_hours": 1.5, "downtime_hours": 0.5, "results": [], "parts": []}
        body.update(kw)
        return body


class Authentication(Base):
    def test_token_is_verified_by_thingsboard(self):
        self.assertIn("Sign in", self.call(None, "GET", "/state", expect=401)["error"])
        self.assertIn("expired", self.call("forged", "GET", "/state", expect=401)["error"])

    def test_customer_user_without_role_has_no_access(self):
        self.assertIn("no maintenance role", self.call("none", "GET", "/state", expect=403)["error"])

    def test_user_of_another_tenant_is_refused(self):
        u = self.tb.user("tok-alien", "Alien", "TENANT_ADMIN")
        u["tenantId"] = {"id": "tenant-2"}
        self.call("alien", "GET", "/state", expect=403)

    def test_role_comes_from_settings_and_tenant_admin_is_admin(self):
        self.assertEqual(self.state("admin")["me"]["role"], "admin")
        me = self.state("tech")["me"]
        self.assertEqual((me["role"], me["name"]), ("technician", "Ravi"))
        self.assertIn("wo_complete", me["can"])
        self.assertNotIn("wo_verify", me["can"])


class Scoping(Base):
    def test_customer_user_sees_only_its_equipment(self):
        names = lambda who: [e["name"] for e in self.state(who)["equipment"]]
        self.assertEqual(names("admin"), ["DG SET1", "LT Panel 2", "RO Plant System"])     # x9: profile not configured
        self.assertEqual(names("sup"), ["DG SET1", "RO Plant System"])
        self.assertEqual(names("c2"), ["LT Panel 2"])

    def test_only_admin_can_delete_a_work_order(self):
        r = self.act("sup", "wo_create", {"equipment_id": self.ids["dg1"], "title": "Test", "type": "Inspection",
                                          "priority": "P3", "due_date": today(3)})
        self.act("sup", "wo_delete", {"id": r["id"]}, expect=403)
        self.act("admin", "wo_delete", {"id": r["id"]})
        self.assertEqual(self.state("admin")["work_orders"], [])
        self.act("admin", "wo_delete", {"id": r["id"]}, expect=404)

    def test_records_of_other_customers_are_invisible_and_untouchable(self):
        r = self.act("sup", "wo_create", {"equipment_id": self.ids["dg1"], "title": "Belt check", "type": "Inspection",
                                          "priority": "P3", "due_date": today(3)})
        self.assertEqual(self.state("c2")["work_orders"], [])
        self.act("c2", "wo_cancel", {"id": r["id"], "reason": "x"}, expect=404)
        self.act("c2", "wo_create", {"equipment_id": self.ids["dg1"], "title": "x", "type": "Inspection", "priority": "P3",
                                     "due_date": today(3)}, expect=400)

    def test_pm_details_and_templates_only_for_admin(self):
        dg = lambda who: next(e for e in self.state(who)["equipment"] if e["name"] == "DG SET1")
        self.assertEqual(dg("sup")["pm"], {"kind": "DG"})
        self.assertIn("limits", dg("admin")["pm"])
        self.assertNotIn("templates", self.state("sup"))
        self.assertIn("templates", self.state("admin"))
        self.assertEqual(dg("sup")["meter"], 166.1)                                    # skips 'error' and 32767


class Permissions(Base):
    def test_viewer_changes_nothing(self):
        self.act("view", "request_create", {"equipment_id": self.ids["dg1"], "title": "x", "description": "y"}, expect=403)
        self.act("view", "wo_create", {}, expect=403)
        self.upload("view", "a.png", expect=403)
        self.assertNotIn("assignees", self.state("view"))

    def test_requester_requests_but_does_not_plan(self):
        self.act("req", "wo_create", {}, expect=403)
        self.act("req", "plan_save", {}, expect=403)
        self.upload("req", "manual.pdf", "document", expect=403)

    def test_only_admin_changes_settings_and_roles(self):
        self.act("sup", "settings_save", {"settings": SEED}, expect=403)
        self.act("sup", "role_save", {"user_id": self.people["none"]["id"]["id"], "role": "viewer"}, expect=403)
        self.call("sup", "GET", "/users", expect=403)

    def test_assignees_with_the_same_name_are_told_apart(self):
        self.tb.user("tok-dup", "Ravi", "TENANT_ADMIN")["email"] = "ravi.k@site"
        names = sorted(u["name"] for u in self.state("sup")["assignees"])
        self.assertIn("Ravi (ravi@site)", names)
        self.assertIn("Ravi (ravi.k@site)", names)
        self.assertNotIn("Ravi", names)

    def test_role_matrix_is_cumulative(self):
        for a in R.ACTIONS:
            granted = [r for r in R.ROLES if R.can(r, a)]
            self.assertEqual(granted, R.ROLES[R.ROLES.index(granted[0]):], a)
        self.assertTrue(R.can("admin", "request_create"))
        self.assertFalse(R.can("", "request_create"))


class RequestToClose(Base):
    def test_full_workflow_with_roles(self):
        photo = self.upload("req", "leak.jpg")
        r = self.act("req", "request_create", {"equipment_id": self.ids["dg1"], "title": "Oil leak under DG",
                                               "description": "Drops near the sump", "attachments": [photo["id"]]})
        w = self.wo("sup", r["number"])
        self.assertEqual((w["status"], w["source"], w["type"]), ("Requested", "request", None))
        self.assertEqual(w["detail"]["requested_by"]["name"], "Priya")
        self.assertEqual(w["detail"]["attachments"][0]["title"], f"{r['number']} - leak.jpg")
        docs = self.tb.j(self.ids["dg1"], "maint_docs")
        self.assertEqual((docs[0]["category"], docs[0]["wo"]), ("Photo", r["number"]))
        self.act("tech", "request_approve", {"id": r["id"]}, expect=403)

        ravi = self.people["tech"]["id"]["id"]
        self.act("sup", "request_approve", {"id": r["id"], "rev": w["rev"], "type": "Corrective", "priority": "P2",
                                            "due_date": today(3), "assignee_id": ravi, "checklist": ["Find source", "Fix"]})
        w = self.wo("tech", r["number"])
        self.assertEqual((w["status"], w["assignee"], w["assignee_id"]), ("Scheduled", "Ravi", ravi))
        self.assertIn("Assigned", "Assigned")
        self.assertIn("assigned to Ravi", self.act("tech2", "wo_start", {"id": r["id"]}, expect=403)["error"])
        self.act("tech", "wo_start", {"id": r["id"], "rev": w["rev"]})

        w = self.wo("tech", r["number"])
        bad = self.done(results=[{"done": True}, {"done": False}])
        self.assertIn("remark", self.act("tech", "wo_complete", dict(bad, id=r["id"]), expect=400)["error"])
        nofail = self.done(results=[{"done": True}, {"done": True}])
        self.assertIn("failure", self.act("tech", "wo_complete", dict(nofail, id=r["id"]), expect=400)["error"])
        ok = dict(nofail, id=r["id"], rev=w["rev"], failure={"problem": "Leakage", "cause": "Wear / ageing", "action": "Replace"},
                  parts=[{"name": "Gasket", "qty": 1, "rate": 450}])
        self.act("tech", "wo_complete", ok)
        w = self.wo("sup", r["number"])
        self.assertEqual(w["status"], "Completed")
        self.assertEqual((w["detail"]["completed_by"]["name"], w["detail"]["cost_total"]), ("Ravi", 450))
        rec = json.loads(self.tb.ts[-1]["values"]["maintenance_record"])
        self.assertEqual((rec["wo_number"], rec["logged_by"], rec["parts"]), (r["number"], "Ravi", "Gasket x1"))

        self.act("tech", "wo_verify", {"id": r["id"]}, expect=403)
        self.act("sup", "wo_verify", {"id": r["id"], "rev": w["rev"]})
        w = self.wo("view", r["number"])
        self.assertEqual((w["status"], w["detail"]["verified_by"]["name"]), ("Closed", "Sunil"))
        hist = [(h["action"], h["name"]) for h in w["detail"]["history"]]
        self.assertEqual(hist, [("requested", "Priya"), ("approved", "Sunil"), ("started", "Ravi"), ("completed", "Ravi"),
                                ("verified and closed", "Sunil")])

    def test_requests_can_be_withdrawn_by_their_author_or_rejected(self):
        r = self.act("req", "request_create", {"equipment_id": self.ids["ro"], "title": "Low flow", "description": "Since morning"})
        self.tb.user("tok-req2", "Asha", "CUSTOMER_USER", self.cust[0])
        roles = self.tb.j(self.tb.by_name("Maintenance Settings"), "cmms_roles")
        roles[self.tb.tokens["tok-req2"]["id"]["id"]] = {"role": "requester"}
        self.tb.a(self.tb.by_name("Maintenance Settings"))["cmms_roles"] = json.dumps(roles)
        self.act("req2", "request_withdraw", {"id": r["id"], "reason": "dup"}, expect=403)
        self.act("req", "request_withdraw", {"id": r["id"], "reason": "Flow is back"})
        self.assertEqual(self.wo("sup", r["number"])["status"], "Cancelled")
        r2 = self.act("req", "request_create", {"equipment_id": self.ids["ro"], "title": "Noise", "description": "Pump"})
        self.act("sup", "request_reject", {"id": r2["id"], "reason": "Normal operation"})
        w = self.wo("sup", r2["number"])
        self.assertEqual((w["status"], w["detail"]["cancel_reason"]), ("Cancelled", "Normal operation"))

    def test_technician_takes_unassigned_work_and_cannot_verify_own(self):
        r = self.act("sup", "wo_create", {"equipment_id": self.ids["ro"], "title": "Clean strainer", "type": "Inspection",
                                          "priority": "P3", "due_date": today(2)})
        self.act("tech2", "wo_start", {"id": r["id"]})
        w = self.wo("sup", r["number"])
        self.assertEqual((w["assignee"], w["assignee_id"]), ("Mohan", self.people["tech2"]["id"]["id"]))
        self.act("tech", "wo_hold", {"id": r["id"], "reason": "x"}, expect=403)       # now assigned to Mohan
        self.act("sup", "wo_complete", dict(self.done(), id=r["id"]))                 # supervisors may record any work
        self.assertIn("another user", self.act("sup", "wo_verify", {"id": r["id"]}, expect=403)["error"])
        self.act("admin", "wo_verify", {"id": r["id"]})

    def test_stale_revision_is_refused(self):
        r = self.act("sup", "wo_create", {"equipment_id": self.ids["ro"], "title": "T", "type": "Inspection", "priority": "P3",
                                          "due_date": today(2)})
        w = self.wo("sup", r["number"])
        self.act("tech", "wo_start", {"id": r["id"], "rev": w["rev"]})
        self.assertIn("changed by someone else", self.act("sup", "wo_cancel", {"id": r["id"], "rev": w["rev"], "reason": "x"}, expect=409)["error"])

    def test_lifecycle_is_enforced_on_the_server(self):
        r = self.act("sup", "wo_create", {"equipment_id": self.ids["ro"], "title": "T", "type": "Inspection", "priority": "P3",
                                          "due_date": today(2)})
        self.act("sup", "wo_verify", {"id": r["id"]}, expect=400)
        self.act("sup", "request_approve", {"id": r["id"], "type": "Inspection", "priority": "P3", "due_date": today(2)}, expect=400)
        self.act("sup", "wo_create", {"equipment_id": self.ids["ro"], "title": "T", "type": "Nope", "priority": "P3",
                                      "due_date": today(2)}, expect=400)
        self.act("sup", "wo_create", {"equipment_id": self.ids["ro"], "title": "T", "type": "Inspection", "priority": "P3",
                                      "due_date": today(2), "due_rh": 100}, expect=400)          # RO has no run-hours meter


class WorkDoneAndPlans(Base):
    def test_direct_work_record_resets_pm_service_and_takes_attachments(self):
        f = self.upload("tech", "jobcard.pdf")
        self.assertEqual(self.upload("tech2", "x.pdf")["file"], "x.pdf")
        body = self.done(draft={"equipment_id": self.ids["dg1"], "type": "Preventive", "title": "250 h service"},
                         done_rh=170, service_reset=True, attachments=[f["id"]])
        self.act("tech2", "wo_complete", body, expect=400)                              # Ravi's upload, not Mohan's
        r = self.act("tech", "wo_complete", body)
        w = self.wo("sup", r["number"])
        self.assertEqual((w["status"], w["source"], w["due_date"], w["detail"]["direct"]), ("Completed", "direct", None, True))
        self.assertEqual(self.tb.j(self.ids["dg1"], "pm_config")["limits"]["service"]["last_service_run_hours"], 170)
        self.assertEqual(w["detail"]["attachments"][0]["file"], "jobcard.pdf")
        self.act("tech", "wo_complete", self.done(draft={"equipment_id": self.ids["dg1"], "type": "Preventive", "title": "x"}),
                 expect=400)                                                             # meter reading required
        self.act("req", "wo_complete", body, expect=403)

    def test_meter_plan_moves_after_completion_and_cancel_skips(self):
        p = self.act("sup", "plan_save", {"equipment_id": self.ids["dg1"], "title": "Oil change", "type": "Preventive",
                                          "priority": "P3", "strategy": "meter", "interval_rh": 250, "next_due_rh": 250,
                                          "checklist": ["Drain", "Fill"]})
        self.assertEqual(p["number"], "PL-0001")
        r = self.act("sup", "plan_raise", {"id": p["id"]})
        self.act("sup", "plan_raise", {"id": p["id"]}, expect=400)                     # one active WO per plan
        w = self.wo("tech", r["number"])
        self.assertEqual((w["due_rh"], w["detail"]["checklist"]), (250, ["Drain", "Fill"]))
        self.act("tech", "wo_complete", dict(self.done(results=[{"done": True}, {"done": True}]), id=r["id"]), expect=400)
        self.act("tech", "wo_complete", dict(self.done(results=[{"done": True}, {"done": True}]), id=r["id"], done_rh=248.5))
        pl = next(x for x in self.state("sup")["plans"] if x["id"] == p["id"])
        self.assertEqual((pl["next_due_rh"], pl["detail"]["last_wo"]), (498.5, r["number"]))

        t = self.act("sup", "plan_save", {"equipment_id": self.ids["ro"], "title": "Membrane CIP", "type": "Preventive",
                                          "priority": "P3", "strategy": "time", "interval_days": 30, "next_due_date": today(5),
                                          "lead_days": 7})
        r2 = self.act("sup", "plan_raise", {"id": t["id"]})
        self.act("sup", "wo_cancel", {"id": r2["id"], "reason": "Plant shut"})
        pl = next(x for x in self.state("sup")["plans"] if x["id"] == t["id"])
        self.assertEqual(pl["next_due_date"], today(35))

    def test_numbers_are_unique_when_a_number_was_taken_meanwhile(self):
        self.tb.asset(f"WO-{YEAR}-00001", "Work Order")
        self.tb.hidden_names.add(f"WO-{YEAR}-00001")
        r = self.act("sup", "wo_create", {"equipment_id": self.ids["ro"], "title": "T", "type": "Inspection", "priority": "P3",
                                          "due_date": today(2)})
        self.assertEqual(r["number"], f"WO-{YEAR}-00002")


class RecordWorkDone(Base):
    def test_start_finish_and_condition_are_required_and_checked(self):
        d = {"equipment_id": self.ids["ro"], "type": "Inspection", "title": "Strainer check"}
        no_start = self.done(draft=d); no_start.pop("started_ts")
        self.assertIn("Start time", self.act("tech", "wo_complete", no_start, expect=400)["error"])
        late = self.done(draft=d, started_ts=int(time.time() * 1000))
        self.assertIn("cannot start after", self.act("tech", "wo_complete", late, expect=400)["error"])
        self.act("tech", "wo_complete", self.done(draft=d, condition="Fine"), expect=400)
        self.assertIn("limitation", self.act("tech", "wo_complete", self.done(draft=d, condition="In service with limitations"), expect=400)["error"])

    def test_out_of_service_with_follow_up_request(self):
        r = self.act("tech", "wo_complete", self.done(
            draft={"equipment_id": self.ids["dg1"], "type": "Corrective", "title": "Starter motor check", "reported_ts": int(time.time() * 1000) - 9000000},
            failure={"problem": "Fails to start", "cause": "Wear / ageing", "action": "Temporary fix"},
            condition="Out of service", condition_note="Starter motor burnt, replacement awaited",
            follow_up={"title": "Replace starter motor", "description": "Part ordered"}))
        w = self.wo("sup", r["number"])
        self.assertEqual((w["detail"]["condition_after"], w["detail"]["condition_note"]), ("Out of service", "Starter motor burnt, replacement awaited"))
        self.assertLess(w["detail"]["work_started_ts"], w["completed_ts"])
        fu = self.wo("sup", r["follow_up"]["number"])
        self.assertEqual((fu["status"], fu["title"], fu["detail"]["follow_up_of"]["number"], fu["detail"]["requested_by"]["name"]),
                         ("Requested", "Replace starter motor", r["number"], "Ravi"))
        self.assertEqual(w["detail"]["follow_up"]["number"], fu["number"])
        rec = json.loads(self.tb.ts[-1]["values"]["maintenance_record"])
        self.assertEqual((rec["condition_after"], rec["follow_up"]), ("Out of service", fu["number"]))
        self.act("tech", "wo_complete", self.done(draft={"equipment_id": self.ids["dg1"], "type": "Inspection", "title": "x"},
                                                  follow_up={"title": ""}), expect=400)


class DocumentsAndSettings(Base):
    def test_general_library_is_managed_by_the_tenant(self):
        f = self.upload("sup", "sop.pdf", "document")
        self.act("sup", "doc_add", {"owner": "general", "file_id": f["id"], "title": "SOP", "category": "Manual"}, expect=403)
        f = self.upload("admin", "sop.pdf", "document")
        self.act("admin", "doc_add", {"owner": "general", "file_id": f["id"], "title": "SOP", "category": "Manual"})
        self.assertEqual(self.call("c2", "GET", f"/files/{f['id']}"), b"\x89PNGdata")       # every customer reads it
        self.act("sup", "doc_delete", {"owner": "general", "id": f["id"]}, expect=403)

    def test_customer_role_admin_is_not_honoured(self):
        sid = self.tb.by_name("Maintenance Settings")
        roles = self.tb.j(sid, "cmms_roles")
        roles[self.people["none"]["id"]["id"]] = {"role": "admin"}
        self.tb.a(sid)["cmms_roles"] = json.dumps(roles)
        self.call("none", "GET", "/state", expect=403)

    def test_documents_upload_download_delete(self):
        f = self.upload("sup", "manual.pdf", "document")
        self.act("sup", "doc_add", {"owner": self.ids["dg1"], "file_id": f["id"], "title": "DG manual", "category": "Nope"}, expect=400)
        self.act("sup", "doc_add", {"owner": self.ids["dg1"], "file_id": f["id"], "title": "DG manual", "category": "Manual",
                                    "revision": "B", "expiry": today(400)})
        self.act("sup", "doc_add", {"owner": self.ids["dg1"], "file_id": f["id"], "title": "again", "category": "Manual"}, expect=400)
        self.assertEqual(self.call("view", "GET", f"/files/{f['id']}?name=m.pdf"), b"\x89PNGdata")
        self.call("c2", "GET", f"/files/{f['id']}", expect=404)                        # other customer's equipment
        p = self.act("sup", "plan_save", {"equipment_id": self.ids["dg1"], "title": "Check", "type": "Inspection", "priority": "P3",
                                          "strategy": "time", "interval_days": 7, "next_due_date": today(3), "lead_days": 1,
                                          "docs": [f["id"]]})
        self.act("sup", "doc_delete", {"owner": self.ids["dg1"], "id": f["id"]})
        self.assertNotIn(f["id"], self.tb.resources)
        pl = next(x for x in self.state("sup")["plans"] if x["id"] == p["id"])
        self.assertEqual(pl["detail"]["docs"], [])

    def test_settings_are_validated_and_revision_guarded(self):
        bad = copy.deepcopy(SEED)
        bad["priorities"][0]["code"] = bad["priorities"][1]["code"]
        self.assertIn("priority codes", self.act("admin", "settings_save", {"rev": 1, "settings": bad}, expect=400)["error"])
        good = copy.deepcopy(SEED)
        good["due_soon_days"] = 5
        self.act("admin", "settings_save", {"rev": 1, "settings": good})
        self.assertEqual(self.state("sup")["settings"]["due_soon_days"], 5)
        self.act("admin", "settings_save", {"rev": 1, "settings": good}, expect=409)

    def test_admin_manages_roles(self):
        users = self.call("admin", "GET", "/users")["users"]
        nobody = next(u for u in users if u["name"] == "Nobody")
        self.assertEqual((nobody["role"], nobody["customer"]), ("", "Developer"))
        admin = next(u for u in users if u["name"] == "Admin")
        self.act("admin", "role_save", {"user_id": admin["id"], "role": "viewer"}, expect=400)
        self.act("admin", "role_save", {"user_id": nobody["id"], "role": "boss"}, expect=400)
        self.act("admin", "role_save", {"user_id": nobody["id"], "role": "admin"}, expect=400)   # admin: tenant administrators only
        self.act("admin", "role_save", {"user_id": nobody["id"], "role": "viewer", "rev": 1})
        self.assertEqual(self.state("none")["me"]["role"], "viewer")
        self.act("admin", "role_save", {"user_id": nobody["id"], "role": "", "rev": 1}, expect=409)
        self.act("admin", "role_save", {"user_id": nobody["id"], "role": ""})
        self.api._tokens.clear()
        self.call("none", "GET", "/state", expect=403)

    def test_pm_configuration_by_admin(self):
        pc = self.tb.j(self.ids["dg1"], "pm_config")
        lim = pc["limits"]
        lim["alarm_codes"] = {"288": "Mains failure"}
        self.act("sup", "pm_save", {"equipment_id": self.ids["dg1"], "engine": pc["engine"], "limits": lim}, expect=403)
        self.act("admin", "pm_save", {"equipment_id": self.ids["dg1"], "engine": pc["engine"], "limits": lim})
        self.assertEqual(self.tb.j(self.ids["dg1"], "pm_config")["limits"]["alarm_codes"], {"288": "Mains failure"})
        self.assertEqual(self.act("admin", "pm_enable", {"equipment_id": self.ids["ro"]})["kind"], "RO")
        self.act("admin", "pm_enable", {"equipment_id": self.ids["ro"]}, expect=400)


if __name__ == "__main__":
    unittest.main()
