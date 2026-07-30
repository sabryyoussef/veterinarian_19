import type { Page } from "@playwright/test";
import { loginBackend } from "../helpers/odoo_rpc.js";

export class LoginPage {
  constructor(private readonly page: Page) {}

  async login(): Promise<void> {
    await loginBackend(this.page);
  }
}
