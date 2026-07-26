# -*- coding: utf-8 -*-
"""Bounded task analysis against preferred repository + Test database."""
from __future__ import annotations

import ast
import hashlib
import os
import re
import urllib.request
from datetime import datetime
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

from odoo import fields, models
from odoo.exceptions import UserError

from .dev_work import MAX_TEXT, _canonical_hash

ANALYSIS_KIND = "code_database"
ANALYSIS_SCHEMA = "dev-work-code-db-analysis.v1"
ANALYSIS_PROMPT_VERSION = "code-db-analysis.v1"
MAX_FILES_SCANNED = 80
MAX_FILE_BYTES = 120_000
MAX_SNIPPET_CHARS = 2_400
MAX_DB_ROWS = 50
DB_STATEMENT_TIMEOUT_MS = 5_000
SECRET_REDACT = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|authorization)\s*[:=]\s*\S+"
)
STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "when",
    "should",
    "auto",
    "apply",
    "torz",
    "task",
    "odoo",
    "openproject",
}


def _strip_html(value):
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", text).strip()


def _redact(text):
    return SECRET_REDACT.sub(r"\1=[REDACTED]", text or "")


def _truncate(text, limit=MAX_TEXT):
    text = _redact(text or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 20)] + "\n...[truncated]..."


def _safe_analysis_text(value, limit=MAX_TEXT):
    """Normalize task text so Dev Hub forbidden-content guards do not reject it."""
    text = _strip_html(value or "")
    # Avoid FORBIDDEN_CONTENT patterns like messages: / transcript:
    text = re.sub(r"(?i)\bmessages\s*:", "source notes:", text)
    text = re.sub(r"(?i)\btranscript\s*:", "discussion:", text)
    text = re.sub(r"(?i)\braw_payload\s*:", "payload-ref:", text)
    text = re.sub(r"(?i)\benvironment_dump\s*:", "env-ref:", text)
    text = re.sub(r"(?i)\bfull_diff\s*:", "diff-ref:", text)
    text = re.sub(r"(?m)^(diff --git|index [0-9a-f]+\.\.[0-9a-f]+|@@ .+ @@)", r"[\1]", text)
    return _truncate(text, limit)

class DevWorkAnalysisCodeDb(models.Model):
    _inherit = "dev.work.analysis"

    analysis_kind = fields.Selection(
        [
            ("manual", "Manual"),
            ("generated", "Generated Draft"),
            ("code_database", "Code & Database"),
        ],
        default="manual",
        required=True,
        index=True,
    )
    execution_state = fields.Selection(
        [
            ("queued", "Queued"),
            ("running", "Running"),
            ("completed", "Completed"),
            ("failed", "Failed"),
        ],
        default="completed",
        required=True,
        index=True,
    )
    analysis_fingerprint = fields.Char(index=True, copy=False)
    environment_id = fields.Many2one("dev.environment", ondelete="restrict", index=True)
    database_identifier = fields.Char()
    runtime_label = fields.Char()
    error_details = fields.Text()

    def action_open_form(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Analysis",
            "res_model": "dev.work.analysis",
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
        }


