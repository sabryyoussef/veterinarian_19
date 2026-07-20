# -*- coding: utf-8 -*-
import os
import re
import uuid

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


def _new_uuid(_recordset=None):
    return str(uuid.uuid4())


HOST_KEY_FINGERPRINT = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")
TAILSCALE_DNS_NAME = re.compile(r"^[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.ts\.net$")
PROJECT_CODE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
SSH_USERNAME = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class DevMachine(models.Model):
    _name = "dev.machine"
    _description = "Development Machine"
    _order = "name"

    name = fields.Char(required=True, index=True)
    stable_uuid = fields.Char(
        required=True, default=_new_uuid, copy=False, index=True
    )
    hostname = fields.Char(required=True)
    tailscale_name = fields.Char()
    tailscale_ip_reference = fields.Char(string="Tailscale IP Reference")
    tailscale_destination_verified = fields.Boolean(
        string="Tailscale Destination Verified",
        help="Launch is denied until the destination identity has been verified.",
    )
    tailscale_verified_at = fields.Datetime(readonly=True)
    pinned_host_key_fingerprint = fields.Char(
        string="Pinned SSH Host-Key Fingerprint",
        help="Expected SHA256 fingerprint of the verified destination SSH host key.",
    )
    ssh_alias = fields.Char(required=True, index=True)
    verification_ssh_user = fields.Char(
        string="Verification SSH User",
        help=(
            "POSIX username used by server-side Verify Tailscale Destination. "
            "Active verification connects with -F /dev/null and does not parse "
            "ssh_alias OpenSSH configuration."
        ),
    )
    os_name = fields.Char(string="Operating System")
    architecture = fields.Char()
    role = fields.Char(required=True)
    trust_zone = fields.Selection(
        [
            ("trusted_dev", "Trusted Development"),
            ("internal", "Internal"),
            ("restricted", "Restricted"),
            ("production", "Production"),
        ],
        required=True,
        default="restricted",
    )
    production = fields.Boolean(
        string="Hosts Production Workloads",
        help="Informational. Environment policy, not this flag alone, controls launch.",
    )
    active = fields.Boolean(default=True)
    last_reachability_status = fields.Selection(
        [
            ("unresolved", "Unresolved"),
            ("reachable", "Reachable"),
            ("unreachable", "Unreachable"),
        ],
        default="unresolved",
        required=True,
    )
    last_checked_at = fields.Datetime()
    allowed_path_prefixes = fields.Text(
        required=True,
        help="One absolute allowlisted development path prefix per line.",
    )
    environment_ids = fields.One2many("dev.environment", "machine_id", readonly=True)

    _stable_uuid_unique = models.Constraint(
        "unique(stable_uuid)", "Machine UUID must be unique."
    )
    _ssh_alias_unique = models.Constraint(
        "unique(ssh_alias)", "SSH alias must be unique."
    )

    @api.constrains("verification_ssh_user")
    def _check_verification_ssh_user(self):
        for record in self:
            if record.verification_ssh_user and not SSH_USERNAME.fullmatch(
                record.verification_ssh_user
            ):
                raise ValidationError(
                    "Verification SSH user must be a safe POSIX username."
                )

    @api.constrains("allowed_path_prefixes")
    def _check_allowed_paths(self):
        for record in self:
            paths = [
                line.strip()
                for line in (record.allowed_path_prefixes or "").splitlines()
                if line.strip()
            ]
            if not paths or any(
                not path.startswith("/")
                or path != os.path.realpath(path)
                or "\x00" in path
                for path in paths
            ):
                raise ValidationError(
                    "Allowed development paths must be canonical absolute POSIX paths."
                )

    @api.constrains(
        "tailscale_name",
        "tailscale_destination_verified",
        "tailscale_verified_at",
        "pinned_host_key_fingerprint",
    )
    def _check_verified_destination(self):
        for record in self:
            if not record.tailscale_destination_verified:
                continue
            if not TAILSCALE_DNS_NAME.fullmatch(record.tailscale_name or ""):
                raise ValidationError(
                    "A verified destination requires a valid Tailscale DNS name."
                )
            if not record.tailscale_verified_at:
                raise ValidationError(
                    "A verified destination requires a verification timestamp."
                )
            if not HOST_KEY_FINGERPRINT.fullmatch(
                record.pinned_host_key_fingerprint or ""
            ):
                raise ValidationError(
                    "A verified destination requires a pinned SHA256 SSH host key."
                )


