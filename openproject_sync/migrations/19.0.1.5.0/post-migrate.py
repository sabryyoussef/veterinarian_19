# -*- coding: utf-8 -*-
"""Post-upgrade hook for OP task placement (test DB — audit only, no auto-move)."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
  env = __import__("odoo.api", fromlist=["Environment"]).Environment(cr, 1, {})
  try:
      backends = env["openproject.backend"].search([])
      Wizard = env["openproject.task.realign.wizard"]
      for backend in backends:
          wiz = Wizard.create({"backend_id": backend.id, "dry_run": True})
          wiz.action_build_audit()
          moves = wiz.line_ids.filtered(lambda l: l.action == "move")
          _logger.info(
              "openproject_sync 19.0.1.5.0: backend %s realign audit — %s move(s) pending (dry-run only)",
              backend.name,
              len(moves),
          )
  except Exception:
      _logger.exception("openproject_sync 19.0.1.5.0 post-migrate audit failed")
