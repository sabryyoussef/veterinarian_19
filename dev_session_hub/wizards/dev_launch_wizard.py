# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import AccessError


ARTIFACT_FIELDS = {
    "command_linux",
    "command_windows",
    "manifest_json",
    "drift_warning",
    "workspace_file",
    "workspace_filename",
    "manifest_file",
    "manifest_filename",
    "safety_note",
}


class DevLaunchWizard(models.TransientModel):
    _name = "dev.launch.wizard"
    _description = "Explicit Cursor Remote SSH Launcher"

    session_id = fields.Many2one("dev.session", required=True, readonly=True)
    command_linux = fields.Text(readonly=True)
    command_windows = fields.Text(readonly=True)
    manifest_json = fields.Text(readonly=True)
    drift_warning = fields.Text(readonly=True)
    workspace_file = fields.Binary(readonly=True, attachment=False)
    workspace_filename = fields.Char(readonly=True)
    manifest_file = fields.Binary(readonly=True, attachment=False)
    manifest_filename = fields.Char(readonly=True)
    safety_note = fields.Text(readonly=True)

    @api.model
    def create_from_session(self, session):
        raise AccessError(
            "Remote launch artifacts are disabled until a managed helper "
            "enforces the pinned SSH host key end-to-end."
        )

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(
            "Remote launch artifacts are disabled until a managed helper "
            "enforces the pinned SSH host key end-to-end."
        )

    @api.model
    def _artifact_values(self, session):
        raise AccessError(
            "Remote launch artifacts are disabled until a managed helper "
            "enforces the pinned SSH host key end-to-end."
        )

    def write(self, vals):
        if ARTIFACT_FIELDS.intersection(vals) or "session_id" in vals:
            raise AccessError("Launcher targets and artifacts are immutable.")
        return super().write(vals)

    def _download(self, field_name, filename):
        raise AccessError("Remote launch artifact downloads are disabled.")

    def init(self):
        self.env.cr.execute("DELETE FROM dev_launch_wizard")

    def action_download_workspace(self):
        return self._download("workspace_file", self.workspace_filename)

    def action_download_manifest(self):
        return self._download("manifest_file", self.manifest_filename)
