import { spawnSync } from "child_process";
import * as fs from "fs";
import * as path from "path";
import { fileURLToPath } from "url";
import { TEST_DB } from "./env.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export type ShellStep =
  | "activate_synthetic"
  | "cleanup_synthetic"
  | "pickup_lifecycle"
  | "delivery_lifecycle"
  | "exception_matrix";

export function runShellWorkflow(
  step: ShellStep,
  opts: { runId: string; outPath: string; db?: string } ,
): Record<string, unknown> {
  const db = opts.db || TEST_DB;
  if (db === "pet_spot_elsahel" || (!db.includes("test") && db !== TEST_DB)) {
    throw new Error(
      `BLOCKED_PRODUCTION_SAFETY_GUARD: refusing shell workflow on db=${db}`,
    );
  }

  const conf =
    process.env.PETSPOT_TEST_ODOO_CONF ||
    "/home/sabry/odoo_base/base_odoo_19/config/projects/pet_spot_elsahel_test.conf";
  const bin =
    process.env.PETSPOT_ODOO_BIN ||
    "/home/sabry/odoo_base/base_odoo_19/odoo19/odoo19/odoo-bin";
  const py =
    process.env.PETSPOT_ODOO_PYTHON ||
    "/home/sabry/odoo_base/base_odoo_19/venv19/bin/python3";
  const script = path.join(__dirname, "shell_workflow.py");

  fs.mkdirSync(path.dirname(opts.outPath), { recursive: true });

  const env = {
    ...process.env,
    PETSPOT_PW_STEP: step,
    PETSPOT_PW_RUN_ID: opts.runId,
    PETSPOT_PW_OUT: opts.outPath,
  };

  const result = spawnSync(
    py,
    [bin, "shell", "-c", conf, "-d", db, "--no-http"],
    {
      env,
      input: fs.readFileSync(script),
      encoding: "utf-8",
      maxBuffer: 20 * 1024 * 1024,
      timeout: 300_000,
    },
  );

  if (!fs.existsSync(opts.outPath)) {
    throw new Error(
      `shell workflow produced no output file (status=${result.status}): ${result.stderr?.slice(-2000) || result.stdout?.slice(-2000)}`,
    );
  }
  const payload = JSON.parse(fs.readFileSync(opts.outPath, "utf-8")) as Record<
    string,
    unknown
  >;
  if (!payload.ok) {
    throw new Error(
      `shell step ${step} failed: ${payload.error || JSON.stringify(payload)}`,
    );
  }
  return payload;
}
