# -*- coding: utf-8 -*-

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_CRON_INTERVALS = [
    ("minutes", "Minutes"),
    ("hours", "Hours"),
    ("days", "Days"),
    ("weeks", "Weeks"),
    ("months", "Months"),
]


class ResumeCronBulkWizard(models.TransientModel):
    _name = "resume.cron.bulk.wizard"
    _description = "Bulk cron control"

    cron_ids = fields.Many2many(
        comodel_name="ir.cron",
        string="Scheduled jobs",
        required=True,
        help="Jobs selected in the list are pre-filled. Add or remove rows as needed.",
    )
    operation = fields.Selection(
        selection=[
            ("enable", "Start — enable selected jobs"),
            ("disable", "Stop — disable selected jobs"),
            ("interval", "Change interval for selected jobs"),
            ("run_now", "Run once now (manual trigger)"),
        ],
        string="Operation",
        required=True,
        default="enable",
    )
    interval_number = fields.Integer(
        string="Every",
        default=15,
        help="Repeat every N units (must be ≥ 1).",
    )
    interval_type = fields.Selection(
        selection=_CRON_INTERVALS,
        string="Interval unit",
        default="minutes",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_ids = self.env.context.get("active_ids")
        active_model = self.env.context.get("active_model")
        if active_model == "ir.cron" and active_ids:
            res["cron_ids"] = [(6, 0, list(active_ids))]
        return res

    def action_apply(self):
        self.ensure_one()
        crons = self.cron_ids
        if not crons:
            raise UserError(_("Select at least one scheduled job."))

        if self.operation == "enable":
            crons.write({"active": True})
        elif self.operation == "disable":
            crons.write({"active": False})
        elif self.operation == "interval":
            if not self.interval_number or self.interval_number < 1:
                raise UserError(_("Interval must be a positive number."))
            crons.write({
                "interval_number": self.interval_number,
                "interval_type": self.interval_type,
            })
        elif self.operation == "run_now":
            if len(crons) > 25:
                raise UserError(
                    _("Run at most 25 jobs at once from this wizard (you selected %d).")
                    % len(crons)
                )
            failed = []
            for cron in crons:
                try:
                    cron.method_direct_trigger()
                except UserError as err:
                    failed.append("%s: %s" % (cron.name, err.args[0] if err.args else err))
                    _logger.warning("Cron manual run failed: %s", failed[-1])
                except Exception as exc:
                    failed.append("%s: %s" % (cron.name, exc))
                    _logger.exception("Cron manual run error")
            if failed:
                raise UserError(
                    _("Some jobs could not run:\n\n%s") % "\n".join(failed[:15])
                )
        else:
            raise UserError(_("Unknown operation."))

        return {"type": "ir.actions.act_window_close"}
