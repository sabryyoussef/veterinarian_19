# -*- coding: utf-8 -*-
"""
Custom auth method for the Lead Engine inbound REST endpoint.

auth="lead_engine_bearer" is called by Odoo's _serve_db BEFORE request.env is
created from session.uid.  By setting request.session.uid = SUPERUSER_ID here,
the transaction's default_env will have a real uid, which is required for ORM
flush to work correctly (e.g., monetary fields that access res.currency).

Token validity is verified later inside the controller so that we can return a
proper 401 JSON response instead of a generic HTTP exception.
"""

from odoo import SUPERUSER_ID, models
from odoo.http import request, SessionExpiredException


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _auth_method_lead_engine_bearer(cls):
        """Accept any request — real token check is done in the controller."""
        auth = request.httprequest.headers.get("Authorization", "")
        if not auth.lower().startswith("bearer "):
            raise SessionExpiredException("Lead Engine: Bearer token required")
        token = auth[7:].strip()
        if not token:
            raise SessionExpiredException("Lead Engine: empty Bearer token")
        # Set session uid so future env creations (e.g. in _pre_dispatch) use SUPERUSER.
        # Token ↔ source validation happens inside intake_v1().
        request.session.uid = SUPERUSER_ID
        # Also immediately re-initialise request.env with the correct uid so that
        # the transaction's default_env (used during flush) is set to a real user.
        # This is needed because _serve_db creates request.env before calling
        # _authenticate, so the env already has uid=None by the time we get here.
        request.env = request.env(user=SUPERUSER_ID, su=True)
