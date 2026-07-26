    @api.model
    def import_plan_draft(self, payload):
        """Strict authenticated RPC callback; exact human approval remains mandatory."""
        _require_importer(self.env)
        actor_id = self.env.user.id
        if not isinstance(payload, dict):
            raise ValidationError("Plan import must be a JSON object.")
        allowed = {
            "work_item_uuid",
            "analysis_revision",
            "goal",
            "scope",
            "out_of_scope",
            "proposed_changes",
            "affected_components",
            "migration_impact",
            "security_impact",
            "test_plan",
            "rollback_plan",
            "dependencies",
            "risks",
            "acceptance_criteria",
            "run_reference",
            "steps",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValidationError(
                "Unsupported plan import fields: %s" % ", ".join(sorted(unknown))
            )
        required = (
            "goal",
            "scope",
            "out_of_scope",
            "proposed_changes",
            "affected_components",
            "migration_impact",
            "security_impact",
            "test_plan",
            "rollback_plan",
            "dependencies",
            "risks",
            "acceptance_criteria",
        )
        missing = [name for name in required if not payload.get(name)]
        if missing:
            raise ValidationError("Plan import requires: %s." % ", ".join(missing))
        work = self.sudo().with_context(
            dev_integration_actor_id=actor_id
        ).search([("uuid", "=", payload.get("work_item_uuid"))], limit=1)
        if not work:
            raise ValidationError("Unknown Work Item UUID.")
        analysis = work.analysis_ids.filtered(lambda item: item.status == "accepted")
        if payload.get("analysis_revision"):
            analysis = analysis.filtered(
                lambda item: item.revision == payload["analysis_revision"]
            )
        analysis = analysis.sorted(lambda item: (item.revision, item.id), reverse=True)[:1]
        if not analysis:
            raise UserError("Plan import requires an accepted analysis revision.")
        if work.current_phase == "analyzing":
            work.transition_lifecycle(
                "planning", "Bounded plan draft imported", actor_type="automation"
            )
        if work.current_phase != "planning":
            raise UserError("Plan drafts may be imported only while Planning.")
        steps = payload.get("steps") or []
        if not isinstance(steps, list) or not 1 <= len(steps) <= 30:
            raise ValidationError("Plan steps must contain between 1 and 30 items.")
        values = {
            key: value
            for key, value in payload.items()
            if key not in ("work_item_uuid", "analysis_revision", "steps")
        }
        values.update(
            work_item_id=work.id,
            analysis_id=analysis.id,
            status="draft",
            origin="generated",
            generated_at=fields.Datetime.now(),
            author_id=actor_id,
        )
        plan = self.env["dev.work.plan"].sudo().with_context(
            dev_integration_actor_id=actor_id
        ).create(values)
        step_allowed = {
            "step_key",
            "sequence",
            "title",
            "description",
            "dependency_keys",
            "acceptance_evidence",
        }
        for item in steps:
            if not isinstance(item, dict) or set(item) - step_allowed:
                raise ValidationError("Plan step import contains unsupported fields.")
            self.env["dev.work.plan.step"].sudo().create({"plan_id": plan.id, **item})
        return plan.id
