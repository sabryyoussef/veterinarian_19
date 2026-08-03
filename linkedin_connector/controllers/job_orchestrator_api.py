# -*- coding: utf-8 -*-
"""Signed, scoped Job Application Orchestrator API for n8n (no direct DB access)."""

import hashlib
import hmac
import json
import logging
import time

from odoo import fields, http
from odoo.exceptions import UserError
from odoo.http import request

_logger = logging.getLogger(__name__)


def _get_secret():
    return (
        request.env["ir.config_parameter"]
        .sudo()
        .get_param("linkedin_connector.orchestrator_webhook_secret", "")
        or ""
    ).strip()


def _live_submit_icp_enabled():
    return (
        request.env["ir.config_parameter"]
        .sudo()
        .get_param("linkedin_connector.live_submit_enabled", "False")
        or "False"
    ).strip().lower() in ("1", "true", "yes")


def _assert_live_submit_allowed(app):
    """Fail-closed gate for live attempt states. Returns (ok, error_code)."""
    if not _live_submit_icp_enabled():
        return False, "live_submit_disabled"
    Policy = request.env["linkedin.apply.policy"].sudo()
    try:
        policy = Policy.get_policy_for_account(app.account_id)
        platform = getattr(app.job_id, "platform", None) or None
        policy.assert_orchestration_allowed(platform=platform, for_submit=True)
        policy.assert_submit_caps()
        company = ""
        if app.job_id:
            company = app.job_id.company or ""
        policy.assert_company_cooldown(company)
    except UserError as exc:
        _logger.warning("live submit blocked by policy: %s", exc)
        return False, "policy_blocked"
    except Exception as exc:  # noqa: BLE001 — fail closed
        _logger.exception("live submit gate error")
        return False, "policy_gate_error"
    return True, "ok"


def _verify_signature(raw_body, signature_header, timestamp_header):
    secret = _get_secret()
    if not secret:
        return False, "secret_not_configured"
    try:
        ts = int(timestamp_header or "0")
    except ValueError:
        return False, "bad_timestamp"
    # 5-minute skew window
    if abs(int(time.time()) - ts) > 300:
        return False, "timestamp_expired"
    payload = ("%s." % ts).encode("utf-8") + (raw_body or b"")
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    provided = (signature_header or "").strip()
    if provided.startswith("sha256="):
        provided = provided[7:]
    if not hmac.compare_digest(expected, provided):
        return False, "bad_signature"
    return True, "ok"


def _json_error(message, status=400, code=None):
    return request.make_json_response(
        {"ok": False, "error": message, "code": code or message},
        status=status,
    )


def _require_auth():
    raw = request.httprequest.get_data()
    ok, reason = _verify_signature(
        raw,
        request.httprequest.headers.get("X-Orchestrator-Signature"),
        request.httprequest.headers.get("X-Orchestrator-Timestamp"),
    )
    if not ok:
        _logger.warning("orchestrator auth failed: %s", reason)
        return None, _json_error("unauthorized", status=401, code=reason), raw
    try:
        body = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        return None, _json_error("invalid_json", status=400), raw
    return body, None, raw


