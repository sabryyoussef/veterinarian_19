"""Fail-closed abort for the first Phase 5 pilot."""

import json
from pathlib import Path

from odoo import fields


state_path = Path("/srv/devhub-uat/runtime/phase5-pilot-state.json")
state = json.loads(state_path.read_text(encoding="utf-8"))
workspace = env["dev.execution.workspace"].browse(state["workspace_id"]).exists()
workspace.assert_lease(state["lease_token"], state["lease_version"])
workspace._validate_physical()
checkpoint = workspace.worker_checkpoint(
    state["lease_token"],
    state["lease_version"],
    (
        "Worker stopped fail-closed: post-write allowlist comparison rejected "
        "the preserved file set."
    ),
    test_result={"run": 0, "passed": 0, "failed": 0, "command": "not run"},
)
workspace.work_item_id.sudo().action_block(
    (
        "Phase 5 worker stopped: allowlist validation did not accept the "
        "preserved changed-file set."
    )
)
workspace.sudo()._internal_write(
    {
        "state": "blocked",
        "worker_status": "blocked_fail_closed",
        "worker_stopped_at": fields.Datetime.now(),
        "validation_status": (
            "Worker stopped at allowlist boundary; human investigation required"
        ),
        "worker_log_summary": (
            "P1 passed. P2 filesystem write preserved. No tests executed. "
            "Lease revoked."
        ),
        "lease_owner": False,
        "lease_client_id": False,
        "lease_token": False,
        "lease_expires_at": fields.Datetime.now(),
        "last_checkpoint_id": checkpoint.id,
    }
)
workspace._event(
    "worker_blocked",
    "Dev Worker stopped fail-closed and lease was revoked",
    {"checkpoint_id": checkpoint.id, "version": state["lease_version"]},
)
env.cr.commit()
state_path.unlink()
print(
    json.dumps(
        {
            "workspace_id": workspace.id,
            "state": workspace.state,
            "work_phase": workspace.work_item_id.current_phase,
            "checkpoint_id": checkpoint.id,
            "lease_revoked": not bool(workspace.lease_token),
        },
        sort_keys=True,
    )
)
