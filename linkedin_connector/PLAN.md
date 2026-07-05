# LinkedIn Connector — Full Management Plan

Modeled on `social` + `social_linkedin` enterprise modules but **standalone**
(your own OAuth credentials, no IAP, no `social` dependency).

Current module version: **19.0.1.0.9**

---

## Phase 1 — Posts (Create + Schedule + Draft)

**New model: `linkedin.post`**

| Field | Type | Notes |
|---|---|---|
| `account_id` | Many2one `linkedin.account` | which connected account |
| `message` | Text | post body |
| `image_ids` | Many2many `ir.attachment` | up to 20 images |
| `post_method` | Selection: `now` / `scheduled` | |
| `scheduled_date` | Datetime | when to publish |
| `state` | Selection: `draft / scheduled / posted / failed` | |
| `linkedin_post_urn` | Char | returned by API on success |
| `failure_reason` | Text | API error body |
| `published_date` | Datetime | actual publish time |
| `visibility` | Selection: `PUBLIC / CONNECTIONS` | |

**Actions:**
- `action_post_now` — calls LinkedIn `POST /rest/posts` (UGC v2)
- `action_schedule` — sets state to `scheduled`
- Cron every 5 min — publishes scheduled posts whose `scheduled_date <= now`
- `action_cancel` — back to draft

**Views:** Form (with preview panel), List (filterable by state), Calendar (by `scheduled_date`)

**LinkedIn API product required:** Share on LinkedIn (`w_member_social`) — already working ✅

---

## Phase 2 — Feed / Stream (Read Posts)

**New model: `linkedin.stream.post`** — cached snapshot of LinkedIn feed items

| Field | Notes |
|---|---|
| `account_id` | which account fetched it |
| `author_name` / `author_image_url` | display |
| `message` | post text |
| `published_date` | |
| `post_urn` | LinkedIn URN |
| `post_link` | URL to open on LinkedIn |
| `likes_count` / `comments_count` / `reposts_count` | engagement |
| `image_urls` | Text (JSON) |
| `last_fetched` | Datetime |

**Actions:**
- Button **Refresh Feed** on account form — `GET /rest/posts?author=urn:li:person:xxx`
- Cron every 30 min — auto-refresh all active accounts
- Kanban view grouped by account (pattern: `social.stream.post` feed kanban)
- Click a post → panel: full text + engagement + **Reply / Like / Delete** buttons

**LinkedIn API product required:** Share on LinkedIn (`w_member_social`) ✅

---

## Phase 3 — Job Search

**Models:** `linkedin.job.search` (transient wizard) + `linkedin.job` (stored results)

| Model | Key Fields |
|---|---|
| Wizard | `keywords`, `location`, `job_type`, `remote`, `account_id` |
| `linkedin.job` | `title`, `company`, `location`, `description`, `apply_url`, `job_id`, `listed_at`, `account_id`, `saved` |

**API:** `GET /v2/jobSearch?keywords=...&location=...`

**Views:** Wizard form → results list with **Save / Apply** buttons; saved jobs list filtered by `saved=True`

**LinkedIn API product required:** Jobs Search API (separate product request in LinkedIn Developers)

---

## Phase 4 — Resume / Document Upload

**New model: `linkedin.resume`**

| Field | Notes |
|---|---|
| `account_id` | |
| `attachment_id` | Many2one `ir.attachment` (PDF) |
| `linkedin_document_urn` | returned after upload |
| `upload_date` | Datetime |
| `state` | `draft / uploaded / failed` |

**API flow:**
1. `POST /rest/documents?action=initializeUpload` → get upload URL
2. `PUT <uploadUrl>` → binary upload of PDF
3. Store returned `documentUrn`
4. Optionally create a `linkedin.post` with the document as media

**Views:** Form with file picker + Upload button + display of `linkedin_document_urn`

**LinkedIn API product required:** Share on LinkedIn + Documents API (`w_member_social`) ✅

---

## Phase 5 — Messaging

**Models:** `linkedin.conversation` + `linkedin.message`

| Model | Key Fields |
|---|---|
| `linkedin.conversation` | `account_id`, `conversation_id`, `participants` (JSON), `last_message`, `last_activity_at`, `unread_count` |
| `linkedin.message` | `conversation_id`, `sender_name`, `body`, `sent_at`, `direction` (in/out), `linkedin_msg_id` |

**API:**
- `GET /v2/conversations` — list conversations
- `GET /v2/conversations/{id}/events` — messages in thread
- `POST /v2/messages` — send reply

**Views:**
- Two-panel layout: left = conversation list, right = message thread
- Reply box at bottom with **Send** button
- Cron every 5 min — sync new messages, update `unread_count`

**LinkedIn API product required:** Messaging API (`w_messages`) — restricted, must request access separately

---

## Architecture overview

```
linkedin.account  (OAuth, tokens)
    │
    ├── linkedin.post           (create / schedule / publish)
    ├── linkedin.stream.post    (read own feed — Phase 2)
    ├── linkedin.job            (job search results — Phase 3)
    ├── linkedin.resume         (document upload — Phase 4)
    └── linkedin.conversation ──< linkedin.message  (messaging — Phase 5)
```

---

## Implementation order & effort

| Phase | Feature | Effort | API product |
|---|---|---|---|
| 1 | Posts + Schedule + Draft | Medium | `w_member_social` ✅ |
| 2 | Feed / Stream | Medium | `w_member_social` ✅ |
| 3 | Job Search | Low–Medium | Jobs Search (request needed) |
| 4 | Resume Upload | Medium | Documents API (`w_member_social`) ✅ |
| 5 | Messaging | High | `w_messages` (request needed) |

---

## Reference

- Enterprise module used as reference: `D:\odoo\odoo19\enterprise\social` + `D:\odoo\odoo19\enterprise\social_linkedin`
- Current connector source: `D:\odoo\odoo19\projects\resume\linkedin_connector\`
- LinkedIn REST API base: `https://api.linkedin.com/rest/` (use `LinkedIn-Version: 202410` header)
- LinkedIn OAuth scopes currently on account: `openid profile w_member_social`
