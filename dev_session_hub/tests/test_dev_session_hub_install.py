# -*- coding: utf-8 -*-
import json
import re
import uuid
from pathlib import Path

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDevSessionHubInstall(TransactionCase):
    """Regression coverage for menu load order and module install integrity."""

    def test_menu_parents_defined_before_children(self):
        menu_xml = Path(__file__).resolve().parents[1] / "views" / "dev_session_hub_menus.xml"
        content = menu_xml.read_text(encoding="utf-8")
        defined = set(re.findall(r'<menuitem id="([^"]+)"', content))
        for match in re.finditer(
            r'<menuitem id="([^"]+)"[^>]*parent="([^"]+)"', content
        ):
            menu_id, parent_id = match.group(1), match.group(2)
            self.assertIn(
                parent_id,
                defined,
                "Menu %s references parent %s before it is defined in %s"
                % (menu_id, parent_id, menu_xml.name),
            )
            parent_pos = content.find('id="%s"' % parent_id)
            child_pos = match.start()
            self.assertLess(
                parent_pos,
                child_pos,
                "Menu %s must appear after parent %s in %s"
                % (menu_id, parent_id, menu_xml.name),
            )

    def test_dev_session_hub_module_installed(self):
        module = self.env["ir.module.module"].search(
            [("name", "=", "dev_session_hub")], limit=1
        )
        self.assertTrue(module, "dev_session_hub must be installed for post_install tests")
        self.assertEqual(module.state, "installed")
        self.assertEqual(module.latest_version, "19.0.8.1.0")

    def test_openproject_sync_dependency_installed(self):
        module = self.env["ir.module.module"].search(
            [("name", "=", "openproject_sync")], limit=1
        )
        self.assertTrue(module)
        self.assertEqual(module.state, "installed")

    def test_configuration_menu_xmlid_resolves(self):
        menu = self.env.ref("dev_session_hub.menu_dev_session_hub_configuration")
        self.assertTrue(menu.exists())
        self.assertEqual(menu.name, "Configuration")

    def test_github_apps_menu_xmlid_resolves(self):
        menu = self.env.ref("dev_session_hub.menu_dev_session_hub_github_apps")
        self.assertTrue(menu.exists())
        self.assertEqual(
            menu.parent_id,
            self.env.ref("dev_session_hub.menu_dev_session_hub_configuration"),
        )

    def test_preexisting_outbox_rows_preserved_after_test_owned_create(self):
        Outbox = self.env["dev.external.outbox"]
        before_ids = set(Outbox.search([]).ids)
        work = self.env["dev.work.item"].search([("op_work_package_id", ">", 0)], limit=1)
        if not work or not work.op_backend_id or not work.op_work_package_id:
            self.skipTest("No OpenProject-linked work item fixture available")
        correlation_id = "install-test-%s" % uuid.uuid4().hex
        test_row = Outbox.with_context(dev_internal_outbox=True).create(
            {
                "work_item_id": work.id,
                "channel": "openproject",
                "operation": "milestone",
                "idempotency_key": correlation_id,
                "payload_json": json.dumps(
                    {
                        "schema": "dev-hub.op-milestone.v1",
                        "backend_id": work.op_backend_id.id,
                        "work_package_id": work.op_work_package_id,
                        "milestone": "material_blocker",
                        "summary": "Install regression outbox row.",
                        "status_hint": "on_hold",
                    }
                ),
                "state": "pending",
            }
        )
        after_ids = set(Outbox.search([]).ids)
        self.assertTrue(before_ids.issubset(after_ids))
        self.assertIn(test_row.id, after_ids)
        self.assertEqual(
            len(after_ids - before_ids),
            1,
            "Only the test-owned outbox row may be added.",
        )
