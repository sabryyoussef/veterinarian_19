# UAT section patches (theme 190551687449)

Applied live via Admin `themeFilesUpsert` on 2026-07-31. Live theme untouched. UAT remains unpublished.

## Change
Replace in both files:
```liquid
<p class="petspot-product-card__price">{{ product.price | money }}</p>
```
with:
```liquid
<div class="petspot-product-card__price">{% render 'petspot-card-price', product: product %}</div>
```

## Files
- `sections/petspot-product-grid.liquid`
- `sections/petspot-collection-tabs.liquid`
- `snippets/petspot-card-price.liquid` (new)
- `assets/petspot-pricing-guard.js` (DOM scrubber for leftover LE 1.00)

## Verification
`VISIBLE_LE1_ON_UAT = 0` on preview `?preview_theme_id=190551687449` (Zuoywizzo shows Price unavailable).
