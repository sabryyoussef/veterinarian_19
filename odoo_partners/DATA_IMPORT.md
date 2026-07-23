# Odoo Partners — data import guidance

- **Categories** load via `data/res_partner_category_data.xml` on install (always).
- **Partner companies** remain in `demo/res_partner_demo.xml` (~3900 records).
  Do **not** enable demo data on the shared PetSpot Enterprise DB.
- For Production/Test directory load: use CSV import or copy a curated subset
  from demo XML into a one-shot data file after dedupe on email/website.
