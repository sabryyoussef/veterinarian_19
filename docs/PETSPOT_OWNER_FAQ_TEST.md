# PetSpot Owner FAQ — how to test in Odoo

## Ready now (no extra install)

1. Open Odoo: `http://127.0.0.1:8027` (or https://drpaws.ai)
2. Go to **Knowledge**
3. Open workspace article **PetSpot Owner FAQ** (id `73`)
4. You should see **21 child articles** (hours, booking, vaccines, emergency, loyalty, …)
5. Search inside Knowledge for e.g. `تطعيم` or `طوارئ`

Public article URL pattern: https://drpaws.ai/knowledge/article/73

Reload articles anytime:

```bash
cd /home/sabry/odoo_base/base_odoo_19
./venv19/bin/python3 odoo19/odoo19/odoo-bin shell \
  -c config/projects/pet_spot_elsahel.conf \
  -d pet_spot_elsahel --no-http \
  < projects/pet_spot_elsahel/scripts/load_petspot_owner_faq_knowledge.py
```

## Ask AI (needs pgvector)

Articles are linked to **Ask AI** agent as a Knowledge source (status may stay `processing` until embeddings work).

Install once (needs sudo):

```bash
sudo apt-get install -y postgresql-18-pgvector
sudo -u postgres psql -d pet_spot_elsahel -c 'CREATE EXTENSION IF NOT EXISTS vector;'
cd /home/sabry/odoo_base/base_odoo_19
./venv19/bin/python3 odoo19/odoo19/odoo-bin \
  -c config/projects/pet_spot_elsahel.conf \
  -d pet_spot_elsahel -u ai --stop-after-init
# then restart your Odoo 8027 process
```

After that, open **Ask AI** in Odoo and ask: `ازاي أحجز موعد في بيت سبوت؟`

## WhatsApp bot (already live)

Bridge retrieves the same Dify FAQ for FAQ-like messages in the PetSpot group.

Try in the clinic WhatsApp group:

- `مواعيد العيادة؟`
- `تطعيم كلاب`
- `جرومينج`

Booking/exam/status intents are unchanged (`حجز` / `كشف` / `حالة`).