class DevClient(models.Model):
    _name = "dev.client"
    _description = "Development Client"
    _order = "name"

    name = fields.Char(required=True)
    user_name = fields.Char(string="User", required=True)
    os_name = fields.Char(string="Operating System", required=True)
    architecture = fields.Char(required=True)
    cursor_version = fields.Char(default="unresolved")
    cursor_agent_version = fields.Char(default="unresolved")
    helper_version = fields.Char(default="not_installed")
    baseline_revision = fields.Char(default="mvp-report-only")
    compliance_status = fields.Selection(
        [
            ("unresolved", "Unresolved"),
            ("compliant", "Compliant"),
            ("warning", "Warning"),
            ("noncompliant", "Non-compliant"),
        ],
        default="unresolved",
        required=True,
    )
    compliance_note = fields.Text()
    last_seen_at = fields.Datetime()
    public_key_fingerprint_reference = fields.Char(
        help="Optional public-key fingerprint reference only; never a private key."
    )
    active = fields.Boolean(default=True)


class DevProject(models.Model):
    _name = "dev.project"
    _description = "Development Project"
    _order = "name"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    owner_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user
    )
    member_ids = fields.Many2many(
        "res.users",
        "dev_project_res_users_rel",
        "project_id",
        "user_id",
        string="Authorized Members",
    )
    repository_ids = fields.One2many("dev.repository", "project_id")
    environment_ids = fields.One2many("dev.environment", "project_id")
    default_repository_id = fields.Many2one(
        "dev.repository",
        domain="[('project_id', '=', id)]",
        ondelete="restrict",
    )
    default_environment_id = fields.Many2one(
        "dev.environment",
        domain="[('project_id', '=', id)]",
        ondelete="restrict",
    )
    openproject_reference = fields.Char()
    github_reference = fields.Char()
    production_policy = fields.Text(required=True)
    agent_instruction_summary = fields.Text()
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint(
        "unique(code)", "Project code must be unique."
    )

    @api.constrains("code")
    def _check_project_code(self):
        for record in self:
            if not PROJECT_CODE.fullmatch(record.code or ""):
                raise ValidationError(
                    "Project code may contain only letters, digits, underscores, "
                    "and hyphens."
                )


class DevRepository(models.Model):
    _name = "dev.repository"
    _description = "Development Repository"
    _order = "project_id, name"

    name = fields.Char(required=True)
    project_id = fields.Many2one(
        "dev.project", required=True, ondelete="cascade", index=True
    )
    git_remote = fields.Char(required=True)
    canonical_remote_path = fields.Char(required=True)
    working_directory = fields.Char(required=True)
    default_branch = fields.Char(required=True)
    repository_role = fields.Selection(
        [
            ("primary", "Primary"),
            ("addons", "Odoo Addons"),
            ("infrastructure", "Infrastructure"),
            ("documentation", "Documentation"),
        ],
        default="primary",
        required=True,
    )
    current_branch_cache = fields.Char(readonly=True)
    head_cache = fields.Char(readonly=True)
    dirty_state_summary = fields.Char(readonly=True)
    last_git_snapshot_at = fields.Datetime(readonly=True)
    active = fields.Boolean(default=True)

    _working_directory_unique = models.Constraint(
        "unique(working_directory)",
        "A canonical worktree can be registered only once.",
    )
    _canonical_remote_path_unique = models.Constraint(
        "unique(canonical_remote_path)",
        "A canonical remote path can be registered only once.",
    )

    @api.constrains("working_directory", "canonical_remote_path")
    def _check_absolute_paths(self):
        for record in self:
            for path in (record.working_directory, record.canonical_remote_path):
                if path and (
                    not path.startswith("/")
                    or path != os.path.realpath(path)
                    or "\x00" in path
                ):
                    raise ValidationError(
                        "Repository paths must be canonical absolute paths."
                    )
            if (
                record.working_directory
                and record.canonical_remote_path
                and os.path.realpath(record.working_directory)
                != os.path.realpath(record.canonical_remote_path)
            ):
                raise ValidationError(
                    "Working directory and canonical remote path must identify "
                    "the exact same directory."
                )


