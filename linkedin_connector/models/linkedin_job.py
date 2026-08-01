import hashlib
import json
import logging
import re
from html import unescape
from urllib.parse import urlencode, urlparse

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_JSEARCH_HOST = "jsearch.p.rapidapi.com"
_JSEARCH_URL = "https://%s/search" % _JSEARCH_HOST

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
            self._maybe_create_applications()
        return res

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
        """Return (score, breakdown_dict, flags)."""
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
                "Senior Odoo Developer|Odoo Developer|Odoo Consultant|Senior Odoo",
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
    def _cron_daily_job_digest(self):
        """Daily discovery + digest. Live LinkedIn calls gated by ICP flag."""
        if not self._live_job_search_enabled():
            _logger.info(
                "linkedin.job digest skipped: linkedin_connector.live_job_search_enabled is False "
                "(enable only after UAT approval)."
            )
            return

        Wizard = self.env["linkedin.job.search"]
        personal = self.env["linkedin.account"].get_personal_account()
        locations_raw = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("linkedin_connector.job_search_locations", "Remote|Egypt|United Arab Emirates")
        )
        locations = [x.strip() for x in locations_raw.split("|") if x.strip()] or [""]
        new_apps = self.env["linkedin.job.application"]

        for keywords in self._job_search_queries():
            for location in locations:
                wiz = Wizard.create(
                    {
                        "account_id": personal.id if personal else False,
                        "keywords": keywords,
                        "location": location,
                        "remote": location.lower() == "remote",
                        "num_pages": 1,
                        "source": "linkedin_guest",
                    }
                )
                try:
                    wiz.action_search()
                except Exception:
                    _logger.exception(
                        "linkedin.job digest search failed keywords=%s location=%s",
                        keywords,
                        location,
                    )

        threshold = self._score_threshold()
        apps = self.env["linkedin.job.application"].search(
            [
                ("state", "=", "discovered"),
                ("score", ">=", threshold),
                ("create_date", ">=", fields.Datetime.now().replace(hour=0, minute=0, second=0)),
            ]
        )
        new_apps |= apps
        self._send_job_digest(new_apps)

    @api.model
    def _send_job_digest(self, applications):
        group = self.env.ref(
            "linkedin_connector.group_linkedin_job_hunt", raise_if_not_found=False
        )
        if not group:
            return
        users = group.users
        if not users:
            return
        lines = []
        for app in applications[:50]:
            lines.append(
                "- [%.0f] %s @ %s (%s)"
                % (app.score or 0, app.job_title or "?", app.job_company or "?", app.state)
            )
        if not lines:
            body = _("Daily job digest: no new shortlist-threshold applications today.")
        else:
            body = _("Daily job digest (%s):\n%s") % (len(lines), "\n".join(lines))
        for user in users:
            if user.partner_id:
                user.partner_id.message_post(
                    body=body.replace("\n", "<br/>"),
                    subject=_("LinkedIn job digest"),
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
    num_pages = fields.Integer(string="Pages to fetch", default=1,
                               help="Each page = ~10 results. Max 3 recommended for free tier.")
    source = fields.Selection(
        [
            ("auto", "Auto (LinkedIn public → JSearch if subscribed)"),
            ("linkedin_guest", "LinkedIn Public (free, no key needed)"),
            ("remoteok", "RemoteOK (free, remote jobs only)"),
            ("jsearch", "JSearch via RapidAPI (needs subscription)"),
            ("browser", "Open LinkedIn.com in browser"),
        ],
        default="auto",
        string="Source",
        required=True,
    )
    result_count = fields.Integer(string="Results found", readonly=True)

    def _get_rapidapi_key(self):
        return self.env["ir.config_parameter"].sudo().get_param(
            "linkedin_connector.rapidapi_key", ""
        ).strip()

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

        # Auto: LinkedIn guest first; if subscribed to JSearch use that
        if source == "auto":
            source = "linkedin_guest"

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

        # JSearch via RapidAPI
        if not api_key:
            return self._open_in_browser()

        query = self.keywords
        if self.location:
            query += " in %s" % self.location

        headers = {
            "X-RapidAPI-Key": api_key,
            "X-RapidAPI-Host": _JSEARCH_HOST,
        }

        Job = self.env["linkedin.job"]
        acc_id = self.account_id.id if self.account_id else False
        created = 0
        updated = 0

        for page in range(1, (self.num_pages or 1) + 1):
            params = {
                "query": query,
                "page": str(page),
                "num_pages": "1",
                "country": "us",
            }
            if self.remote:
                params["remote_jobs_only"] = "true"

            try:
                resp = requests.get(_JSEARCH_URL, headers=headers, params=params, timeout=30)
            except requests.RequestException as exc:
                raise UserError(_("Network error fetching jobs: %s") % exc)

            if resp.status_code == 401:
                raise UserError(
                    _("RapidAPI key is invalid or expired.\n\n"
                      "Go to Settings → LinkedIn → RapidAPI Key and update it.\n"
                      "Sign up free at https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch")
                )
            if resp.status_code == 429:
                raise UserError(
                    _("RapidAPI rate limit reached (free tier: 200 req/month).\n"
                      "Wait until next month or upgrade your RapidAPI plan.")
                )
            if resp.status_code != 200:
                raise UserError(_("JSearch API error (HTTP %s): %s") % (resp.status_code, resp.text[:300]))

            data = resp.json()
            jobs = data.get("data", [])
            _logger.info("linkedin.job.search: page %d returned %d jobs", page, len(jobs))

            for item in jobs:
                job_id = item.get("job_id") or ""
                if not job_id:
                    continue

                existing = Job.search([("job_id", "=", job_id)], limit=1)
                desc_html = item.get("job_description") or ""
                if desc_html and not desc_html.startswith("<"):
                    desc_html = "<p>%s</p>" % desc_html.replace("\n\n", "</p><p>").replace("\n", "<br/>")

                # Prefer LinkedIn apply URL when available
                apply_url = (
                    item.get("job_apply_link")
                    or item.get("job_google_link")
                    or ""
                )
                source = item.get("job_publisher") or "JSearch"

                vals = {
                    "job_id": job_id,
                    "title": item.get("job_title") or "",
                    "company": item.get("employer_name") or "",
                    "location": "%s, %s" % (
                        item.get("job_city") or "",
                        item.get("job_country") or "",
                    ),
                    "remote": bool(item.get("job_is_remote")),
                    "employment_type": item.get("job_employment_type") or "",
                    "description": desc_html,
                    "apply_url": apply_url,
                    "source": source,
                    "listed_at": self._parse_jsearch_date(item),
                    "search_keywords": self.keywords,
                    "search_location": self.location or "",
                }
                if acc_id:
                    vals["account_id"] = acc_id

                if existing:
                    existing.write(vals)
                    updated += 1
                else:
                    Job.create(vals)
                    created += 1

        total = created + updated
        self.result_count = total

        if total == 0:
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
