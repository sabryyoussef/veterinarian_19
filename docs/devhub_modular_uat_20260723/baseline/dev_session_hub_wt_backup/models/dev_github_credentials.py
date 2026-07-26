# -*- coding: utf-8 -*-
import os
import re

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


GITHUB_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
CREDENTIAL_ROOT = "/srv/devhub/credentials/github/"
FORBIDDEN_PATH_MARKERS = ("token=", "secret=")


def assert_token_mint_scope(github_repository, workspace_repository):
    """Deny minting any credential token scoped outside the exact workspace repository."""
    expected = getattr(workspace_repository, "github_repository", None)
    if expected is None:
        expected = workspace_repository
    if not github_repository or not expected or github_repository != expected:
        raise AccessError(
            "Token mint scope must match the exact workspace repository; "
            "cross-repository minting is denied."
        )
    return True


class DevGithubAppInstallation(models.Model):
    _name = "dev.github.app.installation"
    _description = "GitHub App Installation Restricted to Selected Repositories"
    _order = "name"

    name = fields.Char(required=True)
    app_slug = fields.Char(required=True)
    app_id = fields.Integer(required=True)
    installation_id = fields.Integer(required=True)
    app_role = fields.Selection(
        [("pr", "Pull Request"), ("merge", "Merge")], required=True
    )
    permission_summary = fields.Text(required=True)
    selected_repositories_only = fields.Boolean(default=True, required=True)
    allow_all_repositories = fields.Boolean(default=False, required=True)
    active = fields.Boolean(default=True)
    allowlist_ids = fields.One2many(
        "dev.github.repository.allowlist", "installation_id", readonly=True
    )

    _installation_unique = models.Constraint(
        "unique(app_id, installation_id)",
        "A GitHub App installation must be registered only once.",
    )

    @api.constrains(
        "allow_all_repositories", "selected_repositories_only", "app_id", "installation_id"
    )
    def _check_selected_repositories_only(self):
        for record in self:
            if record.allow_all_repositories:
                raise ValidationError(
                    "GitHub App installations must never use All repositories access."
                )
            if not record.selected_repositories_only:
                raise ValidationError(
                    "GitHub App installations must be restricted to Selected repositories."
                )
            if record.app_id <= 0 or record.installation_id <= 0:
                raise ValidationError(
                    "A GitHub App installation requires a valid app and installation id."
                )

    def assert_repository_authorized(self, github_repository):
        """Fail closed unless an active allowlist entry authorizes the exact repository."""
        self.ensure_one()
        if not self.active or self.allow_all_repositories:
            raise AccessError("The GitHub App installation is not authorized for use.")
        allowlist = self.env["dev.github.repository.allowlist"].sudo().search(
            [
                ("installation_id", "=", self.id),
                ("github_repository", "=", github_repository),
                ("active", "=", True),
            ],
            limit=1,
        )
        if not allowlist:
            raise AccessError(
                "Repository %s is not on the approved Selected-repo allowlist."
                % (github_repository or "(unset)")
            )
        return allowlist


class DevGithubRepositoryAllowlist(models.Model):
    _name = "dev.github.repository.allowlist"
    _description = "Approved Selected-Repo Allowlist Entry"
    _order = "github_repository"

    installation_id = fields.Many2one(
        "dev.github.app.installation", required=True, ondelete="restrict", index=True
    )
    github_repository = fields.Char(required=True, index=True)
    installation_repository_id = fields.Integer()
    credential_profile_reference = fields.Char(required=True)
    credential_broker_reference = fields.Char(required=True)
    active = fields.Boolean(default=True)

    _allowlist_unique = models.Constraint(
        "unique(installation_id, github_repository)",
        "A repository may be allowlisted only once per installation.",
    )

    @api.constrains("github_repository")
    def _check_repository_format(self):
        for record in self:
            if not GITHUB_REPO_RE.fullmatch(record.github_repository or ""):
                raise ValidationError(
                    "The allowlisted repository must be an exact owner/name reference."
                )

    @api.constrains("installation_id")
    def _check_installation_allows_selected_repos(self):
        for record in self:
            if record.installation_id.allow_all_repositories:
                raise ValidationError(
                    "An allowlist entry cannot be attached to an All repositories installation."
                )

    @api.constrains("credential_profile_reference", "credential_broker_reference")
    def _check_credential_paths(self):
        for record in self:
            for path in (
                record.credential_profile_reference,
                record.credential_broker_reference,
            ):
                if not path:
                    raise ValidationError(
                        "Credential profile and broker references are required."
                    )
                lowered = path.casefold()
                if any(marker in lowered for marker in FORBIDDEN_PATH_MARKERS):
                    raise ValidationError(
                        "Credential references must never embed a token or secret value."
                    )
                canonical = os.path.realpath(path)
                if not canonical.startswith(CREDENTIAL_ROOT):
                    raise ValidationError(
                        "Credential references must stay under the protected credential root."
                    )

    def assert_authorized(self):
        self.ensure_one()
        self.installation_id.assert_repository_authorized(self.github_repository)
        if not self.active:
            raise AccessError("The allowlist entry is not active.")
        return True
