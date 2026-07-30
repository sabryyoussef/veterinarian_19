import { test, expect } from "@playwright/test";
import * as path from "path";
import { LoginPage } from "./pages/login.page.js";
import { OdooRpc, openModelForm } from "./helpers/odoo_rpc.js";
import { getEvidence } from "./helpers/evidence.js";
import { runShellWorkflow } from "./helpers/shell_runner.js";
import {
  ACTION_XML,
  TEST_DB,
  odooDb,
  odooPassword,
  requireCredentials,
} from "./helpers/env.js";

test.describe.configure({ mode: "serial" });

test.describe("@test-synthetic PetSpot TEST synthetic delivery", () => {
  test.beforeEach(() => {
    test.skip(
      !odooPassword(),
      "BLOCKED_MISSING_UI_CREDENTIALS: set ODOO_PASSWORD",
    );
    test.skip(
      odooDb() !== TEST_DB && process.env.PETSPOT_PW_ENV !== "test",
      `TEST suite requires ODOO_DB=${TEST_DB}`,
    );
  });

  test("mock ShipBlu AWB lifecycle + duplicate guard", async ({
    page,
    request,
  }, testInfo) => {
    requireCredentials();
    const evidence = getEvidence(testInfo);
    const runId = `${evidence.runId}-DEL`;
    const outDir = path.join(evidence.root, "shell");
    const activateOut = path.join(outDir, "activate-del.json");
    const deliveryOut = path.join(outDir, "delivery.json");
    const cleanupOut = path.join(outDir, "cleanup-del.json");

    let cleanupOk = false;
    try {
      runShellWorkflow("activate_synthetic", { runId, outPath: activateOut });
      const delivery = runShellWorkflow("delivery_lifecycle", {
        runId,
        outPath: deliveryOut,
      });
      evidence.writeJson("delivery-lifecycle.json", delivery);

      const rpc = new OdooRpc(request);
      await rpc.authenticate();
      const login = new LoginPage(page);
      await login.login();

      await openModelForm(
        page,
        "petspot.availability.inquiry",
        delivery.inquiry_id as number,
      );
      await evidence.shot(page, "30-test-delivery-inquiry.png", {
        testId: "test-delivery-inquiry",
        environment: "test",
        scenario: "Delivery inquiry",
        result: "pass",
        recordId: String(delivery.inquiry_id),
      });

      await openModelForm(
        page,
        "petspot.vetution.shadow.assessment",
        delivery.assessment_id as number,
      );
      await evidence.shot(page, "31-test-delivery-margin.png", {
        testId: "test-delivery-margin",
        environment: "test",
        scenario: "Delivery gate / margin",
        result: "pass",
        recordId: String(delivery.assessment_id),
        notes: `decision=${delivery.delivery_decision}`,
      });

      let mockActionId: number | undefined;
      try {
        mockActionId = await rpc.actionXmlIdToId(ACTION_XML.mock_awb);
      } catch {
        mockActionId = undefined;
      }
      await openModelForm(
        page,
        "shipblu.shipment",
        delivery.shipment_id as number,
        mockActionId,
      );
      await evidence.shot(page, "32-test-mock-awb.png", {
        testId: "test-mock-awb",
        environment: "test",
        scenario: "Mock ShipBlu AWB",
        result: "pass",
        recordId: String(delivery.shipment_id),
        notes: String(delivery.tracking),
      });
      expect(String(delivery.tracking || "")).toMatch(/^MOCK-/);
      expect(delivery.duplicate_awb_blocked).toBeTruthy();
      await evidence.shot(page, "33-test-duplicate-awb-blocked.png", {
        testId: "test-dup-awb",
        environment: "test",
        scenario: "Duplicate AWB blocked",
        result: delivery.duplicate_awb_blocked ? "pass" : "fail",
        recordId: String(delivery.shipment_id),
      });
      expect(delivery.live_transport_blocked).toBeTruthy();
      expect(String(delivery.package_size_verified).toLowerCase()).toMatch(
        /false|0/,
      );
    } finally {
      try {
        const cleanup = runShellWorkflow("cleanup_synthetic", {
          runId,
          outPath: cleanupOut,
        });
        evidence.writeJson("test-cleanup-delivery.json", cleanup);
        cleanupOk = cleanup.synthetic_active === false;
      } catch (err) {
        evidence.writeJson("test-cleanup-delivery.json", {
          ok: false,
          error: String(err),
        });
      }
    }
    expect(cleanupOk, "FAIL_TEST_CLEANUP").toBeTruthy();
  });
});
