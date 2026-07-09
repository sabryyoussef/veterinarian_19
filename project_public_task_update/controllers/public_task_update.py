# -*- coding: utf-8 -*-
from __future__ import annotations

import logging

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


class PublicTaskUpdateController(http.Controller):
    """Public tokenized task update — no login, no OpenProject exposure."""

    def _render_error(self, status: int = 404):
        return request.render(
            "project_public_task_update.public_task_update_error",
            {
                "error_message_en": PUBLIC_ERROR_MESSAGE,
                "error_message_ar": PUBLIC_ERROR_MESSAGE_AR,
            },
            status=status,
        )

    def _get_valid_task(self, token: str):
        Task = request.env["project.task"]
        task = Task._get_task_by_public_update_token(token)
        if not task:
            return None
        return task

    @http.route(
        "/task/update/<string:token>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        sitemap=False,
    )
    def public_task_update_form(self, token, **kwargs):
        task = self._get_valid_task(token)
        if not task:
            return self._render_error(status=404)
        return request.render(
            "project_public_task_update.public_task_update_form",
            {
                "token": token,
                "task_title": task._public_task_title(),
                "task_instruction": task._public_task_instruction(),
            },
        )

    @http.route(
        "/task/update/<string:token>",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        sitemap=False,
    )
    def public_task_update_submit(self, token, **post):
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
            )
        except UserError as exc:
            return request.render(
                "project_public_task_update.public_task_update_form",
                {
                    "token": token,
                    "task_title": task._public_task_title(),
                    "task_instruction": task._public_task_instruction(),
                    "error_message": str(exc),
                    "form": post,
                },
            )
        except Exception:
            _logger.exception("public_task_update submit failed token_prefix=%s", token[:8])
            return self._render_error(status=500)
        return request.render(
            "project_public_task_update.public_task_update_success",
            {"task_title": task._public_task_title()},
        )
