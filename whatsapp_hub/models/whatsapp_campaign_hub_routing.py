# -*- coding: utf-8 -*-
"""Phase 5A: Campaign Hub routing helpers / adapter stub (no send)."""
from __future__ import annotations

import logging

from odoo import api, models

from .whatsapp_message import campaign_business_key

_logger = logging.getLogger(__name__)

CAMPAIGN_HUB_PRIORITY = 3
CAMPAIGN_HUB_PURPOSE = "campaign"


def _icp_bool(env, key, default=False):
    raw = (env["ir.config_parameter"].sudo().get_param(key) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _icp_int(env, key, default=0):
    raw = (env["ir.config_parameter"].sudo().get_param(key) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _parse_campaign_allowlist(env):
    """Return list of ints, or None if empty (fail-closed), or False if malformed."""
    raw = (
        env["ir.config_parameter"]
        .sudo()
        .get_param("whatsapp_hub.campaign_hub_allowed_campaign_ids")
        or ""
    ).strip()
    if not raw:
        return None
    ids = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            return False
        ids.append(int(part))
    return ids


class WhatsappCampaignHubRouting(models.AbstractModel):
    """
    Campaign → Hub routing helpers (Phase 5A/5B).

    P5B adds resolve_outbound_route + service_admit_campaign_line.
    Production flags remain OFF — admission stays fail-closed until cutover.
    """

    _name = "whatsapp.campaign.hub.routing"
    _description = "WhatsApp Campaign Hub Routing Helpers"

    @api.model
    def campaign_admit_batch_size(self):
        return max(1, _icp_int(self.env, "whatsapp_hub.campaign_admit_batch_size", 25))

    @api.model
    def max_pending_campaign_jobs(self):
        return max(1, _icp_int(self.env, "whatsapp_hub.max_pending_campaign_jobs", 100))

    @api.model
    def parse_allowlist(self):
        return _parse_campaign_allowlist(self.env)

    @api.model
    def is_campaign_allowlisted(self, campaign_id):
        allow = _parse_campaign_allowlist(self.env)
        if allow is None or allow is False:
            return False
        try:
            cid = int(campaign_id)
        except (TypeError, ValueError):
            return False
        return cid in allow

    @api.model
    def get_allowlist_ids(self):
        """Return list of allowlisted Campaign IDs (empty list if unset/malformed)."""
        allow = _parse_campaign_allowlist(self.env)
        if allow is None or allow is False:
            return []
        return list(allow)

    @api.model
    def service_set_allowlist_ids(self, campaign_ids):
        """Replace allowlist CSV with unique positive ints (order preserved)."""
        cleaned = []
        seen = set()
        for raw in campaign_ids or []:
            try:
                cid = int(raw)
            except (TypeError, ValueError):
                continue
            if cid <= 0 or cid in seen:
                continue
            seen.add(cid)
            cleaned.append(cid)
        value = ",".join(str(x) for x in cleaned)
        self.env["ir.config_parameter"].sudo().set_param(
            "whatsapp_hub.campaign_hub_allowed_campaign_ids", value
        )
        return cleaned

    @api.model
    def service_allowlist_add(self, campaign_id):
        """Idempotently add one Campaign ID to the active allowlist."""
        cid = int(campaign_id)
        ids = self.get_allowlist_ids()
        if cid not in ids:
            ids.append(cid)
            self.service_set_allowlist_ids(ids)
        return {"ok": True, "allowlist": self.get_allowlist_ids(), "added": cid}

    @api.model
    def service_allowlist_remove(self, campaign_id):
        """Remove one Campaign ID from the active allowlist (no history deletion)."""
        cid = int(campaign_id)
        ids = [x for x in self.get_allowlist_ids() if x != cid]
        self.service_set_allowlist_ids(ids)
        return {"ok": True, "allowlist": ids, "removed": cid}

    @api.model
    def campaign_is_admission_capable(self, campaign):
        """
        True when Campaign could admit new Hub jobs if mode=hub + allowlisted.

        Completed/cancelled Campaigns are historical only (P5F-A allowlist lifecycle).
        """
        if not campaign or not campaign.exists():
            return False
        if (campaign.wa_outbound_mode or "legacy") != "hub":
            return False
        if campaign.state in ("completed", "cancelled"):
            return False
        return True

    @api.model
    def service_assess_hub_eligibility(self, campaign):
        """
        P5F-A: assess whether a Campaign may be approved for Hub admission.

        Initial broader text cutover supports manual/immediate text-only only.
        Scheduled/queue-timed and media remain legacy.
        """
        result = {
            "ok": False,
            "eligible": False,
            "reason": "unknown",
            "details": [],
        }
        if not campaign or not campaign.exists():
            result["reason"] = "missing_campaign"
            return result
        if campaign.state in ("completed", "cancelled"):
            result["reason"] = campaign.state
            result["details"].append("Campaign cannot admit new Hub jobs")
            return result
        ok_text, err_text = self.text_eligible(campaign)
        if not ok_text:
            result["reason"] = "attachments_media"
            result["details"].append(err_text or "attachments/media present")
            return result
        send_mode = (campaign.send_mode or "").strip()
        if send_mode == "scheduled" or campaign.state == "scheduled":
            result["reason"] = "scheduled_not_supported"
            result["details"].append(
                "Scheduled Campaign Hub execution is not supported (P5F-E)"
            )
            return result
        if send_mode == "queue" and getattr(campaign, "scheduled_date", False):
            result["reason"] = "scheduled_not_supported"
            result["details"].append(
                "Queue + scheduled_date Campaigns stay legacy until Hub due-time parity"
            )
            return result
        if send_mode != "immediate":
            result["reason"] = "orchestration_not_supported"
            result["details"].append(
                "P5F initial Hub approval requires send_mode=immediate "
                f"(got {send_mode or 'empty'})"
            )
            return result
        inst = self.resolve_hub_instance()
        if not inst:
            result["reason"] = "invalid_instance"
            result["details"].append("no Hub instance resolved")
            return result
        lines = campaign.campaign_line_ids
        if not lines:
            result["reason"] = "invalid_recipient"
            result["details"].append("no Campaign lines")
            return result
        bad_phones = lines.filtered(lambda l: not (l.phone or "").strip())
        if bad_phones:
            result["reason"] = "invalid_recipient"
            result["details"].append(
                f"{len(bad_phones)} line(s) missing phone"
            )
            return result
        # Render freeze available (fields present); readiness is separate
        if "rendered_locked" not in lines._fields:
            result["reason"] = "render_not_ready"
            result["details"].append("render freeze fields missing")
            return result
        result["ok"] = True
        result["eligible"] = True
        result["reason"] = "eligible"
        unlocked = lines.filtered(
            lambda l: l.status == "pending" and not l.rendered_locked
        )
        if unlocked:
            result["details"].append(
                f"{len(unlocked)} pending line(s) not yet frozen (freeze before Hub flip)"
            )
        return result

    @api.model
    def resolve_hub_instance(self):
        """Prefer purpose=campaign instance; fall back to default (compat parity)."""
        Instance = self.env["whatsapp.instance"].sudo()
        rec = Instance.search(
            [("purpose", "=", "campaign"), ("active", "=", True)], limit=1
        )
        if rec:
            return rec
        return Instance.search([("is_default", "=", True), ("active", "=", True)], limit=1) or Instance.search(
            [("active", "=", True)], limit=1
        )

    @api.model
    def text_eligible(self, campaign):
        """Hub text-only gate: empty attachments."""
        if not campaign:
            return False, "missing campaign"
        if campaign.attachment_ids:
            return False, "campaign has attachments; Hub text-only until media support"
        return True, ""

    @api.model
    def hub_cutover_prerequisites(self, campaign, hub_instance=None):
        """
        Full Hub send gate (P5B+). Returns (ok, error).

        Requires: global unified + campaign cutover, instance flags,
        purpose allowlist includes campaign, campaign allowlisted, mode=hub,
        text-only.
        """
        if not campaign:
            return False, "missing campaign"
        mode = getattr(campaign, "wa_outbound_mode", "legacy") or "legacy"
        if mode != "hub":
            return False, f"campaign wa_outbound_mode={mode} (need hub)"
        ok_text, err_text = self.text_eligible(campaign)
        if not ok_text:
            return False, err_text
        if not _icp_bool(self.env, "whatsapp_hub.unified_outbound_enabled", False):
            return False, "global unified_outbound_enabled is OFF"
        if not _icp_bool(self.env, "whatsapp_hub.campaign_cutover_enabled", False):
            return False, "global campaign_cutover_enabled is OFF"
        if not self.is_campaign_allowlisted(campaign.id):
            return False, "campaign not in campaign_hub_allowed_campaign_ids (fail-closed)"
        purposes = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("whatsapp_hub.unified_outbound_purposes")
            or ""
        ).strip()
        if purposes:
            allowed = {p.strip() for p in purposes.split(",") if p.strip()}
            if CAMPAIGN_HUB_PURPOSE not in allowed:
                return False, "unified_outbound_purposes does not include campaign"
        inst = hub_instance or self.resolve_hub_instance()
        if not inst:
            return False, "no Hub instance resolved"
        if not inst.unified_outbound_enabled:
            return False, "instance unified_outbound_enabled is OFF"
        if not getattr(inst, "campaign_cutover_enabled", False):
            return False, "instance campaign_cutover_enabled is OFF"
        return True, ""

    @api.model
    def shadow_eligible(self, campaign):
        """Shadow mode needs text-only + mode=shadow; ignore allowlist."""
        if not campaign:
            return False, "missing campaign"
        mode = getattr(campaign, "wa_outbound_mode", "legacy") or "legacy"
        if mode != "shadow":
            return False, f"wa_outbound_mode={mode} (need shadow)"
        return self.text_eligible(campaign)

    @api.model
    def build_hub_candidate(self, campaign, line, body=None):
        """
        Build a Hub admission candidate dict (validation / shadow only).

        Does NOT create whatsapp.message or outbound jobs (no identity reservation).
        """
        import hashlib

        errors = []
        if not campaign or not line:
            return {
                "eligible": False,
                "classification": "validation_error",
                "errors": ["missing campaign or line"],
                "candidate": {},
            }
        ok_text, err_text = self.text_eligible(campaign)
        if not ok_text:
            return {
                "eligible": False,
                "classification": "has_attachments",
                "errors": [err_text],
                "candidate": {},
            }
        dest = (line.phone or "").strip()
        if not dest:
            return {
                "eligible": False,
                "classification": "invalid_destination",
                "errors": ["empty phone"],
                "candidate": {},
            }
        inst = self.resolve_hub_instance()
        if not inst:
            return {
                "eligible": False,
                "classification": "missing_instance",
                "errors": ["no Hub instance"],
                "candidate": {},
            }
        rendered = body if body is not None else (line.message or campaign.message or "")
        biz = campaign_business_key(campaign.id, line.id)
        digits = "".join(c for c in dest if c.isdigit())
        remote_jid = f"{digits}@s.whatsapp.net" if digits else dest
        body_hash = hashlib.sha256((rendered or "").strip().encode("utf-8")).hexdigest()[
            :32
        ]
        expected_conv = False
        try:
            from .whatsapp_conversation import build_conversation_identity_key

            expected_conv = build_conversation_identity_key(
                instance_id=inst.id,
                instance_reference=inst.instance_name,
                remote_jid=remote_jid,
                purpose=CAMPAIGN_HUB_PURPOSE,
            )
        except Exception:
            expected_conv = False
        candidate = {
            "business_key": biz,
            "client_request_id": biz,
            "destination": dest,
            "remote_jid": remote_jid,
            "body": rendered,
            "body_hash": body_hash,
            "message_type": "text",
            "purpose": CAMPAIGN_HUB_PURPOSE,
            "source_app": CAMPAIGN_HUB_PURPOSE,
            "source_model": "wa.campaign.line",
            "source_res_id": line.id,
            "campaign_id": campaign.id,
            "campaign_line_id": line.id,
            "priority": CAMPAIGN_HUB_PRIORITY,
            "instance_id": inst.id,
            "instance_reference": inst.instance_name,
            "partner_id": line.partner_id.id if line.partner_id else False,
            "lead_id": line.lead_id.id if line.lead_id else False,
            "expected_conversation_identity_key": expected_conv,
        }
        return {
            "eligible": True,
            "classification": "matched",
            "errors": errors,
            "candidate": candidate,
        }

    @api.model
    def service_preview_campaign_hub(self, campaign, line, body=None):
        """Public preview stub for shadow / ops — never sends."""
        return self.build_hub_candidate(campaign, line, body=body)

    @api.model
    def service_preview_campaign_line(self, campaign, line, body=None):
        """P5C/P5E: observational Hub candidate preview (no send, no Hub records)."""
        if body is None and line and getattr(line, "rendered_locked", False):
            body = line.rendered_body
        return self.service_preview_campaign_hub(campaign, line, body=body)

    @api.model
    def service_freeze_campaign_line(self, line):
        """P5E: freeze Campaign template into immutable line snapshot."""
        if not line:
            return False
        return line.service_freeze_rendered_body()

    @api.model
    def body_hash(self, text):
        import hashlib

        return hashlib.sha256((text or "").encode("utf-8")).hexdigest()

    @api.model
    def pending_campaign_job_count(self, instance=None):
        Out = self.env["whatsapp.outbound.message"].sudo()
        domain = [
            ("purpose", "=", CAMPAIGN_HUB_PURPOSE),
            ("transport_mode", "=", "unified_bridge"),
            ("state", "in", ("pending", "processing")),
        ]
        if instance:
            domain.append(("instance_id", "=", instance.id))
        return Out.search_count(domain)

    @api.model
    def backpressure_ok(self, hub_instance=None):
        inst = hub_instance or self.resolve_hub_instance()
        count = self.pending_campaign_job_count(inst)
        limit = self.max_pending_campaign_jobs()
        if count >= limit:
            return False, f"pending campaign jobs {count} >= max {limit}"
        return True, ""

    @api.model
    def resolve_outbound_route(self, campaign):
        """
        Single routing decision for Campaign processor (P5B).

        Returns dict: route in {legacy, shadow, hub}, ok, error.
        mode=hub with failed prerequisites → route=hub, ok=False (no legacy fallback).
        """
        if not campaign:
            return {"route": "legacy", "ok": True, "error": ""}
        mode = (getattr(campaign, "wa_outbound_mode", None) or "legacy").strip()
        if mode == "legacy":
            return {"route": "legacy", "ok": True, "error": ""}
        if mode == "shadow":
            return {"route": "shadow", "ok": True, "error": ""}
        if mode == "hub":
            ok, err = self.hub_cutover_prerequisites(campaign)
            return {"route": "hub", "ok": ok, "error": err or ""}
        return {"route": "legacy", "ok": True, "error": ""}

    @api.model
    def service_admit_campaign_line(self, campaign, line, body=None, send_now=False):
        """
        Admit one Campaign line into Hub unified outbound (P5B).

        Does not mark the line sent. Does not create bridge queue rows.
        Idempotent on campaign:{campaign_id}:{line_id}.
        """
        result = {
            "ok": False,
            "duplicate": False,
            "message_id": False,
            "outbound_id": False,
            "state": False,
            "error": "",
            "backpressure": False,
        }
        if not campaign or not line:
            result["error"] = "missing campaign or line"
            return result

        ok_prereq, err_prereq = self.hub_cutover_prerequisites(campaign)
        if not ok_prereq:
            result["error"] = err_prereq
            return result

        preview = self.build_hub_candidate(campaign, line, body=body)
        if not preview.get("eligible"):
            result["error"] = "; ".join(preview.get("errors") or ["not eligible"])
            return result

        cand = preview["candidate"]
        inst = self.env["whatsapp.instance"].sudo().browse(cand["instance_id"])
        bp_ok, bp_err = self.backpressure_ok(inst)
        # Allow idempotent re-admit of already-linked lines even under backpressure
        if not bp_ok and not (line.hub_outbound_id or line.hub_message_id):
            result["error"] = bp_err
            result["backpressure"] = True
            return result

        Out = self.env["whatsapp.outbound.message"].sudo()
        vals = {
            "destination": cand["destination"],
            "body": cand["body"],
            "message_type": "text",
            "purpose": CAMPAIGN_HUB_PURPOSE,
            "source_app": CAMPAIGN_HUB_PURPOSE,
            "related_model": "wa.campaign.line",
            "related_res_id": line.id,
            "campaign_id": campaign.id,
            "campaign_line_id": line.id,
            "partner_id": cand.get("partner_id") or False,
            "instance_id": cand["instance_id"],
            "client_request_id": cand["client_request_id"],
            "business_key": cand["business_key"],
            "priority": CAMPAIGN_HUB_PRIORITY,
            "send_now": bool(send_now),
            "name": f"Campaign {campaign.id} line {line.id}",
        }
        try:
            hub_res = Out.service_enqueue_message(vals)
        except Exception as exc:
            result["error"] = str(exc)[:500]
            return result

        msg_id = hub_res.get("message_id") or False
        out_id = hub_res.get("outbound_id") or False
        line_vals = {}
        if msg_id and line.hub_message_id != msg_id:
            line_vals["hub_message_id"] = msg_id
        if out_id and line.hub_outbound_id != out_id:
            line_vals["hub_outbound_id"] = out_id
        # Never mark sent on admission alone
        if line.status not in ("sent", "delivered", "read", "failed", "skipped"):
            line_vals.setdefault("status", "pending")
        if line_vals:
            line.sudo().write(line_vals)

        # Compatibility log (converge; no second send)
        self._ensure_hub_compat_log(campaign, line, msg_id, hub_res)

        result.update(
            {
                "ok": bool(hub_res.get("ok")),
                "duplicate": bool(hub_res.get("duplicate")),
                "message_id": msg_id,
                "outbound_id": out_id,
                "state": hub_res.get("state") or False,
                "evolution_message_id": hub_res.get("evolution_message_id") or False,
            }
        )
        if not result["ok"]:
            result["error"] = hub_res.get("error") or "Hub admission failed"
        return result

    @api.model
    def _ensure_hub_compat_log(self, campaign, line, hub_message_id, hub_res=None):
        """Create/update wa.message.log with send_origin=hub_unified (no twin)."""
        if "wa.message.log" not in self.env or not hub_message_id:
            return self.env["wa.message.log"].browse()
        Log = self.env["wa.message.log"].sudo()
        existing = Log.search(
            [
                ("campaign_line_id", "=", line.id),
                ("send_origin", "=", "hub_unified"),
            ],
            limit=1,
        )
        hub_msg = self.env["whatsapp.message"].sudo().browse(int(hub_message_id))
        evo_id = False
        if hub_res:
            evo_id = hub_res.get("evolution_message_id") or False
        if not evo_id and hub_msg:
            evo_id = hub_msg.evolution_message_id or False
        state = (hub_res or {}).get("state") or (hub_msg.state if hub_msg else "")
        delivery = "pending"
        if state == "sent":
            delivery = "sent"
        elif state == "failed":
            delivery = "failed"
        body = line.message or campaign.message or ""
        if existing:
            updates = {
                "hub_message_id": hub_msg.id if hub_msg else existing.hub_message_id,
                "delivery_status": delivery,
            }
            if evo_id:
                updates["wa_message_id"] = evo_id
            existing.write(updates)
            return existing
        return Log.create(
            {
                "phone": line.phone,
                "direction": "out",
                "message_text": (body or "")[:2000],
                "wa_message_id": evo_id or False,
                "delivery_status": delivery,
                "send_origin": "hub_unified",
                "partner_id": line.partner_id.id if line.partner_id else False,
                "lead_id": line.lead_id.id if line.lead_id else False,
                "campaign_id": campaign.id,
                "campaign_line_id": line.id,
                "hub_message_id": hub_msg.id if hub_msg else False,
            }
        )
