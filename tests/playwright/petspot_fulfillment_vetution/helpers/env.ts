/**
 * Environment helpers for PetSpot Fulfillment × Vetution Playwright UAT.
 * Credentials come from env vars only — never commit secrets.
 */

export type PetspotEnvName = "production" | "test";

export function envName(): PetspotEnvName {
  const raw = (process.env.PETSPOT_PW_ENV || process.env.ODOO_DB || "").toLowerCase();
  if (raw.includes("test") || raw === "test") return "test";
  if (process.env.PETSPOT_PW_ENV === "production") return "production";
  // Infer from DB name when set
  const db = process.env.ODOO_DB || "";
  if (db.endsWith("_test") || db === "pet_spot_elsahel_test") return "test";
  return "production";
}

export function odooUrl(): string {
  if (process.env.ODOO_URL) return process.env.ODOO_URL.replace(/\/$/, "");
  return envName() === "test"
    ? "http://127.0.0.1:8028"
    : "http://127.0.0.1:8027";
}

export function odooDb(): string {
  if (process.env.ODOO_DB) return process.env.ODOO_DB;
  return envName() === "test" ? "pet_spot_elsahel_test" : "pet_spot_elsahel";
}

export function odooLogin(): string {
  return (
    process.env.ODOO_LOGIN ||
    process.env.ODOO_TEST_LOGIN ||
    process.env.ODOO_USERNAME ||
    "admin"
  );
}

export function odooPassword(): string {
  return (
    process.env.ODOO_PASSWORD ||
    process.env.ODOO_TEST_PASSWORD ||
    ""
  );
}

export function requireCredentials(): void {
  if (!odooPassword()) {
    throw new Error(
      "BLOCKED_MISSING_UI_CREDENTIALS: set ODOO_PASSWORD (or ODOO_TEST_PASSWORD).",
    );
  }
}

export const PROD_DB = "pet_spot_elsahel";
export const TEST_DB = "pet_spot_elsahel_test";
export const SYNTHETIC_POLICY_NAME = "TEST-SYNTHETIC-E2E-NOT-FOR-COMMERCE";
export const E2E_SKU = "SHP-472-1065";
export const E2E_SIZE_ID = 3975;
export const BLOCKED_SKU = "SHP-139-144";

/** Action XML IDs used for backend navigation (from menu.xml / views). */
export const ACTION_XML: Record<string, string> = {
  shadow_assessments: "petspot_fulfillment_vetution.action_shadow_assessment",
  mapping_reviews: "petspot_fulfillment_vetution.action_mapping_review",
  automation_allowlist: "petspot_fulfillment_vetution.action_automation_allowlist",
  landed_cost_policy: "petspot_fulfillment_vetution.action_landed_cost_policy",
  data_health: "petspot_fulfillment_vetution.action_data_health",
  ops_health: "petspot_fulfillment_vetution.action_ops_health",
  quotation_ledger: "petspot_fulfillment_vetution.action_quotation_ledger",
  message_log: "petspot_fulfillment_vetution.action_message_log",
  payment_events: "petspot_fulfillment_vetution.action_payment_event",
  payment_trust: "petspot_fulfillment_vetution.action_payment_trust",
  price_queue: "petspot_fulfillment_vetution.action_price_queue",
  price_publish_queue: "petspot_fulfillment_vetution.action_price_publish_queue",
  mock_awb: "petspot_fulfillment_vetution.action_mock_awb",
  supplier_tasks: "petspot_fulfillment_vetution.action_supplier_task",
  giza_receipts: "petspot_fulfillment_vetution.action_giza_receipt",
  auto_quote: "petspot_fulfillment_vetution.action_auto_quote",
  shipblu_backend: "petspot_shipblu_base.action_shipblu_backend",
};

export const REQUIRED_PROD_ICPS: Record<string, string> = {
  "petspot_fulfillment_vetution.auto_quote_enabled": "False",
  "petspot_fulfillment_vetution.chatwoot_transport": "mock",
  "petspot_fulfillment_vetution.shopify_publish_transport": "mock",
  "petspot_fulfillment_vetution.shipblu_create_transport": "mock",
  "petspot_fulfillment_vetution.rfq_send_enabled": "False",
  "petspot_fulfillment_vetution.shipblu_package_size_verified": "False",
  "petspot_fulfillment.automation_enabled": "False",
};
