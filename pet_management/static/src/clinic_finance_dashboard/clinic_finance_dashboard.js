/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const HERO_KEYS = ["net_profit_loss", "revenue_period", "expenses_period"];
const SECONDARY_KEYS = [
    "revenue_today",
    "expenses_today",
    "quick_expenses_period",
    "expenses_month",
];

export class PetClinicFinanceDashboard extends Component {
    static template = "pet_management.ClinicFinanceDashboard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            period: "month",
            loading: true,
            data: null,
            error: null,
        });
        onWillStart(async () => {
            await this.load();
        });
    }

    get performanceCards() {
        return this.state.data?.sections?.performance?.cards || [];
    }

    get heroCards() {
        const byKey = Object.fromEntries(this.performanceCards.map((c) => [c.key, c]));
        return HERO_KEYS.map((key) => byKey[key]).filter(Boolean);
    }

    get secondaryCards() {
        const byKey = Object.fromEntries(this.performanceCards.map((c) => [c.key, c]));
        return SECONDARY_KEYS.map((key) => byKey[key]).filter(Boolean);
    }

    async load() {
        this.state.loading = true;
        this.state.error = null;
        try {
            this.state.data = await this.orm.call("pet.clinic.finance", "get_dashboard_data", [], {
                period: this.state.period,
            });
        } catch (e) {
            this.state.error = e.message || String(e);
        } finally {
            this.state.loading = false;
        }
    }

    async setPeriod(period) {
        if (this.state.period === period) {
            return;
        }
        this.state.period = period;
        await this.load();
    }

    async onPeriodClick(ev) {
        const period = ev.currentTarget?.dataset?.period;
        if (period) {
            await this.setPeriod(period);
        }
    }

    openExpenses() {
        this.action.doAction("pet_management.action_pet_clinic_expense");
    }

    openQuickExpense() {
        this.action.doAction("pet_management.action_pet_clinic_quick_expense");
    }

    formatAmount(amount) {
        const value = Number(amount ?? 0) || 0;
        return value.toLocaleString("en-EG", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    amountClass(amount, kind = "balance") {
        const value = Number(amount || 0);
        if (kind === "partner") {
            return value > 0 ? "o_cf_amount_warn" : "";
        }
        if (kind === "net") {
            if (value > 0) {
                return "o_cf_amount_good";
            }
            if (value < 0) {
                return "o_cf_amount_bad";
            }
            return "";
        }
        if (kind === "flow") {
            return "";
        }
        if (value < 0) {
            return "o_cf_amount_bad";
        }
        return "";
    }
}

registry.category("actions").add("pet_clinic_finance_dashboard", PetClinicFinanceDashboard);
