import hashlib
import io
import json
import logging
import re
from datetime import datetime
from html import unescape
from urllib.parse import urlencode, urlparse

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_JSEARCH_HOST = "jsearch.p.rapidapi.com"
_JSEARCH_URL = "https://%s/search-v2" % _JSEARCH_HOST
_JSEARCH_LEGACY_PATH = "/search"
_DEFAULT_JSEARCH_QUERIES = [
    {"query": "Odoo Developer in UAE", "country": "ae", "remote": False},
    {"query": "Odoo Developer in Egypt", "country": "eg", "remote": False},
    {"query": "Remote Odoo Developer", "country": "", "remote": True},
]

_LI_GUEST_URL = (
    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
)

_SENIOR_RE = re.compile(
    r"\b(senior|lead|principal|architect|staff|head of|technical lead)\b", re.I
)
_JUNIOR_RE = re.compile(r"\b(junior|intern|internship|entry[- ]level|graduate)\b", re.I)
_ODOO_RE = re.compile(r"\bodoo\b", re.I)
_STACK_RE = re.compile(r"\b(python|erp|implementation|postgresql|owl)\b", re.I)
_EASY_APPLY_RE = re.compile(r"easy\s*apply", re.I)
_UNRELATED_RE = re.compile(
    r"\b(java developer|\.net developer|php only|react native only|ios developer|android developer)\b",
    re.I,
)


