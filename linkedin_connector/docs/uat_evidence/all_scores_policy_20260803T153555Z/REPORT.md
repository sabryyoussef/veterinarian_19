# All-scores application policy

**Verdict:** `ALL_SCORES_POLICY_ACTIVE_WAITING_FOR_SAFE_CANARY`

## Module
- `linkedin_connector` **19.0.2.16.0**
- Account `id=2` only; company `id=1` untouched (`company_apps=0`)

## Policy
| | Old | New |
|--|--|--|
| `min_score` | 65 | **0** |
| `job_score_threshold` | 65 | **0** |
| Score role | hard gate | **informational only** |

Hard gates retained: duplicate/applied, CAPTCHA→human_required, auth/sponsorship, location policy, unsupported ATS, sensitive docs.

## Tests
- Odoo: **0 failed, 0 error(s) of 55 tests** (TEST)
- Worker: score=0 passes authorize gate; CAPTCHA still human_required

## Backup
`dump=/home/sabry/private/job_orchestrator/backups/pet_spot_elsahel_pre_all_scores_20260803T153555Z.dump size=79130267 sha256=07f1e6341f20803b7107f9667c80c17f1c77d000199dd43535594dc196881b60 toc=32449`

## Re-evaluation (account id=2)
- Jobs re-evaluated: **40** (+1 applied preserved = 41)
- Auto eligible / safe canary: **0**
- Queued (auto queue): **0**
- Human required: **12** (all `captcha_or_turnstile`)
- Hard excluded: **17** (location_unknown 9, location_out_of_policy 4, gulf_without_sponsorship 2, eu_without_sponsorship 1, + applied Odoo S.A. preserved blocker)
- Unsupported ATS: **12**
- External submissions: **1** (Odoo S.A. applied — not resubmitted)

## Canary / submit controls
- No safe unattended canary (CAPTCHA or hard location/auth blockers)
- `kill_switch=True`, `live_submit_enabled=False`, browser/email submit off
- Caps unchanged: 2/day, 30 min spacing

## Dashboard
LinkedIn → Reporting → Caught Jobs Dashboard — KPIs now: All Caught Jobs, Auto Eligible, Queued, Applied Today/Total, Human Required, Hard Excluded, Unsupported ATS, Submission Unknown, capacity remaining, score distribution (informational).

Evidence: `/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/linkedin_connector/docs/uat_evidence/all_scores_policy_20260803T153555Z`