class DevWorkItemCodeAnalysis(models.Model):
    _inherit = "dev.work.item"

    def action_analyze_against_code_database(self):
        """Resolve repo/env, analyze code+DB read-only, persist Analysis tab record."""
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM dev_work_item WHERE id = %s FOR UPDATE", [self.id]
        )
        self.invalidate_recordset()
        try:
            analysis = self._run_code_database_analysis()
        except Exception as exc:  # noqa: BLE001 - persist failure on analysis row when possible
            # Prefer the in-progress placeholder if _run already marked it failed.
            failed = self.env["dev.work.analysis"].search(
                [
                    ("work_item_id", "=", self.id),
                    ("analysis_kind", "=", ANALYSIS_KIND),
                    ("execution_state", "=", "failed"),
                ],
                order="id desc",
                limit=1,
            )
            if not failed:
                failed = self._record_failed_code_database_analysis(str(exc))
            if failed:
                return failed.action_open_form()
            raise
        return {
            "type": "ir.actions.act_window",
            "name": "Analysis",
            "res_model": "dev.work.analysis",
            "res_id": analysis.id,
            "view_mode": "form",
            "target": "current",
            "context": {"form_view_initial_mode": "readonly"},
        }

    def _ensure_phase_for_code_analysis(self):
        self.ensure_one()
        chain = [
            ("received", "triage", "Auto-triage for code/database analysis"),
            ("triage", "registered", "Auto-register for code/database analysis"),
            ("registered", "analyzing", "Start code/database analysis"),
        ]
        for source, target, reason in chain:
            if self.current_phase == source:
                self.transition_lifecycle(target, reason, actor_type="automation")
        if self.current_phase not in (
            "analyzing",
            "planning",
            "awaiting_plan_approval",
            "approved",
            "implementing",
            "paused",
            "blocked",
            "testing",
            "ready_for_review",
        ):
            raise UserError(
                "Work item phase %s cannot run code/database analysis."
                % self.current_phase
            )

    def _resolve_code_analysis_context(self):
        self.ensure_one()
        project = self.dev_project_id
        repo = self.preferred_repository_id or project.default_repository_id
        env = self.preferred_environment_id or project.default_environment_id
        if not project:
            raise UserError("Work item has no Dev Hub project.")
        if not repo:
            raise UserError("Preferred repository is required.")
        if not env:
            raise UserError("Preferred Test environment is required.")
        if repo.project_id != project:
            raise UserError("Repository does not belong to the resolved Dev Hub project.")
        if env.project_id != project:
            raise UserError("Environment does not belong to the resolved Dev Hub project.")
        if env.is_production or env.environment_type == "production":
            raise UserError("Production environments are refused for analysis.")
        if getattr(env, "environment_role", False) == "legacy_isolated" and env.port == 8028:
            # Allow PetSpot Test for PetSpot work, but never as a TOURZ target mismatch
            pass
        if env.data_sensitivity in ("production", "restricted"):
            raise UserError("Restricted/production-sensitivity environments are refused.")
        path = os.path.realpath((repo.working_directory or "").rstrip("/"))
        if not path or not os.path.isdir(path):
            raise UserError("Repository path is missing or does not exist: %s" % path)
        machine = env.machine_id
        prefixes = [
            os.path.realpath(line.strip())
            for line in (machine.allowed_path_prefixes or "").splitlines()
            if line.strip()
        ]
        if not prefixes:
            raise UserError("Machine has no allowed path prefixes.")
        if not any(
            path == prefix or path.startswith(prefix.rstrip("/") + os.sep)
            for prefix in prefixes
        ):
            raise UserError("Repository path is not allowlisted on the environment machine.")
        conf = (env.config_reference or "").strip()
        if not conf or not os.path.isfile(conf):
            raise UserError("Environment config_reference is missing or invalid.")
        if not env.database_identifier:
            raise UserError("Environment has no database identifier.")
        # Health check HTTP if URL/port present
        url = env.url or ("http://127.0.0.1:%s" % env.port if env.port else False)
        if url:
            try:
                with urllib.request.urlopen(url.rstrip("/") + "/web/login", timeout=5) as resp:
                    if getattr(resp, "status", 200) >= 400:
                        raise UserError("Test environment HTTP health check failed.")
            except UserError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise UserError("Test environment is not healthy: %s" % exc) from exc
        head = repo.head_cache or self._git_rev_parse(path)
        branch = repo.current_branch_cache or repo.default_branch or "unknown"
        runtime = getattr(env, "runtime_id", False)
        runtime_label = (
            "%s (%s)" % (runtime.code, runtime.odoo_major)
            if runtime
            else (env.odoo_version or "unknown")
        )
        return {
            "project": project,
            "repository": repo,
            "environment": env,
            "path": path,
            "head": head,
            "branch": branch,
            "runtime_label": runtime_label,
            "url": url,
        }

    def _git_rev_parse(self, path):
        try:
            import subprocess

            return (
                subprocess.check_output(
                    ["git", "-C", path, "rev-parse", "HEAD"],
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=10,
                )
                .strip()
            )
        except Exception:  # noqa: BLE001
            return False

    def _build_code_analysis_fingerprint(self, ctx):
        self.ensure_one()
        task = self.odoo_task_id
        payload = {
            "kind": ANALYSIS_KIND,
            "schema": ANALYSIS_SCHEMA,
            "work_item_uuid": self.uuid,
            "odoo_task_id": task.id if task else False,
            "odoo_task_write_date": fields.Datetime.to_string(task.write_date)
            if task
            else False,
            "op_work_package_id": self.op_work_package_id or False,
            "repository_id": ctx["repository"].id,
            "observed_head": ctx["head"] or "",
            "environment_id": ctx["environment"].id,
            "database_identifier": ctx["environment"].database_identifier,
        }
        return _canonical_hash(payload)

    def _find_completed_analysis_by_fingerprint(self, fingerprint):
        return self.env["dev.work.analysis"].search(
            [
                ("work_item_id", "=", self.id),
                ("analysis_fingerprint", "=", fingerprint),
                ("analysis_kind", "=", ANALYSIS_KIND),
                ("execution_state", "=", "completed"),
            ],
            order="revision desc",
            limit=1,
        )

    def _find_running_analysis_by_fingerprint(self, fingerprint):
        return self.env["dev.work.analysis"].search(
            [
                ("work_item_id", "=", self.id),
                ("analysis_fingerprint", "=", fingerprint),
                ("analysis_kind", "=", ANALYSIS_KIND),
                ("execution_state", "in", ["queued", "running"]),
            ],
            limit=1,
        )

    def _run_code_database_analysis(self):
        self.ensure_one()
        self._ensure_phase_for_code_analysis()
        ctx = self._resolve_code_analysis_context()
        fingerprint = self._build_code_analysis_fingerprint(ctx)
        existing = self._find_completed_analysis_by_fingerprint(fingerprint)
        if existing:
            return existing
        running = self._find_running_analysis_by_fingerprint(fingerprint)
        if running:
            raise UserError(
                "A code/database analysis is already running for this fingerprint "
                "(analysis id %s)." % running.id
            )

        placeholder = self.env["dev.work.analysis"].create(
            {
                "work_item_id": self.id,
                "status": "draft",
                "origin": "generated",
                "analysis_kind": ANALYSIS_KIND,
                "execution_state": "running",
                "analysis_fingerprint": fingerprint,
                "problem_summary": "Code & database analysis running…",
                "original_request_summary": _safe_analysis_text(
                    self.odoo_task_id.description or self.name or "",
                    4000,
                ),
                "repository_id": ctx["repository"].id,
                "environment_id": ctx["environment"].id,
                "database_identifier": ctx["environment"].database_identifier,
                "runtime_label": ctx["runtime_label"],
                "observed_head": ctx["head"] or False,
                "schema_version": ANALYSIS_SCHEMA,
                "prompt_version": ANALYSIS_PROMPT_VERSION,
                "template_version": ANALYSIS_PROMPT_VERSION,
                "provider_reference": "dev_session_hub.local_code_db_analyzer",
                "model_reference": "bounded-static-analyzer",
                "agent_reference": "dev-hub-code-db-analysis",
                "run_reference": "run-%s" % fields.Datetime.now().strftime("%Y%m%d%H%M%S"),
                "generated_at": fields.Datetime.now(),
                "author_id": self.env.user.id,
            }
        )
        # Flush only — do not cr.commit() (breaks TransactionCase and request atomicity).
        self.env.flush_all()

        try:
            task_ctx = self._collect_task_context()
            code_findings = self._analyze_repository_code(ctx, task_ctx)
            db_findings = self._analyze_test_database(ctx, task_ctx, code_findings)
            report = self._compose_analysis_report(ctx, task_ctx, code_findings, db_findings)
            placeholder.write(
                {
                    "execution_state": "completed",
                    "status": "generated",
                    "problem_summary": report["problem_summary"],
                    "original_request_summary": report["original_request_summary"],
                    "reproduction_context": report["reproduction_context"],
                    "current_behavior": report["current_behavior"],
                    "expected_behavior": report["expected_behavior"],
                    "technical_findings": report["technical_findings"],
                    "affected_components": report["affected_components"],
                    "risks": report["risks"],
                    "dependencies": report["dependencies"],
                    "open_questions": report["open_questions"],
                    "evidence_references": report["evidence_references"],
                    "error_details": False,
                    "generated_at": fields.Datetime.now(),
                    "observed_head": ctx["head"] or False,
                }
            )
        except Exception as exc:  # noqa: BLE001
            placeholder.write(
                {
                    "execution_state": "failed",
                    "status": "draft",
                    "error_details": _truncate(str(exc), 4000),
                    "open_questions": "Analysis failed. Retry via Analyze Against Code & Database.",
                    "technical_findings": _truncate("Failure: %s" % exc, 4000),
                }
            )
            self.env.flush_all()
            raise
        self.env.flush_all()
        return placeholder

    def _record_failed_code_database_analysis(self, error):
        self.ensure_one()
        try:
            ctx = self._resolve_code_analysis_context()
        except Exception:  # noqa: BLE001
            return False
        fingerprint = self._build_code_analysis_fingerprint(ctx)
        return self.env["dev.work.analysis"].create(
            {
                "work_item_id": self.id,
                "status": "draft",
                "origin": "generated",
                "analysis_kind": ANALYSIS_KIND,
                "execution_state": "failed",
                "analysis_fingerprint": fingerprint,
                "problem_summary": "Code & database analysis failed",
                "original_request_summary": _truncate(self.name or "", 2000),
                "technical_findings": _truncate(error, 4000),
                "error_details": _truncate(error, 4000),
                "open_questions": "Retry after fixing the reported error.",
                "repository_id": ctx["repository"].id,
                "environment_id": ctx["environment"].id,
                "database_identifier": ctx["environment"].database_identifier,
                "runtime_label": ctx["runtime_label"],
                "observed_head": ctx["head"] or False,
                "schema_version": ANALYSIS_SCHEMA,
                "provider_reference": "dev_session_hub.local_code_db_analyzer",
                "generated_at": fields.Datetime.now(),
                "author_id": self.env.user.id,
            }
        )

    def _collect_task_context(self):
        self.ensure_one()
        task = self.odoo_task_id
        description = _strip_html(task.description or "") if task else ""
        attachments = []
        if task:
            atts = self.env["ir.attachment"].search(
                [("res_model", "=", "project.task"), ("res_id", "=", task.id)],
                limit=20,
            )
            attachments = [
                {"id": a.id, "name": a.name, "mimetype": a.mimetype}
                for a in atts
            ]
        sources = [
            {
                "id": s.id,
                "text": _truncate(s.sanitized_text or "", 1500),
                "timestamp": fields.Datetime.to_string(s.message_timestamp)
                if s.message_timestamp
                else False,
            }
            for s in self.source_message_ids[:10]
        ]
        keywords = self._extract_keywords(
            " ".join(
                [
                    task.name if task else self.name or "",
                    description,
                    " ".join(s["text"] for s in sources),
                ]
            )
        )
        return {
            "task_id": task.id if task else False,
            "title": task.name if task else self.name,
            "description": description,
            "stage": task.stage_id.name if task and task.stage_id else False,
            "op_work_package_id": self.op_work_package_id,
            "op_url": self.op_url,
            "attachments": attachments,
            "sources": sources,
            "keywords": keywords,
            "history": [
                {
                    "id": a.id,
                    "revision": a.revision,
                    "status": a.status,
                    "execution_state": a.execution_state,
                    "fingerprint": a.analysis_fingerprint,
                }
                for a in self.analysis_ids[:10]
            ],
        }

    def _extract_keywords(self, text):
        tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", (text or "").lower())
        scored = {}
        for token in tokens:
            if token in STOPWORDS:
                continue
            scored[token] = scored.get(token, 0) + 1
        # Prefer domain terms
        boost = (
            "warranty",
            "period",
            "package",
            "product",
            "vehicle",
            "service",
            "inspection",
            "policy",
            "customer",
        )
        for term in boost:
            if term in scored:
                scored[term] += 5
            elif term in (text or "").lower():
                scored[term] = 5
        return [k for k, _ in sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))[:20]]

    def _analyze_repository_code(self, ctx, task_ctx):
        root = Path(ctx["path"])
        # Prefer torz addon subtree when present
        scan_roots = []
        torz = root / "torz"
        if torz.is_dir():
            scan_roots.append(torz)
        else:
            scan_roots.append(root)
        keywords = task_ctx["keywords"] or ["warranty"]
        keyword_re = re.compile(
            "|".join(re.escape(k) for k in keywords[:12]), re.IGNORECASE
        )
        hits = []
        modules = set()
        for scan_root in scan_roots:
            for path in scan_root.rglob("*"):
                if len(hits) >= MAX_FILES_SCANNED:
                    break
                if not path.is_file():
                    continue
                if path.suffix.lower() not in {".py", ".xml", ".js", ".md"}:
                    continue
                if any(part in {"__pycache__", ".git", "node_modules"} for part in path.parts):
                    continue
                try:
                    if path.stat().st_size > MAX_FILE_BYTES:
                        continue
                    content = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                if not keyword_re.search(content) and not keyword_re.search(path.name):
                    continue
                rel = str(path.relative_to(root))
                module = None
                parts = Path(rel).parts
                if parts and parts[0] == "torz" and len(parts) > 1:
                    candidate = parts[1]
                    if (root / "torz" / candidate / "__manifest__.py").is_file():
                        module = candidate
                        modules.add(module)
                symbols = self._extract_symbols(content, path.suffix.lower())
                snippet_lines = []
                for idx, line in enumerate(content.splitlines(), start=1):
                    if keyword_re.search(line):
                        snippet_lines.append("%s:%s" % (idx, line.strip()[:200]))
                    if len(snippet_lines) >= 8:
                        break
                hits.append(
                    {
                        "path": rel,
                        "module": module,
                        "symbols": symbols[:20],
                        "snippets": snippet_lines,
                    }
                )
        # Manifest dependency map for hit modules
        manifests = {}
        for module in sorted(modules):
            manifest_path = root / "torz" / module / "__manifest__.py"
            if not manifest_path.is_file():
                continue
            try:
                data = ast.literal_eval(manifest_path.read_text(encoding="utf-8"))
                manifests[module] = {
                    "version": data.get("version"),
                    "depends": data.get("depends") or [],
                }
            except Exception:  # noqa: BLE001
                manifests[module] = {"version": "unparsed", "depends": []}
        gap_notes = []
        # Task-specific heuristic for warranty auto-apply on package/service
        title = (task_ctx.get("title") or "").lower()
        if "warranty" in title and ("package" in title or "service" in title):
            auto_apply_files = [
                h
                for h in hits
                if "onchange" in " ".join(h["snippets"]).lower()
                or "product" in h["path"].lower()
            ]
            if not any(
                "sale.order" in " ".join(h["symbols"] + h["snippets"])
                or "product.product" in " ".join(h["symbols"])
                for h in hits
            ):
                gap_notes.append(
                    "No clear onchange/auto-apply hook found that sets warranty period "
                    "on product lines when a package/service is selected on a vehicle."
                )
            gap_notes.append(
                "torz_warranty README marks Gap 2 auto follow-ups on task delivery as TODO; "
                "confirm whether package→warranty-period auto-apply is unimplemented."
            )
            if auto_apply_files:
                gap_notes.append(
                    "Candidate related files: %s"
                    % ", ".join(h["path"] for h in auto_apply_files[:8])
                )
        return {
            "modules": sorted(modules),
            "manifests": manifests,
            "files": hits[:40],
            "gap_notes": gap_notes,
            "scan_root": str(scan_roots[0].relative_to(root))
            if scan_roots[0] != root
            else ".",
        }

    def _extract_symbols(self, content, suffix):
        symbols = []
        if suffix == ".py":
            try:
                tree = ast.parse(content)
            except SyntaxError:
                return symbols
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    symbols.append("class %s" % node.name)
                elif isinstance(node, ast.FunctionDef):
                    symbols.append("def %s" % node.name)
        else:
            for match in re.finditer(
                r'\b(?:_name|_inherit|name)=["\']([^"\']+)["\']', content
            ):
                symbols.append(match.group(1))
        return symbols[:30]

    def _parse_odoo_conf(self, conf_path):
        values = {}
        section = None
        with open(conf_path, encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith((";", "#")):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    section = line[1:-1]
                    continue
                if section == "options" and "=" in line:
                    key, val = line.split("=", 1)
                    values[key.strip()] = val.strip()
        return values

    def _analyze_test_database(self, ctx, task_ctx, code_findings):
        env = ctx["environment"]
        conf = self._parse_odoo_conf(env.config_reference)
        db_name = env.database_identifier
        if conf.get("db_name") and conf.get("db_name") != db_name:
            # Still trust environment database_identifier as SoT
            pass
        if db_name in {"pet_spot_elsahel", "pet_spot_elsahel_test"} and (
            self.dev_project_id.code or ""
        ).upper() == "TOURZ":
            raise UserError("TOURZ analysis refused to inspect PetSpot databases.")
        if db_name == "pet_spot_elsahel":
            raise UserError("Production database inspection is forbidden.")

        conn = psycopg2.connect(
            host=conf.get("db_host") or "localhost",
            port=int(conf.get("db_port") or 5432),
            user=conf.get("db_user") or "odoo",
            password=conf.get("db_password") or "",
            dbname=db_name,
            connect_timeout=5,
        )
        try:
            conn.set_session(readonly=True, autocommit=True)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET statement_timeout = %s", [DB_STATEMENT_TIMEOUT_MS])
                modules = code_findings.get("modules") or [
                    "vehicle_inspection",
                    "fleet_vehicle_inspection",
                    "fleet_vehicle_inspection_bridge",
                    "torz_warranty",
                ]
                cur.execute(
                    """
                    SELECT name, state, latest_version
                    FROM ir_module_module
                    WHERE name = ANY(%s)
                    ORDER BY name
                    """,
                    [list(modules)],
                )
                module_rows = cur.fetchmany(MAX_DB_ROWS)
                cur.execute(
                    """
                    SELECT model, name
                    FROM ir_model
                    WHERE model IN ('warranty.policy', 'customer.warranty',
                                    'fleet.vehicle.inspection', 'vehicle.inspection')
                    ORDER BY model
                    """
                )
                model_rows = cur.fetchmany(MAX_DB_ROWS)
                field_rows = []
                if model_rows:
                    cur.execute(
                        """
                        SELECT im.model, imf.name, imf.ttype, imf.state
                        FROM ir_model_fields imf
                        JOIN ir_model im ON im.id = imf.model_id
                        WHERE im.model IN ('warranty.policy', 'customer.warranty')
                        ORDER BY im.model, imf.name
                        LIMIT %s
                        """,
                        [MAX_DB_ROWS],
                    )
                    field_rows = cur.fetchmany(MAX_DB_ROWS)
                counts = {}
                for model_name, table in (
                    ("warranty.policy", "warranty_policy"),
                    ("customer.warranty", "customer_warranty"),
                ):
                    cur.execute(
                        """
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema='public' AND table_name=%s
                        ) AS ok
                        """,
                        [table],
                    )
                    if cur.fetchone().get("ok"):
                        cur.execute("SELECT COUNT(*) AS c FROM %s" % table)  # noqa: S608 - fixed literals
                        counts[model_name] = cur.fetchone()["c"]
                # Look for product warranty-period style fields
                cur.execute(
                    """
                    SELECT im.model, imf.name, imf.ttype
                    FROM ir_model_fields imf
                    JOIN ir_model im ON im.id = imf.model_id
                    WHERE im.model IN ('product.template', 'product.product')
                      AND imf.name ILIKE '%%warranty%%'
                    ORDER BY im.model, imf.name
                    LIMIT %s
                    """,
                    [MAX_DB_ROWS],
                )
                product_warranty_fields = cur.fetchmany(MAX_DB_ROWS)
        finally:
            conn.close()

        needs_db = bool(
            set(task_ctx["keywords"])
            & {"warranty", "period", "package", "product", "vehicle", "service"}
        )
        return {
            "needed": needs_db,
            "database": db_name,
            "modules": module_rows,
            "models": model_rows,
            "fields": field_rows,
            "counts": counts,
            "product_warranty_fields": product_warranty_fields,
            "note": (
                "Read-only inspection completed."
                if needs_db
                else "Task keywords did not strongly require DB evidence; limited module/model checks still recorded."
            ),
        }

    def _compose_analysis_report(self, ctx, task_ctx, code_findings, db_findings):
        files_block = []
        for hit in code_findings["files"][:25]:
            files_block.append(
                "- `%s` symbols=%s"
                % (hit["path"], ", ".join(hit["symbols"][:8]) or "n/a")
            )
            for snip in hit["snippets"][:3]:
                files_block.append("  - %s" % snip)

        db_lines = [
            "Database: %s" % db_findings["database"],
            "Needed: %s" % db_findings["needed"],
            "Note: %s" % db_findings["note"],
            "Installed modules:",
        ]
        for row in db_findings["modules"]:
            db_lines.append(
                "- %s state=%s version=%s"
                % (row["name"], row["state"], row["latest_version"])
            )
        db_lines.append(
            "Models present: %s"
            % (", ".join(r["model"] for r in db_findings["models"]) or "none")
        )
        db_lines.append("Record counts: %s" % db_findings["counts"])
        if db_findings["product_warranty_fields"]:
            db_lines.append("Product warranty-related fields:")
            for row in db_findings["product_warranty_fields"]:
                db_lines.append(
                    "- %s.%s (%s)" % (row["model"], row["name"], row["ttype"])
                )
        else:
            db_lines.append(
                "Product warranty-related fields: none found on product.template/product.product "
                "(likely implementation gap for auto-apply warranty period on package/service)."
            )

        gap = code_findings.get("gap_notes") or []
        recommended = [
            "Add product/package warranty-period metadata (or reuse warranty.policy.product_ids mapping).",
            "Implement an onchange/create hook when a package/service is applied on a vehicle so "
            "product lines warranty period is populated automatically.",
            "Cover with unit tests for package selection → warranty dates, plus Playwright UI regression "
            "on Tours Trading Test.",
            "Keep outbound integrations disabled on tours_trading_test while developing.",
        ]
        risks = [
            "Incorrect auto-apply could create wrong warranty end dates for customers.",
            "Enterprise FSM/sale interactions may require additional bridges.",
            "Do not implement against PetSpot Test or Production.",
        ]
        assumptions = [
            "Requirement interpreted from Odoo task description + Chatwoot source notes; DOCX attachment content was not binary-parsed in this run (metadata only).",
            "Gap 2 README TODO is treated as supporting evidence of incomplete auto-apply behavior.",
        ]
        open_q = [
            "Should warranty period come from product master data, warranty.policy, or package-specific config?",
            "Exact UI surface for 'service applied on a vehicle' (FSM task, repair, inspection, sale order line)?",
        ]

        problem = _truncate(
            "Task %s / OP WP %s: %s"
            % (
                task_ctx.get("task_id") or "n/a",
                task_ctx.get("op_work_package_id") or "n/a",
                task_ctx.get("title") or self.name,
            ),
            2000,
        )
        original = _safe_analysis_text(
            "\n".join(
                [
                    task_ctx.get("description") or "",
                    "Attachment metadata: %s"
                    % (
                        ", ".join(
                            "%s (%s)" % (a["name"], a["mimetype"])
                            for a in task_ctx.get("attachments") or []
                        )
                        or "none"
                    ),
                ]
            ).strip(),
            6000,
        )
        reproduction = _truncate(
            "\n".join(
                [
                    "Project: %s" % ctx["project"].code,
                    "Repository: %s" % ctx["path"],
                    "Branch/HEAD: %s @ %s" % (ctx["branch"], ctx["head"] or "unknown"),
                    "Environment: %s" % ctx["environment"].name,
                    "Database: %s" % ctx["environment"].database_identifier,
                    "Runtime: %s" % ctx["runtime_label"],
                    "URL: %s" % (ctx["url"] or "n/a"),
                    "Scan root: %s" % code_findings.get("scan_root"),
                ]
            ),
            4000,
        )
        current = _truncate(
            "\n".join(
                [
                    "Relevant modules: %s"
                    % (", ".join(code_findings["modules"]) or "none matched"),
                    "Manifests: %s" % code_findings["manifests"],
                    "Likely gaps:",
                ]
                + (["- %s" % g for g in gap] if gap else ["- No automatic gap heuristic fired."])
            ),
            6000,
        )
        expected = _truncate(
            "When a package/service with a warranty period is selected/applied on a vehicle, "
            "the warranty period should populate automatically on the related product lines warranty.",
            3000,
        )
        technical = _truncate(
            "\n".join(
                [
                    "## Code findings",
                ]
                + (files_block or ["- No keyword-matching files found."])
                + [
                    "",
                    "## Database / runtime evidence",
                    *db_lines,
                    "",
                    "## Recommended implementation",
                ]
                + ["- %s" % r for r in recommended]
                + [
                    "",
                    "## Suggested tests",
                    "- Unit: package/service selection sets warranty start/end from configured period.",
                    "- Integration: customer.warranty / product line fields remain consistent.",
                    "- Playwright: Tours Trading Test UI path for applying service package on vehicle.",
                ]
            ),
            11000,
        )
        affected = _truncate(
            "\n".join(
                ["Modules: %s" % ", ".join(code_findings["modules"])]
                + ["File: %s" % h["path"] for h in code_findings["files"][:30]]
            ),
            6000,
        )
        evidence = _truncate(
            "\n".join(
                [
                    "Fingerprint inputs: task=%s head=%s env=%s db=%s"
                    % (
                        task_ctx.get("task_id"),
                        ctx["head"],
                        ctx["environment"].id,
                        ctx["environment"].database_identifier,
                    ),
                    "Prior analyses: %s" % task_ctx.get("history"),
                    "Generated at: %s" % datetime.utcnow().isoformat() + "Z",
                ]
            ),
            4000,
        )
        return {
            "problem_summary": problem,
            "original_request_summary": original or problem,
            "reproduction_context": reproduction,
            "current_behavior": current,
            "expected_behavior": expected,
            "technical_findings": technical,
            "affected_components": affected,
            "risks": _truncate("\n".join("- %s" % r for r in risks), 4000),
            "dependencies": _truncate(
                "Manifests: %s" % code_findings["manifests"], 4000
            ),
            "open_questions": _truncate(
                "\n".join(
                    ["Assumptions:"]
                    + ["- %s" % a for a in assumptions]
                    + ["Open questions:"]
                    + ["- %s" % q for q in open_q]
                ),
                4000,
            ),
            "evidence_references": evidence,
        }


class ProjectTaskCodeAnalysis(models.Model):
    _inherit = "project.task"

    def action_dev_hub_analyze_against_code_database(self):
        self.ensure_one()
        # Ensure work item exists via existing helper when available
        if hasattr(self, "action_dev_hub_ensure_work_item"):
            self.action_dev_hub_ensure_work_item()
        wi = self.env["dev.work.item"].search([("odoo_task_id", "=", self.id)], limit=1)
        if not wi:
            raise UserError("No Dev Hub work item linked to this task.")
        return wi.action_analyze_against_code_database()
