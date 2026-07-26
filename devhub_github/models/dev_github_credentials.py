# -*- coding: utf-8 -*-
import os
import re

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


CREDENTIAL_ROOT = "/srv/devhub/credentials/github/"
FORBIDDEN_PATH_MARKERS = ("token=", "secret=", "password=", "passwd=")
GITHUB_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _assert_credential_path(path):
    canonical = os.path.realpath(path or "")
    if not canonical.startswith(CREDENTIAL_ROOT):
        raise ValidationError(
            "Credential references must stay under the protected GitHub root."
        )
    lowered = (path or "").casefold()
    if any(marker in lowered for marker in FORBIDDEN_PATH_MARKERS):
        raise ValidationError("Credential references must not embed secret material.")
    return canonical


class DevGithubAppInstallation(models.Model):
    _name = "dev.github.app.installation"
    _description = "Registered GitHub App Installation (Selected Repositories)"
    _order = "app_role, name"

    name = fields.Char(required=True)
    app_slug = fields.Char(required=True)
    app_id = fields.Integer(required=True)
    installation_id = fields.Integer(required=True)
    app_role = fields.Selection(
        [("pr", "Pull Request"), ("merge", "Merge")],
        required=True,
    )
    permission_summary = fields.Text(required=True)
    selected_repositories_only = fields.Boolean(default=True, required=True)
    allow_all_repositories = fields.Boolean(default=False, required=True)
    active = fields.Boolean(default=True)
    allowlist_ids = fields.One2many(
        "dev.github.repository.allowlist", "installation_id", string="Allowlist"
    )

    _installation_unique = models.Constraint(
        "unique(app_id, installation_id, app_role)",
        "Each App installation role must be unique.",
    )

    @api.constrains(
        "selected_repositories_only",
        "allow_all_repositories",
        "app_id",
        "installation_id",
        "permission_summary",
    )
    def _check_selected_only(self):
        for record in self:
            if record.allow_all_repositories or not record.selected_repositories_only:
                raise ValidationError(
                    "GitHub App installations must use Selected repositories only."
                )
            if record.app_id <= 0 or record.installation_id <= 0:
                raise ValidationError("App and installation IDs must be positive.")
            if not (record.permission_summary or "").strip():
                raise ValidationError("Permission summary is required.")

    def assert_repository_authorized(self, github_repository):
        self.ensure_one()
        if not self.active:
            raise AccessError("GitHub App installation is inactive.")
        self._check_selected_only()
        repo = (github_repository or "").strip()
        if not GITHUB_REPO_RE.fullmatch(repo):
            raise ValidationError("github_repository must be owner/name.")
        allowlist = self.allowlist_ids.filtered(
            lambda row: row.active and row.github_repository == repo
        )
        if not allowlist:
            raise AccessError(
                "Repository is not on the Selected-repositories allowlist for this App."
            )
        return allowlist[:1]


class DevGithubRepositoryAllowlist(models.Model):
    _name = "dev.github.repository.allowlist"
    _description = "GitHub App Selected Repository Allowlist Entry"
    _order = "installation_id, github_repository"

    installation_id = fields.Many2one(
        "dev.github.app.installation",
        required=True,
        ondelete="restrict",
        index=True,
    )
    github_repository = fields.Char(required=True)
    installation_repository_id = fields.Integer(required=True)
    credential_profile_reference = fields.Char(required=True)
    credential_broker_reference = fields.Char(required=True)
    active = fields.Boolean(default=True)

    _allowlist_unique = models.Constraint(
        "unique(installation_id, github_repository)",
        "Allowlist entries must be unique per installation and repository.",
    )

    @api.constrains(
        "github_repository",
        "installation_repository_id",
        "credential_profile_reference",
        "credential_broker_reference",
    )
    def _check_allowlist(self):
        for record in self:
            if not GITHUB_REPO_RE.fullmatch(record.github_repository or ""):
                raise ValidationError("github_repository must be owner/name.")
            if record.installation_repository_id <= 0:
                raise ValidationError("installation_repository_id must be positive.")
            _assert_credential_path(record.credential_profile_reference)
            _assert_credential_path(record.credential_broker_reference)

    @api.model
    def assert_token_mint_scope(self, github_repository, workspace_repository):
        """Fail closed when a mint request targets a different repository."""
        requested = (github_repository or "").strip()
        bound = (workspace_repository or "").strip()
        if not requested or not bound or requested != bound:
            raise AccessError(
                "Token minting is restricted to the Workspace-bound repository."
            )
        if not GITHUB_REPO_RE.fullmatch(requested):
            raise ValidationError("github_repository must be owner/name.")
        return True