class LinkedinJob(models.Model):
    _name = "linkedin.job"
    _description = "LinkedIn Job"
    _order = "score desc, listed_at desc, id desc"
    _rec_name = "title"

    account_id = fields.Many2one(
        "linkedin.account", string="Account", ondelete="set null", index=True
    )
    job_id = fields.Char(string="Job ID", index=True)
    title = fields.Char(string="Job Title")
    company = fields.Char(string="Company")
    location = fields.Char(string="Location")
    remote = fields.Boolean(string="Remote")
    employment_type = fields.Char(string="Type")
    description = fields.Html(string="Description")
    apply_url = fields.Char(string="Apply URL")
    source = fields.Char(string="Source", default="JSearch")
    listed_at = fields.Datetime(string="Listed At")
    saved = fields.Boolean(string="Saved", default=False, index=True)
    search_keywords = fields.Char(string="Search Keywords")
    search_location = fields.Char(string="Search Location")

    score = fields.Float(string="Match score", default=0.0, index=True)
    score_breakdown = fields.Text(string="Score breakdown", readonly=True)
    seniority_match = fields.Boolean(string="Seniority match", default=False)
    odoo_match = fields.Boolean(string="Odoo match", default=False)
    easy_apply_hint = fields.Boolean(
        string="Easy Apply hint",
        default=False,
        help="Informational only — detected from listing text. Never used for auto-submit.",
    )
    fingerprint = fields.Char(string="Fingerprint", index=True, copy=False)
    is_duplicate = fields.Boolean(string="Duplicate", default=False, index=True)
    duplicate_of_id = fields.Many2one(
        "linkedin.job", string="Canonical job", ondelete="set null", index=True
    )
    application_ids = fields.One2many(
        "linkedin.job.application", "job_id", string="Applications"
    )
    application_count = fields.Integer(compute="_compute_application_count")

    def _compute_application_count(self):
        for rec in self:
            rec.application_count = len(rec.application_ids)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get("skip_job_postprocess"):
            records._score_and_dedupe()
            if self._auto_create_applications_enabled():
                records._maybe_create_applications()
        return records

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get("skip_job_postprocess"):
            return res
        watch = {
            "title",
            "company",
            "description",
            "apply_url",
            "job_id",
            "location",
            "remote",
        }
        if watch.intersection(vals):
            self._score_and_dedupe()
            if self._auto_create_applications_enabled():
                self._maybe_create_applications()
        return res

    @api.model
    def _auto_create_applications_enabled(self):
        """Applications stay review-first; cron path never auto-creates."""
        if self.env.context.get("skip_application_create"):
            return False
        raw = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("linkedin_connector.auto_create_applications", "False")
            or ""
        )
        return str(raw).strip().lower() in ("1", "true", "yes")

    def _plain_text_blob(self):
        self.ensure_one()
        html = self.description or ""
        text = re.sub(r"<[^>]+>", " ", html)
        text = unescape(text)
        return "%s %s %s %s" % (
            self.title or "",
            self.company or "",
            self.location or "",
            text,
        )

    def _compute_fingerprint_value(self):
        self.ensure_one()
        company = re.sub(r"\s+", " ", (self.company or "").lower().strip())
        title = re.sub(r"\s+", " ", (self.title or "").lower().strip())
        key = (self.job_id or "").strip()
        if not key and self.apply_url:
            parsed = urlparse(self.apply_url)
            key = (parsed.netloc + parsed.path).rstrip("/").lower()
        raw = "%s|%s|%s" % (company, title, key)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _score_job_values(self):
        """Return (score, breakdown_dict, flags). Uses local CV text for relevance only."""
        self.ensure_one()
        blob = self._plain_text_blob()
        title = self.title or ""
        breakdown = {}
        score = 0.0

        odoo_match = bool(_ODOO_RE.search(blob))
        seniority_match = bool(_SENIOR_RE.search(title) or _SENIOR_RE.search(blob))
        easy_hint = bool(_EASY_APPLY_RE.search(blob))

        if odoo_match:
            score += 30
            breakdown["odoo"] = 30
        if seniority_match:
            score += 25
            breakdown["seniority"] = 25
        if _STACK_RE.search(blob):
            score += 10
            breakdown["stack"] = 10

        loc = (self.location or "").lower()
        preferred = self._preferred_geo_tokens()
        if self.remote or "remote" in loc or any(t in loc for t in preferred):
            score += 10
            breakdown["geo_remote"] = 10
        if easy_hint:
            score += 5
            breakdown["easy_apply_hint"] = 5

        cv_boost = self._cv_relevance_boost(blob)
        if cv_boost:
            score += cv_boost
            breakdown["cv_relevance"] = cv_boost

        if _JUNIOR_RE.search(title) or _JUNIOR_RE.search(blob):
            score -= 40
            breakdown["junior_penalty"] = -40
        if _UNRELATED_RE.search(blob) and not odoo_match:
            score -= 40
            breakdown["unrelated_stack"] = -40

        return score, breakdown, {
            "odoo_match": odoo_match,
            "seniority_match": seniority_match,
            "easy_apply_hint": easy_hint,
        }

    @api.model
    def _cv_text_tokens(self, account=None):
        """Extract significant tokens from personal default CV PDF (never uploaded)."""
        cache = getattr(self.env.registry, "_linkedin_cv_token_cache", None)
        if cache is None:
            cache = {}
            self.env.registry._linkedin_cv_token_cache = cache
        personal = account or self.env["linkedin.account"].get_personal_account()
        if not personal:
            return set()
        if personal.id in cache:
            return cache[personal.id]
        Cv = self.env["linkedin.cv.version"].sudo()
        cv = Cv.search(
            [("account_id", "=", personal.id), ("is_default", "=", True), ("active", "=", True)],
            limit=1,
        ) or Cv.search([("account_id", "=", personal.id), ("active", "=", True)], limit=1)
        tokens = set()
        if cv and cv.attachment_id:
            try:
                raw = cv.attachment_id.raw or b""
                if raw:
                    from PyPDF2 import PdfReader

                    reader = PdfReader(io.BytesIO(raw))
                    text_parts = []
                    for page in reader.pages[:8]:
                        try:
                            text_parts.append(page.extract_text() or "")
                        except Exception:
                            continue
                    text = " ".join(text_parts).lower()
                    tokens = {
                        t
                        for t in re.findall(r"[a-zA-Z][a-zA-Z0-9_+#.-]{3,}", text)
                        if t not in {"with", "from", "that", "this", "have", "your", "will"}
                    }
            except Exception:
                _logger.info("linkedin.job: CV text extract skipped for scoring", exc_info=True)
        cache[personal.id] = tokens
        return tokens

    def _cv_relevance_boost(self, blob):
        """Local-only CV overlap boost (0–15). Never sends CV externally."""
        tokens = self._cv_text_tokens(self.account_id)
        if not tokens:
            return 0.0
        blob_l = (blob or "").lower()
        hits = sum(1 for t in tokens if t in blob_l)
        if hits >= 12:
            return 15.0
        if hits >= 6:
            return 10.0
        if hits >= 3:
            return 5.0
        return 0.0

    @api.model
    def _preferred_geo_tokens(self):
        raw = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(
                "linkedin_connector.job_preferred_geos",
                "egypt,cairo,uae,dubai,remote,europe,eu,germany,netherlands,uk",
            )
        )
        return [t.strip().lower() for t in (raw or "").split(",") if t.strip()]

    @api.model
    def _score_threshold(self):
        raw = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("linkedin_connector.job_score_threshold", "50")
        )
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 50.0

    def _score_and_dedupe(self):
        for rec in self:
            score, breakdown, flags = rec._score_job_values()
            fp = rec._compute_fingerprint_value()
            rec.with_context(skip_job_postprocess=True).write(
                {
                    "score": score,
                    "score_breakdown": json.dumps(breakdown, sort_keys=True),
                    "seniority_match": flags["seniority_match"],
                    "odoo_match": flags["odoo_match"],
                    "easy_apply_hint": flags["easy_apply_hint"],
                    "fingerprint": fp,
                }
            )
        self._mark_duplicates()

    def _mark_duplicates(self):
        for rec in self:
            if not rec.fingerprint:
                continue
            twins = self.search(
                [
                    ("fingerprint", "=", rec.fingerprint),
                    ("id", "!=", rec.id),
                ]
            )
            if not twins:
                if rec.is_duplicate:
                    rec.with_context(skip_job_postprocess=True).write(
                        {"is_duplicate": False, "duplicate_of_id": False}
                    )
                continue
            group = twins | rec
            canonical = group.sorted(key=lambda r: (r.score, r.id), reverse=True)[0]
            for job in group:
                vals = {
                    "is_duplicate": job.id != canonical.id,
                    "duplicate_of_id": False if job.id == canonical.id else canonical.id,
                }
                job.with_context(skip_job_postprocess=True).write(vals)

    def _maybe_create_applications(self):
        threshold = self._score_threshold()
        App = self.env["linkedin.job.application"]
        for rec in self:
            if rec.is_duplicate or rec.score < threshold:
                continue
            if App.search_count([("job_id", "=", rec.id)]):
                continue
            if rec.account_id and rec.account_id.account_type == "personal":
                personal = rec.account_id
            else:
                personal = self.env["linkedin.account"].get_personal_account()
            if not personal:
                continue
            App.create(
                {
                    "job_id": rec.id,
                    "account_id": personal.id,
                    "state": "discovered",
                }
            )

    def action_open_apply(self):
        """Blocked: use approved application pipeline instead."""
        self.ensure_one()
        app = self.application_ids[:1]
        if app:
            return app.action_open_application()
        raise UserError(
            _(
                "Direct apply from the job is disabled. "
                "Open the related Application, prepare the pack, Approve, "
                "then use Open application. (Review-first — no Easy Apply automation.)"
            )
        )

    def action_toggle_saved(self):
        for rec in self:
            rec.saved = not rec.saved

    def action_create_application(self):
        personal = self.env["linkedin.account"].get_personal_account()
        if not personal:
            raise UserError(_("Create a personal LinkedIn account first."))
        App = self.env["linkedin.job.application"]
        created = App
        for rec in self:
            existing = App.search([("job_id", "=", rec.id)], limit=1)
            if existing:
                created |= existing
                continue
            created |= App.create(
                {
                    "job_id": rec.id,
                    "account_id": personal.id,
                    "state": "discovered",
                }
            )
        return {
            "type": "ir.actions.act_window",
            "name": _("Applications"),
            "res_model": "linkedin.job.application",
            "view_mode": "list,form",
            "domain": [("id", "in", created.ids)],
        }

    @api.model
    def action_open_linkedin_jobs_search(self, keywords="", location=""):
        params = {}
        if keywords:
            params["keywords"] = keywords
        if location:
            params["location"] = location
        url = (
            "https://www.linkedin.com/jobs/search/?" + urlencode(params)
            if params
            else "https://www.linkedin.com/jobs/"
        )
        return {"type": "ir.actions.act_url", "url": url, "target": "new"}

    @api.model
    def _job_search_queries(self):
        raw = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(
                "linkedin_connector.job_search_queries",
                "Odoo Developer in UAE|Odoo Developer in Egypt|Remote Odoo Developer",
            )
        )
        return [q.strip() for q in (raw or "").split("|") if q.strip()]

    @api.model
    def _live_job_search_enabled(self):
        raw = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("linkedin_connector.live_job_search_enabled", "False")
            or ""
        )
        return str(raw).strip().lower() in ("1", "true", "yes")

    @api.model
    def _icp_int(self, key, default):
        raw = self.env["ir.config_parameter"].sudo().get_param(key, str(default))
        try:
            return int(raw)
        except (TypeError, ValueError):
            return int(default)

    @api.model
    def _jsearch_daily_queries(self):
        raw = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("linkedin_connector.jsearch_daily_queries_json", "")
            or ""
        )
        if raw.strip():
            try:
                data = json.loads(raw)
                if isinstance(data, list) and data:
                    out = []
                    for item in data[:3]:
                        if not isinstance(item, dict):
                            continue
                        q = (item.get("query") or "").strip()
                        if not q:
                            continue
                        out.append(
                            {
                                "query": q,
                                "country": (item.get("country") or "").strip().lower(),
                                "remote": bool(item.get("remote")),
                            }
                        )
                    if out:
                        return out[:3]
            except Exception:
                _logger.warning("linkedin.job: invalid jsearch_daily_queries_json; using defaults")
        return list(_DEFAULT_JSEARCH_QUERIES)

    @api.model
    def _jsearch_usage_load(self):
        ICP = self.env["ir.config_parameter"].sudo()
        today = fields.Date.context_today(self)
        month = today.strftime("%Y-%m")
        day = fields.Date.to_string(today)
        try:
            data = json.loads(ICP.get_param("linkedin_connector.jsearch_usage_json", "{}") or "{}")
        except Exception:
            data = {}
        if data.get("day") != day:
            data["day"] = day
            data["day_count"] = 0
            data["day_jobs"] = 0
        if data.get("month") != month:
            data["month"] = month
            data["month_count"] = 0
        data.setdefault("day_count", 0)
        data.setdefault("day_jobs", 0)
        data.setdefault("month_count", 0)
        return data

    @api.model
    def _jsearch_usage_save(self, data):
        self.env["ir.config_parameter"].sudo().set_param(
            "linkedin_connector.jsearch_usage_json", json.dumps(data, sort_keys=True)
        )

    @api.model
    def _jsearch_assert_endpoint(self, url=None):
        url = url or _JSEARCH_URL
        if _JSEARCH_LEGACY_PATH in url and "search-v2" not in url:
            raise UserError(
                _("Refusing deprecated JSearch endpoint %s — use search-v2 only.") % url
            )
        if "search-v2" not in url:
            raise UserError(_("JSearch URL must be search-v2: %s") % url)

    @api.model
    def _jsearch_reserve_request(self):
        """Fail closed when daily (3) or monthly (120) API caps are reached."""
        data = self._jsearch_usage_load()
        day_max = self._icp_int("linkedin_connector.jsearch_max_requests_per_day", 3)
        month_max = self._icp_int("linkedin_connector.jsearch_max_requests_per_month", 120)
        if data["day_count"] >= day_max:
            _logger.warning(
                "linkedin.job JSearch fail-closed: daily API cap reached (%s/%s)",
                data["day_count"],
                day_max,
            )
            return False
        if data["month_count"] >= month_max:
            _logger.warning(
                "linkedin.job JSearch fail-closed: monthly API cap reached (%s/%s)",
                data["month_count"],
                month_max,
            )
            return False
        data["day_count"] += 1
        data["month_count"] += 1
        self._jsearch_usage_save(data)
        return True

    @api.model
    def _jsearch_jobs_remaining_today(self):
        data = self._jsearch_usage_load()
        job_max = self._icp_int("linkedin_connector.jsearch_max_jobs_per_day", 30)
        return max(0, job_max - int(data.get("day_jobs") or 0))

    @api.model
    def _jsearch_record_imported(self, count):
        if count <= 0:
            return
        data = self._jsearch_usage_load()
        data["day_jobs"] = int(data.get("day_jobs") or 0) + int(count)
        self._jsearch_usage_save(data)

    @api.model
    def _canonical_apply_url(self, url):
        if not url:
            return ""
        parsed = urlparse(url.strip())
        if not parsed.scheme or not parsed.netloc:
            return ""
        return ("%s://%s%s" % (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path)).rstrip("/")

    @api.model
    def _cron_daily_jsearch(self):
        """07:00 Cairo — exactly up to 3 JSearch search-v2 requests for personal account."""
        if not self._live_job_search_enabled():
            _logger.info(
                "linkedin.job daily JSearch skipped: live_job_search_enabled is False"
            )
            return
        personal = self.env["linkedin.account"].get_personal_account()
        if not personal or personal.account_type != "personal":
            _logger.warning("linkedin.job daily JSearch: no personal account")
            return
        if personal.id != 2:
            _logger.info(
                "linkedin.job daily JSearch using personal account id=%s (expected 2 on Production)",
                personal.id,
            )

        Search = self.env["linkedin.job.search"]
        api_key = Search._get_rapidapi_key()
        if not api_key:
            _logger.error("linkedin.job daily JSearch: RapidAPI key missing in environment")
            return

        self._jsearch_assert_endpoint(_JSEARCH_URL)
        imported_total = 0
        for spec in self._jsearch_daily_queries()[:3]:
            remaining = self._jsearch_jobs_remaining_today()
            if remaining <= 0:
                _logger.warning("linkedin.job daily JSearch fail-closed: daily job import cap")
                break
            if not self._jsearch_reserve_request():
                break
            try:
                created = Search._import_jsearch_v2(
                    query=spec["query"],
                    country=spec.get("country") or "",
                    remote=bool(spec.get("remote")),
                    date_posted="week",
                    page=1,
                    account=personal,
                    max_new=remaining,
                    source_label="JSearch-daily",
                )
            except Exception:
                _logger.exception(
                    "linkedin.job daily JSearch failed query=%s country=%s",
                    spec.get("query"),
                    spec.get("country"),
                )
                continue
            imported_total += created
            self._jsearch_record_imported(created)
        _logger.info(
            "linkedin.job daily JSearch done imported=%s account=%s",
            imported_total,
            personal.id,
        )

    @api.model
    def _cairo_day_start_utc_naive(self):
        """Return UTC-naive datetime for Africa/Cairo midnight of context today."""
        try:
            import pytz

            cairo = pytz.timezone("Africa/Cairo")
            today = fields.Date.context_today(self)
            local_start = cairo.localize(datetime(today.year, today.month, today.day, 0, 0, 0))
            return local_start.astimezone(pytz.UTC).replace(tzinfo=None)
        except Exception:
            now = fields.Datetime.now()
            return now.replace(hour=0, minute=0, second=0, microsecond=0)

    @api.model
    def _cron_daily_job_digest(self):
        """07:15 Cairo — internal Odoo note only (no email, no applications, no API)."""
        if not self._live_job_search_enabled():
            _logger.info(
                "linkedin.job digest skipped: linkedin_connector.live_job_search_enabled is False "
                "(enable only after UAT approval)."
            )
            return

        personal = self.env["linkedin.account"].get_personal_account()
        if not personal:
            _logger.warning("linkedin.job digest: no personal account")
            return

        threshold = self._score_threshold()
        top_n = self._icp_int("linkedin_connector.digest_top_n", 10)
        since = self._cairo_day_start_utc_naive()
        jobs = self.search(
            [
                ("account_id", "=", personal.id),
                ("is_duplicate", "=", False),
                ("score", ">=", threshold),
                ("apply_url", "!=", False),
                ("apply_url", "!=", ""),
                ("create_date", ">=", fields.Datetime.to_string(since)),
            ],
            order="score desc, id desc",
            limit=top_n,
        )
        self._send_job_digest(jobs)

    @api.model
    def _digest_recipient_partners(self):
        """Sabry only: Job Hunt Manager group users (admin on Production)."""
        group = self.env.ref(
            "linkedin_connector.group_linkedin_job_hunt", raise_if_not_found=False
        )
        if not group:
            return self.env["res.partner"]
        # Odoo 19: res.groups.user_ids (legacy .users removed)
        partners = group.user_ids.mapped("partner_id")
        admin = self.env.ref("base.user_admin", raise_if_not_found=False)
        if admin and admin.partner_id and admin.partner_id in partners:
            return admin.partner_id
        return partners[:1]

    @api.model
    def _send_job_digest(self, jobs):
        partners = self._digest_recipient_partners()
        if not partners:
            return
        lines = []
        for job in jobs[:50]:
            listed = job.listed_at or job.create_date or ""
            lines.append(
                "- [%.0f] %s @ %s | %s | listed %s | %s"
                % (
                    job.score or 0,
                    job.title or "?",
                    job.company or "?",
                    job.location or "?",
                    listed,
                    job.apply_url or "",
                )
            )
        if not lines:
            body = _("Daily job digest: no new jobs at or above score threshold today.")
        else:
            body = _("Daily job digest — top %s new relevant jobs:\n%s") % (
                len(lines),
                "\n".join(lines),
            )
        for partner in partners:
            partner.message_post(
                body=body.replace("\n", "<br/>"),
                subject=_("LinkedIn job digest (internal)"),
                message_type="notification",
                subtype_xmlid="mail.mt_note",
            )

    @api.model
    def score_job_dict_for_tests(self, vals):
        """Helper for unit tests without persisting."""
        rec = self.new(vals)
        score, breakdown, flags = rec._score_job_values()
        return score, breakdown, flags


