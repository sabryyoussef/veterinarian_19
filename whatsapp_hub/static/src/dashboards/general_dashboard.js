/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

export class WhatsappHubGeneralDashboard extends Component {
    static template = "whatsapp_hub.GeneralDashboard";
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
                "get_general_dashboard_data",
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

    openWhatsappDashboard() {
        return this.openAction("whatsapp_hub.action_whatsapp_hub_whatsapp_dashboard");
    }

    onTileClick(ev) {
        const xmlid = ev.currentTarget?.dataset?.actionXmlid;
        if (xmlid && ev.currentTarget?.dataset?.available !== "0") {
            this.openAction(xmlid);
        }
    }

    onQuickClick(ev) {
        const xmlid = ev.currentTarget?.dataset?.actionXmlid;
        if (xmlid) {
            this.openAction(xmlid);
        }
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
    .add("whatsapp_hub_general_dashboard", WhatsappHubGeneralDashboard);
