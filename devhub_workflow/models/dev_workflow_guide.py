# -*- coding: utf-8 -*-
"""Interactive walkthrough payload: WhatsApp → completed delivery."""
from __future__ import annotations

from odoo import api, models


class DevWorkflowBoardWalkthrough(models.Model):
    _inherit = "dev.workflow.board"

    @api.model
    def get_walkthrough(self, work_item_id=None):
        """Return guided steps from WhatsApp intake through completion.

        Soft-discovers installed capability models. Never hard-fails if optional
        modules (WhatsApp, Git, Deploy) are absent.
        """
        Work = self.env["dev.work.item"] if "dev.work.item" in self.env else None
        work_items = []
        work = None
        if Work is not None:
            rows = Work.search([], order="write_date desc, id desc", limit=40)
            work_items = [
                {
                    "id": row.id,
                    "name": row.display_name,
                    "phase": row.current_phase,
                    "phase_label": dict(row._fields["current_phase"].selection).get(
                        row.current_phase, row.current_phase
                    ),
                }
                for row in rows
            ]
            if work_item_id:
                work = Work.browse(int(work_item_id)).exists()
            if not work and rows:
                work = rows[:1]

        steps = self._walkthrough_steps(work)
        current = next(
            (step["key"] for step in steps if step["status"] in ("current", "blocked")),
            steps[-1]["key"] if steps else None,
        )
        return {
            "work_items": work_items,
            "selected_id": work.id if work else False,
            "selected_name": work.display_name if work else False,
            "selected_phase": work.current_phase if work else False,
            "path_label": (
                "WhatsApp → Work → Analysis → Plan → Approval → Session → "
                "Execution → Git → GitHub → Deploy → Complete"
            ),
            "current_step_key": current,
            "steps": steps,
            "hint": (
                "Pick a work item, follow the highlighted step, click Open when ready. "
                "If a step is blocked, finish the missing items listed first."
            ),
        }

    def _act_window(self, name, model, res_id=None, domain=None, context=None, view_mode="list,form"):
        action = {
            "type": "ir.actions.act_window",
            "name": name,
            "res_model": model,
            "view_mode": view_mode if not res_id else "form",
            "target": "current",
        }
        if res_id:
            action["res_id"] = int(res_id)
        if domain is not None:
            action["domain"] = domain
        if context:
            action["context"] = context
        return action

    def _walkthrough_steps(self, work):
        phase = work.current_phase if work else None
        env = self.env

        def installed(model_name):
            return model_name in env

        # --- WhatsApp ---
        wa_installed = installed("dev.whatsapp.intake")
        wa_status = "skipped"
        wa_missing = []
        wa_detail = "WhatsApp intake module is not installed — skip or create Work manually."
        wa_action = None
        wa_count = 0
        if wa_installed:
            Intake = env["dev.whatsapp.intake"]
            if work:
                intakes = Intake.search([("work_item_id", "=", work.id)], limit=5)
                pending = Intake.search_count(
                    [("state", "in", ("received", "collecting", "draft_ready", "awaiting_confirm"))]
                )
                wa_count = len(intakes)
                if intakes.filtered(lambda r: r.state in ("confirmed", "merged")) or work:
                    wa_status = "done"
                    wa_detail = "Linked WhatsApp intake confirmed/merged into this work item (or work already exists)."
                elif pending:
                    wa_status = "current"
                    wa_detail = (
                        "%s intake candidate(s) waiting. Confirm an intake to create/link a Work Item."
                        % pending
                    )
                    wa_missing = ["Open DH WhatsApp → confirm an intake candidate"]
                else:
                    wa_status = "pending"
                    wa_detail = "No open intake for this item. New group messages appear here when classified."
                wa_action = self._act_window(
                    "WhatsApp Intake",
                    "dev.whatsapp.intake",
                    res_id=intakes[:1].id if intakes else None,
                    domain=[("work_item_id", "=", work.id)] if intakes else None,
                )
            else:
                pending = Intake.search_count(
                    [("state", "in", ("received", "collecting", "draft_ready", "awaiting_confirm"))]
                )
                wa_count = pending
                if pending:
                    wa_status = "current"
                    wa_detail = "%s intake(s) need attention. Start here from WhatsApp." % pending
                    wa_missing = ["Confirm a WhatsApp intake to create a Work Item"]
                else:
                    wa_status = "pending"
                    wa_detail = "Waiting for a whitelisted WhatsApp message, or create Work manually in DH Work."
                wa_action = self._act_window("WhatsApp Intake", "dev.whatsapp.intake")

        # --- Work ---
        work_status = "pending"
        work_missing = []
        work_detail = "Create or open a Dev Hub Work Item."
        work_action = self._act_window("Work Items", "dev.work.item") if installed("dev.work.item") else None
        if not work:
            if wa_status == "current":
                work_status = "blocked"
                work_missing = ["Complete WhatsApp intake confirmation first (or create Work manually)"]
                work_detail = "No work item selected yet."
            else:
                work_status = "current"
                work_missing = ["Select or create a Work Item in DH Work"]
        else:
            work_action = self._act_window("Work Item", "dev.work.item", res_id=work.id)
            if phase in ("cancelled",):
                work_status = "blocked"
                work_detail = "This work item is cancelled."
                work_missing = ["Pick another work item"]
            else:
                work_status = "done"
                work_detail = "Work item active · phase: %s" % phase

        # --- Analysis ---
        analysis_status = "pending"
        analysis_missing = []
        analysis_detail = "Write and Accept an Analysis while the work item is Analyzing."
        analysis_action = None
        analysis_id = False
        if not installed("dev.work.analysis"):
            analysis_status = "skipped"
            analysis_detail = "Analysis module not installed."
        elif not work:
            analysis_status = "blocked"
            analysis_missing = ["Create/select a Work Item first"]
        else:
            analysis_recs = env["dev.work.analysis"].search(
                [("work_item_id", "=", work.id)], order="revision desc, id desc"
            )
            accepted = analysis_recs.filtered(lambda a: a.status == "accepted")
            drafts = analysis_recs.filtered(
                lambda a: a.status in ("draft", "generated", "reviewed")
            )
            analysis_id = (accepted[:1] or drafts[:1] or analysis_recs[:1]).id or False
            analysis_action = self._act_window(
                "Analysis",
                "dev.work.analysis",
                res_id=analysis_id,
                domain=[("work_item_id", "=", work.id)],
            )
            if accepted:
                analysis_status = "done"
                analysis_detail = "Accepted analysis revision ready for planning."
            elif phase == "analyzing" or drafts:
                analysis_status = "current" if work_status == "done" else "blocked"
                analysis_detail = "Fill findings, then click Accept Analysis (work item must be Analyzing)."
                if phase != "analyzing":
                    analysis_missing.append("Move Work Item to Analyzing")
                analysis_missing.append("Accept an Analysis revision")
            else:
                analysis_status = "current" if work_status == "done" and phase in (
                    "received", "triage", "registered", "analyzing", "planning"
                ) else "blocked"
                analysis_detail = "No analysis yet. Open DH Analysis and create one for this work item."
                analysis_missing = ["Create Analysis", "Accept Analysis"]
                if phase not in ("analyzing", "planning", "awaiting_plan_approval", "approved"):
                    if phase not in ("received", "triage", "registered"):
                        analysis_missing.insert(0, "Move Work Item toward Analyzing")

        # --- Plan ---
        plan_status = "pending"
        plan_missing = []
        plan_detail = "Create a complete Plan with steps, then Request Approval."
        plan_action = None
        plan_id = False
        if not installed("dev.work.plan"):
            plan_status = "skipped"
            plan_detail = "Plan module not installed."
        elif not work:
            plan_status = "blocked"
            plan_missing = ["Complete Work first"]
        else:
            plan_recs = env["dev.work.plan"].search(
                [("work_item_id", "=", work.id)], order="revision desc, id desc"
            )
            approved = plan_recs.filtered(lambda p: p.status == "approved")
            awaiting = plan_recs.filtered(lambda p: p.status == "awaiting_approval")
            drafts = plan_recs.filtered(lambda p: p.status == "draft")
            plan_id = (approved[:1] or awaiting[:1] or drafts[:1] or plan_recs[:1]).id or False
            plan_action = self._act_window(
                "Plan", "dev.work.plan", res_id=plan_id, domain=[("work_item_id", "=", work.id)]
            )
            if approved:
                plan_status = "done"
                plan_detail = "Approved plan (exact hash) is locked for execution."
            elif awaiting:
                plan_status = "done"
                plan_detail = "Plan submitted — waiting for Approval step."
            elif analysis_status != "done":
                plan_status = "blocked"
                plan_missing = ["Accept Analysis first"]
                plan_detail = "Plan is blocked until Analysis is accepted."
            else:
                plan_status = "current"
                plan_detail = "Complete all plan fields + at least one step, set phase to Planning, Request Approval."
                if phase != "planning":
                    plan_missing.append("Move Work Item to Planning")
                plan_missing.extend(["Fill required plan fields", "Add plan steps", "Request Approval"])

        # --- Approval ---
        approval_status = "pending"
        approval_missing = []
        approval_detail = "Approve the exact plan hash (DH Approval / Approve Exact Hash)."
        approval_action = None
        if not installed("dev.work.approval"):
            approval_status = "skipped"
            approval_detail = "Approval module not installed."
        elif not work:
            approval_status = "blocked"
            approval_missing = ["Complete earlier steps first"]
        else:
            approvals = env["dev.work.approval"].search(
                [("work_item_id", "=", work.id), ("decision", "=", "approved")], limit=1
            )
            approval_action = self._act_window(
                "Plan Approvals",
                "dev.work.approval",
                res_id=approvals.id if approvals else False,
                domain=[("work_item_id", "=", work.id)],
            )
            plan_awaiting = env["dev.work.plan"].search_count(
                [("work_item_id", "=", work.id), ("status", "=", "awaiting_approval")]
            )
            plan_approved = env["dev.work.plan"].search_count(
                [("work_item_id", "=", work.id), ("status", "=", "approved")]
            )
            if approvals or plan_approved:
                approval_status = "done"
                approval_detail = "Exact-hash plan approval recorded."
            elif phase == "awaiting_plan_approval" or plan_awaiting:
                approval_status = "current"
                approval_detail = "Plan is awaiting approval. Approver uses Approve Exact Hash."
                approval_missing = ["Approve Exact Hash on the submitted plan"]
            else:
                approval_status = "blocked"
                approval_missing = ["Submit Plan for approval first"]
                approval_detail = "No plan waiting for approval yet."

        # --- Session ---
        session_status = "pending"
        session_missing = []
        session_detail = "Create/start an isolated development session for this work."
        session_action = None
        if not installed("dev.session"):
            session_status = "skipped"
            session_detail = "Sessions module not installed."
        elif not work:
            session_status = "blocked"
            session_missing = ["Complete Approval first"]
        else:
            sessions = env["dev.session"].search([("work_item_id", "=", work.id)], limit=1, order="id desc")
            session_action = self._act_window(
                "Session", "dev.session", res_id=sessions.id if sessions else False,
                domain=[("work_item_id", "=", work.id)],
            )
            if sessions:
                session_status = "done"
                session_detail = "Session exists · state: %s" % sessions.state
            elif approval_status == "done" and phase in (
                "approved", "implementing", "paused", "testing", "ready_for_review", "completed"
            ):
                session_status = "current"
                session_detail = "Plan approved. Create and start an isolated session."
                session_missing = ["Create & start isolated session"]
            else:
                session_status = "blocked"
                session_missing = ["Approve plan first"]
                session_detail = "Session unlocks after plan approval."

        # --- Execution ---
        exec_status = "pending"
        exec_missing = []
        exec_detail = "Prepare the exact execution workspace / worktree."
        exec_action = None
        ws = None
        if not installed("dev.execution.workspace"):
            exec_status = "skipped"
            exec_detail = "Execution module not installed."
        elif not work:
            exec_status = "blocked"
            exec_missing = ["Complete earlier steps"]
        else:
            ws = env["dev.execution.workspace"].search(
                [("work_item_id", "=", work.id)], limit=1, order="id desc"
            )
            exec_action = self._act_window(
                "Execution Workspace",
                "dev.execution.workspace",
                res_id=ws.id if ws else False,
                domain=[("work_item_id", "=", work.id)],
            )
            if ws:
                exec_status = "done"
                exec_detail = "Workspace %s · state: %s" % (ws.display_name, ws.state)
            elif session_status == "done" or approval_status == "done":
                exec_status = "current"
                exec_detail = "Prepare execution workspace from the approved plan."
                exec_missing = ["Prepare / confirm execution workspace"]
            else:
                exec_status = "blocked"
                exec_missing = ["Approve plan / start session first"]

        # --- Git ---
        git_status = "pending"
        git_missing = []
        git_detail = "Review changes, approve commit, create commit, then push."
        git_action = None
        if not installed("dev.git.commit.record"):
            git_status = "skipped"
            git_detail = "Git module not installed."
        elif not work:
            git_status = "blocked"
            git_missing = ["Complete Execution first"]
        else:
            commits = env["dev.git.commit.record"].search(
                [("work_item_id", "=", work.id)], limit=1, order="id desc"
            )
            git_action = self._act_window(
                "Git Commits",
                "dev.git.commit.record",
                res_id=commits.id if commits else False,
                domain=[("work_item_id", "=", work.id)],
            )
            pushed = False
            if installed("dev.git.push.record"):
                pushed = bool(
                    env["dev.git.push.record"].search_count([("work_item_id", "=", work.id)])
                )
            if ws and ws.state in (
                "pushed_reviewed",
                "pr_approved",
                "pr_created_reviewed",
                "merge_approved",
                "merged_reviewed",
                "deployed_staging_reviewed",
            ):
                git_status = "done"
                git_detail = "Commit/push path reached (workspace: %s)." % ws.state
            elif commits and pushed:
                git_status = "done"
                git_detail = "Commit and push records present."
            elif commits:
                git_status = "current"
                git_detail = "Commit done — approve and execute push next."
                git_missing = ["Approve & push the commit"]
            elif ws and ws.state in (
                "review_required",
                "commit_approved",
                "committed_reviewed",
                "push_approved",
                "ready",
                "active",
                "paused",
            ):
                git_status = "current"
                git_detail = "Use workspace Git actions: review → commit approval → commit → push."
                git_missing = ["Complete governed commit/push on the workspace"]
            elif exec_status == "done":
                git_status = "current"
                git_detail = "Workspace ready — implement then run Git commit/push gates."
                git_missing = ["Mark review required and complete Git gates"]
            else:
                git_status = "blocked"
                git_missing = ["Prepare execution workspace first"]

        # --- GitHub PR ---
        pr_status = "pending"
        pr_missing = []
        pr_detail = "Create GitHub App PR to staging (not gh CLI)."
        pr_action = None
        if not installed("dev.git.pr.record"):
            pr_status = "skipped"
            pr_detail = "GitHub module not installed."
        elif not work:
            pr_status = "blocked"
            pr_missing = ["Complete Git push first"]
        else:
            prs = env["dev.git.pr.record"].search(
                [("work_item_id", "=", work.id)], limit=1, order="id desc"
            )
            pr_action = self._act_window(
                "PR Records", "dev.git.pr.record", res_id=prs.id if prs else False,
                domain=[("work_item_id", "=", work.id)],
            )
            if prs or (ws and ws.state in (
                "pr_created_reviewed", "merge_approved", "merged_reviewed", "deployed_staging_reviewed"
            )):
                pr_status = "done"
                pr_detail = "PR created via GitHub App." + (
                    " #%s" % prs.pr_number if prs and hasattr(prs, "pr_number") and prs.pr_number else ""
                )
            elif git_status == "done" or (ws and ws.state == "pushed_reviewed"):
                pr_status = "current"
                pr_detail = "Push reviewed — approve and create the GitHub App PR."
                pr_missing = ["Approve PR creation", "Create approved PR"]
            else:
                pr_status = "blocked"
                pr_missing = ["Finish Git push first"]

        # --- Merge ---
        merge_status = "pending"
        merge_missing = []
        merge_detail = "Human merge approval (requester ≠ approver), then governed squash merge."
        merge_action = None
        if not installed("dev.git.merge.record"):
            merge_status = "skipped"
            merge_detail = "Merge capability not installed."
        elif not work:
            merge_status = "blocked"
            merge_missing = ["Create PR first"]
        else:
            merges = env["dev.git.merge.record"].search(
                [("work_item_id", "=", work.id)], limit=1, order="id desc"
            )
            merge_action = self._act_window(
                "Merge Records",
                "dev.git.merge.record",
                res_id=merges.id if merges else False,
                domain=[("work_item_id", "=", work.id)],
            )
            if merges or (ws and ws.state in ("merged_reviewed", "deployed_staging_reviewed")):
                merge_status = "done"
                merge_detail = "Governed merge completed."
            elif pr_status == "done" or (ws and ws.state in ("pr_created_reviewed", "merge_approved")):
                merge_status = "current"
                merge_detail = "Request merge review, approve exact squash, execute merge."
                merge_missing = [
                    "Merge approval (different user from requester)",
                    "Execute governed squash merge",
                ]
            else:
                merge_status = "blocked"
                merge_missing = ["Create GitHub PR first"]

        # --- Deploy ---
        deploy_status = "pending"
        deploy_missing = []
        deploy_detail = "Test/Staging deploy only (never Production from this control plane)."
        deploy_action = None
        if not installed("dev.deploy.record"):
            deploy_status = "skipped"
            deploy_detail = "Deploy module not installed."
        elif not work:
            deploy_status = "blocked"
            deploy_missing = ["Merge first"]
        else:
            deploys = env["dev.deploy.record"].search([], order="id desc", limit=20)
            # Prefer workspace-linked if field exists
            linked = deploys.filtered(
                lambda d: getattr(d, "workspace_id", False)
                and d.workspace_id
                and d.workspace_id.work_item_id.id == work.id
            ) if deploys else deploys
            rec = linked[:1] or env["dev.deploy.record"]
            deploy_action = self._act_window(
                "Deploy Records",
                "dev.deploy.record",
                res_id=rec.id if rec else False,
            )
            if (rec and getattr(rec, "result_state", "") == "succeeded") or (
                ws and ws.state == "deployed_staging_reviewed"
            ):
                deploy_status = "done"
                deploy_detail = "Test/Staging deploy succeeded."
            elif merge_status == "done" or (ws and ws.state == "merged_reviewed"):
                deploy_status = "current"
                deploy_detail = "Merged — approve and run Test staging deploy."
                deploy_missing = ["Approve Test deploy", "Execute staging deploy"]
            else:
                deploy_status = "blocked"
                deploy_missing = ["Complete governed merge first"]

        # --- Complete ---
        complete_status = "pending"
        complete_missing = []
        complete_detail = "Mark ready for review, approval completion report, then Completed."
        complete_action = (
            self._act_window("Work Item", "dev.work.item", res_id=work.id) if work else None
        )
        if not work:
            complete_status = "blocked"
            complete_missing = ["Finish delivery path first"]
        elif phase in ("completed", "reported"):
            complete_status = "done"
            complete_detail = "Work item completed."
        elif phase == "ready_for_review":
            complete_status = "current"
            complete_detail = "Ready for review — finish completion report approval."
            complete_missing = ["Approve completion report", "Mark Completed"]
        elif deploy_status == "done" or phase in ("testing", "ready_for_review"):
            complete_status = "current"
            complete_detail = "Deploy done / testing — hand off for review and complete."
            complete_missing = ["Ready for review", "Complete work item"]
        else:
            complete_status = "blocked"
            complete_missing = ["Finish Deploy (or testing) before completion"]
            complete_detail = "Completion unlocks after delivery evidence."

        ordered = [
            {
                "key": "whatsapp",
                "seq": 10,
                "title": "WhatsApp message",
                "app": "DH WhatsApp",
                "explain": (
                    "Whitelisted group messages land in WhatsApp Hub, then Dev Hub intake "
                    "classifies and drafts a candidate. Confirm it to create/link a Work Item."
                ),
                "status": wa_status,
                "detail": wa_detail,
                "missing": wa_missing,
                "count": wa_count,
                "action": wa_action,
            },
            {
                "key": "work",
                "seq": 20,
                "title": "Work Item",
                "app": "DH Work",
                "explain": (
                    "The Work Item owns the lifecycle. Move phases intentionally: "
                    "Received → … → Analyzing → Planning → Approval → Implementing → Completed."
                ),
                "status": work_status,
                "detail": work_detail,
                "missing": work_missing,
                "action": work_action,
            },
            {
                "key": "analysis",
                "seq": 30,
                "title": "Analysis",
                "app": "DH Analysis",
                "explain": (
                    "Capture problem, findings, and risks. Accept Analysis only in Analyzing phase. "
                    "Accepted analysis unblocks planning."
                ),
                "status": analysis_status,
                "detail": analysis_detail,
                "missing": analysis_missing,
                "action": analysis_action,
            },
            {
                "key": "plan",
                "seq": 40,
                "title": "Plan",
                "app": "DH Plan",
                "explain": (
                    "Write a complete plan with steps. Request Approval only when phase is Planning "
                    "and Analysis is accepted. Incomplete fields block submit."
                ),
                "status": plan_status,
                "detail": plan_detail,
                "missing": plan_missing,
                "action": plan_action,
            },
            {
                "key": "approval",
                "seq": 50,
                "title": "Plan Approval",
                "app": "DH Approval",
                "explain": (
                    "Human approves the exact plan content hash. Stale hashes are rejected. "
                    "This is the gate before execution."
                ),
                "status": approval_status,
                "detail": approval_detail,
                "missing": approval_missing,
                "action": approval_action,
            },
            {
                "key": "session",
                "seq": 60,
                "title": "Session",
                "app": "DH Sessions",
                "explain": (
                    "Start an isolated session bound to the approved execution workspace path. "
                    "No silent fallback to the main repo."
                ),
                "status": session_status,
                "detail": session_detail,
                "missing": session_missing,
                "action": session_action,
            },
            {
                "key": "execution",
                "seq": 70,
                "title": "Execution workspace",
                "app": "DH Execution",
                "explain": (
                    "Confirm the exact branch/worktree. Implementation happens here under policy."
                ),
                "status": exec_status,
                "detail": exec_detail,
                "missing": exec_missing,
                "action": exec_action,
            },
            {
                "key": "git",
                "seq": 80,
                "title": "Git commit & push",
                "app": "DH Git",
                "explain": (
                    "Governed local commit then push: review → approve → execute. "
                    "No silent git mutations outside approvals."
                ),
                "status": git_status,
                "detail": git_detail,
                "missing": git_missing,
                "action": git_action,
            },
            {
                "key": "github_pr",
                "seq": 90,
                "title": "GitHub App PR",
                "app": "DH GitHub",
                "explain": (
                    "Create an open PR with the GitHub App broker (not gh). Target staging for Test."
                ),
                "status": pr_status,
                "detail": pr_detail,
                "missing": pr_missing,
                "action": pr_action,
            },
            {
                "key": "merge",
                "seq": 100,
                "title": "Governed merge",
                "app": "DH GitHub",
                "explain": (
                    "Requester ≠ approver. Exact squash merge to staging, then merge record."
                ),
                "status": merge_status,
                "detail": merge_detail,
                "missing": merge_missing,
                "action": merge_action,
            },
            {
                "key": "deploy",
                "seq": 110,
                "title": "Test deploy",
                "app": "DH Deploy",
                "explain": (
                    "Deploy the merged SHA to Test/Staging only. Production deploy stays gated off."
                ),
                "status": deploy_status,
                "detail": deploy_detail,
                "missing": deploy_missing,
                "action": deploy_action,
            },
            {
                "key": "complete",
                "seq": 120,
                "title": "Complete",
                "app": "DH Work",
                "explain": (
                    "Ready for review → completion report → mark Completed. "
                    "This closes the governed delivery loop."
                ),
                "status": complete_status,
                "detail": complete_detail,
                "missing": complete_missing,
                "action": complete_action,
            },
        ]
        return ordered
