# -*- coding: utf-8 -*-
import base64
import csv
import io
import json
import os
from datetime import datetime

from odoo import fields, models, _
from odoo.modules.module import get_module_path

from odoo.addons.sabry_odoo_company_isolation.models.outreach_service import (
    OutreachService,
    normalize_email,
)


class SabryOutreachSetupWizard(models.TransientModel):
    _name = "sabry.outreach.setup.wizard"
    _description = "Sabry Outreach Setup"

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("done", "Done"),
        ],
        default="draft",
    )
    result_summary = fields.Text(readonly=True)
    recipient_count = fields.Integer(readonly=True)

    def action_run_full_setup(self):
        self.ensure_one()
        svc = OutreachService(self.env)
        sabry = svc.ensure_company_bootstrap()
        sync = svc.sync_eligible_copies()
        blacklisted = svc.apply_blacklist_for_exclusions()
        mailing_list, keep, rejected = svc.build_mailing_list()

        # CV attachment
        cv_path = "/home/sabry/private/job_orchestrator/handoff/session_cv/Sabry_Youssef_CV.pdf"
        with open(cv_path, "rb") as fh:
            cv_b64 = base64.b64encode(fh.read())
        Attachment = self.env["ir.attachment"].with_company(sabry).sudo()
        cv_att = Attachment.search(
            [
                ("name", "=", "Sabry_Youssef_CV.pdf"),
                ("company_id", "=", sabry.id),
                ("res_model", "=", "mailing.mailing"),
            ],
            limit=1,
        )
        if not cv_att:
            cv_att = Attachment.create(
                {
                    "name": "Sabry_Youssef_CV.pdf",
                    "type": "binary",
                    "datas": cv_b64,
                    "mimetype": "application/pdf",
                    "company_id": sabry.id,
                }
            )
        else:
            cv_att.write({"datas": cv_b64, "company_id": sabry.id})

        # Mail template
        Template = self.env["mail.template"].with_company(sabry).sudo()
        template = Template.search(
            [("name", "=", "SABRY | Odoo Outreach | EN"), ("company_id", "=", sabry.id)],
            limit=1,
        )
        body = """
<div style="font-family: Arial, sans-serif; font-size: 14px; color: #222; line-height: 1.5;">
  <p>Hello,</p>
  <p>My name is <strong>Sabry Youssef</strong>, a Senior Odoo Developer with 8+ years of experience
  (Odoo 16–19). I help Odoo Partners with implementation, customization, integrations, and automation.</p>
  <p>I am available for full-time or subcontracting engagements. My CV is attached.</p>
  <p>
    Portfolio: available on the Sabry Odoo Development website<br/>
    LinkedIn: https://www.linkedin.com/in/sabry-youssef<br/>
    Email: abhorya@gmail.com
  </p>
  <p>Thank you for your time.</p>
  <p>Best regards,<br/>Sabry Youssef<br/>Senior Odoo Developer</p>
</div>
"""
        if not template:
            template = Template.create(
                {
                    "name": "SABRY | Odoo Outreach | EN",
                    "model_id": self.env["ir.model"]._get_id("mailing.contact"),
                    "subject": "Senior Odoo Developer available — Sabry Youssef",
                    "body_html": body,
                    "email_from": "abhorya@gmail.com",
                    "company_id": sabry.id,
                }
            )
        else:
            template.write(
                {
                    "body_html": body,
                    "subject": "Senior Odoo Developer available — Sabry Youssef",
                    "email_from": "abhorya@gmail.com",
                    "company_id": sabry.id,
                }
            )

        # Draft mailing
        Mailing = self.env["mailing.mailing"].with_company(sabry).sudo()
        mailing = Mailing.search(
            [
                ("subject", "=", "Senior Odoo Developer available — Sabry Youssef"),
                ("company_id", "=", sabry.id),
            ],
            limit=1,
        )
        mailing_vals = {
            "subject": "Senior Odoo Developer available — Sabry Youssef",
            "preview": "Sabry CV Outreach — Gold Silver — Canary",
            "body_arch": body,
            "body_html": body,
            "email_from": "abhorya@gmail.com",
            "reply_to_mode": "new",
            "reply_to": "abhorya@gmail.com",
            "mailing_model_id": self.env["ir.model"]._get_id("mailing.contact"),
            "contact_list_ids": [(6, 0, mailing_list.ids)],
            "attachment_ids": [(6, 0, cv_att.ids)],
            "company_id": sabry.id,
            "state": "draft",
            "keep_archives": True,
            "use_exclusion_list": True,
        }
        # Prefer no PetSpot mail server
        personal_server = self.env["ir.mail_server"].sudo().search(
            [("smtp_user", "not ilike", "vetelsahel")], limit=1
        )
        if personal_server:
            mailing_vals["mail_server_id"] = personal_server.id
        if mailing:
            mailing.write(mailing_vals)
        else:
            mailing = Mailing.create(mailing_vals)

        # Test sample list
        test_list = (
            self.env["mailing.list"]
            .with_company(sabry)
            .sudo()
            .search(
                [
                    ("name", "=", "Sabry — Sample Test Only"),
                    ("company_id", "=", sabry.id),
                ],
                limit=1,
            )
        )
        if not test_list:
            test_list = (
                self.env["mailing.list"]
                .with_company(sabry)
                .sudo()
                .create({"name": "Sabry — Sample Test Only", "company_id": sabry.id})
            )
        Contact = self.env["mailing.contact"].with_company(sabry).sudo()
        Subscription = self.env["mailing.subscription"].sudo()
        for email in ("abhorya@gmail.com", "vendorah2@gmail.com"):
            contact = Contact.search(
                [("email", "=ilike", email), ("company_id", "=", sabry.id)], limit=1
            )
            if not contact:
                contact = Contact.create(
                    {
                        "name": email.split("@")[0],
                        "email": email,
                        "company_id": sabry.id,
                    }
                )
            if not Subscription.search(
                [("contact_id", "=", contact.id), ("list_id", "=", test_list.id)], limit=1
            ):
                Subscription.create({"contact_id": contact.id, "list_id": test_list.id})

        # Export CSVs
        docs = (
            "/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/"
            "docs/sabry_company_outreach_20260803"
        )
        os.makedirs(docs, exist_ok=True)
        rows = []
        for p in keep.sorted(key=lambda r: normalize_email(r.email)):
            rows.append(
                {
                    "partner_id": p.id,
                    "name": p.name,
                    "email": p.email,
                    "company_id": p.company_id.id,
                    "source_partner_id": p.x_source_partner_id.id
                    if p.x_source_partner_id
                    else "",
                }
            )

        def write_csv(path, data_rows):
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(
                    fh,
                    fieldnames=[
                        "partner_id",
                        "name",
                        "email",
                        "company_id",
                        "source_partner_id",
                    ],
                )
                writer.writeheader()
                writer.writerows(data_rows)

        write_csv(f"{docs}/recipients_full.csv", rows)
        write_csv(f"{docs}/recipients_first_50.csv", rows[:50])
        # random 50
        import random

        random.seed(20260803)
        sample = rows[:] if len(rows) <= 50 else random.sample(rows, 50)
        write_csv(f"{docs}/recipients_random_50.csv", sample)

        with open(f"{docs}/excluded_audit.json", "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "sync_excluded": sync["excluded"],
                    "list_rejected": rejected,
                    "blacklisted_added": blacklisted,
                    "ts": datetime.utcnow().isoformat() + "Z",
                },
                fh,
                indent=2,
                default=str,
            )

        summary = {
            "sabry_company_id": sabry.id,
            "source_count": sync["source_count"],
            "created": len(sync["created"]),
            "updated": len(sync["updated"]),
            "excluded_during_sync": len(sync["excluded"]),
            "list_id": mailing_list.id,
            "list_name": mailing_list.name,
            "recipient_count": len(keep),
            "mailing_id": mailing.id,
            "cv_attachment_id": cv_att.id,
            "template_id": template.id,
            "test_list_id": test_list.id,
            "blacklisted_added": len(blacklisted),
        }
        with open(f"{docs}/setup_summary.json", "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2)

        self.write(
            {
                "state": "done",
                "recipient_count": len(keep),
                "result_summary": json.dumps(summary, indent=2),
            }
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
