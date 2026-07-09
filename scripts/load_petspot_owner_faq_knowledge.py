#!/usr/bin/env python3
"""Load PetSpot owner FAQ markdown into Odoo Knowledge + Ask AI sources.

Run via odoo-bin shell:
  odoo-bin shell -c ... -d pet_spot_elsahel --no-http < this_file
"""
from __future__ import annotations

import html
import re
from pathlib import Path

SEED_DIR = Path("/home/sabry/infra/nextcloud/seed-docs")
ROOT_NAME = "PetSpot Owner FAQ"


def md_to_simple_html(text: str) -> str:
    """Minimal markdown → HTML for knowledge.article body."""
    lines = text.splitlines()
    out: list[str] = []
    in_ul = False
    in_table = False

    def close_ul():
        nonlocal in_ul
        if in_ul:
            out.append("</ul>")
            in_ul = False

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            close_ul()
            continue
        if line.startswith("|") and "---" in line.replace("|", ""):
            continue
        if line.startswith("|"):
            close_ul()
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not in_table:
                out.append("<table>")
                in_table = True
            out.append("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in cells) + "</tr>")
            continue
        if in_table:
            out.append("</table>")
            in_table = False
        if line.startswith("# "):
            close_ul()
            out.append(f"<h1>{html.escape(line[2:].strip())}</h1>")
            continue
        if line.startswith("## "):
            close_ul()
            out.append(f"<h2>{html.escape(line[3:].strip())}</h2>")
            continue
        if line.startswith("### "):
            close_ul()
            out.append(f"<h3>{html.escape(line[4:].strip())}</h3>")
            continue
        if re.match(r"^[-*] ", line):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            item = re.sub(r"^[-*] ", "", line)
            item = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(item))
            # undo escape inside strong tags we just added poorly — keep simple:
            item = re.sub(r"^[-*] ", "", line)
            item = html.escape(item)
            item = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", item).replace("&lt;strong&gt;", "<strong>").replace("&lt;/strong&gt;", "</strong>")
            # simpler bold:
            item = re.sub(r"^[-*] ", "", line)
            item = html.escape(item)
            item = re.sub(r"\*\*(.+?)\*\*", lambda m: f"<strong>{m.group(1)}</strong>", item)
            # The above won't work after escape. Do bold before escape:
            item = re.sub(r"^[-*] ", "", line)
            parts = re.split(r"(\*\*.+?\*\*)", item)
            buf = []
            for p in parts:
                if p.startswith("**") and p.endswith("**"):
                    buf.append(f"<strong>{html.escape(p[2:-2])}</strong>")
                else:
                    buf.append(html.escape(p))
            out.append(f"<li>{''.join(buf)}</li>")
            continue
        close_ul()
        parts = re.split(r"(\*\*.+?\*\*)", line)
        buf = []
        for p in parts:
            if p.startswith("**") and p.endswith("**"):
                buf.append(f"<strong>{html.escape(p[2:-2])}</strong>")
            else:
                buf.append(html.escape(p))
        out.append(f"<p>{''.join(buf)}</p>")
    close_ul()
    if in_table:
        out.append("</table>")
    return "\n".join(out)


def title_from_md(name: str, text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()[:200]
    return name.replace("petspot-owner-faq-", "").replace(".md", "").replace("-", " ")


Article = env["knowledge.article"]
root = Article.search([("name", "=", ROOT_NAME), ("parent_id", "=", False)], limit=1)
if not root:
    root = Article.create(
        {
            "name": ROOT_NAME,
            "body": "<p>Public owner FAQ for PetSpot El Sahel (synced from Dify seed docs). "
            "Use with Ask AI / Knowledge search. Not clinical protocols.</p>",
            "internal_permission": "write",
            "icon": "🐾",
        }
    )
    print("created root", root.id)
else:
    print("reuse root", root.id)

created = 0
updated = 0
files = sorted(SEED_DIR.glob("petspot-owner-faq-*.md"))
child_ids = []
for path in files:
    text = path.read_text(encoding="utf-8")
    title = title_from_md(path.name, text)
    body = md_to_simple_html(text)
    existing = Article.search([("parent_id", "=", root.id), ("name", "=", title)], limit=1)
    vals = {
        "name": title,
        "body": body,
        "parent_id": root.id,
        "internal_permission": "write",
    }
    if existing:
        existing.write(vals)
        updated += 1
        child_ids.append(existing.id)
    else:
        art = Article.create(vals)
        created += 1
        child_ids.append(art.id)

print(f"articles created={created} updated={updated} total_children={len(child_ids)}")

# Attach root article to Ask AI agent if available
Agent = env["ai.agent"]
ask = Agent.search([("name", "=", "Ask AI")], limit=1) or Agent.browse(2)
if ask and ask.exists():
    Source = env["ai.agent.source"]
    already = Source.search(
        [("agent_id", "=", ask.id), ("article_id", "=", root.id), ("type", "=", "knowledge_article")],
        limit=1,
    )
    if already:
        print("Ask AI source already linked", already.id, already.status)
    else:
        try:
            Source.create_from_articles([root.id], ask.id)
            print("linked root FAQ to Ask AI agent", ask.id)
        except Exception as exc:
            print("WARN link Ask AI failed:", exc)
    # Ensure restrict_to_sources stays False so other sources still work, or True for FAQ-only testing
    # leave as-is
else:
    print("Ask AI agent not found — articles still available in Knowledge app")

env.cr.commit()
print("DONE root_id=", root.id)
print("Open Odoo → Knowledge →", ROOT_NAME)
print("Or Ask AI after sources finish processing (needs pgvector for embeddings).")