class DevEnvironment(models.Model):
    _name = "dev.environment"
    _description = "Development Environment"
    _order = "project_id, environment_type, name"

    name = fields.Char(required=True)
    project_id = fields.Many2one(
        "dev.project", required=True, ondelete="cascade", index=True
    )
    environment_type = fields.Selection(
        [
            ("local", "Local"),
            ("test", "Test"),
            ("staging", "Staging"),
            ("production", "Production"),
            ("lab", "Lab"),
            ("pr", "Pull Request"),
        ],
        required=True,
        index=True,
    )
    machine_id = fields.Many2one(
        "dev.machine", required=True, ondelete="restrict", index=True
    )
    odoo_version = fields.Char()
    database_identifier = fields.Char(required=True)
    url = fields.Char()
    port = fields.Integer(required=True)
    config_reference = fields.Char(required=True)
    service_container_reference = fields.Char(
        string="Service / Container Reference", required=True
    )
    data_sensitivity = fields.Selection(
        [
            ("public", "Public"),
            ("internal_test", "Internal Test"),
            ("confidential", "Confidential"),
            ("restricted", "Restricted"),
            ("production", "Production"),
        ],
        default="internal_test",
        required=True,
    )
    production_guard_policy = fields.Text(required=True)
    is_production = fields.Boolean(
        compute="_compute_is_production", store=True, index=True
    )
    active = fields.Boolean(default=True)

    @api.depends("environment_type")
    def _compute_is_production(self):
        for record in self:
            record.is_production = record.environment_type == "production"

    def _assert_dev_hub_safe(self, project):
        """Apply one fail-closed non-production policy across all automation paths."""
        self.ensure_one()
        machine = self.machine_id
        if (
            not self.active
            or not machine
            or not machine.active
            or self.is_production
            or self.environment_type == "production"
            or self.data_sensitivity in ("production", "restricted", "confidential")
            or machine.production
            or machine.trust_zone != "trusted_dev"
        ):
            raise UserError(
                "Dev Hub automation requires an active, trusted, non-production target."
            )
        policy = self.env["dev.policy"].search(
            [
                ("active", "=", True),
                ("project_id", "=", project.id),
                ("environment_id", "in", [self.id, False]),
            ],
            order="environment_id desc",
            limit=1,
        )
        if (
            not policy
            or not policy.development_allowed
            or policy.production_access_policy != "denied"
            or policy.deploy_permission
        ):
            raise UserError(
                "Dev Hub automation requires an active production-denied policy "
                "without deployment permission."
            )
        return policy

    @api.constrains("port")
    def _check_port(self):
        for record in self:
            if record.port < 1 or record.port > 65535:
                raise ValidationError("Port must be between 1 and 65535.")


class DevTaskLink(models.Model):
    _name = "dev.task.link"
    _description = "Legacy Development Task Link"
    _order = "last_sync_at desc, id desc"

    source_system = fields.Selection(
        [("openproject", "OpenProject"), ("github", "GitHub")],
        default="openproject",
        required=True,
    )
    openproject_work_package_id = fields.Integer(
        string="OpenProject Work Package ID", index=True
    )
    project_id = fields.Many2one(
        "dev.project", required=True, ondelete="cascade", index=True
    )
    cached_task_title = fields.Char(required=True)
    cached_status = fields.Char()
    cached_assignee = fields.Char()
    reference_url = fields.Char(string="URL / Reference")
    last_sync_at = fields.Datetime()
    deprecated = fields.Boolean(
        default=True,
        readonly=True,
        help="Compatibility-only cache. New sessions use dev.work.item and project.task.",
    )

    @api.depends("openproject_work_package_id", "cached_task_title")
    def _compute_display_name(self):
        for record in self:
            record.display_name = "#%s — %s" % (
                record.openproject_work_package_id or "?",
                record.cached_task_title,
            )


