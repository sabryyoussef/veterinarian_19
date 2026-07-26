# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class DevOdooRuntime(models.Model):
    _name = "dev.odoo.runtime"
    _description = "Shared Odoo Major-Version Runtime Stack"
    _order = "odoo_major, name"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    odoo_major = fields.Char(required=True, index=True, help="e.g. 19.0")
    machine_id = fields.Many2one(
        "dev.machine", required=True, ondelete="restrict", index=True
    )
    odoo_bin_path = fields.Char(required=True)
    venv_path = fields.Char(required=True)
    community_addons_path = fields.Char(required=True)
    enterprise_addons_path = fields.Char()
    baseline_database_identifier = fields.Char(
        help="Optional lightweight baseline DB for stack health only."
    )
    active = fields.Boolean(default=True)
    addon_source_ids = fields.One2many(
        "dev.runtime.addon.source", "runtime_id", string="Addon Sources"
    )
    environment_ids = fields.One2many(
        "dev.environment", "runtime_id", string="Bound Environments"
    )

    _code_unique = models.Constraint(
        "unique(code)", "Runtime code must be unique."
    )


class DevRuntimeAddonSource(models.Model):
    _name = "dev.runtime.addon.source"
    _description = "Runtime Addon Source Binding"
    _order = "runtime_id, project_id, addons_subdirectory"

    runtime_id = fields.Many2one(
        "dev.odoo.runtime", required=True, ondelete="cascade", index=True
    )
    repository_id = fields.Many2one(
        "dev.repository", required=True, ondelete="restrict", index=True
    )
    project_id = fields.Many2one(
        related="repository_id.project_id", store=True, index=True
    )
    addons_subdirectory = fields.Char(
        required=True,
        help="Subdirectory under the repository working directory (e.g. torz).",
    )
    absolute_addons_root = fields.Char(
        compute="_compute_absolute_addons_root", store=True
    )

    _runtime_repo_subdir_unique = models.Constraint(
        "unique(runtime_id, repository_id, addons_subdirectory)",
        "Addon source already registered for this runtime/repository/subdir.",
    )

    @api.depends("repository_id.working_directory", "addons_subdirectory")
    def _compute_absolute_addons_root(self):
        for record in self:
            wd = (record.repository_id.working_directory or "").rstrip("/")
            sub = (record.addons_subdirectory or "").strip("/")
            record.absolute_addons_root = f"{wd}/{sub}" if wd and sub else False


class DevEnvironmentRuntime(models.Model):
    _inherit = "dev.environment"

    runtime_id = fields.Many2one(
        "dev.odoo.runtime", ondelete="restrict", index=True
    )
    environment_role = fields.Selection(
        [
            ("dedicated_test", "Dedicated Test DB"),
            ("baseline_shared", "Shared Baseline"),
            ("legacy_isolated", "Legacy Isolated"),
        ],
        default="dedicated_test",
        required=True,
        index=True,
    )

    @api.constrains(
        "environment_role",
        "database_identifier",
        "port",
        "config_reference",
        "runtime_id",
    )
    def _check_dedicated_not_petspot(self):
        for record in self:
            if record.environment_role != "dedicated_test":
                continue
            db = (record.database_identifier or "").strip()
            cfg = (record.config_reference or "").strip()
            if db == "pet_spot_elsahel_test" or record.port == 8028:
                raise ValidationError(
                    "Dedicated Test environments must not target PetSpot Test "
                    "(database pet_spot_elsahel_test / port 8028)."
                )
            if "pet_spot_elsahel_test" in cfg:
                raise ValidationError(
                    "Dedicated Test environments must not use PetSpot Test config."
                )
            if not record.runtime_id:
                raise ValidationError(
                    "Dedicated Test environments require a shared Odoo runtime."
                )


class DevProjectRuntime(models.Model):
    _inherit = "dev.project"

    analysis_runtime_id = fields.Many2one(
        "dev.odoo.runtime",
        string="Shared Odoo Runtime",
        ondelete="restrict",
    )
