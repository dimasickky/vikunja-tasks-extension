"""App-declared structured error codes for the Vikunja tasks connector.

These pair with the platform taxonomy (`imperal_sdk.chat.error_codes`) for
cases that taxonomy doesn't cover — problems specific to reaching/using the
user's *Vikunja* instance, not the Imperal backend itself. Every code here
matches the SDK's app-declared pattern `^[A-Z][A-Z0-9_]{2,63}$`
(imperal_sdk.types.action_result.ActionResult.error).

Platform codes (imported directly where they apply — validation, internal,
permission) are used as-is; these TASKS_* codes only exist where no
platform code honestly fits.
"""

TASKS_BRIDGE_ERROR = "TASKS_BRIDGE_ERROR"                          # Vikunja API call failed or returned an error (incl. not-connected)
TASKS_CONNECT_FAILED = "TASKS_CONNECT_FAILED"                      # connect/disconnect/status calls to Vikunja itself failed
TASKS_PROJECT_NOT_FOUND = "TASKS_PROJECT_NOT_FOUND"                # project name/id didn't resolve to a real Vikunja project
TASKS_TASK_NOT_FOUND = "TASKS_TASK_NOT_FOUND"                      # task name/id didn't resolve to a real Vikunja task
TASKS_TASK_AMBIGUOUS = "TASKS_TASK_AMBIGUOUS"                      # task_name matched more than one task, needs disambiguation
TASKS_BUCKET_NOT_FOUND = "TASKS_BUCKET_NOT_FOUND"                  # bucket (kanban column) name/id didn't resolve
TASKS_CHECKLIST_ITEM_NOT_FOUND = "TASKS_CHECKLIST_ITEM_NOT_FOUND"  # checklist item index not present in task description
TASKS_KANBAN_VIEW_MISSING = "TASKS_KANBAN_VIEW_MISSING"            # project has no kanban/board view configured in Vikunja
TASKS_LAST_BUCKET = "TASKS_LAST_BUCKET"                            # can't delete the only remaining bucket of a kanban view
