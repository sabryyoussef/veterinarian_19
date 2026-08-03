# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.sabry_odoo_company_isolation.models.outreach_service import (
    OutreachService,
)


@tagged("post_install", "-at_install", "sabry_isolation")
class TestSabryIsolation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sabry = cls.env.ref(
            "sabry_odoo_company_isolation.company_sabry_odoo_development"
        )
        cls.pet = cls.env.ref("base.main_company")
        cls.svc = OutreachService(cls.env)

    def test_company_exists(self):
        self.assertTrue(self.sabry)
        self.assertEqual(self.sabry.name, "Sabry Odoo Development")
        self.assertTrue(self.sabry.is_sabry_outreach_company)

    def test_outreach_partner_requires_company(self):
        with self.assertRaises(Exception):
            self.env["res.partner"].create(
                {
                    "name": "Bad Outreach",
                    "email": "bad-outreach-test@example.com",
                    "x_outreach_eligible": True,
                    "company_id": False,
                }
            )

    def test_idempotent_copy(self):
        cats = self.env["res.partner.category"]
        email_ready = cats.search([("name", "=", "Email Ready")], limit=1)
        gold = cats.search([("name", "=", "Gold")], limit=1)
        source = self.env["res.partner"].create(
            {
                "name": "Isolation Test Partner",
                "email": "isolation-test-partner@example-odoo-partner.test",
                "category_id": [(6, 0, (email_ready | gold).ids)],
            }
        )
        p1, created1 = self.svc.copy_partner_to_sabry(source)
        p2, created2 = self.svc.copy_partner_to_sabry(source)
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(p1.id, p2.id)
        self.assertEqual(p1.company_id, self.sabry)
        self.assertEqual(p1.x_source_partner_id, source)

    def test_exclusion_domain(self):
        partner = self.env["res.partner"].new(
            {"name": "Campto", "email": "hello@camptocamp.com"}
        )
        excluded, reason = self.svc.is_excluded_partner(partner)
        self.assertTrue(excluded)
        self.assertEqual(reason, "excluded_domain")

    def test_mailing_list_company(self):
        lst = (
            self.env["mailing.list"]
            .with_company(self.sabry)
            .create({"name": "Sabry Test List Unit", "company_id": self.sabry.id})
        )
        self.assertEqual(lst.company_id, self.sabry)

    def test_vetelsahel_forbidden_on_sabry_mailing(self):
        with self.assertRaises(Exception):
            self.env["mailing.mailing"].with_company(self.sabry).create(
                {
                    "subject": "Test forbidden sender",
                    "email_from": "vetelsahel@gmail.com",
                    "mailing_model_id": self.env["ir.model"]._get_id("mailing.contact"),
                    "body_html": "<p>x</p>",
                    "company_id": self.sabry.id,
                }
            )
