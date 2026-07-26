import { expect, test, type Locator, type Page } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const TEST_URL = (
  process.env.ODOO_TEST_URL ||
  process.env.ODOO_URL ||
  "http://127.0.0.1:8028"
).replace(/\/$/, "");
const TEST_DB =
  process.env.ODOO_TEST_DB ||
  process.env.ODOO_DB ||
  "pet_spot_elsahel_test";
const TEST_LOGIN =
  process.env.ODOO_TEST_LOGIN || process.env.ODOO_LOGIN || "admin";
const TEST_PASSWORD =
  process.env.ODOO_TEST_PASSWORD || process.env.ODOO_PASSWORD || "admin";
const SCREENSHOT_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../dev_session_hub/docs/uat/ui_header_fix_20260719",
);

type VisualState = {
  color: string;
  backgroundColor: string;
  opacity: number;
  contrast: number;
  box: { x: number; y: number; width: number; height: number };
};

async function resolveActionId(page: Page, xmlId: string): Promise<number> {
  return page.evaluate(async (fullXmlId) => {
    const [module, name] = fullXmlId.split(".");
    const response = await fetch(
      "/web/dataset/call_kw/ir.model.data/search_read",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          jsonrpc: "2.0",
          method: "call",
          params: {
            model: "ir.model.data",
            method: "search_read",
            args: [
              [
                ["module", "=", module],
                ["name", "=", name],
              ],
              ["res_id"],
            ],
            kwargs: { limit: 1 },
          },
          id: Date.now(),
        }),
      },
    );
    const payload = await response.json();
    const actionId = payload.result?.[0]?.res_id;
    if (!actionId) {
      throw new Error(`Action not found: ${fullXmlId}`);
    }
    return actionId;
  }, xmlId);
}

async function visualState(locator: Locator): Promise<VisualState> {
  return locator.evaluate((element) => {
    type Rgba = { r: number; g: number; b: number; a: number };

    const parseColor = (value: string): Rgba => {
      const parts = value.match(/[\d.]+/g)?.map(Number) || [];
      return {
        r: parts[0] || 0,
        g: parts[1] || 0,
        b: parts[2] || 0,
        a: parts.length > 3 ? parts[3] : 1,
      };
    };
    const composite = (foreground: Rgba, background: Rgba): Rgba => {
      const alpha =
        foreground.a + background.a * (1 - foreground.a);
      if (!alpha) {
        return { r: 0, g: 0, b: 0, a: 0 };
      }
      return {
        r:
          (foreground.r * foreground.a +
            background.r * background.a * (1 - foreground.a)) /
          alpha,
        g:
          (foreground.g * foreground.a +
            background.g * background.a * (1 - foreground.a)) /
          alpha,
        b:
          (foreground.b * foreground.a +
            background.b * background.a * (1 - foreground.a)) /
          alpha,
        a: alpha,
      };
    };
    const luminance = (color: Rgba): number => {
      const channel = (value: number) => {
        const normalized = value / 255;
        return normalized <= 0.03928
          ? normalized / 12.92
          : ((normalized + 0.055) / 1.055) ** 2.4;
      };
      return (
        0.2126 * channel(color.r) +
        0.7152 * channel(color.g) +
        0.0722 * channel(color.b)
      );
    };

    const style = getComputedStyle(element);
    let effectiveBackground: Rgba = { r: 0, g: 0, b: 0, a: 0 };
    let current: Element | null = element;
    while (current && effectiveBackground.a < 0.999) {
      effectiveBackground = composite(
        effectiveBackground,
        parseColor(getComputedStyle(current).backgroundColor),
      );
      current = current.parentElement;
    }
    effectiveBackground = composite(effectiveBackground, {
      r: 255,
      g: 255,
      b: 255,
      a: 1,
    });
    const foreground = parseColor(style.color);
    const foregroundLuminance = luminance(foreground);
    const backgroundLuminance = luminance(effectiveBackground);
    const contrast =
      (Math.max(foregroundLuminance, backgroundLuminance) + 0.05) /
      (Math.min(foregroundLuminance, backgroundLuminance) + 0.05);
    const box = element.getBoundingClientRect();

    return {
      color: style.color,
      backgroundColor: style.backgroundColor,
      opacity: Number(style.opacity),
      contrast,
      box: {
        x: box.x,
        y: box.y,
        width: box.width,
        height: box.height,
      },
    };
  });
}

