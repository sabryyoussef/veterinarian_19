"""Execute one approved Push with a controlled subprocess transport failure."""

import json
import os
import subprocess
from unittest.mock import patch


workspace = env["dev.execution.workspace"].browse(
    int(os.environ["HARDENING_FAILURE_WORKSPACE_ID"])
).exists().with_user(env.ref("base.user_admin"))
if not workspace or workspace.state != "push_approved":
    raise RuntimeError("Failure workspace is not at the approved Push gate")
approval = workspace.push_approval_id
original_run = subprocess.run
push_attempts = []


def controlled_run(command, *args, **kwargs):
    if isinstance(command, list) and "push" in command:
        push_attempts.append(
            [
                part
                for part in command
                if "SECRET" not in part and "token=" not in part.casefold()
            ]
        )
        return subprocess.CompletedProcess(
            command, 1, stdout=b"", stderr=b"simulated sanitized transport failure"
        )
    return original_run(command, *args, **kwargs)


with patch.object(subprocess, "run", side_effect=controlled_run):
    record = workspace.execute_approved_push(approval)

if len(push_attempts) != 1:
    raise RuntimeError("Controlled failure did not attempt exactly one Push")
if record.reconciliation_state != "push_failed_review":
    raise RuntimeError("Controlled failure did not reconcile to push_failed_review")
if workspace.state != "push_failed_review":
    raise RuntimeError("Workspace did not stop for human failure review")
env.cr.commit()
print(
    json.dumps(
        {
            "workspace_id": workspace.id,
            "record_id": record.id,
            "state": workspace.state,
            "reconciliation_state": record.reconciliation_state,
            "expected_remote_head": record.expected_remote_head,
            "observed_remote_head": record.remote_head_after or None,
            "approved_pre_refs_digest": record.approved_pre_refs_digest,
            "observed_post_refs_digest": record.observed_post_refs_digest,
            "push_attempts": len(push_attempts),
        },
        sort_keys=True,
    )
)
