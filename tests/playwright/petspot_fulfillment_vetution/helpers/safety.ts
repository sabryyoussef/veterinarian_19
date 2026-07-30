import { expect } from "@playwright/test";
import type { OdooRpc } from "./odoo_rpc.js";
import {
  PROD_DB,
  REQUIRED_PROD_ICPS,
  TEST_DB,
} from "./env.js";

export type SafetySnapshot = {
  ok: boolean;
  verdict?: string;
  icps: Record<string, string>;
  failures: string[];
  synthetic_allowed_dbs: string;
  production_db_in_synthetic_allowlist: boolean;
};

/**
 * Assert Production safety flags. Never mutates anything.
 * On failure: caller must stop Production tests and report FAIL_UNSAFE_PRODUCTION_CONFIGURATION.
 */
export async function assertProductionSafetyFlags(
  rpc: OdooRpc,
): Promise<SafetySnapshot> {
  const icps: Record<string, string> = {};
  const failures: string[] = [];

  for (const [key, expected] of Object.entries(REQUIRED_PROD_ICPS)) {
    const raw = await rpc.getParam(key, "");
    const normalized = normalizeFlag(raw);
    const expectedNorm = normalizeFlag(expected);
    icps[key] = raw;
    if (normalized !== expectedNorm) {
      failures.push(`${key}=${raw || "(empty)"} (expected ${expected})`);
    }
  }

  const synthetic = await rpc.getParam(
    "petspot_fulfillment_vetution.synthetic_policy_allowed_dbs",
    "",
  );
  icps["petspot_fulfillment_vetution.synthetic_policy_allowed_dbs"] = synthetic;
  const allowed = synthetic
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const prodInList = allowed.includes(PROD_DB);
  if (prodInList) {
    failures.push(
      `synthetic_policy_allowed_dbs includes Production DB ${PROD_DB}`,
    );
  }
  if (!allowed.includes(TEST_DB) && allowed.length > 0) {
    // Soft note — Production may list only TEST; empty would also be unsafe for TEST but OK for prod shadow
  }
  if (!allowed.includes(TEST_DB)) {
    failures.push(
      `synthetic_policy_allowed_dbs must include ${TEST_DB} (got: ${synthetic || "(empty)"})`,
    );
  }

  const ok = failures.length === 0;
  return {
    ok,
    verdict: ok ? "SAFE" : "FAIL_UNSAFE_PRODUCTION_CONFIGURATION",
    icps,
    failures,
    synthetic_allowed_dbs: synthetic,
    production_db_in_synthetic_allowlist: prodInList,
  };
}

function normalizeFlag(v: string): string {
  const s = String(v ?? "").trim().toLowerCase();
  if (s === "0" || s === "false" || s === "") return "false";
  if (s === "1" || s === "true") return "true";
  return s;
}

export async function assertShipbluTrackOnly(rpc: OdooRpc): Promise<{
  ok: boolean;
  backends: Record<string, unknown>[];
  failures: string[];
}> {
  const backends = await rpc.searchRead<Record<string, unknown>>(
    "shipblu.backend",
    [],
    [
      "id",
      "name",
      "shipping_owner_mode",
      "shipment_creation_enabled",
      "enable_pickup_automation",
      "default_zone_id",
      "default_package_size",
    ],
    { limit: 5 },
  );
  const failures: string[] = [];
  if (!backends.length) {
    failures.push("No shipblu.backend row found");
  }
  for (const b of backends) {
    const mode = String(b.shipping_owner_mode || "");
    if (mode !== "track_only") {
      failures.push(
        `backend ${b.id}: shipping_owner_mode=${mode} (expected track_only)`,
      );
    }
    if (b.shipment_creation_enabled) {
      failures.push(`backend ${b.id}: shipment_creation_enabled is True`);
    }
    if (b.enable_pickup_automation) {
      failures.push(`backend ${b.id}: enable_pickup_automation is True`);
    }
  }
  return { ok: failures.length === 0, backends, failures };
}

export type SideEffectCounts = {
  sale_order: number;
  purchase_order: number;
  account_payment: number;
  stock_picking: number;
  shipblu_shipment: number;
  message_log: number;
  price_publish: number;
};

export async function collectSideEffectCounts(
  rpc: OdooRpc,
): Promise<SideEffectCounts> {
  const safeCount = async (model: string, domain: unknown[] = []) => {
    try {
      return await rpc.searchCount(model, domain);
    } catch {
      return -1;
    }
  };
  return {
    sale_order: await safeCount("sale.order"),
    purchase_order: await safeCount("purchase.order"),
    account_payment: await safeCount("account.payment"),
    stock_picking: await safeCount("stock.picking"),
    shipblu_shipment: await safeCount("shipblu.shipment"),
    message_log: await safeCount("petspot.vetution.message.log"),
    price_publish: await safeCount("petspot.vetution.price.publish.queue"),
  };
}

export function assertNoSideEffectIncrease(
  before: SideEffectCounts,
  after: SideEffectCounts,
): string[] {
  const failures: string[] = [];
  for (const key of Object.keys(before) as (keyof SideEffectCounts)[]) {
    if (before[key] < 0 || after[key] < 0) continue;
    if (after[key] > before[key]) {
      failures.push(`${key}: ${before[key]} -> ${after[key]}`);
    }
  }
  return failures;
}

export function expectSafetyOrThrow(snap: SafetySnapshot): void {
  expect(
    snap.ok,
    `FAIL_UNSAFE_PRODUCTION_CONFIGURATION: ${snap.failures.join("; ")}`,
  ).toBeTruthy();
}
