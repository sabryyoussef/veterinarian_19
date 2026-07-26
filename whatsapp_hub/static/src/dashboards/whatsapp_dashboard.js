/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

export class WhatsappHubWhatsappDashboard extends Component {
    static template = "whatsapp_hub.WhatsappDashboard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
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
            this.state.data = await this.orm.call(
                "whatsapp.hub.dashboard",
                "get_whatsapp_dashboard_data",
                []
            );
        } catch (e) {
            this.state.error = e.message || String(e);
        } finally {
            this.state.loading = false;
        }
    }

    async openAction(xmlid) {
        if (!xmlid) {
            return;
        }
        try {
            await this.action.doAction(xmlid);
        } catch (e) {
            this.notification.add(e.message || String(e), { type: "danger" });
        }
    }

    openGeneral() {
        return this.openAction("whatsapp_hub.action_whatsapp_hub_general_dashboard");
    }

    onActionClick(ev) {
        const xmlid = ev.currentTarget?.dataset?.actionXmlid;
        if (xmlid) {
            this.openAction(xmlid);
        }
    }

    openMessage(ev) {
        const id = Number(ev.currentTarget?.dataset?.id || 0);
        if (!id) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "whatsapp.message",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    toneClass(tone) {
        if (tone === "warn") {
            return "o_wa_tone_warn";
        }
        if (tone === "bad") {
            return "o_wa_tone_bad";
        }
        return "o_wa_tone_ok";
    }
}

registry
    .category("actions")
    .add("whatsapp_hub_whatsapp_dashboard", WhatsappHubWhatsappDashboard);
