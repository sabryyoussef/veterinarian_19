import { test, expect, request as playwrightRequest } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";
import { fileURLToPath } from "url";
import {
  ODOO_DB,
  authenticateApi,
  callKw,
  assertTestEnvironment,
  loginUi,
} from "./helpers/intake.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(
  __dirname,
  "../../dev_session_hub/docs/uat/phase6_human_merge_20260719",
);
const SHOTS = path.join(ROOT, "screenshots");
const WORKSPACE_ID = Number(process.env.PHASE6_MERGE_WORKSPACE_ID || 0);
type Row = Record<string, any>;
let api: APIRequestContext;

test.skip(!WORKSPACE_ID, "A verified PR-created Merge workspace is required.");

async function gotoWorkspace(page: Page): Promise<void> {
  await page.goto(
    `${process.env.ODOO_TEST_URL}/odoo/dev.execution.workspace/${WORKSPACE_ID}`,
    { waitUntil: "domcontentloaded", timeout: 60_000 },
  );
  await expect(page.locator(".o_form_view, .o_form_sheet").first()).toBeVisible();
}

async function workspace(fields: string[]): Promise<Row> {
  return (
    await callKw<Row[]>(
      api,
      "dev.execution.workspace",
      "read",
      [[WORKSPACE_ID]],
      { fields },
    )
  )[0];
}

async function shot(page: Page, name: string): Promise<void> {
  await page.screenshot({ path: path.join(SHOTS, name), fullPage: true });
}

test.beforeAll(async () => {
  assertTestEnvironment();
  expect(ODOO_DB).toBe("devhub_merge_uat_20260719");
  fs.mkdirSync(SHOTS, { recursive: true, mode: 0o700 });
  api = await playwrightRequest.newContext();
  await authenticateApi(api);
});

test.afterAll(async () => api?.dispose());

test("dedicated merge approval stops before irreversible remote merge", async ({
  page,
}) => {
  const initial = await workspace(["state"]);
  expect(["pr_created_reviewed", "merge_approved"]).toContain(initial.state);
  await loginUi(page);
  await gotoWorkspace(page);
  await shot(page, "01_pr_created_reviewed.png");

  if (initial.state === "pr_created_reviewed") {
    await page.getByRole("button", { name: "Review Merge Eligibility" }).click();
    await expect
      .poll(async () => (await workspace(["merge_head_sha"])).merge_head_sha)
      .toMatch(/^[0-9a-f]{40}$/);
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByRole("tab", { name: "Review Human Merge" }).click();
    await shot(page, "02_merge_eligibility_review.png");

    const reviewed = await workspace([
      "merge_pr_number",
      "merge_pr_url",
      "merge_head_branch",
      "merge_head_sha",
      "merge_base_branch",
      "merge_base_sha",
      "merge_method",
      "merge_checks_summary",
      "merge_requester_id",
      "merge_record_id",
    ]);
    expect(reviewed.merge_pr_number).toBe(2);
    expect(reviewed.merge_pr_url).toBe(
      "https://github.com/sabryyoussef/veterinarian_19/pull/2",
    );
    expect(reviewed.merge_head_branch).toContain("devhub/");
    expect(reviewed.merge_head_sha).toMatch(/^[0-9a-f]{40}$/);
    expect(reviewed.merge_base_branch).toBe("staging");
    expect(reviewed.merge_base_sha).toMatch(/^[0-9a-f]{40}$/);
    expect(reviewed.merge_method).toBe("squash");
    expect(reviewed.merge_checks_summary).toContain(
      "GitGuardian Security Checks",
    );
    expect(reviewed.merge_requester_id).toBeTruthy();
    expect(reviewed.merge_record_id).toBeFalsy();
    await shot(page, "03_exact_pr_head_base_method.png");
    await shot(page, "04_successful_required_checks.png");

    await page
      .getByRole("button", { name: "Approve Exact Squash Merge" })
      .click();
    const dialog = page.locator(".modal-dialog").last();
    await dialog
      .locator(
        '.o_field_widget[name="confirm_exact_merge"] input[type="checkbox"]',
      )
      .check();
    await dialog
      .locator(
        '.o_field_widget[name="confirm_distinct_approval"] input[type="checkbox"]',
      )
      .check();
    await dialog
      .locator(
        '.o_field_widget[name="confirm_no_deployment"] input[type="checkbox"]',
      )
      .check();
    await shot(page, "05_dedicated_administrator_approval.png");
    await dialog
      .getByRole("button", { name: "Approve Exact Squash Merge" })
      .click();
    await expect
      .poll(async () => (await workspace(["state"])).state)
      .toBe("merge_approved");
  }

  await gotoWorkspace(page);
  await page.getByRole("tab", { name: "Review Human Merge" }).click();
  await shot(page, "06_merge_approved_stop_gate.png");
  const approved = await workspace([
    "merge_approval_id",
    "merge_record_id",
    "merge_result_sha",
  ]);
  expect(approved.merge_approval_id).toBeTruthy();
  expect(approved.merge_record_id).toBeFalsy();
  expect(approved.merge_result_sha).toBeFalsy();

  await page.getByRole("button", { name: "Final Merge Confirmation" }).click();
  const finalDialog = page.locator(".modal-dialog").last();
  await expect(
    finalDialog.locator('.o_field_widget[name="confirmation_text"]'),
  ).toContainText(/irreversible/i);
  await shot(page, "07_final_irreversible_confirmation_unchecked.png");
  await finalDialog
    .getByRole("button", { name: "Cancel — Do Not Merge" })
    .click();

  await expect
    .poll(async () => (await workspace(["state"])).state)
    .toBe("merge_approved");
  const stopped = await workspace([
    "merge_record_id",
    "merge_result_sha",
    "merged_at",
  ]);
  expect(stopped.merge_record_id).toBeFalsy();
  expect(stopped.merge_result_sha).toBeFalsy();
  expect(stopped.merged_at).toBeFalsy();
  await shot(page, "08_cancelled_no_remote_merge.png");
  await shot(page, "09_empty_terminal_audit_state.png");
  await expect(page.locator("body")).not.toContainText(
    /ghs_|access_token|authorization:\s*bearer|private key|oauth_token/i,
  );
  await shot(page, "10_credential_safe_stop_gate.png");
});
