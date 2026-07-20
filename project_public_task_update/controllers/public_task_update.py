# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
from urllib.parse import urlparse

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

_logger = logging.getLogger(__name__)

# Generic messages — do not reveal whether a token/task exists.
PUBLIC_ERROR_MESSAGE = (
    "This link is unavailable. Please request a new link from your project team."
)
PUBLIC_ERROR_MESSAGE_AR = (
    "هذا الرابط غير متاح. يرجى طلب رابط جديد من فريق المشروع."
)

PUBLIC_CACHE_HEADERS = {
    "Cache-Control": "private, no-store",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'",
    "X-Robots-Tag": "noindex, nofollow",
}


class PublicTaskUpdateController(http.Controller):
    """Public tokenized task update — no login, no OpenProject exposure.

    POST uses standard Odoo CSRF (session cookie + csrf_token form field).
    """

    def _apply_public_headers(self, response):
        """Mark public responses as non-cacheable, non-indexable, non-embeddable."""
        if response is None:
            return response
        headers = getattr(response, "headers", None)
        if headers is not None:
            for key, value in PUBLIC_CACHE_HEADERS.items():
                headers[key] = value
        return response

    def _render_error(self, status: int = 404):
        return self._apply_public_headers(request.render(
            "project_public_task_update.public_task_update_error",
            {
                "error_message_en": PUBLIC_ERROR_MESSAGE,
                "error_message_ar": PUBLIC_ERROR_MESSAGE_AR,
            },
            status=status,
        ))

    def _get_valid_task(self, token: str):
        Task = request.env["project.task"]
        return Task._get_task_by_public_update_token(token)

    def _form_context(self, task, token: str, **extra):
        """Build safe template context — no internal OP/sync data."""
        ctx = {
            "token": token,
            "task_title": task._public_task_title(),
            "task_instruction": task._public_task_instruction(),
            "is_team_planning": task._is_team_planning_mode(),
            "implementation_plan": task._public_implementation_plan(),
            "missing_data_questions": task._public_missing_data_questions(),
            "child_tasks": task._public_child_tasks_payload(),
        }
        ctx.update(extra)
        return ctx

    def _reject_clearly_cross_origin(self) -> bool:
        """If Origin is present and clearly mismatches web.base.url, reject.

        Does not trust X-Forwarded-* headers. Returns True when the request
        should be rejected.
        """
        origin = (request.httprequest.headers.get("Origin") or "").strip()
        if not origin:
            return False
        base = request.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/")
        if not base:
            return False
        try:
            origin_parts = urlparse(origin)
            base_parts = urlparse(base)
        except Exception:
            return False
        if not origin_parts.scheme or not origin_parts.netloc:
            return False
        if not base_parts.scheme or not base_parts.netloc:
            return False
        return (
            origin_parts.scheme != base_parts.scheme
            or origin_parts.netloc.lower() != base_parts.netloc.lower()
        )

    @http.route(
        "/task/update/<string:token>",
        type="http",
        auth="public",
        methods=["GET"],
        sitemap=False,
    )
    def public_task_update_form(self, token, **kwargs):
        # GET is read-only: never mutates task/token/chatter/counters.
        task = self._get_valid_task(token)
        if not task:
            return self._render_error(status=404)
        return self._apply_public_headers(request.render(
            "project_public_task_update.public_task_update_form",
            self._form_context(task, token),
        ))

    @http.route(
        "/task/update/<string:token>",
        type="http",
        auth="public",
        methods=["POST"],
        # Standard Odoo CSRF (default True): requires session cookie + csrf_token field.
        csrf=True,
        sitemap=False,
    )
    def public_task_update_submit(self, token, **post):
        if self._reject_clearly_cross_origin():
            _logger.info("public_task_update rejected reason=cross_origin")
            return self._render_error(status=403)

        task = self._get_valid_task(token)
        if not task:
            return self._render_error(status=404)
        try:
            task._record_public_update_submission(
                submitter_name=post.get("submitter_name", ""),
                submitter_contact=post.get("submitter_contact", ""),
                clarification=post.get("clarification", ""),
                priority_suggestion=post.get("priority_suggestion", ""),
                due_date_suggestion=post.get("due_date_suggestion", ""),
                notes=post.get("notes", ""),
                suggested_subtasks=post.get("suggested_subtasks", ""),
            )
        except UserError as exc:
            return self._apply_public_headers(request.render(
                "project_public_task_update.public_task_update_form",
                self._form_context(
                    task,
                    token,
                    error_message=str(exc),
                    form={
                        "submitter_name": post.get("submitter_name", ""),
                        "submitter_contact": post.get("submitter_contact", ""),
                        "clarification": post.get("clarification", ""),
                        "priority_suggestion": post.get("priority_suggestion", ""),
                        "due_date_suggestion": post.get("due_date_suggestion", ""),
                        "notes": post.get("notes", ""),
                        "suggested_subtasks": post.get("suggested_subtasks", ""),
                    },
                ),
                status=400,
            ))
        except Exception:
            _logger.exception(
                "public_task_update submit failed reason=unhandled task_id=%s",
                task.id,
            )
            return self._render_error(status=500)
        return self._apply_public_headers(request.render(
            "project_public_task_update.public_task_update_success",
            {
                "task_title": task._public_task_title(),
                "is_team_planning": task._is_team_planning_mode(),
            },
        ))
