#!/usr/bin/env python3
"""Patch tenant Root Rule Chain: auto-assign new dashboards/devices to Public customer."""

import json
import sys
import urllib.request

TB_URL = "http://127.0.0.1:9090"
SYSADMIN_USER = "sysadmin@thingsboard.org"
SYSADMIN_PASS = "sysadmin"
TENANT_ADMIN_USER_ID = "e146f8f0-5e9c-11f1-bade-0bee8153e08f"
ROOT_RULE_CHAIN_ID = "ccf1bde0-5e9c-11f1-bade-0bee8153e08f"
VIEWER_CUSTOMER = "Public"

MARKER = "Variphi Viewer Entity Type Switch"
ASSIGN_DASHBOARD = "Variphi Assign Dashboard to Public"
ASSIGN_DEVICE = "Variphi Assign Device to Public"
MSG_SWITCH = "Message Type Switch"


def request(method, path, token=None, data=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(f"{TB_URL}{path}", data=body, headers=headers, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def main():
    sys_token = request(
        "POST",
        "/api/auth/login",
        data={"username": SYSADMIN_USER, "password": SYSADMIN_PASS},
    )["token"]
    tenant_token = request(
        "GET",
        f"/api/user/{TENANT_ADMIN_USER_ID}/token",
        token=sys_token,
    )["token"]

    meta = request(
        "GET",
        f"/api/ruleChain/{ROOT_RULE_CHAIN_ID}/metadata",
        token=tenant_token,
    )

    if any(n.get("name") == MARKER for n in meta["nodes"]):
        print("Rule chain already patched.")
        return 0

    msg_idx = next(i for i, n in enumerate(meta["nodes"]) if n["name"] == MSG_SWITCH)

    meta["nodes"].extend(
        [
            {
                "type": "org.thingsboard.rule.engine.filter.TbOriginatorTypeSwitchNode",
                "name": MARKER,
                "configurationVersion": 0,
                "configuration": {"version": 0},
                "additionalInfo": {"layoutX": 520, "layoutY": 280},
            },
            {
                "type": "org.thingsboard.rule.engine.action.TbAssignToCustomerNode",
                "name": ASSIGN_DASHBOARD,
                "configurationVersion": 1,
                "configuration": {
                    "customerNamePattern": VIEWER_CUSTOMER,
                    "createCustomerIfNotExists": False,
                },
                "additionalInfo": {"layoutX": 760, "layoutY": 220},
            },
            {
                "type": "org.thingsboard.rule.engine.action.TbAssignToCustomerNode",
                "name": ASSIGN_DEVICE,
                "configurationVersion": 1,
                "configuration": {
                    "customerNamePattern": VIEWER_CUSTOMER,
                    "createCustomerIfNotExists": False,
                },
                "additionalInfo": {"layoutX": 760, "layoutY": 340},
            },
        ]
    )

    switch_idx = len(meta["nodes"]) - 3
    dash_idx = len(meta["nodes"]) - 2
    device_idx = len(meta["nodes"]) - 1

    meta["connections"].append(
        {"fromIndex": msg_idx, "toIndex": switch_idx, "type": "Entity Created"}
    )
    meta["connections"].append(
        {"fromIndex": switch_idx, "toIndex": dash_idx, "type": "Dashboard"}
    )
    meta["connections"].append(
        {"fromIndex": switch_idx, "toIndex": device_idx, "type": "Device"}
    )

    saved = request(
        "POST",
        "/api/ruleChain/metadata",
        token=tenant_token,
        data=meta,
    )
    print(
        f"Patched Root Rule Chain ({saved['ruleChainId']['id']}): "
        f"{len(saved['nodes'])} nodes, {len(saved['connections'])} connections"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
