# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


class DevResumeBriefWizard(models.TransientModel):
    _name = "dev.resume.brief.wizard"
    _description = "Development Resume Brief"

    session_id = fields.Many2one(
        "dev.session", required=True, readonly=True, ondelete="cascade"
    )
    work_item_id = fields.Many2one(
        "dev.work.item", related="session_id.work_item_id", readonly=True
    )
    context_revision = fields.Char(readonly=True)
    resume_brief = fields.Text(required=True, readonly=True)
    drift_warning = fields.Text(related="session_id.drift_warning", readonly=True)

    @api.model
    def create_from_session(self, session):
        session.ensure_one()
        if session.state != "resumed":
            raise UserError("A resume brief can be generated only after Resume.")
        if session.work_item_id:
            brief, revision = session.work_item_id.build_resume_brief(session=session)
        else:
            revision = session.manifest_revision or "legacy-session"
            brief = (
                "# Resume Brief\n\n"
                "Legacy session without a canonical Work Item.\n\n"
                "- Session: %s\n"
                "- Project: %s\n"
                "- Branch: %s\n"
                "- HEAD: %s\n"
                "- Drift: %s\n\n"
                "Guardrails: no production access, deployment, branch switching, "
                "automatic commit, or push."
                % (
                    session.name,
                    session.project_id.name,
                    session.git_branch_snapshot or "unavailable",
                    session.git_head_snapshot or "unavailable",
                    session.drift_warning or "none",
                )
            )
        return self.create(
            {
                "session_id": session.id,
                "context_revision": revision,
                "resume_brief": brief[:16000],
            }
        )

    def action_continue_to_launcher(self):
        self.ensure_one()
        if self.session_id.state != "resumed":
            raise UserError("The session is no longer in Resumed state.")
        return self.session_id._open_launcher()
