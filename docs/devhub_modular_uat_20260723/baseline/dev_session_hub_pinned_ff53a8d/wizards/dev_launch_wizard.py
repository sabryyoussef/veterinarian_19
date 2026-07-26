# -*- coding: utf-8 -*-
import base64
import json
from urllib.parse import quote

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
        session.ensure_one()
        values = self._artifact_values(session)
        return self.with_context(dev_internal_launch=True).create(
            {"session_id": session.id, **values}
        )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("dev_internal_launch"):
            raise AccessError("Launch artifacts may be created only by the session action.")
        return super().create(vals_list)

    @api.model
    def _artifact_values(self, session):
        session.ensure_one()
        session._validate_launch_context()
        alias = session.machine_id.ssh_alias
        path = session._validated_repository_path()
        workspace_filename = "devhub-session-%s.code-workspace" % session.id
        manifest_filename = "devhub-session-%s-manifest.json" % session.id
        remote_uri = "vscode-remote://ssh-remote+%s%s" % (
            quote(alias, safe=""),
            quote(path, safe="/"),
        )
        workspace = {
            "folders": [{"name": session.project_id.name, "uri": remote_uri}],
            "settings": {
                "remote.SSH.remotePlatform": {alias: "linux"},
                "devHub.sessionId": session.id,
                "devHub.environment": session.environment_id.name,
            },
        }
        manifest = session._manifest_dict()
        workspace_json = json.dumps(workspace, indent=2, sort_keys=True)
        manifest_json = json.dumps(manifest, indent=2, sort_keys=True)
        return {
            "command_linux": (
                'cursor --new-window "$HOME/Downloads/%s"' % workspace_filename
            ),
            "command_windows": (
                'cursor --new-window (Join-Path $HOME "Downloads\\%s")'
                % workspace_filename
            ),
            "manifest_json": manifest_json,
            "drift_warning": session.drift_warning or False,
            "workspace_file": base64.b64encode(workspace_json.encode("utf-8")),
            "workspace_filename": workspace_filename,
            "manifest_file": base64.b64encode(manifest_json.encode("utf-8")),
            "manifest_filename": manifest_filename,
            "safety_note": (
                "Explicit fallback only: download the workspace, verify the target is "
                "%s and the environment is non-production, then open it locally. "
                "Cursor/SSH must already enforce the registered pinned host key. "
                "The managed one-click helper remains disabled." % alias
            ),
        }

    def write(self, vals):
        if ARTIFACT_FIELDS.intersection(vals) or "session_id" in vals:
            raise AccessError("Launcher targets and artifacts are immutable.")
        return super().write(vals)

    def _download(self, field_name, filename):
        self.ensure_one()
        if field_name not in ("workspace_file", "manifest_file"):
            raise AccessError("Unsupported launch artifact.")
        return {
            "type": "ir.actions.act_url",
            "url": (
                "/web/content?model=dev.launch.wizard&id=%s&field=%s"
                "&filename=%s&download=true"
            )
            % (self.id, field_name, quote(filename or "devhub-artifact")),
            "target": "self",
        }

    def init(self):
        self.env.cr.execute("DELETE FROM dev_launch_wizard")

    def action_download_workspace(self):
        return self._download("workspace_file", self.workspace_filename)

    def action_download_manifest(self):
        return self._download("manifest_file", self.manifest_filename)
