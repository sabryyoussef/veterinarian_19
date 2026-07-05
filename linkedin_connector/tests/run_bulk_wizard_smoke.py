#!/usr/bin/env python3
"""One-shot smoke test (no interactive shell). Run with Odoo's Python, e.g.:
   py -3.12 run_bulk_wizard_smoke.py
   from repo root or pass ODOO_ROOT / ODOO_CONF / PGDATABASE env if needed.
"""
import os
import sys

ODOO_ROOT = os.environ.get("ODOO_ROOT", r"D:\odoo\odoo19\odoo19")
ODOO_CONF = os.environ.get("ODOO_CONF", r"D:\odoo\odoo19\odoo_conf\odoo19.conf")
DB = os.environ.get("PGDATABASE") or os.environ.get("ODOO_DB", "resume_restore19")

if ODOO_ROOT not in sys.path:
    sys.path.insert(0, ODOO_ROOT)

import odoo.tools.config as config  # noqa: E402
from odoo.modules.module import initialize_sys_path  # noqa: E402

config.parse_config(["-c", ODOO_CONF, "-d", DB])
initialize_sys_path()

import odoo  # noqa: E402, F401
from odoo.modules.registry import Registry  # noqa: E402
from odoo import api, SUPERUSER_ID  # noqa: E402


def _assert_wizard_fields(env):
    wiz = env["linkedin.post.bulk.schedule"]
    required = ("recurrence_mode", "schedule_count")
    missing = [f for f in required if f not in wiz._fields]
    if missing:
        print(
            "FAIL: linkedin.post.bulk.schedule is stale (missing fields %s).\n"
            "Cause: Odoo imported an older version of the addon (common with server_wide_modules).\n"
            "Fix: stop the Odoo process completely, start it again, then Apps → Upgrade LinkedIn Connector."
            % (", ".join(missing))
        )
        return False
    return True


def main():
    registry = Registry.new(DB)
    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})
        if not _assert_wizard_fields(env):
            return 1
        acc = env["linkedin.account"].search([], limit=1)
        if not acc:
            print("SKIP: no linkedin.account in DB")
            return 0
        wiz = env["linkedin.post.bulk.schedule"].create(
            {
                "account_id": acc.id,
                "post_text": "Post 1\n\nFirst body.\n\nPost 2\n\nSecond body.",
                "title_prefix": "Smoke bulk",
            }
        )
        bodies = wiz._split_post_bodies(wiz.post_text)
        assert len(bodies) == 2, bodies
        action = wiz.action_schedule()
        assert action["type"] == "ir.actions.act_window"
        posts = env["linkedin.post"].search(action["domain"])
        assert len(posts) == 2, len(posts)
        assert all(p.state == "scheduled" for p in posts)
        posts.unlink()
        cr.commit()
    print("OK: bulk wizard created 2 scheduled posts (smoke rows removed).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
