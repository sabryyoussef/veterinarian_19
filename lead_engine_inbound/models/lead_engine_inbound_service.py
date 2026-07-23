# -*- coding: utf-8 -*-

import logging
import secrets
import uuid

from odoo import SUPERUSER_ID, _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_LEAD_FIELD_KEYS = frozenset(
    {
        "name",
        "contact_name",
        "email_from",
        "phone",
        "partner_name",
        "description",
        "type",
    }
)
_UTM_FIELD_KEYS = frozenset({"campaign_id", "medium_id", "source_id"})


class LeadEngineInboundService(models.AbstractModel):
    _name = "lead.engine.inbound.service"
    _description = "Lead Engine Inbound Orchestration"

    @api.model
    def _valid_le_channels(self):
        field = self.env["crm.lead"]._fields["le_channel"]
        sel = field.selection
        if callable(sel):
            sel = sel(self.env["crm.lead"])
        return {k for k, _ in sel}

    @api.model
    def normalize_payload(self, payload: dict) -> dict:
        """Return {lead: {...}, utm: {...}, meta: {external_ref, le_channel}} from raw dict."""
        if not isinstance(payload, dict):
            raise UserError(_("Payload must be a JSON object."))
        external_ref = (payload.get("external_ref") or "").strip()
        le_channel = payload.get("le_channel")
        valid_ch = self._valid_le_channels()
        if le_channel and le_channel not in valid_ch:
            raise UserError(_("Invalid le_channel value."))
        lead_vals = {}
        for key in _LEAD_FIELD_KEYS:
            if key not in payload:
                continue
            val = payload[key]
            if val is None:
                continue
            if key == "type" and val not in ("lead", "opportunity"):
                raise UserError(_("type must be 'lead' or 'opportunity'."))
            lead_vals[key] = val
        utm_block = payload.get("utm") or {}
        if utm_block and not isinstance(utm_block, dict):
            raise UserError(_("utm must be an object."))
        utm_vals = {}
        for key in _UTM_FIELD_KEYS:
            if key not in utm_block:
                continue
            raw = utm_block[key]
            if raw in (None, False):
                utm_vals[key] = False
            else:
                try:
                    utm_vals[key] = int(raw)
                except (TypeError, ValueError) as exc:
                    raise UserError(_("UTM field %s must be an integer id.") % key) from exc
        return {
            "lead": lead_vals,
            "utm": utm_vals,
            "meta": {
                "external_ref": external_ref or False,
                "le_channel": le_channel or False,
            },
        }

    @api.model
    def validate_business_payload(self, normalized: dict):
        meta = normalized["meta"]
        if not meta["external_ref"]:
            raise UserError(_("external_ref is required."))
        lead = normalized["lead"]
        if not lead.get("name") and not lead.get("contact_name") and not lead.get("email_from"):
            raise UserError(_("Provide at least one of: name, contact_name, email_from."))

    @api.model
    def _token_equals(self, stored, provided) -> bool:
        a = str(stored).encode()
        b = str(provided).encode()
        if len(a) != len(b):
            return False
        return secrets.compare_digest(a, b)

    @api.model
    def resolve_source_from_token(self, token: str):
        if not token:
            return self.env["lead.engine.source"]
        token = token.strip()
        # Direct SQL keeps token matching independent of ORM field visibility / company tricks.
        self.env.cr.execute(
            """
            SELECT id, inbound_api_token
            FROM lead_engine_source
            WHERE active IS TRUE
              AND inbound_api_token IS NOT NULL
              AND btrim(inbound_api_token) <> ''
            """
        )
        Source = self.env["lead.engine.source"].sudo()
        for sid, stored in self.env.cr.fetchall():
            stored_str = (stored or "").strip()
            if stored_str and self._token_equals(stored_str, token):
                return Source.browse(sid)
        return self.env["lead.engine.source"]

    @api.model
    def process_intake(self, source, payload_dict: dict, raw_body: str):
        """Log → validate → upsert lead → UTM → pipeline → terminal log. Returns response dict."""
        # Ensure a real superuser env so ORM flush (currency, monetary fields) has a valid user.
        env = self.env(user=SUPERUSER_ID)
        svc = self.with_env(env)
        Intake = env["lead.engine.intake.service"]
        Pipeline = env["lead.engine.qualification.pipeline"]
        Lead = env["crm.lead"]

        request_uuid = str(uuid.uuid4())
        log = Intake.create_intake_log(
            source,
            payload_raw=raw_body,
            normalized_payload=payload_dict,
            request_uuid=request_uuid,
        )
        try:
            log.write({"status": "processing", "processing_stage": "normalized"})
            normalized = svc.normalize_payload(payload_dict)
            svc.validate_business_payload(normalized)
            log.write({"external_ref": normalized["meta"]["external_ref"]})

            lead_vals = normalized["lead"].copy()
            utm_vals = normalized["utm"]
            le_channel = normalized["meta"]["le_channel"] or source.channel
            external_ref = normalized["meta"]["external_ref"]

            lead_vals.update(
                {
                    "lead_engine_source_id": source.id,
                    "le_channel": le_channel,
                    "external_ref": external_ref,
                }
            )
            if utm_vals:
                lead_vals.update(utm_vals)

            existing = Lead.search(
                [
                    ("lead_engine_source_id", "=", source.id),
                    ("external_ref", "=", external_ref),
                ],
                limit=1,
                order="id asc",
            )
            if existing:
                existing.write(lead_vals)
                lead = existing
                created = False
            else:
                if not lead_vals.get("name"):
                    lead_vals["name"] = (
                        lead_vals.get("contact_name")
                        or lead_vals.get("email_from")
                        or external_ref
                    )
                lead = Lead.create(lead_vals)
                created = True

            log.write({"lead_id": lead.id, "processing_stage": "deduped"})
            Pipeline.apply(lead)
            env["lead.engine.playbook.service"].try_auto_start_after_qualification(lead)
            log.write({"processing_stage": "completed"})
            duplicate = lead.duplicate_status == "duplicate"
            state = "duplicate" if duplicate else "success"
            log.action_mark_success(
                lead,
                duplicate_of=lead.duplicate_master_id if duplicate else None,
                stage="completed",
            )
            return {
                "ok": True,
                "result": {
                    "state": state,
                    "intake_log_id": log.id,
                    "request_uuid": log.request_uuid,
                    "lead_id": lead.id,
                    "created": created,
                    "duplicate_of_id": lead.duplicate_master_id.id if duplicate else None,
                    "lead_score": lead.lead_score,
                    "assignment_status": lead.assignment_status,
                    "qualification_state": lead.qualification_state,
                    "duplicate_status": lead.duplicate_status,
                },
            }
        except UserError as e:
            log.action_mark_rejected(str(e))
            return {
                "ok": False,
                "error": {
                    "code": "rejected",
                    "message": str(e),
                    "intake_log_id": log.id,
                    "request_uuid": log.request_uuid,
                },
            }
        except Exception as e:  # pylint: disable=broad-except
            _logger.exception("Lead Engine intake failure")
            log.action_mark_error(str(e), stage=log.processing_stage)
            return {
                "ok": False,
                "error": {
                    "code": "error",
                    "message": _("Internal error processing intake."),
                    "intake_log_id": log.id,
                    "request_uuid": log.request_uuid,
                },
            }
