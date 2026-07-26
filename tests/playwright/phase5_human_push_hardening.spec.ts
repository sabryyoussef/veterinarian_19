import { test, expect, request as playwrightRequest } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";
import { execFileSync } from "child_process";
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
  "../../dev_session_hub/docs/uat/phase5_human_push_hardening_20260719",
);
const SHOTS = path.join(ROOT, "screenshots");
const SSH = [
  "-o", "BatchMode=yes",
  "-o", "ConnectTimeout=10",
  "-o", "StrictHostKeyChecking=yes",
  "-o", "UserKnownHostsFile=/home/sabry/.ssh/known_hosts.old",
  "sabry3@sabry3-precision-5540.tailcf9988.ts.net",
];
const SUCCESS = 12;
const FAILURE = 13;
type Row = Record<string, any>;
let api: APIRequestContext;

function remote(command: string): string {
  return execFileSync("ssh", [...SSH, command], {
    encoding: "utf8",
    timeout: 120_000,
  }).trim();
}

async function gotoModel(page: Page, model: string, id: number): Promise<void> {
  await page.goto(`${process.env.ODOO_TEST_URL}/odoo/${model}/${id}`, {
    waitUntil: "domcontentloaded",
    timeout: 60_000,
  });
  await expect(page.locator(".o_form_view, .o_form_sheet").first()).toBeVisible({
    timeout: 45_000,
  });
}

async function state(id: number): Promise<string> {
  return (
    await callKw<Row[]>(api, "dev.execution.workspace", "read", [[id]], {
      fields: ["state"],
    })
  )[0].state;
}

async function shot(page: Page, name: string): Promise<void> {
  await page.screenshot({ path: path.join(SHOTS, name), fullPage: true });
}

async function confirmButton(page: Page, name: RegExp): Promise<void> {
  await page.getByRole("button", { name }).first().click();
  const dialog = page.locator(".modal-dialog").last();
  if (await dialog.isVisible({ timeout: 3000 }).catch(() => false)) {
    await dialog.getByRole("button", { name: /Confirm|Ok|Continue/i }).last().click();
  }
}

async function commitWorkspace(page: Page, id: number, label: string): Promise<void> {
  await gotoModel(page, "dev.execution.workspace", id);
  await page.getByRole("button", { name: "Approve Git Commit" }).click();
  await page.getByRole("tab", { name: "Commit Message" }).click();
  await page
    .locator('.o_field_widget[name="commit_message"]:visible textarea')
    .fill(`[DW-${id - 4}] Validate Push hardening ${label} path`);
  await page
    .getByRole("button", { name: /Record Exact-State Commit Approval/i })
    .click();
  await expect.poll(() => state(id), { timeout: 30_000 }).toBe("commit_approved");
  await gotoModel(page, "dev.execution.workspace", id);
  await page.getByRole("button", { name: "Create Approved Commit" }).click();
  await confirmButton(page, /Confirm and Create One Local Commit/i);
  await expect.poll(() => state(id), { timeout: 45_000 }).toBe("committed_reviewed");
}

async function approvePush(page: Page, id: number): Promise<void> {
  await gotoModel(page, "dev.execution.workspace", id);
  await page.getByRole("button", { name: "Review Push Target" }).click();
  await gotoModel(page, "dev.execution.workspace", id);
  await page.getByRole("button", { name: "Approve Git Push" }).click();
  await expect(
    page.locator('.o_field_widget[name="confirmation_text"]:visible').first(),
  ).toContainText(/will not create a PR, merge, or deploy/i);
  await page
    .locator('.o_field_widget[name="confirm_exact_push"]:visible input[type="checkbox"]')
    .check();
  await page.getByRole("button", { name: /Record Exact Push Approval/i }).click();
  await expect.poll(() => state(id), { timeout: 30_000 }).toBe("push_approved");
}

test.beforeAll(async () => {
  assertTestEnvironment();
  expect(ODOO_DB).toBe("devhub_isolation_uat");
  fs.mkdirSync(SHOTS, { recursive: true, mode: 0o700 });
  api = await playwrightRequest.newContext();
  await authenticateApi(api);
});

test.afterAll(async () => api?.dispose());