class LinkedinJobOrchestratorController(http.Controller):

    @http.route(
        "/linkedin/orchestrator/v1/applications/<int:application_id>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def get_application(self, application_id, **kwargs):
        body, err, _raw = _require_auth()
        if err:
            return err
        App = request.env["linkedin.job.application"].sudo()
        app = App.browse(application_id)
        if not app.exists():
            return _json_error("not_found", status=404)
        if app.account_id.account_type != "personal" or app.account_id.id == 1:
            return _json_error("company_account_forbidden", status=403)
        try:
            payload = app.to_orchestrator_payload()
        except Exception as exc:
            return _json_error(str(exc), status=403)
        return request.make_json_response({"ok": True, "data": payload})

    @http.route(
        "/linkedin/orchestrator/v1/applications/<int:application_id>/pack",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def write_pack(self, application_id, **kwargs):
        body, err, _raw = _require_auth()
        if err:
            return err
        App = request.env["linkedin.job.application"].sudo()
        app = App.browse(application_id)
        if not app.exists():
            return _json_error("not_found", status=404)
        if app.account_id.account_type != "personal" or app.account_id.id == 1:
            return _json_error("company_account_forbidden", status=403)
        pack = body.get("pack") if isinstance(body, dict) else None
        if not isinstance(pack, dict):
            return _json_error("pack_required", status=400)
        # Fail closed: refuse invented salary/visa/notice keys inside screening if flagged
        if pack.get("invented_facts"):
            return _json_error("invented_facts_forbidden", status=422)
        try:
            app.write_pack_from_orchestrator(pack)
            if body.get("n8n_execution_id"):
                app.n8n_execution_id = body["n8n_execution_id"]
            if body.get("dify_run_id"):
                app.dify_run_id = body["dify_run_id"]
            request.env.cr.commit()
        except Exception as exc:
            request.env.cr.rollback()
            return _json_error(str(exc), status=409)
        return request.make_json_response(
            {"ok": True, "application_id": app.id, "state": app.state}
        )

    @http.route(
        "/linkedin/orchestrator/v1/applications/<int:application_id>/attempts",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def upsert_attempt(self, application_id, **kwargs):
        body, err, _raw = _require_auth()
        if err:
            return err
        App = request.env["linkedin.job.application"].sudo()
        app = App.browse(application_id)
        if not app.exists():
            return _json_error("not_found", status=404)
        if app.account_id.account_type != "personal" or app.account_id.id == 1:
            return _json_error("company_account_forbidden", status=403)
        Attempt = request.env["linkedin.apply.attempt"].sudo()
        idem = (body.get("idempotency_key") or "").strip()
        if idem:
            existing = Attempt.search([("idempotency_key", "=", idem)], limit=1)
            if existing:
                if existing.application_id.id != app.id:
                    return _json_error("idempotency_conflict", status=409)
                try:
                    existing.write_status_from_worker(body)
                    request.env.cr.commit()
                except Exception as exc:
                    request.env.cr.rollback()
                    return _json_error(str(exc), status=409)
                return request.make_json_response(
                    {"ok": True, "attempt_id": existing.id, "state": existing.state, "idempotent": True}
                )
        state = body.get("state") or "pending"
        want_live = (body.get("dry_run") is False) or state in ("submitted", "succeeded")
        if want_live:
            ok, code = _assert_live_submit_allowed(app)
            if not ok:
                return _json_error(code, status=403)
            dry_run = False
        else:
            dry_run = True
        vals = {
            "application_id": app.id,
            "dry_run": dry_run,
            "state": state,
            "stop_reason": body.get("stop_reason") or "none",
            "stop_detail": body.get("stop_detail") or "",
            "final_url": body.get("final_url") or "",
            "worker_attempt_id": body.get("worker_attempt_id") or "",
            "n8n_execution_id": body.get("n8n_execution_id") or "",
            "dify_run_id": body.get("dify_run_id") or "",
            "response_payload_json": json.dumps(body.get("response") or {}),
            "idempotency_key": idem or False,
        }
        try:
            attempt = Attempt.create(vals)
            request.env.cr.commit()
        except Exception as exc:
            request.env.cr.rollback()
            return _json_error(str(exc), status=409)
        return request.make_json_response(
            {"ok": True, "attempt_id": attempt.id, "state": attempt.state, "idempotent": False}
        )

    @http.route(
        "/linkedin/orchestrator/v1/health",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def health(self, **kwargs):
        configured = bool(_get_secret())
        return request.make_json_response(
            {
                "ok": True,
                "service": "linkedin-job-orchestrator",
                "secret_configured": configured,
                "ts": fields.Datetime.to_string(fields.Datetime.now()),
            }
        )
