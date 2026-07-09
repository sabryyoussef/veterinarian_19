# -*- coding: utf-8 -*-
from __future__ import annotations

import logging

from odoo import _, http
from odoo.exceptions import UserError
from odoo.http import request

_logger = logging.getLogger(__name__)


class PublicTaskUpdateController(http.Controller):
    """Public tokenized task update — no login, no OpenProject exposure."""

    def _render_error(self, message: str, status: int = 404):
        return request.render(
            "project_public_task_update.public_task_update_error",
            {"error_message": message},
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
            return self._render_error(
                _("This link is invalid, expired, or has been disabled."),
                status=404,
            )
        return request.render(
            "project_public_task_update.public_task_update_form",
            {
                "token": token,
                "task_title": task._public_task_title(),
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
            return self._render_error(
                _("This link is invalid, expired, or has been disabled."),
                status=404,
            )
        try:
            task._record_public_update_submission(
                submitter_name=post.get("submitter_name", ""),
                submitter_contact=post.get("submitter_contact", ""),
                clarification=post.get("clarification", ""),
                priority_suggestion=post.get("priority_suggestion", ""),
                due_date_suggestion=post.get("due_date_suggestion", ""),
            )
        except UserError as exc:
            return request.render(
                "project_public_task_update.public_task_update_form",
                {
                    "token": token,
                    "task_title": task._public_task_title(),
                    "error_message": str(exc),
                    "form": post,
                },
            )
        except Exception:
            _logger.exception("public_task_update submit failed token_prefix=%s", token[:8])
            return self._render_error(
                _("Something went wrong. Please try again later."),
                status=500,
            )
        return request.render(
            "project_public_task_update.public_task_update_success",
            {"task_title": task._public_task_title()},
        )
