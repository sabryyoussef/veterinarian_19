# -*- coding: utf-8 -*-
"""Playbook execution service (Sprint 4 MVP, Sprint 6 reliability).

**Call order**

1. ``start_playbook`` → validates playbook → creates run → ``schedule_next_steps`` → ``execute_due_steps(run=…)``.
2. ``schedule_next_steps`` → creates ``run.line`` rows with ``scheduled_at``.
3. ``execute_due_steps`` → for each due line, ``execute_step`` (atomic *pending*→*due* claim) → ``finalize_run``.
4. ``finalize_run`` → idempotent close when all lines terminal.

Contracts are documented in ``docs/sprint6_report.md`` (duplicate runs, due-step idempotency, cancel/retry, validation).
"""

import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LeadEnginePlaybookService(models.AbstractModel):
    _name = "lead.engine.playbook.service"
    _description = "Lead Engine Playbook Orchestration"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @api.model
    def try_auto_start_after_qualification(self, lead):
        """If source is configured, start playbook after successful qualification (e.g. HTTP intake).

        Skips when:

        - no source or no playbook or auto-start disabled
        - playbook is archived (``active`` is False)
        - playbook has no steps
        - lead is duplicate and ``playbook_auto_start_duplicate`` is False on the source
        - a run is already **running** for this lead **and** this playbook
        """
        lead = lead.sudo()
        if not lead.lead_engine_source_id:
            return self.env["lead.engine.playbook.run"]
        src = lead.lead_engine_source_id
        if not src.playbook_id or not src.playbook_auto_start:
            return self.env["lead.engine.playbook.run"]
        playbook = src.playbook_id
        if not playbook.active:
            return self.env["lead.engine.playbook.run"]
        if not playbook.step_ids:
            return self.env["lead.engine.playbook.run"]
        if (
            lead.duplicate_status == "duplicate"
            and not src.playbook_auto_start_duplicate
        ):
            return self.env["lead.engine.playbook.run"]
        if self._has_running_run_for_playbook(lead, playbook):
            return self.env["lead.engine.playbook.run"]
        return self.start_playbook(lead, playbook)

    @api.model
    def start_playbook(
        self,
        lead,
        playbook,
        *,
        force_duplicate=False,
        allow_duplicate_active_run=False,
    ):
        """Attach a playbook to a lead and begin execution.

        :param force_duplicate: allow starting when ``duplicate_status == duplicate``
            (manual / tests). Auto path never passes this.
        :param allow_duplicate_active_run: if False (default), block when a **running**
            run already exists for the same lead + playbook. Managers may set True to
            force a second concurrent run (explicit override).
        """
        lead = lead.sudo()
        playbook = playbook.sudo()
        playbook.ensure_one()
        if playbook.company_id != lead.company_id:
            raise UserError(_("Playbook and lead must share the same company."))
        if (
            lead.duplicate_status == "duplicate"
            and not force_duplicate
        ):
            raise UserError(
                _("Playbooks do not start on duplicate leads unless forced for manual runs.")
            )
        self._validate_playbook_for_new_run(playbook)
        if (
            not allow_duplicate_active_run
            and self._has_running_run_for_playbook(lead, playbook)
        ):
            raise UserError(
                _("This lead already has a running run for this playbook. Use the manager override to start another, or wait until it finishes.")
            )
        # Runs are created by the service (operators lack direct create ACL on runs).
        Run = self.env["lead.engine.playbook.run"].sudo()
        run = Run.create(
            {
                "playbook_id": playbook.id,
                "lead_id": lead.id,
                "state": "draft",
            }
        )
        self.schedule_next_steps(run)
        self.execute_due_steps(run=run)
        return run

    @api.model
    def schedule_next_steps(self, run):
        """Build run lines from playbook steps with cumulative ``scheduled_at`` from ``started_at``."""
        run = run.sudo()
        run.ensure_one()
        if run.state not in ("draft", "running"):
            return run
        if run.line_ids:
            return run
        steps = run.playbook_id.step_ids.sorted(lambda s: (s.sequence, s.id))
        if not steps:
            raise UserError(
                _("This playbook has no steps. Add at least one step before scheduling a run.")
            )
        base = fields.Datetime.now()
        offset = timedelta(0)
        line_vals = []
        for step in steps:
            self._validate_step_runtime(step)
            if step.delay_unit == "hours":
                offset += timedelta(hours=step.delay_amount)
            elif step.delay_unit == "days":
                offset += timedelta(days=step.delay_amount)
            scheduled = base + offset
            line_vals.append(
                (
                    0,
                    0,
                    {
                        "step_id": step.id,
                        "sequence": step.sequence,
                        "scheduled_at": scheduled,
                        "state": "pending",
                    },
                )
            )
        run.write(
            {
                "line_ids": line_vals,
                "state": "running",
                "started_at": base,
            }
        )
        return run

    @api.model
    def execute_due_steps(self, run=None):
        """Execute pending lines whose schedule has passed and whose prior lines are finished.

        Idempotent: lines already *due* or no longer *pending* are skipped (atomic claim).
        """
        self = self.sudo()
        now = fields.Datetime.now()
        Line = self.env["lead.engine.playbook.run.line"]
        domain = [
            ("state", "=", "pending"),
            ("scheduled_at", "<=", now),
            ("run_id.state", "=", "running"),
        ]
        if run is not None:
            domain.append(("run_id", "=", run.id))
        lines = Line.search(domain, order="run_id, sequence, id")
        runs_to_finalize = self.env["lead.engine.playbook.run"]
        for line in lines:
            if not self._prior_lines_done(line):
                continue
            self.execute_step(line)
            runs_to_finalize |= line.run_id
        if run is not None:
            runs_to_finalize |= run
        for r in runs_to_finalize:
            self.finalize_run(r)
        return True

    @api.model
    def execute_step(self, run_line):
        """Run a single line; only one worker can claim *pending*→*due* for this row."""
        self = self.sudo()
        line = run_line.sudo()
        line.ensure_one()
        line_id = line.id
        run_id = line.run_id.id
        if line.run_id.state != "running":
            return line
        if not self._prior_lines_done(line):
            return line
        now = fields.Datetime.now()
        if line.scheduled_at > now:
            return line
        Line = self.env["lead.engine.playbook.run.line"]
        Line.flush_model()
        if not self._claim_line_pending_to_due(line_id):
            return line
        line = Line.browse(line_id)
        lead = line.run_id.lead_id
        step = line.step_id
        self._validate_step_runtime(step)
        try:
            if step.step_type == "create_activity":
                user_id = step.activity_user_id.id or lead.user_id.id or self.env.uid
                lead.activity_schedule(
                    activity_type_id=step.activity_type_id.id,
                    summary=step.activity_summary or step.name,
                    note=step.activity_note or "",
                    user_id=user_id,
                )
            elif step.step_type == "send_email_template":
                step.mail_template_id.send_mail(lead.id, force_send=False)
            elif step.step_type == "assign_owner":
                vals = {}
                if step.assign_user_id:
                    vals["user_id"] = step.assign_user_id.id
                if step.assign_team_id:
                    vals["team_id"] = step.assign_team_id.id
                if not vals:
                    raise UserError(
                        _("Assign step “%s” has no salesperson or sales team.", step.name)
                    )
                lead.write(vals)
            elif step.step_type == "server_action":
                act = step.server_action_id.with_context(
                    active_id=lead.id,
                    active_ids=lead.ids,
                    active_model="crm.lead",
                )
                act.run()
            self._finalize_line_success(line_id)
        except Exception as err:  # pylint: disable=broad-except
            msg = str(err)
            self._finalize_line_error(line_id, msg)
            self.env["lead.engine.playbook.run"].browse(run_id).write(
                {
                    "state": "error",
                    "error_message": msg,
                }
            )
        Line.invalidate_model()
        run = self.env["lead.engine.playbook.run"].browse(run_id)
        self.finalize_run(run)
        return Line.browse(line_id)

    @api.model
    def finalize_run(self, run):
        """Close run when all lines are terminal; propagate error state. Idempotent."""
        run = run.sudo()
        run.ensure_one()
        if run.state in ("cancelled", "draft", "done"):
            return run
        lines = run.line_ids
        if not lines:
            if run.state == "running":
                run.write(
                    {
                        "state": "done",
                        "completed_at": fields.Datetime.now(),
                    }
                )
            return run
        if any(l.state == "error" for l in lines):
            if run.state != "error":
                run.write(
                    {
                        "state": "error",
                        "error_message": next(
                            (l.error_message for l in lines if l.error_message),
                            _("Step error"),
                        ),
                    }
                )
            return run
        if all(l.state in ("done", "skipped") for l in lines):
            run.write(
                {
                    "state": "done",
                    "completed_at": fields.Datetime.now(),
                    "error_message": False,
                }
            )
        return run

    @api.model
    def cancel_run(self, run):
        """Cancel a run: skip pending, due, and error lines; *done* / *skipped* unchanged.

        :raises UserError: if the run is already *done* or *cancelled*.
        """
        run = run.sudo()
        run.ensure_one()
        if run.state == "done":
            raise UserError(_("This run is already done and cannot be cancelled."))
        if run.state == "cancelled":
            raise UserError(_("This run is already cancelled."))
        done_line_ids_before = set(run.line_ids.filtered(lambda l: l.state == "done").ids)
        run.line_ids.filtered(
            lambda l: l.state in ("pending", "due", "error")
        ).write({"state": "skipped"})
        run.write(
            {
                "state": "cancelled",
                "completed_at": fields.Datetime.now(),
                "error_message": False,
            }
        )
        run.invalidate_recordset()
        for lid in done_line_ids_before:
            line = run.line_ids.browse(lid)
            if not line.exists() or line.state != "done":
                _logger.error(
                    "cancel_run altered a done line on run %s (line %s state=%s)",
                    run.id,
                    lid,
                    line.state if line.exists() else "missing",
                )
                raise UserError(
                    _("Cancel could not complete safely; contact an administrator.")
                )
        return run

    @api.model
    def retry_errored_run(self, run):
        """Resume a run in *error*: reset **error** lines to *pending* (due now).

        :raises UserError: if not in *error* or no error lines.
        """
        run = run.sudo()
        run.ensure_one()
        if run.state != "error":
            raise UserError(_("Only runs in error state can be retried."))
        if not run.playbook_id.active:
            raise UserError(_("Cannot retry using an archived playbook. Restore the playbook or use another run."))
        err_lines = run.line_ids.filtered(lambda l: l.state == "error")
        if not err_lines:
            raise UserError(_("No failed step found to retry."))
        done_line_ids_before = set(run.line_ids.filtered(lambda l: l.state == "done").ids)
        now = fields.Datetime.now()
        err_lines.write(
            {
                "state": "pending",
                "scheduled_at": now,
                "error_message": False,
            }
        )
        run.write(
            {
                "state": "running",
                "error_message": False,
            }
        )
        run.invalidate_recordset()
        if set(run.line_ids.filtered(lambda l: l.state == "done").ids) != done_line_ids_before:
            raise UserError(_("Retry could not complete safely; contact an administrator."))
        self.execute_due_steps(run=run)
        return run

    # ------------------------------------------------------------------
    # Step / playbook validation
    # ------------------------------------------------------------------

    @api.model
    def _validate_playbook_for_new_run(self, playbook):
        playbook.ensure_one()
        if not playbook.active:
            raise UserError(_("Cannot start an archived playbook."))
        if not playbook.step_ids:
            raise UserError(
                _("This playbook has no steps. Add at least one step before starting.")
            )
        for step in playbook.step_ids:
            self._validate_step_runtime(step)

    @api.model
    def _validate_step_runtime(self, step):
        step.ensure_one()
        if step.step_type == "create_activity":
            if not step.activity_type_id:
                raise UserError(
                    _("Step “%s” is missing an activity type.", step.name)
                )
            if not step.activity_type_id.active:
                raise UserError(
                    _("Step “%s” uses an archived activity type.", step.name)
                )
        elif step.step_type == "send_email_template":
            if not step.mail_template_id:
                raise UserError(
                    _("Step “%s” is missing an email template.", step.name)
                )
            if step.mail_template_id.model != "crm.lead":
                raise UserError(
                    _("Step “%s”: the template must target model crm.lead.", step.name)
                )
            if hasattr(step.mail_template_id, "active") and not step.mail_template_id.active:
                raise UserError(
                    _("Step “%s” uses an archived email template.", step.name)
                )
        elif step.step_type == "assign_owner":
            if not step.assign_user_id and not step.assign_team_id:
                raise UserError(
                    _("Step “%s” must set a salesperson and/or a sales team.", step.name)
                )
            if step.assign_user_id and not step.assign_user_id.active:
                raise UserError(
                    _("Step “%s” references an inactive user.", step.name)
                )
            if step.assign_team_id and not step.assign_team_id.active:
                raise UserError(
                    _("Step “%s” references an archived sales team.", step.name)
                )
        elif step.step_type == "server_action":
            if not step.server_action_id:
                raise UserError(
                    _("Step “%s” is missing a server action.", step.name)
                )
            if hasattr(step.server_action_id, "active") and not step.server_action_id.active:
                raise UserError(
                    _("Step “%s” uses an inactive server action.", step.name)
                )

    # ------------------------------------------------------------------
    # DB-safe line transitions
    # ------------------------------------------------------------------

    @api.model
    def _claim_line_pending_to_due(self, line_id):
        """Atomically set *pending* → *due*. Returns True if this call claimed the row."""
        cr = self.env.cr
        table = self.env["lead.engine.playbook.run.line"]._table
        cr.execute(
            f"""
            UPDATE {table}
            SET state = %s
            WHERE id = %s AND state = %s
            RETURNING id
            """,
            ("due", line_id, "pending"),
        )
        return bool(cr.fetchone())

    @api.model
    def _finalize_line_success(self, line_id):
        cr = self.env.cr
        table = self.env["lead.engine.playbook.run.line"]._table
        now = fields.Datetime.now()
        cr.execute(
            f"""
            UPDATE {table}
            SET state = %s, executed_at = %s, error_message = NULL
            WHERE id = %s AND state = %s
            RETURNING id
            """,
            ("done", now, line_id, "due"),
        )
        if not cr.fetchone():
            raise UserError(
                _("Could not finalize playbook step (line %s). It may have been processed already.", line_id)
            )

    @api.model
    def _finalize_line_error(self, line_id, message):
        cr = self.env.cr
        table = self.env["lead.engine.playbook.run.line"]._table
        now = fields.Datetime.now()
        cr.execute(
            f"""
            UPDATE {table}
            SET state = %s, error_message = %s, executed_at = %s
            WHERE id = %s AND state = %s
            RETURNING id
            """,
            ("error", message, now, line_id, "due"),
        )
        if not cr.fetchone():
            cr.execute(
                f"""
                UPDATE {table}
                SET state = %s, error_message = %s, executed_at = %s
                WHERE id = %s AND state = %s
                RETURNING id
                """,
                ("error", message, now, line_id, "pending"),
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _has_running_run_for_playbook(self, lead, playbook):
        return bool(
            self.env["lead.engine.playbook.run"].search_count(
                [
                    ("lead_id", "=", lead.id),
                    ("playbook_id", "=", playbook.id),
                    ("state", "=", "running"),
                ],
                limit=1,
            )
        )

    def _prior_lines_done(self, line):
        priors = line.run_id.line_ids.filtered(
            lambda l: (l.sequence, l.id) < (line.sequence, line.id)
        )
        return all(p.state in ("done", "skipped") for p in priors)
