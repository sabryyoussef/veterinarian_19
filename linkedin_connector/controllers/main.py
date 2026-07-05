import logging
import textwrap
from urllib.parse import quote, urlencode

from odoo import http
from odoo.addons.web.controllers.utils import ensure_db
from odoo.exceptions import UserError
from odoo.http import request

_logger = logging.getLogger(__name__)

_PAGE = textwrap.dedent("""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>LinkedIn Connector</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
        background:#f0f4f8;display:flex;align-items:center;justify-content:center;
        min-height:100vh;padding:24px}}
  .card{{background:#fff;border-radius:12px;box-shadow:0 4px 24px rgba(0,0,0,.10);
         max-width:480px;width:100%;padding:40px 36px;text-align:center}}
  .icon{{font-size:52px;margin-bottom:16px}}
  h1{{font-size:22px;font-weight:700;margin-bottom:10px;color:{title_color}}}
  p{{color:#555;font-size:15px;line-height:1.6;margin-bottom:8px}}
  .urn{{background:#f5f7fa;border-radius:6px;padding:10px 14px;font-size:13px;
        font-family:monospace;color:#333;margin:16px 0;word-break:break-all}}
  .btn{{display:inline-block;margin-top:24px;padding:12px 28px;border-radius:8px;
        font-size:15px;font-weight:600;text-decoration:none;color:#fff;
        background:{btn_color};transition:opacity .2s}}
  .btn:hover{{opacity:.88}}
  .bar{{height:4px;border-radius:2px;background:#e2e8f0;margin-top:28px;overflow:hidden}}
  .bar-inner{{height:100%;width:0;background:{btn_color};
              animation:fill {redirect_secs}s linear forwards}}
  @keyframes fill{{to{{width:100%}}}}
  .timer{{font-size:12px;color:#aaa;margin-top:6px}}
  .error-detail{{background:#fff5f5;border:1px solid #fed7d7;border-radius:6px;
                 padding:12px 14px;font-size:12px;font-family:monospace;color:#c53030;
                 text-align:left;margin-top:16px;white-space:pre-wrap;word-break:break-all}}
</style>
</head>
<body>
<div class="card">
  <div class="icon">{icon}</div>
  <h1>{title}</h1>
  {body}
  <a class="btn" href="{redirect_url}">{btn_label}</a>
  {progress}
</div>
{meta_refresh}
</body>
</html>
""")


def _render_page(title, body_html, btn_label, redirect_url,
                 icon, title_color, btn_color, auto_redirect_secs=5):
    if auto_redirect_secs:
        progress = (
            '<div class="bar"><div class="bar-inner"></div></div>'
            '<p class="timer">Redirecting in %d seconds…</p>' % auto_redirect_secs
        )
        meta = '<meta http-equiv="refresh" content="%d;url=%s"/>' % (
            auto_redirect_secs, redirect_url
        )
    else:
        progress = ""
        meta = ""
    html = _PAGE.format(
        icon=icon,
        title=title,
        title_color=title_color,
        body=body_html,
        btn_label=btn_label,
        redirect_url=redirect_url,
        btn_color=btn_color,
        progress=progress,
        meta_refresh=meta,
        redirect_secs=auto_redirect_secs or 5,
    )
    return request.make_response(html, headers=[("Content-Type", "text/html; charset=utf-8")])


class LinkedinConnectorController(http.Controller):
    @http.route("/linkedin_connector/callback", type="http", auth="none", methods=["GET"], csrf=False)
    def linkedin_callback(self, **kwargs):
        ensure_db(redirect="/web/database/selector")
        db = request.env.cr.dbname
        odoo_url = "/web?db=%s#model=linkedin.account&view_type=list" % quote(db, safe="")

        error = request.params.get("error")
        if error:
            desc = request.params.get("error_description") or "No description provided."
            _logger.error("LinkedIn OAuth callback error: %s | %s", error, desc)
            return _render_page(
                title="LinkedIn denied the request",
                body_html=(
                    "<p>LinkedIn returned an error during authorization.</p>"
                    '<div class="error-detail"><b>%s</b>\n%s</div>' % (error, desc)
                ),
                btn_label="Back to Odoo",
                redirect_url=odoo_url,
                icon="&#10060;",
                title_color="#c53030",
                btn_color="#e53e3e",
                auto_redirect_secs=0,
            )

        code = request.params.get("code")
        state = request.params.get("state")
        if not code or not state:
            return _render_page(
                title="Missing parameters",
                body_html="<p>The callback URL is missing <b>code</b> or <b>state</b>. "
                          "Try connecting again from Odoo.</p>",
                btn_label="Back to Odoo",
                redirect_url=odoo_url,
                icon="&#9888;&#65039;",
                title_color="#b7791f",
                btn_color="#d69e2e",
                auto_redirect_secs=0,
            )

        account = request.env["linkedin.account"].sudo().search(
            [("state_token", "=", state)], limit=1
        )
        if not account:
            return _render_page(
                title="Session expired",
                body_html="<p>The OAuth state token was not found. It may have expired or already been used. "
                          "Please <b>Disconnect</b> the account in Odoo and click <b>Connect</b> again.</p>",
                btn_label="Back to Odoo",
                redirect_url=odoo_url,
                icon="&#128274;",
                title_color="#b7791f",
                btn_color="#d69e2e",
                auto_redirect_secs=0,
            )

        account_url = "/web?db=%s#model=linkedin.account&id=%s&view_type=form" % (
            quote(db, safe=""), account.id
        )
        try:
            account._exchange_code(code)
            account._fetch_member_urn()
        except UserError as exc:
            _logger.error("LinkedIn connector callback failed: %s", exc)
            return _render_page(
                title="Connection failed",
                body_html=(
                    "<p>The token was exchanged but retrieving the LinkedIn member ID failed.</p>"
                    '<div class="error-detail">%s</div>' % str(exc)
                ),
                btn_label="Go to Account",
                redirect_url=account_url,
                icon="&#10060;",
                title_color="#c53030",
                btn_color="#e53e3e",
                auto_redirect_secs=0,
            )
        except Exception as exc:
            _logger.exception("LinkedIn connector unexpected error: %s", exc)
            return _render_page(
                title="Unexpected error",
                body_html=(
                    "<p>Something went wrong. Check Odoo logs for details.</p>"
                    '<div class="error-detail">%s</div>' % str(exc)
                ),
                btn_label="Go to Account",
                redirect_url=account_url,
                icon="&#10060;",
                title_color="#c53030",
                btn_color="#e53e3e",
                auto_redirect_secs=0,
            )

        urn = account.linkedin_member_urn or "resolving…"
        return _render_page(
            title="LinkedIn connected!",
            body_html=(
                "<p>Account <b>%s</b> is now connected.</p>"
                '<div class="urn">%s</div>'
                "<p>You can now post to LinkedIn directly from Odoo.</p>"
            ) % (account.name, urn),
            btn_label="Open Account",
            redirect_url=account_url,
            icon="&#9989;",
            title_color="#276749",
            btn_color="#38a169",
            auto_redirect_secs=5,
        )
