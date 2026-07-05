# PetSpot El Sahel — Gallery photos

Add **your own** clinic photos here (JPEG/PNG, web-optimized).

| File | Alt text |
|------|----------|
| `clinic-front.jpg` | PetSpot El Sahel clinic front |
| `grooming-area.jpg` | PetSpot grooming area |
| `boarding-area.jpg` | PetSpot boarding area |
| `veterinary-care.jpg` | PetSpot veterinary care |

## Scrape from Facebook

In Odoo: **Social Media Connector → Settings → Scrape Facebook Gallery**, or:

```bash
python3 social_media_connector/scripts/scrape_facebook_gallery.py --max 200
```

Photos are saved under `facebook/` with a `manifest.json`. With default options, the scraper also copies the best matches into the four homepage slot files above.

Do not use third-party stock photos unless you own the rights.

After adding or scraping files, re-run `deploy.py` to upload and refresh the homepage gallery.
