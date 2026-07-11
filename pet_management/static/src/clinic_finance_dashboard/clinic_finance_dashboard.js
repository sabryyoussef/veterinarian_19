/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { _t } from "@web/core/l10n/translation";

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

    async onPeriodChange(ev) {
        this.state.period = ev.target.value;
        await this.load();
    }

    openExpenses() {
        this.action.doAction("pet_management.action_pet_clinic_expense");
    }

    openQuickExpense() {
        this.action.doAction("pet_management.action_pet_clinic_quick_expense");
    }

    formatAmount(amount) {
        const value = Number(amount || 0);
        return value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
}

registry.category("actions").add("pet_clinic_finance_dashboard", PetClinicFinanceDashboard);
