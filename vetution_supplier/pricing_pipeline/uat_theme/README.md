# UAT theme containment (theme 190551687449 only)

Applied on unpublished UAT theme `PetSpot Arabic RTL UAT 20260728`.
Live theme `190407639321` must stay unchanged.

## Files added
- `snippets/petspot-pricing-guard.liquid`
- `snippets/petspot-card-price.liquid`
- `sections/petspot-product-grid.liquid` (patched price)
- `sections/petspot-collection-tabs.liquid` (patched price)
- `snippets/petspot-price-unavailable.liquid`
- `snippets/petspot-blocked-variants-boot.liquid`
- `snippets/petspot-jsonld-offer-guard.liquid`
- `assets/petspot-pricing-guard.js`
- `assets/petspot-pricing-guard.css`

## Files patched
- `snippets/price.liquid` — hide LE1 / non-priced; show WhatsApp CTA
- `snippets/product-card.liquid` — mark blocked cards; disable quick-add
- `blocks/buy-buttons.liquid` — hide ATC/Buy for blocked selected variant
- `snippets/add-to-cart-button.liquid` — force disabled when blocked
- `layout/theme.liquid` — load guard assets + boot + JSON-LD guard

## Server-side note
Theme containment does **not** block `POST /cart/add.js`. Remaining purchasable blocked LE1 variants require a Shopify Cart Validation Function / app, or owner-approved inventory/unpublish.

## Homepage LE1 fix (2026-07-31)
Custom PetSpot sections used `{{ product.price | money }}` on `.petspot-product-card__price`, bypassing `snippets/price.liquid`. Replaced with `petspot-card-price` snippet + DOM scrubber.