function expectReadable(state: VisualState): void {
  expect(state.opacity).toBe(1);
  expect(state.contrast).toBeGreaterThanOrEqual(4.5);
  expect(state.box.width).toBeGreaterThan(0);
  expect(state.box.height).toBeGreaterThan(0);
}

function expectSameBox(before: VisualState, after: VisualState): void {
  expect(after.box.width).toBeCloseTo(before.box.width, 1);
  expect(after.box.height).toBeCloseTo(before.box.height, 1);
  expect(after.box.x).toBeCloseTo(before.box.x, 1);
  expect(after.box.y).toBeCloseTo(before.box.y, 1);
}

test("Dev Hub header labels remain readable in every interaction state", async ({
  page,
}) => {
  expect(TEST_DB).toBe("pet_spot_elsahel_test");
  expect(
    TEST_URL.includes("127.0.0.1:8028") ||
      TEST_URL.includes("test.drpaws.ai"),
  ).toBeTruthy();

  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    const text = message.text();
    const isKnownMenuCacheQuotaError =
      text.includes("Error while storing menus in localStorage") &&
      text.includes("QuotaExceededError");
    if (message.type() === "error" && !isKnownMenuCacheQuotaError) {
      consoleErrors.push(message.text());
    }
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${TEST_URL}/web/login?db=${encodeURIComponent(TEST_DB)}`);
  await page.locator('input[name="login"]').fill(TEST_LOGIN);
  await page.locator('input[name="password"]').fill(TEST_PASSWORD);
  await page.getByRole("button", { name: /log in/i }).click();
  await page.waitForSelector(".o_main_navbar", { timeout: 90_000 });

  const dashboardActionId = await resolveActionId(
    page,
    "dev_session_hub.action_dev_dashboard",
  );
  await page.goto(`${TEST_URL}/odoo/action-${dashboardActionId}`);
  await page.waitForSelector(".o_form_view .oe_stat_button", {
    timeout: 90_000,
  });

  const navLinks = page.locator(
    ".o_main_navbar .o_menu_sections a.o_nav_entry:visible",
  );
  expect(await navLinks.count()).toBeGreaterThan(0);
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, "after-normal.png"),
    fullPage: true,
  });

  for (const link of await navLinks.all()) {
    expect((await link.textContent())?.trim()).toBeTruthy();
    const normal = await visualState(link);
    expectReadable(normal);
    expect(normal.backgroundColor).not.toBe("rgb(255, 255, 255)");

    await link.hover();
    const hover = await visualState(link);
    expectReadable(hover);
    expectSameBox(normal, hover);

    const box = await link.boundingBox();
    expect(box).not.toBeNull();
    await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
    await page.mouse.down();
    const active = await visualState(link);
    expectReadable(active);
    expectSameBox(normal, active);
    await page.mouse.move(10, 100);
    await page.mouse.up();
  }

  const recentWorkLink = page
    .locator(".o_main_navbar .o_menu_sections a.o_nav_entry")
    .filter({ hasText: "Recent Work" });
  await recentWorkLink.hover();
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, "after-hover.png"),
    fullPage: true,
  });

  const statButtonLabels = [
    "Recent Work",
    "Active",
    "Paused",
    "Projects",
    "Environments",
    "Machines",
    "Client Warnings",
  ];
  for (const label of statButtonLabels) {
    const button = page.getByRole("button", { name: new RegExp(label, "i") });
    await expect(button).toBeVisible();
    const normal = await visualState(button);
    expectReadable(normal);

    await button.hover();
    const hover = await visualState(button);
    expectReadable(hover);
    expectSameBox(normal, hover);

    const box = await button.boundingBox();
    expect(box).not.toBeNull();
    await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
    await page.mouse.down();
    const active = await visualState(button);
    expectReadable(active);
    expectSameBox(normal, active);
    await page.mouse.move(10, 100);
    await page.mouse.up();
  }

  const contactsActionId = await resolveActionId(page, "contacts.action_contacts");
  await page.goto(`${TEST_URL}/odoo/action-${contactsActionId}`);
  await page.waitForSelector(".o_main_navbar .o_menu_sections", {
    timeout: 90_000,
  });
  const standardNavLinks = page.locator(
    ".o_main_navbar .o_menu_sections a.o_nav_entry:visible",
  );
  for (const link of await standardNavLinks.all()) {
    expectReadable(await visualState(link));
  }

  expect(consoleErrors).toEqual([]);
});
