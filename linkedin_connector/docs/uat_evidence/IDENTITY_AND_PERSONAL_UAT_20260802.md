# Identity verification & personal UAT — 2026-08-02

## Verdict

**`BLOCKED_DEFAULT_CV_UPLOAD_REQUIRED`**

Identity and personal account configuration are complete on `pet_spot_elsahel_test`.  
Bounded CV discovery found **zero** valid `Sabry_Youssef_CV.pdf` candidates on this host.  
Offline UAT (Phase D) and full suite re-run are deferred until the CV is uploaded to the private staging path.

---

## Safety (unchanged / re-verified)

| Item | Value |
|------|--------|
| Database | `pet_spot_elsahel_test` only |
| Branch | `feature/petspot-vendor-sell-through` |
| HEAD (at this write) | `4e77d7e2fa26ec1edbb02bf53b28a5d8d3e867d8` (+ evidence commit after) |
| Module | `linkedin_connector` `19.0.2.8.0` |
| Production | Untouched |
| Live search | `False` |
| LinkedIn crons (publish/feed/messages/digest) | all **inactive** |

Not performed: live LinkedIn search, publish, apply open/submit, profile edit, LinkedIn document upload, CV text logging.

---

## Identity + account (approved)

User confirmation: `CONFIRM_ACCOUNT_2_IS_SABRY_PERSONAL` for OAuth while logged into  
`https://www.linkedin.com/in/sabry-youssef-56a878185/`.

| Field | Account id=2 |
|-------|----------------|
| name | Sabry Youssef — Personal |
| account_type | personal |
| profile_url | `https://www.linkedin.com/in/sabry-youssef-56a878185/` |
| org_id | absent |
| fallback_personal_post | false |
| author | member URN only |

Isolation previously proven: personal rejects company marketing; company rejects job branding.

---

## Phase A — Bounded CV discovery (2026-08-02)

Search roots (read-only): `/home/sabry` (with exclude prune for `.git`, filestore, `server-setup`, Odoo addons demos, secrets, browser, `.cursor`), plus explicit checks of:

- `/home/sabry/Downloads`, `Desktop`, `Documents`, `docs`
- `/home/sabry/odoo_base/base_odoo_19/projects/resume`
- `/mnt/cluster/desktop`, `/mnt/cluster/precision`

Filenames sought: `Sabry_Youssef_CV.pdf` and case/space equivalents.

| Result | Value |
|--------|--------|
| Candidate count | **0** |
| Prior path `/home/sabry3/Sabry_Youssef_CV.pdf` | not present (`/home/sabry3` does not exist on master) |
| Ledger PDF excluded | yes (not used) |

No selection ambiguity — no file to choose.

---

## Phase B — Private staging directory prepared (empty)

Created outside the git repository:

```text
/home/sabry/private/                 mode 0700
/home/sabry/private/linkedin_cv/     mode 0700
```

- Not a git worktree (`NOT_A_GIT_REPO`)
- Target filename when uploaded: `/home/sabry/private/linkedin_cv/Sabry_Youssef_CV.pdf` (to be `0600`)
- No PDF staged yet; nothing to hash/compare

### Exact upload command (from the machine that has the file)

```bash
scp Sabry_Youssef_CV.pdf sabry@<master-host>:/home/sabry/private/linkedin_cv/Sabry_Youssef_CV.pdf
ssh sabry@<master-host> 'chmod 600 /home/sabry/private/linkedin_cv/Sabry_Youssef_CV.pdf && ls -la /home/sabry/private/linkedin_cv/Sabry_Youssef_CV.pdf && sha256sum /home/sabry/private/linkedin_cv/Sabry_Youssef_CV.pdf'
```

Then reply in chat: `CV_UPLOADED_PRIVATE_STAGING_READY`

Do **not** place the PDF under the git repo or `linkedin_connector/docs/`.

---

## Phases C–E

| Phase | Status |
|-------|--------|
| C Odoo attach default CV | blocked — no file |
| D Controlled offline UAT | blocked |
| E Full test suite + final approval verdict | blocked |

---

## Git

- Evidence-only updates; CV never committed.
- Unrelated dirty tree preserved.
- Push: not pushed unless separately authorized.
