"""CMMS user roles and what each may do (the authorisation workflow, like the work-order lifecycle in model.py).

Roles follow the usual CMMS split (requester / technician / planner-supervisor / administrator, plus read-only):

  viewer      sees work orders, plans, documents, KPIs; prints job cards. Changes nothing.
  requester   + raises work requests (fault reports) and withdraws own requests that are not yet approved.
  technician  + starts, holds, resumes and completes work orders assigned to them (or unassigned ones, which it then
                takes), records work done without a work order, attaches photos / reports.
  supervisor  + approves or rejects requests, creates / edits / assigns / cancels work orders, verifies and closes or
                rejects completed work, maintenance plans, technical documents.
  admin       + maintenance and predictive-maintenance settings, user roles.

Each role includes the rights of the roles before it. A ThingsBoard tenant administrator is always admin (settings,
templates and the user list are shared by all customers of the tenant, so admin is never given to a customer user); a
customer user gets one of CUSTOMER_ROLES from an admin (attribute cmms_roles of the asset "Maintenance Settings"); a
customer user without a role has no access. Who holds which role is configuration in ThingsBoard, never code.
"""

ROLES = ["viewer", "requester", "technician", "supervisor", "admin"]
LABELS = {"viewer": "Viewer (read only)", "requester": "Requester", "technician": "Technician",
          "supervisor": "Supervisor / planner", "admin": "Maintenance administrator"}

# minimum role per action
ACTIONS = {
    "request_create": "requester", "request_withdraw": "requester", "upload_attachment": "requester",
    "wo_start": "technician", "wo_hold": "technician", "wo_complete": "technician", "done_record": "technician",
    "wo_create": "supervisor", "wo_edit": "supervisor", "wo_cancel": "supervisor", "wo_verify": "supervisor",
    "wo_reject": "supervisor", "request_approve": "supervisor", "wo_assign_any": "supervisor",
    "plan_save": "supervisor", "plan_toggle": "supervisor", "plan_raise": "supervisor",
    "upload_document": "supervisor", "doc_add": "supervisor", "doc_delete": "supervisor",
    "wo_delete": "admin", "settings_save": "admin", "pm_save": "admin", "pm_enable": "admin", "role_save": "admin",
}
CUSTOMER_ROLES = ["viewer", "requester", "technician", "supervisor"]
ASSIGNABLE = "technician"     # users of this role or higher can be assigned work


class Forbidden(PermissionError):
    pass


def rank(role):
    return ROLES.index(role) if role in ROLES else -1


def can(role, action):
    if action not in ACTIONS:
        raise KeyError(action)
    return rank(role) >= rank(ACTIONS[action])


def require(role, action):
    if not can(role, action):
        need = LABELS[ACTIONS[action]]
        raise Forbidden(f"Your maintenance role ({LABELS.get(role, 'none')}) does not allow this; it needs {need} or higher")


def allowed_actions(role):
    return sorted(a for a in ACTIONS if can(role, a))