class DevPolicy(models.Model):
    _name = "dev.policy"
    _description = "Development Policy"
    _order = "project_id, environment_id"

    name = fields.Char(required=True)
    project_id = fields.Many2one(
        "dev.project", required=True, ondelete="cascade", index=True
    )
    environment_id = fields.Many2one(
        "dev.environment", ondelete="cascade", index=True
    )
    production_access_policy = fields.Selection(
        [
            ("denied", "Denied"),
            ("read_only", "Read-only"),
            ("approved_only", "Approved Only"),
        ],
        default="denied",
        required=True,
    )
    allowed_operations = fields.Text(required=True)
    required_confirmation = fields.Boolean(default=True)
    branch_rules = fields.Text(required=True)
    development_allowed = fields.Boolean(default=False)
    agent_write_permission = fields.Boolean(default=False)
    test_permission = fields.Boolean(default=False)
    deploy_permission = fields.Boolean(default=False)
    launch_allowed = fields.Boolean(default=False)
    active = fields.Boolean(default=True)

    _exact_scope_unique = models.UniqueIndex(
        "(project_id, environment_id) WHERE environment_id IS NOT NULL",
        "Only one policy is allowed per project and environment scope.",
    )
    _generic_scope_unique = models.UniqueIndex(
        "(project_id) WHERE environment_id IS NULL",
        "Only one generic policy is allowed per project.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._validate_policy_scope(vals)
        return super().create(vals_list)

    def write(self, vals):
        if {"project_id", "environment_id"}.intersection(vals):
            for record in self:
                self._validate_policy_scope(vals, record)
        return super().write(vals)

    def _validate_policy_scope(self, vals, record=None):
        project_id = vals.get(
            "project_id", record.project_id.id if record else False
        )
        environment_id = vals.get(
            "environment_id", record.environment_id.id if record else False
        )
        environment = self.env["dev.environment"].browse(environment_id).exists()
        if environment and environment.project_id.id != project_id:
            raise ValidationError(
                "An environment-specific policy must belong to the same project."
            )
        domain = [
            ("project_id", "=", project_id),
            ("environment_id", "=", environment_id or False),
        ]
        if record:
            domain.append(("id", "!=", record.id))
        if self.sudo().search_count(domain):
            raise ValidationError(
                "Only one policy is allowed per project and environment scope."
            )

    @api.constrains("project_id", "environment_id", "active")
    def _check_scope_consistency_and_uniqueness(self):
        for record in self:
            if (
                record.environment_id
                and record.environment_id.project_id != record.project_id
            ):
                raise ValidationError(
                    "An environment-specific policy must belong to the same project."
                )
            duplicate = self.search_count(
                [
                    ("id", "!=", record.id),
                    ("project_id", "=", record.project_id.id),
                    ("environment_id", "=", record.environment_id.id or False),
                ]
            )
            if duplicate:
                raise ValidationError(
                    "Only one policy is allowed per project and environment scope."
                )


class DevDashboard(models.Model):
    _name = "dev.dashboard"
    _description = "Development Hub Dashboard"

    name = fields.Char(required=True, default="Development Hub")
    recent_session_count = fields.Integer(compute="_compute_counts")
    active_session_count = fields.Integer(compute="_compute_counts")
    paused_session_count = fields.Integer(compute="_compute_counts")
    project_count = fields.Integer(compute="_compute_counts")
    environment_count = fields.Integer(compute="_compute_counts")
    machine_count = fields.Integer(compute="_compute_counts")
    client_warning_count = fields.Integer(compute="_compute_counts")

    def _compute_counts(self):
        session_model = self.env["dev.session"]
        for record in self:
            record.recent_session_count = session_model.search_count([])
            record.active_session_count = session_model.search_count(
                [("state", "in", ["started", "in_progress", "resumed"])]
            )
            record.paused_session_count = session_model.search_count(
                [("state", "=", "paused")]
            )
            record.project_count = self.env["dev.project"].search_count(
                [("active", "=", True)]
            )
            record.environment_count = self.env["dev.environment"].search_count(
                [("active", "=", True)]
            )
            record.machine_count = self.env["dev.machine"].search_count(
                [("active", "=", True)]
            )
            record.client_warning_count = self.env["dev.client"].search_count(
                [
                    ("active", "=", True),
                    ("compliance_status", "in", ["unresolved", "warning", "noncompliant"]),
                ]
            )

    def _open_action(self, xmlid, domain=None):
        action = self.env["ir.actions.actions"]._for_xml_id(xmlid)
        if domain is not None:
            action["domain"] = domain
        return action

    def action_sessions(self):
        return self._open_action("dev_session_hub.action_dev_session")

    def action_active_sessions(self):
        return self._open_action(
            "dev_session_hub.action_dev_session",
            [("state", "in", ["started", "in_progress", "resumed"])],
        )

    def action_paused_sessions(self):
        return self._open_action(
            "dev_session_hub.action_dev_session", [("state", "=", "paused")]
        )

    def action_projects(self):
        return self._open_action("dev_session_hub.action_dev_project")

    def action_environments(self):
        return self._open_action("dev_session_hub.action_dev_environment")

    def action_machines(self):
        return self._open_action("dev_session_hub.action_dev_machine")

    def action_clients(self):
        return self._open_action("dev_session_hub.action_dev_client")
