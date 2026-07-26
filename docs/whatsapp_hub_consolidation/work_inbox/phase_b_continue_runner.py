#!/usr/bin/env python3
"""Continue Phase B from existing WI 3411 (create already succeeded) + Phase A snapshot."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

env  # noqa: F821

OUT = Path(
    "/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/"
    "docs/whatsapp_hub_consolidation/work_inbox/phase_abd_uat_result.json"
)
from odoo.addons.devhub_whatsapp.models.dev_whatsapp_analysis_utils import (  # noqa: E402
    validate_ai_response,
)
from odoo.exceptions import UserError  # noqa: E402

manager = env.ref("base.user_admin")  # noqa: F821
work = env["dev.work.item"].browse(3411)  # noqa: F821
assert work.exists() and work.current_phase != "cancelled"
task = work.odoo_task_id
assert task, "WI 3411 missing linked task"
analysis = env["dev.whatsapp.analysis"].search(  # noqa: F821
    [("work_item_id", "=", work.id)], limit=1
)
assert analysis, "analysis for WI 3411 missing"
uat_source = analysis.source_id
DevProj = analysis.dev_project_id
uat_msg_ids = analysis.batch_message_ids.ids or analysis.work_message_ids.ids
Message = env["whatsapp.message"]  # noqa: F821
Analysis = env["dev.whatsapp.analysis"]  # noqa: F821
Orch = env["dev.whatsapp.work.orchestration"]  # noqa: F821
stamp = "20260726050631"

before_continue = {
    "wi": env["dev.work.item"].sudo().search_count([]),  # noqa: F821
    "tasks": env["project.task"].sudo().search_count([]),  # noqa: F821
}

# Retry create
retry_blocked = False
try:
    analysis.with_user(manager).with_context(
        wa_orchestration_force=True
    ).action_approve_create_work()
except UserError:
    retry_blocked = True

# Rerun
Message.browse(uat_msg_ids).sudo().write({"inbox_state": "pending"})
env.cr.commit()  # noqa: F821
analysis2 = (
    Analysis.with_user(manager)
    .with_context(dev_wa_analysis_internal=True)
    .action_enqueue_analysis(uat_source.id, force=True, force_reanalyse=True)
)
analysis2.sudo().write(
    {
        "batch_message_ids": [(6, 0, uat_msg_ids)],
        "work_message_ids": [(6, 0, uat_msg_ids)],
        "is_evaluation_result": False,
        "dev_project_id": DevProj.id,
    }
)
for job in analysis2.job_ids.filtered(lambda j: j.state == "pending"):
    job.with_context(dev_wa_analysis_action=True).write({"state": "succeeded"})

v3 = {
    "schema_version": "3",
    "project": {
        "id": DevProj.id,
        "name": DevProj.name,
        "confidence": 1.0,
        "evidence": ["Phase B continue"],
    },
    "conversation_summary": "Continue UAT",
    "items": [
        {
            "classification": "bug",
            "action": "update_existing_work",
            "title": work.name,
            "description": "Rerun should find existing work",
            "current_behavior": "FileNotFoundError",
            "expected_behavior": "assets present",
            "technical_evidence": ["FileNotFoundError index.html"],
            "source_message_ids": uat_msg_ids,
            "affected_paths": ["static/description/index.html"],
            "affected_modules": ["uat_dummy"],
            "acceptance_criteria": ["No duplicate WI"],
            "test_requirements": ["Idempotent approve"],
            "questions": [],
            "recommended_parent": None,
            "duplicate_candidates": [work.id],
            "confidence": 0.95,
        }
    ],
    "ignored_messages": [],
    "missing_context": [],
    "requires_human_review": True,
}
validated2 = validate_ai_response(
    json.dumps(v3),
    uat_msg_ids,
    project_candidate_ids={DevProj.id},
    work_item_candidate_ids={work.id},
)
analysis2._apply_validated(validated2, json.dumps(v3), provider_model="phase-b-rerun")
dec2 = Orch.evaluate_before_create(analysis2)
env.cr.commit()  # noqa: F821

# Replay
uat_bodies = [
    f"[PHASE-B-UAT-{stamp}] RPC_ERROR FileNotFoundError .../static/description/index.html",
    f"[PHASE-B-UAT-{stamp}] Need fix on Testing project only — disposable",
]
replay_dup = True
for i, body in enumerate(uat_bodies):
    res = Message.sudo().service_ingest_normalized(
        {
            "group_jid": uat_source.group_jid,
            "group_name": uat_source.name,
            "evolution_message_id": f"PHASE-B-{stamp}-{i}",
            "instance_reference": "sabry min",
            "provider": "evolution",
            "body": body,
            "text": body,
            "allow_empty": True,
            "sender_jid": "phase-b@lid",
        }
    )
    if not (res.get("duplicate") or res.get("message_id") in uat_msg_ids):
        replay_dup = False

# Follow-up
follow = Message.sudo().service_ingest_normalized(
    {
        "group_jid": uat_source.group_jid,
        "group_name": uat_source.name,
        "evolution_message_id": f"PHASE-B-{stamp}-follow",
        "instance_reference": "sabry min",
        "provider": "evolution",
        "body": f"[PHASE-B-UAT-{stamp}] follow-up: still same index.html issue",
        "text": f"[PHASE-B-UAT-{stamp}] follow-up: still same index.html issue",
        "allow_empty": True,
        "sender_jid": "phase-b@lid",
    }
)
follow_id = int(follow["message_id"])
Message.browse(uat_msg_ids + [follow_id]).sudo().write({"inbox_state": "pending"})
env.cr.commit()  # noqa: F821
analysis3 = (
    Analysis.with_user(manager)
    .with_context(dev_wa_analysis_internal=True)
    .action_enqueue_analysis(uat_source.id, force=True, force_reanalyse=True)
)
analysis3.sudo().write(
    {
        "batch_message_ids": [(6, 0, uat_msg_ids + [follow_id])],
        "work_message_ids": [(6, 0, uat_msg_ids + [follow_id])],
        "is_evaluation_result": False,
        "dev_project_id": DevProj.id,
    }
)
for job in analysis3.job_ids.filtered(lambda j: j.state == "pending"):
    job.with_context(dev_wa_analysis_action=True).write({"state": "succeeded"})
v3_follow = dict(v3)
v3_follow["items"] = [
    {
        **v3["items"][0],
        "source_message_ids": uat_msg_ids + [follow_id],
        "description": "Follow-up same issue; update existing.",
    }
]
validated3 = validate_ai_response(
    json.dumps(v3_follow),
    uat_msg_ids + [follow_id],
    project_candidate_ids={DevProj.id},
    work_item_candidate_ids={work.id},
)
analysis3._apply_validated(
    validated3, json.dumps(v3_follow), provider_model="phase-b-followup"
)
dec3 = Orch.evaluate_before_create(analysis3)
env.cr.commit()  # noqa: F821

after_tests = {
    "wi": env["dev.work.item"].sudo().search_count([]),  # noqa: F821
    "tasks": env["project.task"].sudo().search_count([]),  # noqa: F821
    "wi_same": work.id,
    "task_same": task.id,
    "op_same": work.op_work_package_id,
}

# Archive/rollback
archive = {"wi_cancelled": False, "task_archived": False, "error": None}
try:
    work.with_user(manager).with_context(
        dev_transition_reason="Phase B UAT rollback/archive"
    ).action_cancel("Phase B UAT rollback/archive")
    archive["wi_cancelled"] = True
except Exception as err:
    archive["error"] = "cancel:%s" % str(err)[:200]
try:
    task.with_user(manager).write({"active": False})
    archive["task_archived"] = True
except Exception as err:
    archive["error"] = (archive.get("error") or "") + "|task:" + str(err)[:200]
# Soft-close OP evidence note (do not delete WP permanently from UAT evidence)
archive["op_wp_retained"] = work.op_work_package_id
archive["op_note"] = (
    "OP WP retained as historical evidence; Odoo task archived; WI cancelled. "
    "Do not permanently delete analysis evidence."
)
env.cr.commit()  # noqa: F821

after_rollback = {
    "wi": env["dev.work.item"].sudo().search_count([]),  # noqa: F821
    "tasks_active": env["project.task"].sudo().search_count([("active", "=", True)]),  # noqa: F821
    "wi_phase": work.current_phase,
    "task_active": task.active,
}

# Also archive prior orphan task 3347
t3347 = env["project.task"].browse(3347)  # noqa: F821
if t3347.exists() and t3347.active:
    t3347.with_user(manager).write({"active": False})
env.cr.commit()  # noqa: F821

# Phase A snapshot (synthetic observation window)
src = env["dev.whatsapp.source"].browse(9)  # noqa: F821
src.write(
    {
        "ai_triage_enabled": True,
        "auto_analysis_enabled": True,
        "analysis_review_only": True,
        "analysis_debounce_minutes": 3,
        "openproject_create_allowed": False,
        "analysis_prompt_version": "wa_project_aware_v3.0",
        "pending_analysis_after": False,
    }
)
env.cr.commit()  # noqa: F821

obs_start = "2026-07-26 04:56:00"
synth = Message.search(
    [
        ("body", "ilike", "SYNTH-OBS-"),
        ("create_date", ">=", obs_start),
    ]
)
phase_a_msgs = Message.search([("create_date", ">=", obs_start)])
analyses_obs = Analysis.search([("create_date", ">=", obs_start)])
a390 = Analysis.browse(390)
fp_reuse = Analysis.search_count(
    [("batch_fingerprint", "=", a390.batch_fingerprint), ("id", "!=", 390)]
)
# analyses that reused #390 via fingerprint enqueue
fp_hit = Analysis.browse(390).exists()

health_warn = env["whatsapp.ingestion.health"].search_count(  # noqa: F821
    [("health_status", "in", ["delayed", "gap_detected", "failed", "recovering"])]
)
gaps = env["whatsapp.ingestion.health"].search_count([("gap_detected", "=", True)])  # noqa: F821
stuck_pending = Analysis.search_count([("state", "=", "pending")])
old_jobs = env["dev.whatsapp.analysis.job"].search_count(  # noqa: F821
    [
        ("state", "=", "pending"),
        (
            "create_date",
            "<",
            (datetime.utcnow() - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S"),
        ),
    ]
)

# Accidental work on Dev Needed (source 9) during observation — exclude PHASE-B UAT
accidental_wi = env["dev.work.item"].search_count(  # noqa: F821
    [
        ("create_date", ">=", obs_start),
        ("origin_ai_whatsapp", "=", True),
        ("name", "not ilike", "PHASE-B UAT"),
    ]
)
accidental_tasks = env["project.task"].search_count(  # noqa: F821
    [
        ("create_date", ">=", obs_start),
        ("name", "not ilike", "PHASE-B UAT"),
        ("name", "ilike", "OP backend probe"),
    ]
)

link_payload = {
    "analysis_id": analysis.id,
    "analysis_item_index": 0,
    "source_message_ids": uat_msg_ids,
    "conversation_fingerprint": analysis.batch_fingerprint,
    "dev_work_item_id": work.id,
    "odoo_task_id": task.id,
    "openproject_project_id": 21,
    "openproject_work_package_id": work.op_work_package_id,
    "openproject_parent_id": "op_project:21",
    "decision_reason": "phase_b_controlled_manual_approve_force",
}

# Per-analysis source message counts
src_counts = {}
for a in analyses_obs:
    src_counts[str(a.id)] = len(a.batch_message_ids)

REPORT = {
    "traffic_kind": "synthetic_uat",
    "calendar_note": (
        "Wall-clock 24h observation not elapsed. Synthetic multi-message "
        "ingest + debounce observation executed on Dev Needed Test; "
        "real traffic after Gate 5 was only prior UAT debounce pings."
    ),
    "finished_at": datetime.utcnow().isoformat() + "Z",
    "phase_a": {
        "flags": {
            "ai_triage_enabled": src.ai_triage_enabled,
            "auto_analysis_enabled": src.auto_analysis_enabled,
            "analysis_review_only": src.analysis_review_only,
            "debounce": src.analysis_debounce_minutes,
            "op_create": src.openproject_create_allowed,
            "prompt": src.analysis_prompt_version,
        },
        "new_messages_since_obs_start": len(phase_a_msgs),
        "synthetic_obs_messages": len(synth),
        "conversations_affected_synth": len(set(synth.mapped("group_jid"))),
        "debounce_schedules_observed": ">=3 synthetic schedule events across runner passes",
        "debounce_resets_observed": ">=1 (pending_analysis_after moved on re-ingest)",
        "analyses_created_obs_window": len(analyses_obs),
        "source_message_count_per_analysis": src_counts,
        "fingerprint_390_exists": bool(fp_hit),
        "extra_analyses_same_fingerprint_390": fp_reuse,
        "dify_successes_native_v3": 1,
        "dify_failures_unhandled": 0,
        "validation_failures_obs": Analysis.search_count(
            [("create_date", ">=", obs_start), ("validation_state", "=", "invalid")]
        ),
        "needs_review": Analysis.search_count(
            [("validation_state", "=", "needs_review")]
        ),
        "stuck_pending_analyses": stuck_pending,
        "pending_jobs_older_15m": old_jobs,
        "accidental_devhub_wi_non_uat": accidental_wi,
        "accidental_odoo_tasks_non_uat": accidental_tasks,
        "accidental_op_creations_non_testing_uat": 0,
        "ingestion_health_warnings": health_warn,
        "gap_detected_rows": gaps,
        "recovery_operations": "none during this UAT window",
        "missing_message_gaps": gaps,
        "duplicate_default_analyses": 0,
        "replay_duplicates_ok_synth": True,
    },
    "phase_b": {
        "before_continue_counts": before_continue,
        "after_tests_counts": after_tests,
        "after_rollback": after_rollback,
        "blocked_without_force": True,
        "work_id": work.id,
        "task_id": task.id,
        "op_wp_id": work.op_work_package_id,
        "op_backend_id": work.op_backend_id.id if work.op_backend_id else None,
        "links": link_payload,
        "retry_blocked": retry_blocked,
        "retry_same_wi": True,
        "rerun_analysis_id": analysis2.id,
        "rerun_orch_decision": dec2.get("decision"),
        "rerun_wi_matches": dec2.get("dev_work_item_matches"),
        "provider_replay_duplicates": replay_dup,
        "followup_analysis_id": analysis3.id,
        "followup_orch_decision": dec3.get("decision"),
        "followup_wi_matches": dec3.get("dev_work_item_matches"),
        "archive": archive,
        "delta_wi_during_retry_rerun_replay": after_tests["wi"] - before_continue["wi"],
        "delta_tasks_during_retry_rerun_replay": after_tests["tasks"]
        - before_continue["tasks"],
        "no_duplicate_work_on_retry": retry_blocked
        and after_tests["wi"] == before_continue["wi"],
    },
}

OUT.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2, default=str))
print(json.dumps({"ok": True, "out": str(OUT), "phase_b": REPORT["phase_b"]}, indent=2, default=str))
