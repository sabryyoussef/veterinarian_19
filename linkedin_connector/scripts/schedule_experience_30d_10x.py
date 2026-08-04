# -*- coding: utf-8 -*-
"""Schedule 10 personal job-branding posts/day for 30 days (300 total).

Personal account only — never PetSpot/company.
Run via: python3 this_file.py
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytz
import xmlrpc.client

DAYS = 30
POSTS_PER_DAY = 10
START = date(2026, 8, 4)
TZ = pytz.timezone("Africa/Cairo")
# Spread across the day (local Cairo)
SLOTS = [
    (8, 0),
    (9, 0),
    (10, 0),
    (11, 0),
    (12, 0),
    (14, 0),
    (15, 0),
    (16, 0),
    (17, 0),
    (18, 0),
]
TITLE_PREFIX = "Personal Brand 30d"


def load_env(path: Path) -> dict:
    data = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.strip().startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def build_messages() -> list[str]:
    """300 unique personal-branding posts (skills + experience + consulting)."""
    # Confirmed profile facts only — do not invent employers/metrics.
    openings = [
        "After 8+ years with Odoo,",
        "As a senior Odoo developer,",
        "Working as an Odoo technical consultant,",
        "In real Odoo delivery,",
        "From a techno-functional Odoo perspective,",
        "When I review Odoo projects,",
        "As someone who builds and advises on Odoo,",
        "In production Odoo work,",
        "Across Odoo implementations I have supported,",
        "As an Odoo engineer focused on maintainability,",
    ]
    skills_blocks = [
        (
            "My core stack is Python, Odoo, PostgreSQL, and Docker.",
            "That combination covers custom modules, data integrity, and deployable environments.",
            "#Odoo #Python #PostgreSQL #Docker #OdooDeveloper",
        ),
        (
            "I treat ACLs and record rules as core delivery — not a side task.",
            "The right person must see the right company data at the right time.",
            "#Odoo #AccessControl #MultiCompany #ERP #OdooDeveloper",
        ),
        (
            "My consulting order is configuration first, Studio second, custom code third.",
            "That protects budget, upgrades, and long-term maintainability.",
            "#Odoo #OdooConsultant #ERPImplementation #BusinessAutomation",
        ),
        (
            "Techno-functional work means I clarify the business rule before writing models.",
            "Who approves? What fails? What is the exception path?",
            "#Odoo #TechnoFunctional #ProcessImprovement #OdooConsultant",
        ),
        (
            "Integrations need a source of truth before any webhook or API adapter.",
            "Architecture first. Adapters second.",
            "#Odoo #SystemIntegration #API #ERP #OdooDeveloper",
        ),
        (
            "I design custom modules for the next upgrade, not only the current go-live.",
            "Readable structure, safe inheritance, minimal override surface.",
            "#Odoo #SoftwareEngineering #ERPUpgrade #OdooMigration",
        ),
        (
            "Performance work is measure → find the hot path → fix → re-measure.",
            "Guessing rewrites without evidence wastes weeks.",
            "#Odoo #Performance #PostgreSQL #Python #OdooDeveloper",
        ),
        (
            "Go-live is a milestone. Operational adoption is the win.",
            "Reports trusted, approvals respected, exceptions handled cleanly.",
            "#Odoo #ChangeManagement #UserAdoption #ERPImplementation",
        ),
        (
            "Reporting quality starts with data discipline, not fancy dashboards.",
            "Bad data + beautiful charts = expensive confusion.",
            "#Odoo #DataQuality #BusinessIntelligence #ERP",
        ),
        (
            "Multi-company setups fail when ownership is vague.",
            "Who owns the customer? Who invoices? What is shared vs isolated?",
            "#Odoo #MultiCompany #OdooArchitect #ERP",
        ),
        (
            "Shopify and ecommerce syncs fail when master-data ownership is unclear.",
            "Decide what Odoo masters vs what the storefront masters — then sync.",
            "#Odoo #Shopify #Ecommerce #SystemIntegration",
        ),
        (
            "Scheduled actions, validation, and clean defaults remove daily friction.",
            "Invisible automation is often the highest-value customization.",
            "#Odoo #Automation #UX #OdooDeveloper",
        ),
        (
            "Users rarely hate Odoo. They hate repeated entry and unclear errors.",
            "Adoption rises when the system is easier than the old manual method.",
            "#Odoo #UserAdoption #ERP #OdooImplementation",
        ),
        (
            "Migration is partly cleanup: drop dead fields, legacy hacks, unused reports.",
            "Do not carry operational debt into the new version blindly.",
            "#Odoo #Migration #ERPUpgrade #OdooDeveloper",
        ),
        (
            "Security maturity beats demo dashboards every time.",
            "Menus, groups, and field behavior by role are part of professional ERP.",
            "#Odoo #CyberSecurity #AccessControl #ERP",
        ),
        (
            "I use Docker so Odoo environments stay reproducible for teams.",
            "Predictable setups reduce “works on my machine” delivery risk.",
            "#Odoo #Docker #DevOps #Python",
        ),
        (
            "PostgreSQL discipline matters: indexes, domains, and careful computes.",
            "Most slow Odoo screens have a measurable database story.",
            "#Odoo #PostgreSQL #Performance #ERP",
        ),
        (
            "A strong Odoo professional knows when not to build.",
            "Activities, automated actions, routes, and reordering rules already solve a lot.",
            "#Odoo #ERP #Implementation #OdooExpert",
        ),
        (
            "I connect technical design back to business impact.",
            "From process → system, and from system → operational outcome.",
            "#Odoo #ERPConsulting #BusinessSystems #OdooDeveloper",
        ),
        (
            "Clean naming, module boundaries, and upgrade-aware inheritance are senior skills.",
            "Fast delivery this week must still be supportable next year.",
            "#Odoo #SoftwareEngineering #Python #OdooDevelopment",
        ),
        (
            "Approval routing and exception handling define whether ERP is trusted.",
            "If exceptions live in chat apps, the system is incomplete.",
            "#Odoo #Workflow #ProcessDesign #OdooConsultant",
        ),
        (
            "I keep personal job branding separate from company marketing pages.",
            "Clarity of voice matters as much as clarity of code.",
            "#Odoo #PersonalBranding #OdooDeveloper #OpenToWork",
        ),
        (
            "Technical leadership in Odoo is teaching standards, not only shipping tickets.",
            "Protect the codebase from unnecessary customization pressure.",
            "#Odoo #TechnicalLeadership #Mentoring #ERP",
        ),
        (
            "API work without governance becomes a conflict engine.",
            "Pricing, partners, and stock each need an explicit owner system.",
            "#Odoo #API #Governance #SystemIntegration",
        ),
        (
            "I am strongest where technical depth and consulting clarity meet.",
            "Code without process understanding creates expensive rework.",
            "#Odoo #TechnoFunctional #OdooDeveloper #Consulting",
        ),
        (
            "Cron pileups and confirm timeouts usually have boring, fixable causes.",
            "Logs and query analysis beat panic every time.",
            "#Odoo #Performance #Troubleshooting #Python",
        ),
        (
            "Portal access, activities, and server actions are underused power tools.",
            "Many “custom module” requests are standard Odoo used poorly.",
            "#Odoo #OdooTips #ERP #Productivity",
        ),
        (
            "Field defaults and smart warnings prevent mistakes before they become tickets.",
            "Good UX in Odoo is often backend discipline, not a redesign.",
            "#Odoo #UX #Automation #OdooDeveloper",
        ),
        (
            "I look for senior Odoo developer, technical lead, and techno-functional roles.",
            "Teams that value maintainable ERP over demo-driven customization.",
            "#Odoo #OpenToWork #Hiring #OdooDeveloper #TechnicalConsultant",
        ),
        (
            "ERP success is operational discipline translated into system logic.",
            "That is the standard I bring as developer and consultant.",
            "#Odoo #ERP #DigitalOperations #OdooConsultant",
        ),
    ]
    middles = [
        "This is the kind of judgment clients feel in daily operations.",
        "That mindset separates demo projects from production systems.",
        "It sounds simple, but it changes project outcomes.",
        "I return to this principle on almost every engagement.",
        "It is how I keep Odoo useful after the celebration of go-live.",
        "This is what I mean by production-safe delivery.",
        "That is where consulting and engineering reinforce each other.",
        "I apply this whether the ask is a small fix or a full workstream.",
        "It keeps technical debt visible instead of hidden in “quick” modules.",
        "This is part of treating Odoo as an operational system, not a slideshow.",
    ]
    closings = [
        "Happy to connect with teams hiring senior Odoo talent.",
        "If this resonates with your Odoo roadmap, let’s talk.",
        "Open to conversations about senior Odoo roles.",
        "Building maintainable ERP is the work I enjoy most.",
        "Profile: https://www.linkedin.com/in/sabry-youssef-56a878185/",
        "This is the standard I hold my own delivery to.",
        "Curious how other Odoo teams handle the same trade-off.",
        "Sharing this for practitioners who care about long-term ERP health.",
        "I write about Odoo the way I implement it: practical and upgrade-aware.",
        "More thoughts coming — follow along if you work with Odoo daily.",
    ]

    messages: list[str] = []
    n = DAYS * POSTS_PER_DAY
    for i in range(n):
        opening = openings[i % len(openings)]
        skill_a, skill_b, tags = skills_blocks[i % len(skills_blocks)]
        middle = middles[(i * 3) % len(middles)]
        closing = closings[(i * 7) % len(closings)]
        # Rotate structure + unique series stamp so every post is distinct
        day_n = (i // POSTS_PER_DAY) + 1
        slot_n = (i % POSTS_PER_DAY) + 1
        stamp = f"(Personal Odoo series · day {day_n} · post {slot_n}/10)"
        if i % 4 == 0:
            body = (
                f"{opening}\n\n{skill_a}\n{skill_b}\n\n{middle}\n\n{closing}\n\n{stamp}\n\n{tags}"
            )
        elif i % 4 == 1:
            body = (
                f"{skill_a}\n\n{opening} {skill_b}\n\n{middle}\n\n{closing}\n\n{stamp}\n\n{tags}"
            )
        elif i % 4 == 2:
            body = (
                f"{opening}\n\n{middle}\n\n{skill_a}\n{skill_b}\n\n{closing}\n\n{stamp}\n\n{tags}"
            )
        else:
            body = (
                f"Day focus for practitioners {stamp}:\n\n"
                f"{skill_a}\n{skill_b}\n\n{opening} {middle}\n\n{closing}\n\n{tags}"
            )
        messages.append(body.strip())
    assert len(messages) == n
    assert len(set(messages)) == n, "duplicate messages generated"
    return messages


def local_to_utc_naive(day: date, hour: int, minute: int) -> datetime:
    local_dt = TZ.localize(datetime.combine(day, time(hour, minute)))
    return local_dt.astimezone(pytz.UTC).replace(tzinfo=None)


def main() -> None:
    env = load_env(
        Path("/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/.env")
    )
    url = "http://100.76.217.35:8027"
    db = env["ODOO_DB"]
    user = env["ODOO_USERNAME"]
    pwd = env["ODOO_PASSWORD"]

    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common", allow_none=True)
    uid = common.authenticate(db, user, pwd, {})
    assert uid, "auth failed"
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object", allow_none=True)

    personal = models.execute_kw(
        db,
        uid,
        pwd,
        "linkedin.account",
        "search_read",
        [[("account_type", "=", "personal")]],
        {"fields": ["id", "name", "account_type"], "limit": 1},
    )
    assert personal, "No personal LinkedIn account"
    personal_id = personal[0]["id"]
    assert personal[0]["account_type"] == "personal"
    print("PERSONAL_ONLY", personal_id, personal[0]["name"])

    company = models.execute_kw(
        db,
        uid,
        pwd,
        "linkedin.account",
        "search",
        [[("account_type", "=", "company")]],
    )
    print("company_accounts_ignored", company)

    # Remove previous sparse Experience Reveal schedule (personal only)
    old_ids = models.execute_kw(
        db,
        uid,
        pwd,
        "linkedin.post",
        "search",
        [
            [
                ("account_id", "=", personal_id),
                ("state", "=", "scheduled"),
                "|",
                ("internal_title", "like", "Experience Reveal%"),
                ("internal_title", "like", f"{TITLE_PREFIX}%"),
            ]
        ],
    )
    if old_ids:
        models.execute_kw(db, uid, pwd, "linkedin.post", "unlink", [old_ids])
        print("removed_old_scheduled", len(old_ids), old_ids)

    messages = build_messages()
    vals_list = []
    idx = 0
    for day_off in range(DAYS):
        day = START + timedelta(days=day_off)
        for slot_i, (hh, mm) in enumerate(SLOTS):
            idx += 1
            scheduled = local_to_utc_naive(day, hh, mm)
            vals_list.append(
                {
                    "account_id": personal_id,
                    "content_purpose": "job_branding",
                    "internal_title": f"{TITLE_PREFIX} D{day_off + 1:02d} P{slot_i + 1:02d}",
                    "message": messages[idx - 1],
                    "post_method": "scheduled",
                    "scheduled_date": scheduled.strftime("%Y-%m-%d %H:%M:%S"),
                    "state": "scheduled",
                    "visibility": "PUBLIC",
                }
            )

    # Safety: never schedule on company
    assert all(v["account_id"] == personal_id for v in vals_list)
    assert all(v["content_purpose"] == "job_branding" for v in vals_list)
    assert len(vals_list) == DAYS * POSTS_PER_DAY

    created_ids: list[int] = []
    batch = 50
    for i in range(0, len(vals_list), batch):
        chunk = vals_list[i : i + batch]
        ids = models.execute_kw(db, uid, pwd, "linkedin.post", "create", [chunk])
        if isinstance(ids, int):
            ids = [ids]
        created_ids.extend(ids)
        print("created_batch", i // batch + 1, "count", len(ids))

    # Isolation proof
    bad = models.execute_kw(
        db,
        uid,
        pwd,
        "linkedin.post",
        "search_count",
        [
            [
                ("id", "in", created_ids),
                "|",
                ("account_id", "!=", personal_id),
                ("content_purpose", "!=", "job_branding"),
            ]
        ],
    )
    assert bad == 0, "isolation breach"

    sample = models.execute_kw(
        db,
        uid,
        pwd,
        "linkedin.post",
        "search_read",
        [[("id", "in", created_ids)]],
        {
            "fields": ["id", "internal_title", "scheduled_date", "account_id", "content_purpose", "state"],
            "order": "scheduled_date asc",
            "limit": 5,
        },
    )
    last = models.execute_kw(
        db,
        uid,
        pwd,
        "linkedin.post",
        "search_read",
        [[("id", "in", created_ids)]],
        {
            "fields": ["id", "internal_title", "scheduled_date"],
            "order": "scheduled_date desc",
            "limit": 3,
        },
    )

    # Ensure publish cron active via SQL-friendly ORM if possible
    # (admin XML-RPC may lack ir.cron ACL — ignore failure)
    try:
        cron = models.execute_kw(
            db,
            uid,
            pwd,
            "ir.cron",
            "search_read",
            [[("id", "=", 60)]],
            {"fields": ["id", "active", "cron_name"]},
        )
        print("cron_orm", cron)
    except Exception as exc:
        print("cron_orm_skip", type(exc).__name__)

    print("TOTAL", len(created_ids))
    print("FIRST", sample)
    print("LAST", last)
    print(
        "VIEW",
        "LinkedIn → Posts (personal) — filter Scheduled / title Personal Brand 30d",
    )


if __name__ == "__main__":
    main()
