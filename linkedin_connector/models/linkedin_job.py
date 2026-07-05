import logging
from urllib.parse import urlencode

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_JSEARCH_HOST = "jsearch.p.rapidapi.com"
_JSEARCH_URL = "https://%s/search" % _JSEARCH_HOST

_LI_GUEST_URL = (
    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
)


class LinkedinJob(models.Model):
    _name = "linkedin.job"
    _description = "LinkedIn Job"
    _order = "listed_at desc, id desc"
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

    def action_open_apply(self):
        self.ensure_one()
        if not self.apply_url:
            raise UserError(_("No apply URL for this job."))
        return {"type": "ir.actions.act_url", "url": self.apply_url, "target": "new"}

    def action_toggle_saved(self):
        for rec in self:
            rec.saved = not rec.saved

    @api.model
    def action_open_linkedin_jobs_search(self, keywords="", location=""):
        params = {}
        if keywords:
            params["keywords"] = keywords
        if location:
            params["location"] = location
        url = "https://www.linkedin.com/jobs/search/?" + urlencode(params) if params else "https://www.linkedin.com/jobs/"
        return {"type": "ir.actions.act_url", "url": url, "target": "new"}


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
