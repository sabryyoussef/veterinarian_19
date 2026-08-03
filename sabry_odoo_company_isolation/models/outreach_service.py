# -*- coding: utf-8 -*-
import json
import logging
import os
import re

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

SABRY_COMPANY_XMLID = "sabry_odoo_company_isolation.company_sabry_odoo_development"
EXCLUSION_JSON = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "outreach_exclusions.json"
)


def load_exclusion_artifact():
    with open(EXCLUSION_JSON, encoding="utf-8") as fh:
        return json.load(fh)


def normalize_email(email):
    if not email:
        return ""
    return (email or "").strip().lower()


def email_domain(email):
    email = normalize_email(email)
    if "@" not in email:
        return ""
    return email.rsplit("@", 1)[-1].strip()


def email_local_part(email):
    email = normalize_email(email)
    if "@" not in email:
        return email
    return email.rsplit("@", 1)[0].strip()


class OutreachService:
    """Business logic for Sabry company bootstrap, partner copy, list build."""

    INCLUSION_CATEGORY_EMAIL = "Email Ready"
    INCLUSION_GRADES = ("Gold", "Silver")
    SOFT_EXCLUDE = ("Needs Review", "Duplicate Candidate")

    def __init__(self, env):
        self.env = env
        self.exclusions = load_exclusion_artifact()

    def sabry_company(self):
        return self.env.ref(SABRY_COMPANY_XMLID)

    def petspot_company(self):
        return self.env.ref("base.main_company")

    def ensure_company_bootstrap(self):
        sabry = self.sabry_company()
        pet = self.petspot_company()
        admin = self.env.ref("base.user_admin")
        companies = admin.company_ids | sabry | pet
        admin.sudo().write(
            {
                "company_ids": [(6, 0, companies.ids)],
                # Keep PetSpot as default so clinic ops stay the landing context.
                "company_id": pet.id,
            }
        )
        # Rebind Sabry websites away from PetSpot.
        Website = self.env["website"].sudo()
        sabry_sites = Website.search(
            [
                "|",
                ("name", "ilike", "Sabry"),
                ("name", "ilike", "sabry_youssef"),
            ]
        )
        for site in sabry_sites:
            vals = {"company_id": sabry.id}
            if "Sabry / Odoo Developer" in (site.name or "") or site.name == "Sabry Odoo Development":
                vals["name"] = "Sabry Odoo Development"
            site.write(vals)
        # Ensure CRM team for Sabry
        team = self.env["crm.team"].sudo().search(
            [("name", "=", "Odoo Partner Outreach")], limit=1
        )
        if team and not team.company_id:
            # Leave shared OR set Sabry — set Sabry for outreach isolation.
            team.company_id = sabry.id
        _logger.info(
            "Sabry company bootstrap complete: company=%s admin_companies=%s",
            sabry.id,
            admin.company_ids.ids,
        )
        return sabry

    def is_excluded_partner(self, partner):
        email = normalize_email(partner.email)
        if not email:
            return True, "empty_email"
        if email in {normalize_email(e) for e in self.exclusions["self_emails"]}:
            return True, "self_email"
        local = email_local_part(email)
        if local in self.exclusions["junk_local_parts"]:
            return True, "junk_local_part"
        domain = email_domain(email)
        if domain in self.exclusions["excluded_domains"]:
            return True, "excluded_domain"
        # website host match
        website = (partner.website or "").lower()
        for d in self.exclusions["excluded_domains"]:
            if d in website:
                return True, "excluded_website_domain"
        name = partner.name or ""
        if isinstance(name, dict):
            name = name.get("en_US") or next(iter(name.values()), "")
        name = str(name)
        for frag in self.exclusions["excluded_name_substrings"]:
            if frag.lower() in name.lower():
                # For job-board names, only exclude if no real company domain
                if frag.lower() in ("indeed", "talentlyft", "workable"):
                    if domain.endswith((".com", ".net", ".org", ".io", ".ai")) and domain not in (
                        "indeed.com",
                        "talentlyft.com",
                        "workable.com",
                    ):
                        continue
                return True, f"excluded_name:{frag}"
        return False, ""

    def source_eligible_partners(self):
        Partner = self.env["res.partner"].sudo()
        Category = self.env["res.partner.category"].sudo()
        email_ready = Category.search([("name", "=", self.INCLUSION_CATEGORY_EMAIL)], limit=1)
        grades = Category.search([("name", "in", list(self.INCLUSION_GRADES))])
        soft = Category.search([("name", "in", list(self.SOFT_EXCLUDE))])
        if not email_ready or not grades:
            raise UserError(_("Missing Email Ready / Gold / Silver categories."))
        domain = [
            ("active", "=", True),
            ("email", "!=", False),
            ("email", "!=", ""),
            ("category_id", "in", email_ready.ids),
            ("category_id", "in", grades.ids),
        ]
        if soft:
            domain.append(("category_id", "not in", soft.ids))
        # Prefer sources that are not already Sabry copies
        sabry = self.sabry_company()
        partners = Partner.search(domain)
        # Drop already-Sabry copies from source set (they have x_source_partner_id)
        partners = partners.filtered(
            lambda p: p.company_id.id != sabry.id
            and not getattr(p, "x_source_partner_id", False)
        )
        return partners

    def category_by_names(self, names):
        Category = self.env["res.partner.category"].sudo()
        cats = Category.search([("name", "in", list(names))])
        return cats

    def copy_partner_to_sabry(self, source):
        sabry = self.sabry_company()
        Partner = self.env["res.partner"].with_company(sabry).sudo()
        email = normalize_email(source.email)
        existing = Partner.search(
            [
                ("email_normalized", "=", email) if "email_normalized" in Partner._fields else ("email", "=ilike", email),
                ("company_id", "=", sabry.id),
            ],
            limit=1,
        )
        if not existing and "email_normalized" in Partner._fields:
            # fallback ilike
            existing = Partner.search(
                [("email", "=ilike", email), ("company_id", "=", sabry.id)], limit=1
            )
        cat_names = source.category_id.mapped("name")
        # normalize translated names
        resolved_names = []
        for n in cat_names:
            if isinstance(n, dict):
                resolved_names.append(n.get("en_US") or next(iter(n.values()), ""))
            else:
                resolved_names.append(n)
        categories = self.category_by_names(resolved_names)
        vals = {
            "name": source.name,
            "email": source.email,
            "phone": source.phone,
            "website": source.website,
            "company_name": source.company_name or source.name,
            "company_id": sabry.id,
            "category_id": [(6, 0, categories.ids)],
            "x_source_partner_id": source.id,
            "x_outreach_eligible": True,
            "is_company": source.is_company,
            "comment": _("Outreach copy of partner %s") % source.id,
        }
        if "mobile" in source._fields and source.mobile:
            vals["mobile"] = source.mobile
        if "company_name" not in source._fields:
            vals.pop("company_name", None)
            if "commercial_company_name" in source._fields:
                vals["commercial_company_name"] = source.commercial_company_name

        if existing:
            existing.write(vals)
            return existing, False
        return Partner.create(vals), True

    def sync_eligible_copies(self):
        sources = self.source_eligible_partners()
        created = self.env["res.partner"]
        updated = self.env["res.partner"]
        excluded = []
        for src in sources:
            excluded_flag, reason = self.is_excluded_partner(src)
            if excluded_flag:
                excluded.append({"id": src.id, "email": src.email, "reason": reason})
                continue
            partner, is_new = self.copy_partner_to_sabry(src)
            if is_new:
                created |= partner
            else:
                updated |= partner
        return {
            "source_count": len(sources),
            "created": created,
            "updated": updated,
            "excluded": excluded,
            "eligible": created | updated,
        }

    def apply_blacklist_for_exclusions(self):
        Blacklist = self.env["mail.blacklist"].sudo()
        added = []
        for email in self.exclusions["self_emails"]:
            if not Blacklist.search([("email", "=", normalize_email(email))], limit=1):
                Blacklist._add(email)
                added.append(email)
        # Representative addresses for bounced domains
        for domain in self.exclusions["excluded_domains"]:
            probe = f"noreply@{domain}"
            if not Blacklist.search([("email", "=", probe)], limit=1):
                Blacklist._add(probe)
                added.append(probe)
        return added

    def build_mailing_list(self, list_name="Sabry — Odoo Partners — Gold Silver"):
        sabry = self.sabry_company()
        MailingList = self.env["mailing.list"].with_company(sabry).sudo()
        mailing_list = MailingList.search(
            [("name", "=", list_name), ("company_id", "=", sabry.id)], limit=1
        )
        if not mailing_list:
            mailing_list = MailingList.create(
                {"name": list_name, "company_id": sabry.id, "active": True}
            )
        partners = (
            self.env["res.partner"]
            .with_company(sabry)
            .sudo()
            .search(
                [
                    ("company_id", "=", sabry.id),
                    ("x_outreach_eligible", "=", True),
                    ("email", "!=", False),
                    ("email", "!=", ""),
                ]
            )
        )
        # Re-check exclusions
        keep = self.env["res.partner"]
        rejected = []
        for p in partners:
            bad, reason = self.is_excluded_partner(p)
            if bad or not p.company_id or p.company_id != sabry:
                rejected.append({"id": p.id, "email": p.email, "reason": reason or "company"})
                continue
            keep |= p
        # Use OCA wizard logic if available
        Contact = self.env["mailing.contact"].with_company(sabry).sudo()
        Subscription = self.env["mailing.subscription"].sudo()
        for partner in keep:
            contact = Contact.search(
                [
                    ("email", "=ilike", normalize_email(partner.email)),
                    ("company_id", "=", sabry.id),
                ],
                limit=1,
            )
            if not contact and "partner_id" in Contact._fields:
                contact = Contact.search([("partner_id", "=", partner.id)], limit=1)
            if not contact:
                vals = {
                    "name": partner.name,
                    "email": partner.email,
                    "company_id": sabry.id,
                    "company_name": partner.company_name or partner.name,
                }
                if "partner_id" in Contact._fields:
                    vals["partner_id"] = partner.id
                contact = Contact.create(vals)
            else:
                contact.write(
                    {
                        "name": partner.name,
                        "company_id": sabry.id,
                        **(
                            {"partner_id": partner.id}
                            if "partner_id" in Contact._fields
                            else {}
                        ),
                    }
                )
            sub = Subscription.search(
                [("contact_id", "=", contact.id), ("list_id", "=", mailing_list.id)],
                limit=1,
            )
            if not sub:
                Subscription.create(
                    {"contact_id": contact.id, "list_id": mailing_list.id}
                )
        return mailing_list, keep, rejected
