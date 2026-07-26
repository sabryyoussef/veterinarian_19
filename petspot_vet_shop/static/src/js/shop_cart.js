/** @odoo-module **/

// Cart UX helpers — commercial warnings are rendered server-side on /shop/cart.
// Kept as a real named export so the Odoo asset bundler does not emit a bare
// `export {}` into the classic AMD wrapper (which SyntaxErrors the whole
// web.assets_frontend_lazy bundle and kills every public widget).
export const PetspotCartHelpers = {};
