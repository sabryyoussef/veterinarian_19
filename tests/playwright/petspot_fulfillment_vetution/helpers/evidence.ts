import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import type { Page, TestInfo } from "@playwright/test";

export type EvidenceIndexRow = {
  testId: string;
  environment: string;
  scenario: string;
  result: string;
  screenshot: string;
  recordId: string;
  notes: string;
};

export function makeRunId(prefix = "PW-VETUTION"): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  const stamp =
    `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-` +
    `${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
  return `${prefix}-${stamp}`;
}

export function resolveEvidenceRoot(): string {
  if (process.env.PETSPOT_PW_EVIDENCE_DIR) {
    return process.env.PETSPOT_PW_EVIDENCE_DIR;
  }
  const stamp = makeRunId("petspot-playwright-uat").replace("PW-VETUTION-", "");
  // Prefer ~/.cursor/evidence; fallback to repo-ignored path
  const preferred = path.join(os.homedir(), ".cursor", "evidence", stamp);
  try {
    fs.mkdirSync(preferred, { recursive: true });
    return preferred;
  } catch {
    const fallback = path.join(
      process.cwd(),
      "test-results",
      "evidence",
      stamp,
    );
    fs.mkdirSync(fallback, { recursive: true });
    return fallback;
  }
}

export class EvidenceCollector {
  readonly root: string;
  readonly screenshotsDir: string;
  readonly runId: string;
  readonly rows: EvidenceIndexRow[] = [];
  private seq = 0;

  constructor(runId?: string, root?: string) {
    this.runId = runId || makeRunId();
    this.root = root || resolveEvidenceRoot();
    this.screenshotsDir = path.join(this.root, "screenshots");
    for (const sub of [
      "screenshots",
      "traces",
      "videos",
      "playwright-report",
    ]) {
      fs.mkdirSync(path.join(this.root, sub), { recursive: true });
    }
    process.env.PETSPOT_PW_EVIDENCE_DIR = this.root;
    process.env.PETSPOT_PW_RUN_ID = this.runId;
  }

  appendLog(line: string): void {
    const logPath = path.join(this.root, "run.log");
    const masked = line
      .replace(/(password["']?\s*[:=]\s*)(["']?)[^"'&\s]+/gi, "$1$2***MASKED***")
      .replace(/(api[_-]?key|token|secret)(["']?\s*[:=]\s*)(["']?)[^"'&\s]+/gi, "$1$2$3***MASKED***");
    fs.appendFileSync(logPath, `${new Date().toISOString()} ${masked}\n`);
  }

  writeJson(name: string, data: unknown): string {
    const file = path.join(this.root, name);
    fs.writeFileSync(file, JSON.stringify(data, null, 2));
    return file;
  }

  async shot(
    page: Page,
    name: string,
    meta: Partial<EvidenceIndexRow> & { scenario: string; environment: string },
  ): Promise<string> {
    this.seq += 1;
    const fileName = name.endsWith(".png") ? name : `${name}.png`;
    const file = path.join(this.screenshotsDir, fileName);
    try {
      await page.screenshot({
        path: file,
        fullPage: true,
        // Mask common sensitive inputs if present
        mask: [
          page.locator('input[type="password"]'),
          page.locator('input[name="password"]'),
          page.locator(".o_field_phone, input[name='phone']"),
        ],
      });
    } catch (err) {
      this.appendLog(`screenshot_failed ${fileName}: ${String(err)}`);
      // Still index as attempted
    }
    this.rows.push({
      testId: meta.testId || `shot-${this.seq}`,
      environment: meta.environment,
      scenario: meta.scenario,
      result: meta.result || "captured",
      screenshot: fileName,
      recordId: meta.recordId || "",
      notes: meta.notes || "",
    });
    this.flushIndex();
    return file;
  }

  recordResult(row: EvidenceIndexRow): void {
    this.rows.push(row);
    this.flushIndex();
  }

  flushIndex(): void {
    const lines = [
      `# PetSpot Playwright UAT Evidence Index`,
      ``,
      `Run ID: \`${this.runId}\``,
      `Root: \`${this.root}\``,
      ``,
      `| Test ID | Environment | Scenario | Result | Screenshot | Record ID | Notes |`,
      `| ------- | ----------- | -------- | ------ | ---------- | --------- | ----- |`,
      ...this.rows.map(
        (r) =>
          `| ${r.testId} | ${r.environment} | ${r.scenario} | ${r.result} | ${r.screenshot} | ${r.recordId} | ${r.notes} |`,
      ),
      ``,
    ];
    fs.writeFileSync(path.join(this.root, "evidence-index.md"), lines.join("\n"));
  }
}

/** Shared evidence collector for a worker (set in global setup / first import). */
let shared: EvidenceCollector | undefined;

export function getEvidence(testInfo?: TestInfo): EvidenceCollector {
  if (!shared) {
    shared = new EvidenceCollector(
      process.env.PETSPOT_PW_RUN_ID,
      process.env.PETSPOT_PW_EVIDENCE_DIR,
    );
  }
  if (testInfo) {
    shared.appendLog(`test_start ${testInfo.title}`);
  }
  return shared;
}
