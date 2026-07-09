# -*- coding: utf-8 -*-
"""Retarget campaign to remote account 4 (connected) and push one post now to confirm."""
import time

env = env  # noqa: F821 (provided by odoo shell)
ICP = env["ir.config_parameter"].sudo()
Post = env["social.media.post"]
Page = env["social.media.page"]

TARGET_ACCOUNT = 4

# 1) Point the connector at the connected page and sync local pages.
ICP.set_param("social_media_connector.single_remote_account_id", str(TARGET_ACCOUNT))
ICP.set_param("social_media_connector.default_remote_account_id", str(TARGET_ACCOUNT))
synced = Page.sync_from_remote()
page4 = Page.search([("remote_account_id", "=", TARGET_ACCOUNT)], limit=1)
print("SYNC: %s remote page(s). Local page4 id=%s name=%r disconnected=%s has_token=%s"
      % (synced, page4.id, page4.name, page4.is_disconnected, page4.has_token))

# 2) Ensure all scheduled (ready) posts point at page4.
ready = Post.search([("state", "=", "ready")])
ready.write({"page_id": page4.id})
print("REPOINTED: %s ready posts -> page4" % len(ready))

# 3) Push ONE post now to confirm it appears on Facebook.
test = Post.search([("state", "=", "ready")], order="scheduled_date, id", limit=1)
print("PUSHNOW: post id=%s title=%r" % (test.id, test.title))
push_error = None
try:
    test.action_push_now()
except Exception as exc:  # noqa: BLE001
    push_error = str(exc)
    print("PUSH_EXCEPTION:", push_error)

env.cr.commit()

# 4) Poll remote state a few times for confirmation.
remote_fb_id = None
for attempt in range(6):
    time.sleep(5)
    test.invalidate_recordset()
    try:
        test._refresh_remote_state()
    except Exception as exc:  # noqa: BLE001
        print("refresh error:", exc)
    print("  [t+%ss] local_state=%s remote_post_id=%s remote_state=%s"
          % ((attempt + 1) * 5, test.state, test.remote_post_id, test.remote_state))
    if test.remote_state in ("posted",):
        break

# 5) Try to fetch the Facebook post id / permalink from remote live posts.
try:
    from odoo.addons.social_media_connector.models.social_media_remote import get_remote_client
    client = get_remote_client(env)
    client.authenticate()
    if test.remote_post_id:
        live = client.search_read(
            "social.live.post",
            [("post_id", "=", test.remote_post_id)],
            ["id", "state", "facebook_post_id"],
        )
        print("LIVE_POSTS:", live)
        for lp in live:
            if lp.get("facebook_post_id"):
                remote_fb_id = lp["facebook_post_id"]
except Exception as exc:  # noqa: BLE001
    print("live-post lookup error:", exc)

if remote_fb_id:
    print("FACEBOOK_POST_ID:", remote_fb_id)
    print("PERMALINK: https://www.facebook.com/%s" % remote_fb_id)

# 6) Enable auto-push only if the push was accepted (pushed, no failure).
confirmed = test.state == "pushed" and not test.failure_reason
if confirmed:
    ICP.set_param("social_media_connector.auto_push_enabled", "True")
    lead = ICP.get_param("social_media_connector.auto_push_lead_minutes", "15")
    print("AUTO_PUSH: ENABLED (lead=%s min)" % lead)
else:
    ICP.set_param("social_media_connector.auto_push_enabled", "False")
    print("AUTO_PUSH: left DISABLED. failure_reason=%r" % test.failure_reason)

env.cr.commit()
print("DONE. confirmed=%s" % confirmed)
