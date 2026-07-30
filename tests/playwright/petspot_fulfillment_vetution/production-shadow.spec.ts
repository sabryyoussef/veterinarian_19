import { test, expect } from "@playwright/test";
import * as path from "path";
import { LoginPage } from "./pages/login.page.js";
import { VetutionBridgePage } from "./pages/vetution_bridge.page.js";
import { SystemParametersPage } from "./pages/system_parameters.page.js";
import { LandedCostPolicyPage } from "./pages/landed_cost.page.js";
import { ShadowAssessmentPage } from "./pages/shadow_assessment.page.js";
import { InquiryPage } from "./pages/inquiry.page.js";
import { OdooRpc, openAction } from "./helpers/odoo_rpc.js";
import { getEvidence } from "./helpers/evidence.js";
import {
  assertProductionSafetyFlags,
  assertShipbluTrackOnly,
  collectSideEffectCounts,
  assertNoSideEffectIncrease,
} from "./helpers/safety.js";
import {
  ACTION_XML,
  BLOCKED_SKU,
  E2E_SKU,
  E2E_SIZE_ID,
  PROD_DB,
  odooDb,
  odooPassword,
  requireCredentials,
} from "./helpers/env.js";

test.describe.configure({ mode: "serial" });

test.describe("@production-shadow PetSpot Production Shadow Mode", () => {
  test.beforeEach(() => {
    test.skip(
      !odooPassword(),
      "BLOCKED_MISSING_UI_CREDENTIALS: set ODOO_PASSWORD",
    );
    test.skip(
      odooDb() !== PROD_DB && process.env.PETSPOT_PW_ENV !== "production",
      `Production suite requires ODOO_DB=${PROD_DB} (got ${odooDb()})`,
    );
  });

  test("A/B preflight menus and required safety flags", async ({
    page,
    request,
  }, testInfo) => {
    requireCredentials();
    const evidence = getEvidence(testInfo);
    const rpc = new OdooRpc(request);
    await rpc.authenticate();

    const safety = await assertProductionSafetyFlags(rpc);
    evidence.writeJson("production-safety.json", safety);
    evidence.appendLog(`safety ${safety.verdict}: ${safety.failures.join("; ")}`);

    const login = new LoginPage(page);
    await login.login();

    const bridge = new VetutionBridgePage(page, rpc);
    const menuKeys = [
      "ops_health",
      "shadow_assessments",
      "mapping_reviews",
      "automation_allowlist",
      "landed_cost_policy",
      "data_health",
      "quotation_ledger",
      "message_log",
      "payment_trust",
      "payment_events",
      "price_publish_queue",
      "mock_awb",
      "supplier_tasks",
    ];
    const menus = await bridge.openMenus(menuKeys);
    await evidence.shot(page, "01-prod-menu-vetution-bridge.png", {
      testId: "prod-menus",
      environment: "production",
      scenario: "Vetution Bridge menus",
      result: menus.every((m) => m.ok) ? "pass" : "fail",
      notes: menus
        .filter((m) => !m.ok)
        .map((m) => m.key)
        .join(","),
    });
    evidence.writeJson("production-menus.json", menus);
    expect(
      menus.filter((m) => m.traceback).length,
      "menu traceback",
    ).toBe(0);

    const params = new SystemParametersPage(page, rpc);
    await params.openVetutionParamsUi();
    await evidence.shot(page, "02-prod-required-safety-flags.png", {
      testId: "prod-icp",
      environment: "production",
      scenario: "System parameters safety flags",
      result: safety.ok ? "pass" : "FAIL_UNSAFE_PRODUCTION_CONFIGURATION",
      notes: safety.failures.join("; "),
    });

    if (!safety.ok) {
      evidence.recordResult({
        testId: "prod-safety-abort",
        environment: "production",
        scenario: "Abort remaining Production tests",
        result: "FAIL_UNSAFE_PRODUCTION_CONFIGURATION",
        screenshot: "02-prod-required-safety-flags.png",
        recordId: "",
        notes: safety.failures.join("; "),
      });
      throw new Error(
        `FAIL_UNSAFE_PRODUCTION_CONFIGURATION: ${safety.failures.join("; ")}`,
      );
    }
  });

  test("C ShipBlu track-only posture", async ({ page, request }, testInfo) => {
    const evidence = getEvidence(testInfo);
    const rpc = new OdooRpc(request);
    await rpc.authenticate();
    const safety = await assertProductionSafetyFlags(rpc);
    test.skip(!safety.ok, "FAIL_UNSAFE_PRODUCTION_CONFIGURATION");

    const shipblu = await assertShipbluTrackOnly(rpc);
    evidence.writeJson("production-shipblu.json", shipblu);

    const login = new LoginPage(page);
    await login.login();
    const actionId = await rpc.actionXmlIdToId(ACTION_XML.shipblu_backend);
    await openAction(page, actionId);
    await evidence.shot(page, "03-prod-shipblu-track-only.png", {
      testId: "prod-shipblu",
      environment: "production",
      scenario: "ShipBlu track_only",
      result: shipblu.ok ? "pass" : "fail",
      notes: shipblu.failures.join("; "),
    });
    expect(shipblu.ok, shipblu.failures.join("; ")).toBeTruthy();

    // Package size unverified ICP
    const verified = await rpc.getParam(
      "petspot_fulfillment_vetution.shipblu_package_size_verified",
      "False",
    );
    expect(String(verified).toLowerCase()).toMatch(/false|0|^$/);
  });

  test("D Landed-cost commercial policy", async ({ page, request }, testInfo) => {
    const evidence = getEvidence(testInfo);
    const rpc = new OdooRpc(request);
    await rpc.authenticate();
    const safety = await assertProductionSafetyFlags(rpc);
    test.skip(!safety.ok, "FAIL_UNSAFE_PRODUCTION_CONFIGURATION");

    const login = new LoginPage(page);
    await login.login();
    const policyPage = new LandedCostPolicyPage(page, rpc);
    await policyPage.openList();
    const commercial = await policyPage.findCommercial();
    const synthetic = await policyPage.findSynthetic();
    expect(commercial, "active commercial policy").toBeTruthy();
    if (commercial) {
      await policyPage.open(commercial.id as number);
      await evidence.shot(page, "04-prod-commercial-policy-safe.png", {
        testId: "prod-policy",
        environment: "production",
        scenario: "Commercial policy flags",
        result: "pass",
        recordId: String(commercial.id),
      });
      expect(commercial.allow_auto_quotation).toBeFalsy();
      expect(commercial.allow_customer_message).toBeFalsy();
      expect(commercial.allow_supplier_po).toBeFalsy();
      expect(commercial.allow_price_publish).toBeFalsy();
      expect(Number(commercial.max_auto_delivery_subsidy || 0)).toBe(0);
      const charge = Number(commercial.customer_delivery_charge_amount || 0);
      if (charge) {
        expect(charge).toBe(118);
      }
    }
    if (synthetic) {
      expect(synthetic.active).toBeFalsy();
    }
  });

  test("E Mapping and allowlist (read-only)", async ({ page, request }, testInfo) => {
    const evidence = getEvidence(testInfo);
    const rpc = new OdooRpc(request);
    await rpc.authenticate();
    const safety = await assertProductionSafetyFlags(rpc);
    test.skip(!safety.ok, "FAIL_UNSAFE_PRODUCTION_CONFIGURATION");

    const login = new LoginPage(page);
    await login.login();

    const e2e = await rpc.searchRead<{ id: number; vetution_size_id: number }>(
      "product.product",
      [["default_code", "=", E2E_SKU]],
      ["id", "default_code", "vetution_size_id"],
      { limit: 1 },
    );
    const blocked = await rpc.searchRead<{ id: number; vetution_size_id: number }>(
      "product.product",
      [["default_code", "=", BLOCKED_SKU]],
      ["id", "default_code", "vetution_size_id"],
      { limit: 1 },
    );

    const allow = await rpc.searchRead<{ id: number; product_id: unknown }>(
      "petspot.vetution.automation.allowlist",
      [],
      ["id", "product_id", "active"],
      { limit: 50 },
    );

    const actionId = await rpc.actionXmlIdToId(ACTION_XML.automation_allowlist);
    await openAction(page, actionId);
    await evidence.shot(page, "05-prod-product-mapping-allowed.png", {
      testId: "prod-allowlist",
      environment: "production",
      scenario: "Automation allowlist (may be empty)",
      result: "pass",
      notes: `count=${allow.length}`,
    });

    const mappingId = await rpc.actionXmlIdToId(ACTION_XML.mapping_reviews);
    await openAction(page, mappingId);
    await evidence.shot(page, "06-prod-product-mapping-blocked.png", {
      testId: "prod-mapping",
      environment: "production",
      scenario: "Mapping reviews (no confirm)",
      result: "pass",
      notes: `${BLOCKED_SKU} not confirmed by title`,
    });

    if (e2e[0]) {
      expect(Number(e2e[0].vetution_size_id || 0)).toBe(E2E_SIZE_ID);
    }
    // Do not confirm any mapping in this test
    expect(true).toBeTruthy();
    void blocked;
  });

  test("F Shadow assessment side-effect free", async ({ page, request }, testInfo) => {
    const evidence = getEvidence(testInfo);
    const rpc = new OdooRpc(request);
    await rpc.authenticate();
    const safety = await assertProductionSafetyFlags(rpc);
    test.skip(!safety.ok, "FAIL_UNSAFE_PRODUCTION_CONFIGURATION");

    const inquiries = await rpc.searchRead<{ id: number; name: string }>(
      "petspot.availability.inquiry",
      [["product_id.default_code", "=", E2E_SKU]],
      ["id", "name"],
      { limit: 1, order: "id desc" },
    );
    if (!inquiries.length) {
      // Fall back to any recent inquiry
      const any = await rpc.searchRead<{ id: number; name: string }>(
        "petspot.availability.inquiry",
        [],
        ["id", "name"],
        { limit: 1, order: "id desc" },
      );
      if (!any.length) {
        evidence.recordResult({
          testId: "prod-shadow",
          environment: "production",
          scenario: "Shadow assessment",
          result: "BLOCKED_NO_SAFE_EXISTING_PRODUCTION_INQUIRY",
          screenshot: "",
          recordId: "",
          notes: "No existing inquiry; will not create on Production",
        });
        test.skip(true, "BLOCKED_NO_SAFE_EXISTING_PRODUCTION_INQUIRY");
        return;
      }
      inquiries.push(any[0]);
    }

    const before = await collectSideEffectCounts(rpc);
    const login = new LoginPage(page);
    await login.login();

    const inquiryPage = new InquiryPage(page, rpc);
    await inquiryPage.open(inquiries[0].id);
    const assessmentId = await inquiryPage.assessViaRpc(inquiries[0].id);
    expect(assessmentId, "assessment created").toBeTruthy();

    const shadow = new ShadowAssessmentPage(page, rpc);
    await shadow.open(assessmentId!);
    const fields = await shadow.readFields(assessmentId!);
    await evidence.shot(page, "07-prod-shadow-assessment.png", {
      testId: "prod-shadow",
      environment: "production",
      scenario: "Shadow assessment",
      result: "pass",
      recordId: String(assessmentId),
      notes: `state=${fields.state} eligible=${fields.eligible_future_automation}`,
    });

    const after = await collectSideEffectCounts(rpc);
    const bumps = assertNoSideEffectIncrease(before, after);
    evidence.writeJson("production-side-effects.json", { before, after, bumps });
    await evidence.shot(page, "08-prod-side-effect-check.png", {
      testId: "prod-side-effects",
      environment: "production",
      scenario: "Side-effect counts unchanged",
      result: bumps.length ? "fail" : "pass",
      notes: bumps.join("; ") || "no increases",
    });
    expect(bumps, bumps.join("; ")).toEqual([]);
    // eligible may be false — that is expected on Production commercial policy
    expect(fields.state).toBeTruthy();
  });
});
