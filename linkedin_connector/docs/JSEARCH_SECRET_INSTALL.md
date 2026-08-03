# JSearch secret installation (Production)

**Status gate:** `JSEARCH_SECRET_INSTALLATION_INSTRUCTIONS_READY`  
**Module:** `linkedin_connector` **19.0.2.8.1** (env-first key resolution; Production upgraded)  
**Do not** paste the RapidAPI key into chat, Git, Odoo ICP, screenshots, or evidence.

## What the connector expects

| Priority | Source | Name |
| --- | --- | --- |
| 1 (preferred) | Process environment | `LINKEDIN_JSEARCH_RAPIDAPI_KEY` |
| 2 | Process environment | `JSEARCH_RAPIDAPI_KEY` |
| 3 | Process environment | `RAPIDAPI_KEY` |
| 4 (deprecated) | `ir.config_parameter` | `linkedin_connector.rapidapi_key` |

Code: `linkedin.job.search._get_rapidapi_key()`. Settings UI only shows whether the env var is loaded — it no longer stores the key.

## Systemd wiring (already added)

- Drop-in: `~/.config/systemd/user/pet_spot_elsahel.service.d/jsearch-env.conf`
- File: `EnvironmentFile=-/etc/petspot/linkedin_jsearch.env`
- Leading `-` means Odoo still starts if the file is missing.

## One-shot install command (hidden input — no history / no chat)

Run this **on the Production host** as your normal user (will prompt for `sudo`):

```bash
sudo install -d -m 0750 -o root -g sabry /etc/petspot && \
umask 077 && \
read -s -p "JSearch RapidAPI key: " LINKEDIN_JSEARCH_RAPIDAPI_KEY && echo && \
printf 'LINKEDIN_JSEARCH_RAPIDAPI_KEY=%s\n' "$LINKEDIN_JSEARCH_RAPIDAPI_KEY" | sudo tee /etc/petspot/linkedin_jsearch.env >/dev/null && \
sudo chown root:sabry /etc/petspot/linkedin_jsearch.env && \
sudo chmod 640 /etc/petspot/linkedin_jsearch.env && \
unset LINKEDIN_JSEARCH_RAPIDAPI_KEY && \
systemctl --user daemon-reload && \
systemctl --user restart pet_spot_elsahel.service && \
sleep 3 && \
systemctl --user is-active pet_spot_elsahel.service && \
pid=$(systemctl --user show -p MainPID --value pet_spot_elsahel.service) && \
tr '\0' '\n' < /proc/"$pid"/environ | grep '^LINKEDIN_JSEARCH_RAPIDAPI_KEY=' | sed 's/=.*/=***masked***/'
```

Expected masked verification line:

```text
LINKEDIN_JSEARCH_RAPIDAPI_KEY=***masked***
```

Also confirm UI: LinkedIn → Settings → **JSearch key loaded from environment** = checked.

## Rollback

```bash
sudo rm -f /etc/petspot/linkedin_jsearch.env
systemctl --user daemon-reload
systemctl --user restart pet_spot_elsahel.service
```

## Explicitly not done in this preflight

- No JSearch HTTP call from this agent
- `live_job_search_enabled` left False
- All four LinkedIn crons forced inactive (XML now `noupdate` + default inactive so upgrades do not re-enable)
- No job import / digest / publish / apply
