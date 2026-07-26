    def action_open_openproject(self):
        self.ensure_one()
        url = self.op_url or self.odoo_task_id.op_url
        if not url:
            raise UserError("No OpenProject URL is available.")
        return {"type": "ir.actions.act_url", "url": url, "target": "new"}
    def _prepare_op_milestone(self, milestone, summary, status_hint=None, link=None):
        self.ensure_one()
        if not self.op_backend_id or not self.op_work_package_id:
            raise UserError("An OP identity is required to prepare a milestone.")
        if milestone not in ("analysis_plan_ready", "material_blocker", "completion"):
            raise ValidationError("Only sparse approved OpenProject milestones are allowed.")
        summary = _clean_text(summary, "OpenProject milestone summary", 2000)
        payload = {
            "schema": "dev-hub.op-milestone.v1",
            "backend_id": self.op_backend_id.id,
            "work_package_id": self.op_work_package_id,
            "milestone": milestone,
            "summary": summary,
        }
        if status_hint:
            if status_hint not in ("new", "in_progress", "on_hold", "in_review", "closed"):
                raise ValidationError("Unsupported broad OpenProject status hint.")
            payload["status_hint"] = status_hint
        if link:
            payload["dev_hub_link"] = _clean_text(link, "Dev Hub link", 500)
        key = "op:%s:%s:%s:%s" % (
            self.op_backend_id.id,
            self.op_work_package_id,
            milestone,
            _canonical_hash(payload)[:16],
        )
        return self._queue_outbox("openproject", "milestone", payload, key)
    def action_prepare_analysis_plan_milestone(self):
        self.ensure_one()
        analysis = self.current_accepted_analysis_id
        plan = self.plan_ids.filtered(
            lambda p: p.status in ("awaiting_approval", "approved")
        ).sorted(lambda p: (p.revision, p.id), reverse=True)[:1]
        if not analysis or not plan:
            raise UserError(
                "This milestone requires accepted analysis and a submitted plan."
            )
        return self._prepare_op_milestone(
            "analysis_plan_ready",
            "Development analysis and plan revision %s are ready." % plan.revision,
            "in_progress",
        )
    def action_prepare_blocker_milestone(self):
        self.ensure_one()
        if self.current_phase != "blocked" or not self.blocker:
            raise UserError("A material blocker must be recorded first.")
        return self._prepare_op_milestone(
            "material_blocker", _bounded(self.blocker, 1800), "on_hold"
        )
    def action_prepare_completion_milestone(self):
        self.ensure_one()
        report = self.completion_report_ids.filtered(lambda r: r.status == "approved")[:1]
        if self.current_phase != "completed" or not report:
            raise UserError(
                "Completed lifecycle work and an approved report are required."
            )
        return self._prepare_op_milestone(
            "completion", _bounded(report.implemented_summary, 1800), "closed"
        )
