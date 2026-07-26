    @api.model
    def import_analysis_draft(self, payload):
        """Strict authenticated RPC callback; it never executes code or starts work."""
        _require_importer(self.env)
        actor_id = self.env.user.id
        if not isinstance(payload, dict):
            raise ValidationError("Analysis import must be a JSON object.")
        allowed = {
            "work_item_uuid",
            "problem_summary",
            "original_request_summary",
            "reproduction_context",
            "current_behavior",
            "expected_behavior",
            "technical_findings",
            "affected_components",
            "risks",
            "dependencies",
            "open_questions",
            "evidence_references",
            "model_reference",
            "provider_reference",
            "run_reference",
            "observed_head",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValidationError(
                "Unsupported analysis import fields: %s" % ", ".join(sorted(unknown))
            )
        required = ("problem_summary", "original_request_summary")
        missing = [name for name in required if not payload.get(name)]
        if missing:
            raise ValidationError(
                "Analysis import requires: %s." % ", ".join(missing)
            )
        work = self.sudo().with_context(
            dev_integration_actor_id=actor_id
        ).search([("uuid", "=", payload.get("work_item_uuid"))], limit=1)
        if not work:
            raise ValidationError("Unknown Work Item UUID.")
        if work.current_phase == "registered":
            work.transition_lifecycle(
                "analyzing", "Bounded analysis draft imported", actor_type="automation"
            )
        if work.current_phase != "analyzing":
            raise UserError("Analysis drafts may be imported only while Analyzing.")
        values = {key: value for key, value in payload.items() if key != "work_item_uuid"}
        values.update(
            work_item_id=work.id,
            status="generated",
            origin="generated",
            repository_id=work.preferred_repository_id.id,
            generated_at=fields.Datetime.now(),
            author_id=actor_id,
        )
        return self.env["dev.work.analysis"].sudo().create(values).id

    @api.model
    def import_merged_analysis_draft(self, payload):
        """Strict callback for the guarded 'merge_analysis' generation kind.

        Creates a new mixed-origin analysis revision that consolidates a base
        analysis with the human 'My Analysis' notes. It never overwrites the
        base revision; traceability links the new revision back to its base.
        """
        _require_importer(self.env)
        actor_id = self.env.user.id
        if not isinstance(payload, dict):
            raise ValidationError("Merged analysis import must be a JSON object.")
        allowed = {
            "work_item_uuid",
            "problem_summary",
            "original_request_summary",
            "reproduction_context",
            "current_behavior",
            "expected_behavior",
            "technical_findings",
            "affected_components",
            "risks",
            "dependencies",
            "open_questions",
            "evidence_references",
            "model_reference",
            "provider_reference",
            "run_reference",
            "observed_head",
            "base_analysis_id",
            "human_input_snapshot",
            "merged_by_id",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValidationError(
                "Unsupported merged analysis fields: %s" % ", ".join(sorted(unknown))
            )
        required = ("problem_summary", "original_request_summary")
        missing = [name for name in required if not payload.get(name)]
        if missing:
            raise ValidationError(
                "Merged analysis import requires: %s." % ", ".join(missing)
            )
        work = self.sudo().with_context(
            dev_integration_actor_id=actor_id
        ).search([("uuid", "=", payload.get("work_item_uuid"))], limit=1)
        if not work:
            raise ValidationError("Unknown Work Item UUID.")
        if work.current_phase != "analyzing":
            raise UserError(
                "Merged analysis may be imported only while Analyzing."
            )
        base = self.env["dev.work.analysis"].sudo().browse(
            payload.get("base_analysis_id") or 0
        ).exists()
        if not base or base.work_item_id != work:
            raise ValidationError("The base analysis is unknown for this work item.")
        values = {
            key: value
            for key, value in payload.items()
            if key not in ("work_item_uuid", "base_analysis_id", "merged_by_id")
        }
        merged_by = self.env["res.users"].sudo().browse(
            payload.get("merged_by_id") or actor_id
        ).exists()
        values.update(
            work_item_id=work.id,
            status="generated",
            origin="mixed",
            parent_revision_id=base.id,
            base_analysis_id=base.id,
            merged_by_id=(merged_by.id if merged_by else actor_id),
            merged_at=fields.Datetime.now(),
            repository_id=(base.repository_id.id or work.preferred_repository_id.id),
            generated_at=fields.Datetime.now(),
            author_id=actor_id,
        )
        return self.env["dev.work.analysis"].sudo().create(values).id
