import unittest

from ownership_guard.guard import alias_devices, plan

PUBLIC, TECH, DEV = "pub", "tech", "dev"
CUST = {PUBLIC: {"title": "Public", "public": True}, TECH: {"title": "Tech Support", "public": False}, DEV: {"title": "Developer", "public": False}}


def dash(title, customers, *devices, alias_type="singleEntity"):
    aliases = []
    for d in devices:
        f = {"type": "singleEntity", "singleEntity": {"entityType": "DEVICE", "id": d}} if alias_type == "singleEntity" \
            else {"type": "entityList", "entityType": "DEVICE", "entityList": list(devices)}
        aliases.append({"alias": d, "filter": f})
    return {"id": title, "title": title, "customers": customers, "aliases": aliases}


def own(**kw):
    return {k: {"name": k.upper(), "customer": v} for k, v in kw.items()}


class GuardPlan(unittest.TestCase):
    def test_public_device_goes_back_to_the_only_shared_customer(self):
        a, _, _ = plan([dash("D1", [TECH], "d1")], CUST, own(d1=PUBLIC), {})
        self.assertEqual(a[0][:3], ("d1", "D1", TECH))

    def test_correctly_owned_device_is_remembered_and_left_alone(self):
        a, st, _ = plan([dash("D1", [TECH, DEV], "d1")], CUST, own(d1=DEV), {})
        self.assertEqual((a, st), ([], {"d1": DEV}))

    def test_remembered_owner_is_used_when_several_customers(self):
        a, _, _ = plan([dash("D1", [TECH, DEV], "d1")], CUST, own(d1=PUBLIC), {"d1": DEV})
        self.assertEqual(a[0][2], DEV)

    def test_ambiguous_owner_is_only_reported(self):
        a, _, notes = plan([dash("D1", [TECH, DEV], "d1")], CUST, own(d1=PUBLIC), {})
        self.assertEqual(a, [])
        self.assertEqual(notes[0][0], "ambiguous")

    def test_public_dashboards_do_not_count(self):
        a, _, _ = plan([dash("D1", [PUBLIC, TECH], "d1")], CUST, own(d1=PUBLIC), {})
        self.assertEqual(a[0][2], TECH)
        self.assertEqual(plan([dash("D2", [PUBLIC], "d2")], CUST, own(d2=PUBLIC), {})[0], [])

    def test_device_of_another_customer_is_not_moved(self):
        a, _, notes = plan([dash("D1", [TECH], "d1")], CUST, own(d1=DEV), {})
        self.assertEqual(a, [])
        self.assertEqual(notes[0][0], "other-owner")

    def test_entity_list_alias_and_shared_device(self):
        a, _, _ = plan([dash("D1", [TECH], "x", "y", alias_type="entityList"), dash("D2", [TECH], "x")], CUST,
                       own(x=PUBLIC, y=TECH), {})
        self.assertEqual([x[0] for x in a], ["x"])

    def test_rule_based_aliases_are_skipped_with_a_note(self):
        d = {"id": "d", "title": "D", "customers": [TECH], "aliases": [{"alias": "all", "filter": {"type": "deviceType", "deviceTypes": ["x"]}}]}
        a, _, notes = plan([d], CUST, own(), {})
        self.assertEqual((a, notes[0][0]), ([], "skip-alias"))
        self.assertEqual(alias_devices(d["aliases"][0]), ([], False))

    def test_unknown_device_is_ignored(self):
        self.assertEqual(plan([dash("D1", [TECH], "gone")], CUST, own(), {})[0], [])


if __name__ == "__main__":
    unittest.main()
