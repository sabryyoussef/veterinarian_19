/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

export class DevHubWorkflowGuide extends Component {
    static template = "devhub_workflow.WorkflowGuide";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            error: null,
            data: null,
            selectedId: null,
            activeKey: null,
        });
        onWillStart(async () => {
            await this.load();
        });
    }

    get steps() {
        return this.state.data?.steps || [];
    }

    get activeStep() {
        const key = this.state.activeKey || this.state.data?.current_step_key;
        return this.steps.find((s) => s.key === key) || this.steps[0] || null;
    }

    get progressDone() {
        return this.steps.filter((s) => s.status === "done" || s.status === "skipped").length;
    }

    get progressTotal() {
        return this.steps.filter((s) => s.status !== "skipped").length || this.steps.length;
    }

    statusLabel(status) {
        return (
            {
                done: "Done",
                current: "Do this now",
                blocked: "Complete earlier first",
                pending: "Up next",
                skipped: "Not installed",
            }[status] || status
        );
    }

    async load(workItemId = null) {
        this.state.loading = true;
        this.state.error = null;
        try {
            const data = await this.orm.call("dev.workflow.board", "get_walkthrough", [
                workItemId || this.state.selectedId || false,
            ]);
            this.state.data = data;
            this.state.selectedId = data.selected_id || null;
            if (!this.state.activeKey || !data.steps.some((s) => s.key === this.state.activeKey)) {
                this.state.activeKey = data.current_step_key;
            }
        } catch (e) {
            this.state.error = e.message || String(e);
        } finally {
            this.state.loading = false;
        }
    }

    async onSelectWork(ev) {
        const id = Number(ev.target.value || 0) || null;
        this.state.selectedId = id;
        this.state.activeKey = null;
        await this.load(id);
    }

    selectStep(ev) {
        const key = ev.currentTarget?.dataset?.stepKey;
        if (key) {
            this.state.activeKey = key;
        }
    }

    async openStep(step) {
        if (!step?.action) {
            this.notification.add("Nothing to open for this step yet.", { type: "warning" });
            return;
        }
        if (step.status === "blocked" && step.missing?.length) {
            this.notification.add(
                `Complete these first:\n• ${step.missing.join("\n• ")}`,
                { type: "danger" }
            );
        }
        await this.action.doAction(step.action);
    }

    async refresh() {
        await this.load(this.state.selectedId);
    }

    async openActive() {
        await this.openStep(this.activeStep);
    }
}

registry.category("actions").add("devhub_workflow_guide", DevHubWorkflowGuide);
