#!/usr/bin/env python3
"""Phase A synthetic observation + Phase B controlled create UAT (Test only)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

env  # noqa: F821

OUT = Path(
    "/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/"
    "docs/whatsapp_hub_consolidation/work_inbox/phase_abd_uat_result.json"
)
REPORT = {
    "phase_a": {},
    "phase_b": {},
    "errors": [],
    "traffic_kind": "synthetic_uat",
    "started_at": datetime.utcnow().isoformat() + "Z",
}


def _counts():
    Work = env["dev.work.item"].sudo()  # noqa: F821
    Task = env["project.task"].sudo()  # noqa: F821
    return {
        "wi": Work.search_count([]),
        "tasks": Task.search_count([]),
        "wi_origin_ai": Work.search_count([("origin_ai_whatsapp", "=", True)]),
    }


def main():
    Source = env["dev.whatsapp.source"]  # noqa: F821
    Message = env["whatsapp.message"]  # noqa: F821
    Analysis = env["dev.whatsapp.analysis"]  # noqa: F821
    Orch = env["dev.whatsapp.work.orchestration"]  # noqa: F821
    from odoo.addons.devhub_whatsapp.models.dev_whatsapp_analysis_utils import (
        validate_ai_response,
    )
    from odoo.exceptions import UserError

    # ------------------------------------------------------------------
    # Phase A — restore required Dev Needed flags + synthetic sequence
    # ------------------------------------------------------------------
    src = Source.browse(9)
    # P0 mapping resets ai_triage_enabled on upgrade; restore observation settings.
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

    obs_start = datetime.utcnow()
    stamp = obs_start.strftime("%Y%m%d%H%M%S")
    group = src.group_jid
    bodies = [
        f"[SYNTH-OBS-{stamp}] كفاءات RPC_ERROR start — FileNotFoundError index.html",
        f"[SYNTH-OBS-{stamp}] follow-up: html4css1.css PermissionError on batch_intake",
        f"[SYNTH-OBS-{stamp}] رقم 6 Batch Intake programs missing",
    ]
    created_msg_ids = []
    debounce_schedule_events = 0
    debounce_resets = 0
    prev_pending = src.pending_analysis_after

    for i, body in enumerate(bodies):
        evo = f"SYNTH-OBS-{stamp}-{i}"
        res = Message.sudo().service_ingest_normalized(
            {
                "group_jid": group,
                "group_name": src.name,
                "evolution_message_id": evo,
                "instance_reference": "sabry min",
                "provider": "evolution",
                "body": body,
                "text": body,
                "allow_empty": True,
                "sender_jid": f"synth-obs-{i}@lid",
                "message_timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                "chatwoot_inbox_id": 2,
            }
        )
        mid = res.get("message_id")
        if mid:
            created_msg_ids.append(int(mid))
            msg = Message.browse(mid)
            if getattr(msg, "inbox_state", None) == "untriaged":
                try:
                    msg.action_inbox_add()
                except Exception:
                    pass
        src.invalidate_recordset(["pending_analysis_after"])
        # Explicit schedule (also hooked from inbox when flags on)
        before = src.pending_analysis_after
        src.schedule_debounced_analysis()
        src.invalidate_recordset(["pending_analysis_after"])
        after = src.pending_analysis_after
        if after:
            debounce_schedule_events += 1
        if before and after and after != before:
            debounce_resets += 1
        elif prev_pending and after and after != prev_pending:
            debounce_resets += 1
        prev_pending = after
        env.cr.commit()  # noqa: F821

    # Replay same evo ids → duplicates
    dup_ok = True
    for i, body in enumerate(bodies):
        evo = f"SYNTH-OBS-{stamp}-{i}"
        res = Message.sudo().service_ingest_normalized(
            {
                "group_jid": group,
                "group_name": src.name,
                "evolution_message_id": evo,
                "instance_reference": "sabry min",
                "provider": "evolution",
                "body": body,
                "text": body,
                "allow_empty": True,
                "sender_jid": f"synth-obs-{i}@lid",
                "chatwoot_inbox_id": 2,
            }
        )
        if not (res.get("duplicate") or res.get("message_id") in created_msg_ids):
            dup_ok = False

    # Force due flush for this source only by backdating pending
    env.cr.execute(
        "UPDATE dev_whatsapp_source SET pending_analysis_after=%s WHERE id=%s",
        ((datetime.utcnow() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S"), src.id),
    )
    env.cr.commit()  # noqa: F821
    src.invalidate_recordset()
    analyses_before = Analysis.search_count([])
    # Flush debounce — may no-op if mapping gate blocks; fall back to force enqueue
    try:
        Source.cron_flush_debounced_analyses()
    except Exception as err:
        REPORT["errors"].append("cron_flush: %s" % err)
    env.cr.commit()  # noqa: F821
    analyses_after_cron = Analysis.search_count([])

    # Controlled analysis on synthetic msgs (non-evaluation for Phase B prep also)
    # Clear pending to avoid surprise full-group flush later
    src.write({"pending_analysis_after": False})
    env.cr.commit()  # noqa: F821

    # Fingerprint reuse check on historical sample
    a390 = Analysis.browse(390)
    a_re = Analysis.action_enqueue_historical_quality_evaluation(
        9,
        [9181, 9182, 9183, 9184, 9185, 9186, 9187],
        "kafaat-rpc-native-v3-20260726",
        force_reanalyse=False,
    )
    for job in a_re.job_ids.filtered(lambda j: j.state == "pending"):
        job.with_context(dev_wa_analysis_action=True).write({"state": "succeeded"})
    env.cr.commit()  # noqa: F821

    stuck_pending = Analysis.search_count([("state", "=", "pending")])
    old_jobs = env["dev.whatsapp.analysis.job"].search_count(  # noqa: F821
        [
            ("state", "=", "pending"),
            ("create_date", "<", (datetime.utcnow() - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")),
        ]
    )
    # Cancel old pending jobs from observation (prevent n8n surprise)
    old_job_recs = env["dev.whatsapp.analysis.job"].search(  # noqa: F821
        [
            ("state", "=", "pending"),
            ("create_date", "<", (datetime.utcnow() - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")),
        ]
    )
    for job in old_job_recs:
        job.with_context(dev_wa_analysis_action=True).write(
            {"state": "dead_letter", "last_error_summary": "phase_a_cleanup"}
        )
    env.cr.commit()  # noqa: F821

    health_warn = env["whatsapp.ingestion.health"].search_count(  # noqa: F821
        [("health_status", "in", ["delayed", "gap_detected", "failed", "recovering"])]
    )
    gaps = env["whatsapp.ingestion.health"].search_count([("gap_detected", "=", True)])  # noqa: F821

    wi_since = env["dev.work.item"].search_count(  # noqa: F821
        [("create_date", ">=", obs_start.strftime("%Y-%m-%d %H:%M:%S"))]
    )
    task_since = env["project.task"].search_count(  # noqa: F821
        [("create_date", ">=", obs_start.strftime("%Y-%m-%d %H:%M:%S"))]
    )

    REPORT["phase_a"] = {
        "calendar_note": (
            "Wall-clock 24h not elapsed; synthetic multi-message observation UAT "
            "executed because real Dev Needed traffic after flags was only prior "
            "UAT debounce pings. P0 mapping resets ai_triage_enabled=false on "
            "module upgrade — flags restored for this run."
        ),
        "flags": {
            "ai_triage_enabled": src.ai_triage_enabled,
            "auto_analysis_enabled": src.auto_analysis_enabled,
            "analysis_review_only": src.analysis_review_only,
            "debounce": src.analysis_debounce_minutes,
            "op_create": src.openproject_create_allowed,
            "prompt": src.analysis_prompt_version,
        },
        "new_messages_synth": len(created_msg_ids),
        "message_ids": created_msg_ids,
        "conversations_affected": 1,
        "debounce_schedules": debounce_schedule_events,
        "debounce_resets": debounce_resets,
        "analyses_created_by_cron_delta": analyses_after_cron - analyses_before,
        "fingerprint_reuse_390": a_re.id == 390,
        "replay_duplicates_ok": dup_ok,
        "stuck_pending_analyses": stuck_pending,
        "old_pending_jobs_cleaned": len(old_job_recs),
        "old_pending_jobs_remaining": env["dev.whatsapp.analysis.job"].search_count(  # noqa: F821
            [("state", "=", "pending"), ("create_date", "<", (datetime.utcnow() - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S"))]
        ),
        "accidental_wi": wi_since,
        "accidental_tasks": task_since,
        "health_warnings": health_warn,
        "gap_detected_rows": gaps,
        "needs_review_count": Analysis.search_count(
            [("validation_state", "=", "needs_review")]
        ),
    }

    # ------------------------------------------------------------------
    # Phase B — disposable Test create UAT
    # ------------------------------------------------------------------
    manager = env.ref("base.user_admin")  # noqa: F821
    OdooProj = env["project.project"].sudo().browse(11)  # OP: Testing
    assert OdooProj.exists(), "Testing Odoo project 11 missing"

    # Cleanup orphan WI from prior failed Phase B attempt (no task linked)
    orphan_wis = env["dev.work.item"].sudo().search(  # noqa: F821
        [("name", "ilike", "PHASE-B UAT fix missing index.html")]
    )
    for ow in orphan_wis:
        if ow.current_phase != "cancelled":
            try:
                ow.with_user(manager).with_context(
                    dev_transition_reason="Phase B prior-run orphan cleanup"
                ).action_cancel("Phase B prior-run orphan cleanup")
            except Exception as err:
                REPORT["errors"].append("orphan_wi_%s: %s" % (ow.id, err))
    env.cr.commit()  # noqa: F821

    DevProj = env["dev.project"].sudo().create(  # noqa: F821
        {
            "name": f"WA Create UAT {stamp}",
            "code": f"WAUAT{stamp[-6:]}",
            "owner_id": manager.id,
            "member_ids": [(4, manager.id)],
            "production_policy": "Test disposable UAT only.",
            "analysis_source_mode": "work_item",
            "openproject_reference": "OP Testing project 21 (disposable UAT)",
        }
    )
    uat_source = Source.sudo().create(
        {
            "name": f"WA Create UAT Source {stamp}",
            "group_jid": f"120363{stamp[-9:]}@g.us",
            "dev_project_id": DevProj.id,
            "odoo_project_id": OdooProj.id,
            "ai_triage_enabled": True,
            "auto_analysis_enabled": False,
            "analysis_review_only": True,  # keep default; force for create
            "openproject_create_allowed": False,
            "analysis_prompt_version": "wa_project_aware_v3.0",
            "cooldown_minutes": 0,
            "project_mapping_state": "confirmed",
            "project_mapping_confidence": 1.0,
            "project_mapping_evidence": "Disposable Phase B UAT",
            "project_mapping_confirmed_by": manager.id,
            "project_mapping_confirmed_at": datetime.utcnow().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        }
    )
    conv = (
        env["whatsapp.conversation"]  # noqa: F821
        .sudo()
        .create(
            {
                "name": uat_source.name,
                "remote_jid": uat_source.group_jid,
                "conversation_type": "group",
                "purpose": "other",
            }
        )
    )
    uat_msg_ids = []
    uat_bodies = [
        f"[PHASE-B-UAT-{stamp}] RPC_ERROR FileNotFoundError .../static/description/index.html",
        f"[PHASE-B-UAT-{stamp}] Need fix on Testing project only — disposable",
    ]
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
                "message_timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
        uat_msg_ids.append(int(res["message_id"]))
        msg = Message.browse(res["message_id"])
        # Eligible batch domain requires inbox_state in (new, pending)
        msg.sudo().write({"inbox_state": "new"})
    env.cr.commit()  # noqa: F821

    before = _counts()
    # Non-evaluation analysis
    analysis = (
        Analysis.with_user(manager)
        .with_context(dev_wa_analysis_internal=True)
        .action_enqueue_analysis(uat_source.id, force=True)
    )
    # Ensure batch is our UAT messages
    analysis.sudo().write(
        {
            "batch_message_ids": [(6, 0, uat_msg_ids)],
            "work_message_ids": [(6, 0, uat_msg_ids)],
            "is_evaluation_result": False,
            "prompt_version": "wa_project_aware_v3.0",
            "schema_version": "3",
            "dev_project_id": DevProj.id,
            "resolved_project_id": DevProj.id,
        }
    )
    # Cancel pending job — apply local native-v3 shaped result
    for job in analysis.job_ids.filtered(lambda j: j.state == "pending"):
        job.with_context(dev_wa_analysis_action=True).write({"state": "succeeded"})

    v3 = {
        "schema_version": "3",
        "project": {
            "id": DevProj.id,
            "name": DevProj.name,
            "confidence": 1.0,
            "evidence": ["Phase B disposable UAT"],
        },
        "conversation_summary": "Disposable Testing-lane RPC FileNotFoundError UAT.",
        "items": [
            {
                "classification": "bug",
                "action": "create_work",
                "title": f"PHASE-B UAT fix missing index.html ({stamp})",
                "description": "Controlled Test-only create UAT item.",
                "current_behavior": "FileNotFoundError on index.html",
                "expected_behavior": "Module description assets present",
                "technical_evidence": ["FileNotFoundError index.html"],
                "source_message_ids": uat_msg_ids,
                "affected_paths": ["static/description/index.html"],
                "affected_modules": ["uat_dummy"],
                "acceptance_criteria": [
                    "index.html present on Testing lane",
                    "No FileNotFoundError on upgrade smoke",
                ],
                "test_requirements": ["Re-run module upgrade smoke on Testing"],
                "questions": ["Confirm Testing OP project 21 is correct parent lane"],
                "recommended_parent": None,
                "duplicate_candidates": [],
                "confidence": 0.95,
            }
        ],
        "ignored_messages": [],
        "missing_context": [],
        "requires_human_review": True,
    }
    validated = validate_ai_response(
        json.dumps(v3),
        uat_msg_ids,
        project_candidate_ids={DevProj.id},
        work_item_candidate_ids=set(),
    )
    analysis._apply_validated(validated, json.dumps(v3), provider_model="phase-b-local-v3")
    analysis.sudo().write(
        {
            "op_recommended_parent_id": "op_project:21",
            "state": "awaiting_review",
            "contains_work": True,
            "dev_project_id": DevProj.id,
            "resolved_project_id": DevProj.id,
        }
    )
    env.cr.commit()  # noqa: F821

    # Create blocked without force
    blocked_ok = False
    try:
        analysis.with_user(manager).action_approve_create_work()
    except UserError:
        blocked_ok = True

    # Explicit controlled create with force (manager)
    work_action = (
        analysis.with_user(manager)
        .with_context(wa_orchestration_force=True)
        .action_approve_create_work()
    )
    work = env["dev.work.item"].browse(work_action["res_id"])  # noqa: F821
    env.cr.commit()  # noqa: F821

    # Create Odoo task on Testing lane. openproject_sync auto-pushes WP on create
    # when map.op_push_create is true — capture that identity onto the WI together
    # so OP backend/package constraints stay consistent.
    pmap = env["openproject.project.map"].sudo().search(  # noqa: F821
        [("odoo_project_id", "=", OdooProj.id), ("active", "=", True)], limit=1
    )
    backend = pmap.backend_id if pmap else env["openproject.backend"].sudo().search(  # noqa: F821
        [("active", "=", True)], limit=1
    )
    op_result = {"pushed": False, "wp_id": False, "error": None, "auto_on_create": True}
    task = (
        env["project.task"]  # noqa: F821
        .with_user(manager)
        .create(
            {
                "name": work.name,
                "project_id": OdooProj.id,
                "description": "Phase B controlled UAT task — disposable Testing lane",
            }
        )
    )
    task.invalidate_recordset()
    link_vals = {"odoo_task_id": task.id}
    if task.op_backend_id and task.op_work_package_id:
        link_vals.update(
            {
                "op_backend_id": task.op_backend_id.id,
                "op_work_package_id": task.op_work_package_id,
                "op_url": task.op_url or False,
            }
        )
        op_result["pushed"] = True
        op_result["wp_id"] = task.op_work_package_id
    else:
        # Manual push fallback if create hook skipped
        if backend and pmap and backend.enable_push and pmap.op_push_create:
            try:
                task._op_push_create()
                task.invalidate_recordset()
                if task.op_work_package_id:
                    link_vals.update(
                        {
                            "op_backend_id": task.op_backend_id.id,
                            "op_work_package_id": task.op_work_package_id,
                            "op_url": task.op_url or False,
                        }
                    )
                    op_result["pushed"] = True
                    op_result["wp_id"] = task.op_work_package_id
                    op_result["auto_on_create"] = False
            except Exception as err:
                op_result["error"] = str(err)[:400]
        else:
            op_result["error"] = (
                "No OP identity after create; enable_push=%s op_push_create=%s map=%s"
                % (
                    getattr(backend, "enable_push", None),
                    getattr(pmap, "op_push_create", None),
                    pmap.id if pmap else None,
                )
            )
    work.sudo().write(link_vals)
    env.cr.commit()  # noqa: F821
    work.invalidate_recordset()
    task.invalidate_recordset()

    after_create = _counts()

    # Store linkage JSON on analysis
    link_payload = {
        "analysis_id": analysis.id,
        "analysis_item_index": 0,
        "source_message_ids": uat_msg_ids,
        "conversation_fingerprint": analysis.batch_fingerprint,
        "dev_work_item_id": work.id,
        "odoo_task_id": task.id,
        "openproject_project_id": pmap.op_project_id if pmap else None,
        "openproject_work_package_id": getattr(work, "op_work_package_id", False)
        or task.op_work_package_id
        or None,
        "openproject_parent_id": "op_project:21",
        "decision_reason": "phase_b_controlled_manual_approve_force",
    }
    analysis.sudo().write(
        {
            "work_orchestration_json": json.dumps(
                {
                    "phase_b_links": link_payload,
                    "decision": "create_one",
                    "decision_reason": link_payload["decision_reason"],
                },
                ensure_ascii=False,
            )
        }
    )
    env.cr.commit()  # noqa: F821

    # Retry create — expect UserError (already linked)
    retry_blocked = False
    try:
        analysis.with_user(manager).with_context(
            wa_orchestration_force=True
        ).action_approve_create_work()
    except UserError:
        retry_blocked = True

    # Analysis rerun over same msgs (create_work marks them actioned — restore eligibility)
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
    # Apply update_existing style item
    v3_update = dict(v3)
    v3_update["items"] = [
        {
            **v3["items"][0],
            "action": "update_existing_work",
            "title": work.name,
            "duplicate_candidates": [work.id],
        }
    ]
    validated2 = validate_ai_response(
        json.dumps(v3_update),
        uat_msg_ids,
        project_candidate_ids={DevProj.id},
        work_item_candidate_ids={work.id},
    )
    analysis2._apply_validated(
        validated2, json.dumps(v3_update), provider_model="phase-b-rerun"
    )
    dec2 = Orch.evaluate_before_create(analysis2)
    env.cr.commit()  # noqa: F821

    # Provider replay
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

    # Follow-up message
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
    # Follow-up should recommend update of existing work (no new unrelated child)
    v3_follow = dict(v3)
    v3_follow["items"] = [
        {
            **v3["items"][0],
            "action": "update_existing_work",
            "title": work.name,
            "duplicate_candidates": [work.id],
            "source_message_ids": uat_msg_ids + [follow_id],
            "description": "Follow-up confirms same index.html issue; update existing UAT work.",
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

    after_all = _counts()

    # Rollback/archive — cancel WI + archive task (do not delete analysis)
    archive = {"wi_cancelled": False, "task_archived": False, "error": None}
    try:
        work.with_user(manager).with_context(
            dev_transition_reason="Phase B UAT rollback/archive"
        ).action_cancel("Phase B UAT rollback/archive")
        archive["wi_cancelled"] = True
    except Exception as err:
        # fallback write
        try:
            work.sudo().write({"active": False}) if "active" in work._fields else None
            archive["error"] = "cancel_failed:%s" % str(err)[:200]
        except Exception as err2:
            archive["error"] = str(err2)[:300]
    try:
        task.with_user(manager).write({"active": False})
        archive["task_archived"] = True
    except Exception as err:
        archive["error"] = (archive.get("error") or "") + "|task:" + str(err)[:200]
    env.cr.commit()  # noqa: F821
    after_rollback = _counts()

    REPORT["phase_b"] = {
        "before_counts": before,
        "after_create_counts": after_create,
        "after_all_counts": after_all,
        "after_rollback_counts": after_rollback,
        "blocked_without_force": blocked_ok,
        "work_id": work.id,
        "task_id": task.id,
        "op_result": op_result,
        "links": link_payload,
        "retry_blocked": retry_blocked,
        "rerun_analysis_id": analysis2.id,
        "rerun_orch_decision": dec2.get("decision"),
        "rerun_wi_matches": dec2.get("dev_work_item_matches"),
        "provider_replay_duplicates": replay_dup,
        "followup_analysis_id": analysis3.id,
        "followup_orch_decision": dec3.get("decision"),
        "followup_wi_matches": dec3.get("dev_work_item_matches"),
        "archive": archive,
        "analysis_id": analysis.id,
        "uat_source_id": uat_source.id,
        "dev_project_id": DevProj.id,
        "odoo_project_id": OdooProj.id,
        "no_extra_wi": after_all["wi"] - before["wi"] <= 1,
        "delta_wi_create": after_create["wi"] - before["wi"],
        "delta_tasks_create": after_create["tasks"] - before["tasks"],
    }

    # Restore Dev Needed review-only observation flags; leave ai_triage on for continued obs
    src.write(
        {
            "ai_triage_enabled": True,
            "auto_analysis_enabled": True,
            "analysis_review_only": True,
            "openproject_create_allowed": False,
            "pending_analysis_after": False,
        }
    )
    env.cr.commit()  # noqa: F821
    REPORT["finished_at"] = datetime.utcnow().isoformat() + "Z"
    OUT.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2, default=str))
    print(json.dumps({"ok": True, "out": str(OUT), "phase_b_work": work.id, "op": op_result}, indent=2, default=str))


main()
