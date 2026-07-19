# -*- coding: utf-8 -*-
"""Preserve legacy task-link sessions without inventing external identities."""

from odoo import SUPERUSER_ID, api, fields


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    sessions = env["dev.session"].search(
        [("work_item_id", "=", False), ("task_link_id", "!=", False)]
    )
    for task_link in sessions.mapped("task_link_id"):
        tasks = env["project.task"].search(
            [("op_work_package_id", "=", task_link.openproject_work_package_id)]
        )
        if len(tasks) != 1 or not tasks.op_backend_id:
            continue
        task = tasks
        work = env["dev.work.item"].search(
            [
                ("op_backend_id", "=", task.op_backend_id.id),
                ("op_work_package_id", "=", task_link.openproject_work_package_id),
            ],
            limit=1,
        )
        if not work:
            source = env["dev.work.source.message"].create(
                {
                    "provider": "manual",
                    "provider_message_id": "legacy-task-link:%s" % task_link.id,
                    "message_timestamp": task_link.create_date or fields.Datetime.now(),
                    "text_snapshot": (
                        "Migrated legacy Dev Hub task reference: %s"
                        % task_link.display_name
                    )[:6000],
                }
            )
            work = env["dev.work.item"].create(
                {
                    "name": task.name,
                    "dev_project_id": task_link.project_id.id,
                    "odoo_project_id": task.project_id.id,
                    "odoo_task_id": task.id,
                    "op_backend_id": task.op_backend_id.id,
                    "op_work_package_id": task_link.openproject_work_package_id,
                    "op_url": task.op_url,
                    "source_message_ids": [(6, 0, source.ids)],
                }
            )
        legacy_sessions = sessions.filtered(lambda item: item.task_link_id == task_link)
        cr.execute(
            "UPDATE dev_session SET work_item_id = %s WHERE id IN %s",
            [work.id, tuple(legacy_sessions.ids)],
        )
