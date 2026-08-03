/** @odoo-module **/

import { Component, onMounted, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const PERIODS = [
    { value: "all", label: "All Time" },
    { value: "today", label: "Today" },
    { value: "7d", label: "Last 7 Days" },
    { value: "30d", label: "Last 30 Days" },
    { value: "custom", label: "Custom" },
];

const CLASS_OPTIONS = [
    { value: "", label: "All classes" },
    { value: "safe_canary_candidate", label: "Safe canary" },
    { value: "human_required", label: "Human required" },
    { value: "ineligible", label: "Ineligible" },
    { value: "unsupported_ats", label: "Unsupported ATS" },
    { value: "unchecked", label: "Unchecked" },
];

const PLATFORM_OPTIONS = [
    { value: "", label: "All platforms" },
    { value: "company_ats", label: "Company ATS" },
    { value: "lever", label: "Lever" },
    { value: "greenhouse", label: "Greenhouse" },
    { value: "ashby", label: "Ashby" },
    { value: "workable", label: "Workable" },
    { value: "unknown", label: "Unknown" },
];

const APP_STATE_OPTIONS = [
    { value: "", label: "All app states" },
    { value: "discovered", label: "Discovered" },
    { value: "shortlisted", label: "Shortlisted" },
    { value: "pack_ready", label: "Pack Ready" },
    { value: "approved", label: "Approved" },
    { value: "human_required", label: "Human Required" },
    { value: "submission_unknown", label: "Submission Unknown" },
    { value: "applied", label: "Applied" },
];

const ELIGIBILITY_OPTIONS = [
    { value: "", label: "All eligibility" },
    { value: "auto_eligible", label: "Auto eligible" },
    { value: "queued", label: "Queued" },
    { value: "human_required", label: "Human required" },
    { value: "hard_excluded", label: "Hard excluded" },
    { value: "unsupported", label: "Unsupported ATS" },
];

const REFRESH_MS = 5 * 60 * 1000;

export class LinkedinCaughtJobsDashboard extends Component {
    static template = "linkedin_connector.CaughtJobsDashboard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.periods = PERIODS;
        this.classOptions = CLASS_OPTIONS;
        this.platformOptions = PLATFORM_OPTIONS;
        this.appStateOptions = APP_STATE_OPTIONS;
        this.eligibilityOptions = ELIGIBILITY_OPTIONS;

        this.state = useState({
            period: "all",
            dateFrom: "",
            dateTo: "",
            discoveryClass: "",
            platform: "",
            minScore: "0",
            maxScore: "",
            search: "",
            appState: "",
            eligibilityState: "",
            hardExclusionReason: "",
            safeCanaryOnly: false,
            offset: 0,
            limit: 40,
            order: "discovered_at desc",
            loading: true,
            error: null,
            data: null,
            lastRefreshed: null,
        });
        this._timer = null;

        onWillStart(async () => {
            await this.load();
        });
        onMounted(() => {
            this._timer = setInterval(() => this.load({ silent: true }), REFRESH_MS);
        });
        onWillUnmount(() => {
            if (this._timer) {
                clearInterval(this._timer);
                this._timer = null;
            }
        });
    }

    get kpis() {
        return this.state.data?.kpis || {};
    }

    get charts() {
        return this.state.data?.charts || {};
    }

    get table() {
        return this.state.data?.table || { rows: [], total: 0, offset: 0, limit: 40 };
    }

    get periodMeta() {
        return this.state.data?.period || {};
    }

    get pageLabel() {
        const t = this.table;
        if (!t.total) {
            return "0 jobs";
        }
        const start = t.offset + 1;
        const end = Math.min(t.offset + t.limit, t.total);
        return `${start}–${end} of ${t.total}`;
    }

    get canPrev() {
        return this.state.offset > 0;
    }

    get canNext() {
        return this.state.offset + this.state.limit < (this.table.total || 0);
    }

    barWidth(value, series) {
        const max = Math.max(...(series || []).map((s) => s.value || 0), 1);
        return `${Math.max(4, Math.round(((value || 0) / max) * 100))}%`;
    }

    async load({ silent = false } = {}) {
        if (!silent) {
            this.state.loading = true;
        }
        this.state.error = null;
        try {
            if (this.state.period === "custom") {
                if (!this.state.dateFrom || !this.state.dateTo) {
                    this.state.error = "Custom period requires From and To dates.";
                    this.state.loading = false;
                    return;
                }
                if (this.state.dateFrom > this.state.dateTo) {
                    this.state.error = "From date must be on or before To date.";
                    this.state.loading = false;
                    return;
                }
            }
            const minScore = Number(this.state.minScore);
            const maxScoreRaw = this.state.maxScore;
            const maxScore = maxScoreRaw === "" || maxScoreRaw === null || maxScoreRaw === undefined
                ? false
                : Number(maxScoreRaw);
            const data = await this.orm.call(
                "linkedin.caught.jobs.dashboard",
                "get_dashboard_data",
                [],
                {
                    period: this.state.period,
                    date_from: this.state.period === "custom" ? this.state.dateFrom : false,
                    date_to: this.state.period === "custom" ? this.state.dateTo : false,
                    discovery_class: this.state.discoveryClass || false,
                    platform: this.state.platform || false,
                    min_score: Number.isFinite(minScore) ? minScore : 0,
                    max_score: Number.isFinite(maxScore) ? maxScore : false,
                    search: this.state.search || "",
                    app_state: this.state.appState || false,
                    eligibility_state: this.state.eligibilityState || false,
                    hard_exclusion_reason: this.state.hardExclusionReason || false,
                    safe_canary_only: !!this.state.safeCanaryOnly,
                    offset: this.state.offset,
                    limit: this.state.limit,
                    order: this.state.order,
                }
            );
            this.state.data = data;
            this.state.lastRefreshed = data.refreshed_at_display || data.refreshed_at;
        } catch (e) {
            this.state.error = e.message || String(e);
            if (!silent) {
                this.notification.add(this.state.error, { type: "danger" });
            }
        } finally {
            this.state.loading = false;
        }
    }

    async onRefresh() {
        await this.load();
    }

    async onPeriodClick(ev) {
        const period = ev.currentTarget?.dataset?.period;
        if (!period || period === this.state.period) {
            return;
        }
        this.state.period = period;
        this.state.offset = 0;
        await this.load();
    }

    async onFilterChange() {
        this.state.offset = 0;
        await this.load();
    }

    async onSearchSubmit(ev) {
        ev?.preventDefault?.();
        this.state.offset = 0;
        await this.load();
    }

    async onSort(ev) {
        const col = ev.currentTarget?.dataset?.sort;
        if (!col) {
            return;
        }
        const current = this.state.order;
        if (current === `${col} desc`) {
            this.state.order = col;
        } else if (current === col) {
            this.state.order = `${col} desc`;
        } else {
            this.state.order = `${col} desc`;
        }
        this.state.offset = 0;
        await this.load();
    }

    async prevPage() {
        if (!this.canPrev) {
            return;
        }
        this.state.offset = Math.max(0, this.state.offset - this.state.limit);
        await this.load();
    }

    async nextPage() {
        if (!this.canNext) {
            return;
        }
        this.state.offset = this.state.offset + this.state.limit;
        await this.load();
    }

    async openJob(ev) {
        const id = Number(ev.currentTarget?.dataset?.jobId);
        if (!id) {
            return;
        }
        const action = await this.orm.call(
            "linkedin.caught.jobs.dashboard",
            "action_open_job",
            [],
            { job_id: id }
        );
        if (action) {
            await this.action.doAction(action);
        }
    }

    openApplyUrl(ev) {
        ev.stopPropagation();
        const url = ev.currentTarget?.dataset?.url;
        if (url) {
            window.open(url, "_blank", "noopener,noreferrer");
        }
    }

    async openSmart(ev) {
        const key = ev.currentTarget?.dataset?.key;
        if (!key) {
            return;
        }
        const action = await this.orm.call(
            "linkedin.caught.jobs.dashboard",
            "action_open_smart",
            [],
            { key }
        );
        if (action) {
            await this.action.doAction(action);
        }
    }

    classBadge(klass) {
        if (klass === "safe_canary_candidate") {
            return "o_lcj_badge o_lcj_badge_ok";
        }
        if (klass === "human_required") {
            return "o_lcj_badge o_lcj_badge_warn";
        }
        if (klass === "unsupported_ats") {
            return "o_lcj_badge o_lcj_badge_info";
        }
        return "o_lcj_badge";
    }
}

registry.category("actions").add("linkedin_caught_jobs_dashboard", LinkedinCaughtJobsDashboard);