class LinkedinJobSearch(models.TransientModel):
    _name = "linkedin.job.search"
    _description = "LinkedIn Job Search"

    account_id = fields.Many2one(
        "linkedin.account",
        string="Account",
        domain="[('access_token', '!=', False)]",
    )
    keywords = fields.Char(string="Keywords", required=True)
    location = fields.Char(string="Location")
    remote = fields.Boolean(string="Remote only")
    country = fields.Char(
        string="Country code",
        help="ISO-2 country for JSearch (e.g. ae, eg). Empty for remote/global.",
    )
    date_posted = fields.Selection(
        [
            ("all", "All"),
            ("today", "Today"),
            ("3days", "3 days"),
            ("week", "Week"),
            ("month", "Month"),
        ],
        string="Date posted",
        default="week",
    )
    num_pages = fields.Integer(string="Pages to fetch", default=1,
                               help="Each page = ~10 results. Max 3 recommended for free tier.")
    source = fields.Selection(
        [
            ("auto", "Auto (JSearch search-v2 when key present)"),
            ("linkedin_guest", "LinkedIn Public (disallowed for Production cron)"),
            ("remoteok", "RemoteOK (free, remote jobs only)"),
            ("jsearch", "JSearch via RapidAPI (search-v2 only)"),
            ("browser", "Open LinkedIn.com in browser"),
        ],
        default="jsearch",
        string="Source",
        required=True,
    )
    result_count = fields.Integer(string="Results found", readonly=True)

    def _get_rapidapi_key(self):
        """Resolve JSearch RapidAPI key from process environment first.

        Preferred (Production): systemd EnvironmentFile → LINKEDIN_JSEARCH_RAPIDAPI_KEY.
        Never log the key. ICP ``linkedin_connector.rapidapi_key`` is deprecated fallback only.
        """
        import os

        for env_name in (
            "LINKEDIN_JSEARCH_RAPIDAPI_KEY",
            "JSEARCH_RAPIDAPI_KEY",
            "RAPIDAPI_KEY",
        ):
            val = (os.environ.get(env_name) or "").strip()
            if val:
                return val
        icp = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("linkedin_connector.rapidapi_key", "")
            or ""
        ).strip()
        if icp:
            _logger.warning(
                "linkedin_connector.rapidapi_key is set in ir.config_parameter; "
                "prefer LINKEDIN_JSEARCH_RAPIDAPI_KEY via systemd EnvironmentFile "
                "and clear the ICP value."
            )
        return icp

    # ------------------------------------------------------------------
    # RemoteOK — free, no key, remote jobs only
    # ------------------------------------------------------------------
    def _search_remoteok(self, keywords):
        """Search RemoteOK free API. Tries multiple tags derived from keywords."""
        tags = [t.strip().lower().replace(" ", "-") for t in keywords.split() if t.strip()]
        if not tags:
            tags = ["python"]

        Job = self.env["linkedin.job"]
        acc_id = self.account_id.id if self.account_id else False
        kw_lower = keywords.lower()
        created = updated = 0

        seen_ids = set()
        for tag in tags[:3]:  # max 3 tags to avoid rate limit
            try:
                resp = requests.get(
                    "https://remoteok.io/api",
                    params={"tag": tag},
                    headers={"User-Agent": "OdooLinkedInConnector/1.0"},
                    timeout=20,
                )
            except requests.RequestException:
                continue
            if resp.status_code != 200:
                continue
            for item in resp.json():
                if not isinstance(item, dict) or not item.get("position"):
                    continue
                # Filter: item must mention a keyword from search in title or tags
                title_lower = (item.get("position") or "").lower()
                item_tags = " ".join(item.get("tags") or []).lower()
                if not any(k in title_lower or k in item_tags for k in tags):
                    # If searching "odoo" specifically but no tag hit, still keep if in desc
                    desc_lower = (item.get("description") or "").lower()
                    if kw_lower not in title_lower and kw_lower not in desc_lower and kw_lower not in item_tags:
                        continue

                job_id = "remoteok_%s" % item.get("id", "")
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                existing = Job.search([("job_id", "=", job_id)], limit=1)
                desc = item.get("description") or ""
                if desc and not desc.startswith("<"):
                    desc = "<p>%s</p>" % desc.replace("\n\n", "</p><p>").replace("\n", "<br/>")

                import datetime as _dt
                listed = False
                ts = item.get("epoch")
                if ts:
                    try:
                        listed = fields.Datetime.to_string(_dt.datetime.utcfromtimestamp(int(ts)))
                    except Exception:
                        pass

                vals = {
                    "job_id": job_id,
                    "title": item.get("position") or "",
                    "company": item.get("company") or "",
                    "location": item.get("location") or "Remote",
                    "remote": True,
                    "description": desc,
                    "apply_url": item.get("url") or item.get("apply_url") or "",
                    "source": "RemoteOK",
                    "listed_at": listed,
                    "search_keywords": self.keywords,
                    "search_location": "Remote",
                }
                if acc_id:
                    vals["account_id"] = acc_id

                if existing:
                    existing.write(vals)
                    updated += 1
                else:
                    Job.create(vals)
                    created += 1

        return created, updated

    # ------------------------------------------------------------------
    # LinkedIn public guest API — free, no key, real LinkedIn jobs
    # ------------------------------------------------------------------
    def _search_linkedin_guest(self, keywords, location="", remote=False, pages=3):
        """Fetch jobs from LinkedIn's public (unauthenticated) job listing endpoint."""
        import re
        from html import unescape

        Job = self.env["linkedin.job"]
        acc_id = self.account_id.id if self.account_id else False
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        params_base = {
            "keywords": keywords,
            "location": location or "",
        }
        if remote:
            params_base["f_WT"] = "2"

        created = updated = 0
        seen_ids = set()

        for page_n in range(pages):
            start = page_n * 25
            params = dict(params_base, start=str(start))
            try:
                resp = requests.get(
                    _LI_GUEST_URL, headers=headers, params=params, timeout=20
                )
            except requests.RequestException:
                break
            if resp.status_code != 200:
                break

            html = resp.text
            # Each job is inside an <li> block; parse all job ids and card metadata
            # LinkedIn returns one <li> per job card
            li_blocks = re.split(r'(?=<li\b)', html)

            for block in li_blocks:
                if not block.strip():
                    continue

                job_id_m = re.search(r'jobPosting:(\d+)', block)
                if not job_id_m:
                    # fallback: look for data-entity-urn
                    job_id_m = re.search(r'data-entity-urn="[^"]*jobPosting:(\d+)"', block)
                if not job_id_m:
                    continue
                raw_id = job_id_m.group(1)
                job_id = "li_%s" % raw_id
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                title_m = re.search(
                    r'class="base-search-card__title"[^>]*>\s*(.*?)\s*</h3>',
                    block, re.DOTALL,
                )
                company_m = re.search(
                    r'class="base-search-card__subtitle"[^>]*>.*?<a[^>]*>(.*?)</a>',
                    block, re.DOTALL,
                )
                location_m = re.search(
                    r'class="job-search-card__location"[^>]*>\s*(.*?)\s*</span>',
                    block, re.DOTALL,
                )
                link_m = re.search(
                    r'href="(https://www\.linkedin\.com/jobs/view/[^"?]+)',
                    block,
                )

                title = unescape(title_m.group(1).strip()) if title_m else ""
                company = unescape(company_m.group(1).strip()) if company_m else ""
                loc = unescape(location_m.group(1).strip()) if location_m else ""
                apply_url = link_m.group(1) if link_m else (
                    "https://www.linkedin.com/jobs/view/%s/" % raw_id
                )

                if not title:
                    continue

                existing = Job.search([("job_id", "=", job_id)], limit=1)
                vals = {
                    "job_id": job_id,
                    "title": title,
                    "company": company,
                    "location": loc,
                    "remote": remote,
                    "apply_url": apply_url,
                    "source": "LinkedIn",
                    "search_keywords": self.keywords,
                    "search_location": location or "",
                }
                if acc_id:
                    vals["account_id"] = acc_id

                if existing:
                    existing.write(vals)
                    updated += 1
                else:
                    Job.create(vals)
                    created += 1

            if len(li_blocks) < 2:
                # no more results
                break

        return created, updated

    @staticmethod
    def _parse_jsearch_date(item):
        """Return an Odoo-compatible datetime string from a JSearch job item."""
        import datetime as _dt
        import re as _re

        # 1. ISO UTC string: '2026-04-07T00:00:00.000Z'
        iso = item.get("job_posted_at_datetime_utc") or ""
        if iso:
            try:
                iso_clean = iso.replace("Z", "").split(".")[0]
                return _dt.datetime.strptime(iso_clean, "%Y-%m-%dT%H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass

        # 2. Unix timestamp
        ts = item.get("job_posted_at_timestamp")
        if ts:
            try:
                return _dt.datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass

        # 3. Relative text: "3 days ago", "1 month ago", "2 weeks ago", "just now"
        posted_text = (item.get("job_posted_at") or "").lower().strip()
        if posted_text:
            now = _dt.datetime.utcnow()
            m = _re.search(r"(\d+)\s*(second|minute|hour|day|week|month|year)", posted_text)
            if m:
                n, unit = int(m.group(1)), m.group(2)
                delta_map = {
                    "second": _dt.timedelta(seconds=n),
                    "minute": _dt.timedelta(minutes=n),
                    "hour":   _dt.timedelta(hours=n),
                    "day":    _dt.timedelta(days=n),
                    "week":   _dt.timedelta(weeks=n),
                    "month":  _dt.timedelta(days=n * 30),
                    "year":   _dt.timedelta(days=n * 365),
                }
                delta = delta_map.get(unit)
                if delta:
                    return (now - delta).strftime("%Y-%m-%d %H:%M:%S")
            if "just now" in posted_text or "today" in posted_text:
                return now.strftime("%Y-%m-%d %H:%M:%S")

        # No date from the publisher — use current fetch time so the record
        # still appears in sorted views rather than sinking to the bottom.
        return _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    def action_search(self):
        self.ensure_one()

        source = self.source
        api_key = self._get_rapidapi_key()

        # Auto prefers JSearch search-v2 when key is present (never legacy /search).
        if source == "auto":
            source = "jsearch" if api_key else "browser"

        if source == "browser":
            return self._open_in_browser()

        if source == "linkedin_guest":
            pages = max(1, self.num_pages or 1)
            created, updated = self._search_linkedin_guest(
                self.keywords,
                location=self.location or "",
                remote=self.remote,
                pages=pages,
            )
            total = created + updated
            self.result_count = total
            if total == 0:
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": _("Job Search"),
                        "message": _(
                            "No jobs found for '%s' on LinkedIn public search.\n"
                            "Try broader keywords or switch to JSearch source."
                        ) % self.keywords,
                        "type": "warning",
                        "sticky": True,
                    },
                }
            return {
                "type": "ir.actions.act_window",
                "name": _("Jobs — %s") % self.keywords,
                "res_model": "linkedin.job",
                "view_mode": "list,form",
                "domain": [("search_keywords", "=", self.keywords)],
                "target": "current",
            }

        if source == "remoteok":
            created, updated = self._search_remoteok(self.keywords)
            total = created + updated
            self.result_count = total
            if total == 0:
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": _("Job Search"),
                        "message": _("No remote jobs found for '%s' on RemoteOK. "
                                     "Try different keywords or use JSearch source.") % self.keywords,
                        "type": "warning",
                        "sticky": True,
                    },
                }
            return {
                "type": "ir.actions.act_window",
                "name": _("Jobs — %s") % self.keywords,
                "res_model": "linkedin.job",
                "view_mode": "list,form",
                "domain": [("search_keywords", "=", self.keywords)],
                "target": "current",
            }

        # JSearch via RapidAPI search-v2 only
        if not api_key:
            return self._open_in_browser()

        query = self.keywords
        if self.location and " in " not in query.lower():
            query = "%s in %s" % (query, self.location)

        self.env["linkedin.job"]._jsearch_assert_endpoint(_JSEARCH_URL)
        remaining = self.env["linkedin.job"]._jsearch_jobs_remaining_today()
        if remaining <= 0:
            raise UserError(_("Daily JSearch import cap reached. Fail closed until tomorrow."))
        created = self._import_jsearch_v2(
            query=query,
            country=(self.country or "").strip().lower(),
            remote=bool(self.remote),
            date_posted=self.date_posted or "week",
            page=1,
            account=self.account_id,
            max_new=remaining,
            source_label="JSearch",
            num_pages=max(1, min(self.num_pages or 1, 3)),
            consume_quota=True,
        )
        self.env["linkedin.job"]._jsearch_record_imported(created)
        self.result_count = created

        if created == 0:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Job Search"),
                    "message": _("No jobs found for '%s'. Try different keywords.") % self.keywords,
                    "type": "warning",
                },
            }

        return {
            "type": "ir.actions.act_window",
            "name": _("Jobs — %s") % self.keywords,
            "res_model": "linkedin.job",
            "view_mode": "list,form",
            "domain": [("search_keywords", "=", self.keywords)],
            "target": "current",
            "context": {"search_default_search_keywords": self.keywords},
        }

    def _import_jsearch_v2(
        self,
        query,
        country="",
        remote=False,
        date_posted="week",
        page=1,
        account=None,
        max_new=10,
        source_label="JSearch",
        num_pages=1,
        consume_quota=False,
        api_key=None,
    ):
        """Call JSearch search-v2 once per page; import with score/dedupe, never applications.

        Returns count of newly created jobs (updates do not count toward daily import cap).
        """
        Job = self.env["linkedin.job"]
        Job._jsearch_assert_endpoint(_JSEARCH_URL)
        api_key = api_key or self._get_rapidapi_key()
        if not api_key:
            raise UserError(_("JSearch RapidAPI key is not configured in the environment."))

        headers = {
            "X-RapidAPI-Key": api_key,
            "X-RapidAPI-Host": _JSEARCH_HOST,
        }
        acc_id = account.id if account else False
        created = 0
        pages = max(1, min(int(num_pages or 1), 3))

        for page_no in range(int(page or 1), int(page or 1) + pages):
            if created >= max_new:
                break
            if consume_quota and not Job._jsearch_reserve_request():
                break

            params = {
                "query": query,
                "page": str(page_no),
                "num_pages": "1",
                "date_posted": date_posted or "week",
            }
            if country:
                params["country"] = country
            if remote:
                params["remote_jobs_only"] = "true"

            try:
                resp = requests.get(_JSEARCH_URL, headers=headers, params=params, timeout=30)
            except requests.RequestException as exc:
                raise UserError(_("Network error fetching jobs: %s") % exc)

            if resp.status_code == 401:
                raise UserError(
                    _("RapidAPI key is invalid or expired.\n\n"
                      "Install LINKEDIN_JSEARCH_RAPIDAPI_KEY via systemd EnvironmentFile.")
                )
            if resp.status_code == 429:
                raise UserError(
                    _("RapidAPI rate limit reached. Fail closed until quota resets.")
                )
            if resp.status_code != 200:
                raise UserError(
                    _("JSearch API error (HTTP %s): %s") % (resp.status_code, resp.text[:300])
                )

            data = resp.json()
            payload = data.get("data", [])
            if isinstance(payload, dict):
                jobs = payload.get("jobs") or payload.get("data") or []
            else:
                jobs = payload or []
            if not isinstance(jobs, list):
                jobs = []
            _logger.info(
                "linkedin.job.search-v2: page %d returned %d jobs query=%s",
                page_no,
                len(jobs),
                query,
            )

            for item in jobs:
                if created >= max_new:
                    break
                job_id = (item.get("job_id") or "").strip()
                apply_url = (
                    item.get("job_apply_link")
                    or item.get("job_google_link")
                    or ""
                ).strip()
                canon = Job._canonical_apply_url(apply_url)
                if not job_id or not canon:
                    continue

                existing = Job.search([("job_id", "=", job_id)], limit=1)
                if not existing:
                    existing = Job.search([("apply_url", "=", apply_url)], limit=1)
                if not existing and canon:
                    candidates = Job.search([("apply_url", "ilike", canon)], limit=5)
                    for cand in candidates:
                        if Job._canonical_apply_url(cand.apply_url) == canon:
                            existing = cand
                            break
                if existing:
                    # Update metadata only; do not count toward import cap
                    desc_html = item.get("job_description") or ""
                    if desc_html and not desc_html.startswith("<"):
                        desc_html = "<p>%s</p>" % desc_html.replace("\n\n", "</p><p>").replace(
                            "\n", "<br/>"
                        )
                    loc = (
                        item.get("job_location")
                        or ", ".join(
                            [
                                x
                                for x in (
                                    item.get("job_city") or "",
                                    item.get("job_country") or "",
                                )
                                if x
                            ]
                        )
                    )
                    vals = {
                        "job_id": job_id,
                        "title": item.get("job_title") or existing.title,
                        "company": item.get("employer_name") or existing.company,
                        "location": loc or existing.location,
                        "remote": bool(item.get("job_is_remote")),
                        "employment_type": item.get("job_employment_type") or "",
                        "description": desc_html or existing.description,
                        "apply_url": apply_url,
                        "source": source_label,
                        "listed_at": self._parse_jsearch_date(item),
                        "search_keywords": query,
                        "search_location": country or ("remote" if remote else ""),
                    }
                    if acc_id:
                        vals["account_id"] = acc_id
                    existing.with_context(
                        skip_job_postprocess=True, skip_application_create=True
                    ).write(vals)
                    existing.with_context(skip_application_create=True)._score_and_dedupe()
                    continue

                desc_html = item.get("job_description") or ""
                if desc_html and not desc_html.startswith("<"):
                    desc_html = "<p>%s</p>" % desc_html.replace("\n\n", "</p><p>").replace(
                        "\n", "<br/>"
                    )
                loc = (
                    item.get("job_location")
                    or ", ".join(
                        [
                            x
                            for x in (
                                item.get("job_city") or "",
                                item.get("job_country") or "",
                            )
                            if x
                        ]
                    )
                )
                vals = {
                    "job_id": job_id,
                    "title": item.get("job_title") or "",
                    "company": item.get("employer_name") or "",
                    "location": loc,
                    "remote": bool(item.get("job_is_remote")),
                    "employment_type": item.get("job_employment_type") or "",
                    "description": desc_html,
                    "apply_url": apply_url,
                    "source": source_label,
                    "listed_at": self._parse_jsearch_date(item),
                    "search_keywords": query,
                    "search_location": country or ("remote" if remote else ""),
                }
                if acc_id:
                    vals["account_id"] = acc_id
                Job.with_context(
                    skip_job_postprocess=True, skip_application_create=True
                ).create(vals)._score_and_dedupe()
                created += 1

        return created

    def _open_in_browser(self):
        params = {"keywords": self.keywords}
        if self.location:
            params["location"] = self.location
        if self.remote:
            params["f_WT"] = "2"
        return {
            "type": "ir.actions.act_url",
            "url": "https://www.linkedin.com/jobs/search/?" + urlencode(params),
            "target": "new",
        }