test("hardened Push succeeds exactly and failed transport stops for review", async ({
  page,
}) => {
  expect(["review_required", "pushed_reviewed"]).toContain(await state(SUCCESS));
  expect(["review_required", "push_approved", "push_failed_review"]).toContain(
    await state(FAILURE),
  );
  const remoteRecord = (
    await callKw<Row[]>(api, "dev.git.remote", "search_read", [
      [["name", "=", "devhub-uat"]],
      ["name", "remote_url", "protocol"],
    ])
  )[0];
  expect(remoteRecord.protocol).toBe("file");
  expect(remoteRecord.remote_url).not.toMatch(/[?#]/);
  expect(remoteRecord.remote_url).not.toMatch(/token|secret|password/i);
  const refsBefore = remote(
    "sudo -u devworker git --git-dir=/srv/devhub-uat/remotes/petspot-human-push-uat.git " +
    "for-each-ref --format='%(refname) %(objectname)' | sort",
  );

  await loginUi(page);
  if ((await state(SUCCESS)) === "review_required") {
    await commitWorkspace(page, SUCCESS, "success");
    await gotoModel(page, "dev.execution.workspace", SUCCESS);
    await page.getByRole("tab", { name: "Review Git Push" }).click();
    await shot(page, "01_safe_push_review.png");
    await approvePush(page, SUCCESS);
    await gotoModel(page, "dev.execution.workspace", SUCCESS);
    await page.getByRole("button", { name: "Push Approved Commit" }).click();
    await page
      .locator('.o_field_widget[name="confirm_push_now"]:visible input[type="checkbox"]')
      .check();
    await shot(page, "02_safe_push_confirmation.png");
    await confirmButton(page, /Confirm and Push One Branch/i);
    await expect.poll(() => state(SUCCESS), { timeout: 60_000 }).toBe(
      "pushed_reviewed",
    );
    await gotoModel(page, "dev.execution.workspace", SUCCESS);
    await page.getByRole("tab", { name: "Review Git Push" }).click();
    await shot(page, "03_safe_push_success.png");
  }

  if ((await state(FAILURE)) === "review_required") {
    await commitWorkspace(page, FAILURE, "failure");
    await approvePush(page, FAILURE);
    await gotoModel(page, "dev.execution.workspace", FAILURE);
    await shot(page, "04_failure_push_approved.png");
  }
  if ((await state(FAILURE)) === "push_approved") {
    remote(
      "sudo -u devworker sh -c \"env HARDENING_FAILURE_WORKSPACE_ID=13 " +
      "/srv/devhub-uat/runtime/venv19/bin/python3 " +
      "/srv/devhub-uat/runtime/odoo19/odoo19/odoo-bin shell " +
      "-c /srv/devhub-uat/config/odoo.conf -d devhub_isolation_uat --no-http " +
      "--log-level=error < /srv/devhub-uat/runtime/addons/dev_session_hub/docs/uat/" +
      "phase5_human_push_hardening_20260719/simulate_transport_failure.py\"",
    );
  }
  await expect.poll(() => state(FAILURE), { timeout: 30_000 }).toBe(
    "push_failed_review",
  );
  await gotoModel(page, "dev.execution.workspace", FAILURE);
  await expect(
    page.getByRole("button", { name: "Review Failed Push State" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Approve Git Push" }),
  ).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText(/access_token|SECRET|password=/i);
  await shot(page, "05_push_failed_review.png");

  const failureWorkspace = (
    await callKw<Row[]>(
      api,
      "dev.execution.workspace",
      "read",
      [[FAILURE]],
      { fields: ["push_record_id"] },
    )
  )[0];
  const failureRecord = (
    await callKw<Row[]>(
      api,
      "dev.git.push.record",
      "read",
      [[failureWorkspace.push_record_id[0]]],
      {
        fields: [
          "reconciliation_state",
          "expected_remote_head",
          "remote_head_after",
          "approved_pre_refs_digest",
          "observed_post_refs_digest",
          "reconciliation_result",
        ],
      },
    )
  )[0];
  expect(failureRecord.reconciliation_state).toBe("push_failed_review");
  expect(failureRecord.expected_remote_head).toMatch(/^[0-9a-f]{40}$/);
  expect(failureRecord.remote_head_after).toBe(false);
  expect(failureRecord.approved_pre_refs_digest).toMatch(/^[0-9a-f]{64}$/);
  expect(failureRecord.observed_post_refs_digest).toMatch(/^[0-9a-f]{64}$/);
  expect(failureRecord.reconciliation_result).toContain("observed absent");
  await gotoModel(page, "dev.git.push.record", failureWorkspace.push_record_id[0]);
  await shot(page, "06_failed_reconciliation_record.png");

  await gotoModel(page, "dev.execution.workspace", FAILURE);
  await page.getByRole("button", { name: "Review Failed Push State" }).click();
  await expect.poll(() => state(FAILURE), { timeout: 30_000 }).toBe(
    "committed_reviewed",
  );
  await gotoModel(page, "dev.execution.workspace", FAILURE);
  await shot(page, "07_human_reconciliation_complete.png");

  const refsAfter = remote(
    "sudo -u devworker git --git-dir=/srv/devhub-uat/remotes/petspot-human-push-uat.git " +
    "for-each-ref --format='%(refname) %(objectname)' | sort",
  );
  const success = (
    await callKw<Row[]>(
      api,
      "dev.execution.workspace",
      "read",
      [[SUCCESS]],
      { fields: ["execution_branch", "committed_sha"] },
    )
  )[0];
  expect(refsAfter).toContain(
    `refs/heads/${success.execution_branch} ${success.committed_sha}`,
  );
  expect(refsAfter).not.toContain("DW-9");
  fs.writeFileSync(
    path.join(ROOT, "sanitized_remote_before_after.txt"),
    `BEFORE\n${refsBefore}\nAFTER\n${refsAfter}\n`,
    { encoding: "utf8", mode: 0o600 },
  );
  fs.writeFileSync(
    path.join(ROOT, "failure_reconciliation.json"),
    JSON.stringify(failureRecord, null, 2) + "\n",
    { encoding: "utf8", mode: 0o600 },
  );
});
