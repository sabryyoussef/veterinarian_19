# -*- coding: utf-8 -*-

from odoo import api, fields, models


class LeadEngineIntakeService(models.AbstractModel):
    """Helpers to create intake logs with payload truncation (Sprint 1)."""

    _name = "lead.engine.intake.service"
    _description = "Lead Engine Intake Service"

    @api.model
    def _payload_limit(self):
        param = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("lead_engine.payload_max_chars", "65536")
        )
        try:
            return max(1024, int(param))
        except (TypeError, ValueError):
            return 65536

    @api.model
    def create_intake_log(
        self,
        source,
        *,
        channel=None,
        external_ref=None,
        payload_raw=None,
        normalized_payload=None,
        request_uuid=None,
    ):
        """Create a pending intake log row linked to a lead.engine.source record."""
        Log = self.env["lead.engine.intake.log"].sudo()
        limit = self._payload_limit()
        raw = payload_raw or ""
        if len(raw) > limit:
            raw = raw[:limit] + "\n...[truncated]"
        vals = {
            "source_id": source.id,
            "channel": channel or source.channel,
            "external_ref": external_ref,
            "payload_raw": raw or False,
            "normalized_payload": normalized_payload,
            "status": "pending",
            "processing_stage": "received",
        }
        if request_uuid:
            vals["request_uuid"] = request_uuid
        return Log.create(vals)
