/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const DATE_PRESETS = [
    { id: "today", label: "Today" },
    { id: "7d", label: "Last 7 days" },
    { id: "30d", label: "Last 30 days" },
    { id: "all", label: "All dates" },
];

function pad2(n) {
    return String(n).padStart(2, "0");
}

/** Local datetime → Odoo-friendly string (user TZ wall clock). */
function toOdooDatetime(d) {
    return (
        `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ` +
        `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`
    );
}

function startOfLocalDay(d = new Date()) {
    const x = new Date(d);
    x.setHours(0, 0, 0, 0);
    return x;
}

function endOfLocalDay(d = new Date()) {
    const x = new Date(d);
    x.setHours(23, 59, 59, 0);
    return x;
}

function rangeForPreset(preset) {
    if (!preset || preset === "all") {
        return { date_from: false, date_to: false };
    }
    const end = endOfLocalDay();
    if (preset === "today") {
        return { date_from: toOdooDatetime(startOfLocalDay()), date_to: toOdooDatetime(end) };
    }
    const days = preset === "30d" ? 29 : 6; // inclusive window ending today
    const start = startOfLocalDay();
    start.setDate(start.getDate() - days);
    return { date_from: toOdooDatetime(start), date_to: toOdooDatetime(end) };
}

function parseTs(ts) {
    if (!ts) {
        return null;
    }
    // Odoo may send "YYYY-MM-DD HH:MM:SS" — normalize for Date
    const raw = String(ts).includes("T") ? String(ts) : String(ts).replace(" ", "T");
    const d = new Date(raw);
    return Number.isNaN(d.getTime()) ? null : d;
}

function dateKeyFromTs(ts) {
    const d = parseTs(ts);
    if (!d) {
        return "unknown";
    }
    return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

function dateLabelFromTs(ts) {
    const d = parseTs(ts);
    if (!d) {
        return "Unknown date";
    }
    const today = startOfLocalDay();
    const that = startOfLocalDay(d);
    const diffDays = Math.round((today - that) / 86400000);
    if (diffDays === 0) {
        return "Today";
    }
    if (diffDays === 1) {
        return "Yesterday";
    }
    return d.toLocaleDateString(undefined, {
        weekday: "short",
        day: "numeric",
        month: "short",
        year: "numeric",
    });
}

export class DevhubWhatsappWorkInbox extends Component {
    static template = "devhub_whatsapp.WorkInbox";
    static props = {
        ...standardActionServiceProps,
        focusMessageId: { type: [Number, Boolean], optional: true },
        highlightMessageIds: { type: Array, optional: true },
        conversationId: { type: [Number, Boolean], optional: true },
    };

    static extractProps(action) {
        const params = action.params || {};
        const ctx = action.context || {};
        return {
            focusMessageId:
                params.focus_message_id ||
                ctx.focus_message_id ||
                ctx.active_id ||
                false,
            highlightMessageIds:
                params.highlight_message_ids || ctx.highlight_message_ids || [],
            conversationId: params.conversation_id || ctx.conversation_id || false,
        };
    }

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.datePresets = DATE_PRESETS;
        const focusId = this.props.focusMessageId || false;
        const openConv = this.props.conversationId || false;
        const datePreset = "today";
        const range = rangeForPreset(datePreset);
        this.state = useState({
            loadingInbox: true,
            loadingChildren: false,
            loadingContext: false,
            error: null,
            datePreset,
            filters: {
                inbox_state: "default",
                date_from: range.date_from || undefined,
                date_to: range.date_to || undefined,
            },
            conversations: [],
            expandedKey: openConv ? String(openConv) : false,
            expandedGroupJid: false,
            expandedConversationId: openConv || false,
            childRows: [],
            childCursor: false,
            counters: {},
            selectedId: focusId || false,
            highlightIds: new Set(this.props.highlightMessageIds || []),
            context: null,
            selectedContextIds: new Set(focusId ? [focusId] : []),
            primaryId: focusId || false,
            rightTab: "chat",
            groupAnalyses: [],
            loadingAnalyses: false,
            analysingAll: false,
            analysingGroup: false,
        });
        onWillStart(async () => {
            await this.reloadTree();
            if (focusId && !this.state.expandedKey) {
                try {
                    const rows = await this.orm.read("whatsapp.message", [focusId], [
                        "conversation_id",
                        "group_jid",
                    ]);
                    const cid = rows?.[0]?.conversation_id?.[0];
                    const gj = rows?.[0]?.group_jid || "";
                    if (gj || cid) {
                        this.state.expandedGroupJid = gj || false;
                        this.state.expandedConversationId = cid || false;
                        this.state.expandedKey = gj || String(cid);
                    }
                } catch (e) {
                    /* ignore */
                }
            }
            if (this.state.expandedKey) {
                await this.loadConversationMessages(false);
            }
            if (this.state.selectedId) {
                await this.loadContext(this.state.selectedId);
            }
        });
    }

    /** RPC filters: strip empty date keys. */
    rpcFilters() {
        const f = { ...this.state.filters };
        if (!f.date_from) {
            delete f.date_from;
        }
        if (!f.date_to) {
            delete f.date_to;
        }
        return f;
    }

    get childSections() {
        const sections = [];
        let current = null;
        for (const row of this.state.childRows) {
            const key = dateKeyFromTs(row.message_timestamp);
            if (!current || current.key !== key) {
                current = {
                    key,
                    label: dateLabelFromTs(row.message_timestamp),
                    rows: [],
                };
                sections.push(current);
            }
            current.rows.push(row);
        }
        return sections;
    }

    convKey(conv) {
        return conv.group_jid || String(conv.conversation_id);
    }

    isExpandedKey(key) {
        return this.state.expandedKey === key;
    }

    async reloadTree() {
        this.state.loadingInbox = true;
        this.state.error = null;
        try {
            const result = await this.orm.call(
                "whatsapp.message",
                "get_work_inbox_conversations",
                [],
                { filters: this.rpcFilters(), limit: 100 }
            );
            this.state.conversations = result.conversations || [];
            this.state.counters = result.counters || {};
            if (this.state.expandedKey) {
                const still = this.state.conversations.some(
                    (c) => this.convKey(c) === this.state.expandedKey
                );
                if (still) {
                    await this.loadConversationMessages(false);
                } else {
                    this.state.expandedKey = false;
                    this.state.expandedGroupJid = false;
                    this.state.expandedConversationId = false;
                    this.state.childRows = [];
                    this.state.childCursor = false;
                }
            }
        } catch (e) {
            this.state.error = e.message || String(e);
        } finally {
            this.state.loadingInbox = false;
        }
    }

    async setFilter(state) {
        this.state.filters = { ...this.state.filters, inbox_state: state };
        this.state.expandedKey = false;
        this.state.expandedGroupJid = false;
        this.state.expandedConversationId = false;
        this.state.childRows = [];
        this.state.childCursor = false;
        this.state.context = null;
        this.state.selectedId = false;
        this.state.selectedContextIds = new Set();
        await this.reloadTree();
    }

    onFilterClick(ev) {
        const state = ev.currentTarget?.dataset?.state;
        if (state) {
            this.setFilter(state);
        }
    }

    async setDatePreset(preset) {
        const range = rangeForPreset(preset);
        this.state.datePreset = preset;
        this.state.filters = {
            ...this.state.filters,
            date_from: range.date_from || undefined,
            date_to: range.date_to || undefined,
        };
        this.state.expandedKey = false;
        this.state.expandedGroupJid = false;
        this.state.expandedConversationId = false;
        this.state.childRows = [];
        this.state.childCursor = false;
        this.state.context = null;
        this.state.selectedId = false;
        this.state.selectedContextIds = new Set();
        await this.reloadTree();
    }

    onDatePresetClick(ev) {
        const preset = ev.currentTarget?.dataset?.preset;
        if (preset) {
            this.setDatePreset(preset);
        }
    }

    async toggleConversation(ev) {
        const cid = Number(ev.currentTarget?.dataset?.conversationId || 0);
        const gj = ev.currentTarget?.dataset?.groupJid || "";
        const key = gj || String(cid);
        if (!key || key === "0") {
            return;
        }
        if (this.state.expandedKey === key) {
            this.state.expandedKey = false;
            this.state.expandedGroupJid = false;
            this.state.expandedConversationId = false;
            this.state.childRows = [];
            this.state.childCursor = false;
            return;
        }
        this.state.expandedKey = key;
        this.state.expandedGroupJid = gj || false;
        this.state.expandedConversationId = cid || false;
        this.state.context = null;
        this.state.selectedId = false;
        await this.loadConversationMessages(false);
        if (gj) {
            await this.loadGroupAnalyses();
        }
    }

    onRightTabClick(ev) {
        const tab = ev.currentTarget?.dataset?.tab;
        if (tab === "chat" || tab === "ai") {
            this.setRightTab(tab);
        }
    }

    setRightTab(tab) {
        this.state.rightTab = tab;
        if (tab === "ai" && this.state.expandedGroupJid) {
            this.loadGroupAnalyses();
        }
    }

    async loadGroupAnalyses() {
        const gj = this.state.expandedGroupJid;
        if (!gj) {
            this.state.groupAnalyses = [];
            return;
        }
        this.state.loadingAnalyses = true;
        try {
            const res = await this.orm.call(
                "dev.whatsapp.analysis",
                "get_group_analyses_payload",
                [gj],
                { limit: 20 }
            );
            this.state.groupAnalyses = res.analyses || [];
        } catch (e) {
            this.notification.add(e.message || String(e), { type: "danger" });
            this.state.groupAnalyses = [];
        } finally {
            this.state.loadingAnalyses = false;
        }
    }

    dateFilterKwargs() {
        const f = this.rpcFilters();
        return {
            date_from: f.date_from || false,
            date_to: f.date_to || false,
        };
    }

    async analyseExpandedGroup() {
        const gj = this.state.expandedGroupJid;
        if (!gj) {
            this.notification.add("Expand a group first.", { type: "warning" });
            return;
        }
        this.state.analysingGroup = true;
        try {
            const analysis = await this.orm.call(
                "dev.whatsapp.analysis",
                "action_enqueue_by_group_jid",
                [gj],
                { force: true, ...this.dateFilterKwargs() }
            );
            const aid = Array.isArray(analysis)
                ? analysis[0]
                : analysis?.id || analysis;
            this.notification.add(`Analysis queued (#${aid}).`, {
                type: "success",
            });
            this.state.rightTab = "ai";
            await this.reloadTree();
            await this.loadGroupAnalyses();
        } catch (e) {
            this.notification.add(e.message || String(e), { type: "danger" });
        } finally {
            this.state.analysingGroup = false;
        }
    }

    async analyseAllGroups() {
        this.state.analysingAll = true;
        try {
            const res = await this.orm.call(
                "dev.whatsapp.analysis",
                "action_enqueue_all_enabled_sources",
                [],
                this.dateFilterKwargs()
            );
            const n = (res.created || []).length;
            const s = (res.skipped || []).length;
            this.notification.add(
                `Queued ${n} group analysis job(s); skipped ${s}. Uses current Dates filter.`,
                { type: n ? "success" : "warning" }
            );
            await this.reloadTree();
            if (this.state.expandedGroupJid) {
                this.state.rightTab = "ai";
                await this.loadGroupAnalyses();
            }
        } catch (e) {
            this.notification.add(e.message || String(e), { type: "danger" });
        } finally {
            this.state.analysingAll = false;
        }
    }

    async onAiBadgeClick(ev) {
        ev.stopPropagation();
        const gj = ev.currentTarget?.dataset?.groupJid || "";
        if (!gj) {
            return;
        }
        const conv = this.state.conversations.find((c) => c.group_jid === gj);
        if (conv) {
            this.state.expandedKey = this.convKey(conv);
            this.state.expandedGroupJid = gj;
            this.state.expandedConversationId = conv.conversation_id;
            await this.loadConversationMessages(false);
        }
        this.state.rightTab = "ai";
        await this.loadGroupAnalyses();
    }

    async openAnalysisForm(ev) {
        const id = Number(ev.currentTarget?.dataset?.id || 0);
        if (!id) {
            return;
        }
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "dev.whatsapp.analysis",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async approveIgnoreAnalysis(ev) {
        const id = Number(ev.currentTarget?.dataset?.id || 0);
        if (!id) {
            return;
        }
        try {
            await this.orm.call("dev.whatsapp.analysis", "action_approve_ignore", [
                [id],
            ]);
            this.notification.add("Ignore applied.", { type: "success" });
            await this.reloadTree();
            await this.loadGroupAnalyses();
        } catch (e) {
            this.notification.add(e.message || String(e), { type: "danger" });
        }
    }

    async approveCreateWorkAnalysis(ev) {
        const id = Number(ev.currentTarget?.dataset?.id || 0);
        if (!id) {
            return;
        }
        try {
            const action = await this.orm.call(
                "dev.whatsapp.analysis",
                "action_approve_create_work",
                [[id]]
            );
            await this.reloadTree();
            await this.loadGroupAnalyses();
            if (action) {
                await this.action.doAction(action);
            }
        } catch (e) {
            this.notification.add(e.message || String(e), { type: "danger" });
        }
    }

    async applyDemoAnalysis(ev) {
        const id = Number(ev.currentTarget?.dataset?.id || 0);
        if (!id) {
            return;
        }
        try {
            await this.orm.call("dev.whatsapp.analysis", "action_apply_demo_result", [
                [id],
            ]);
            this.notification.add(
                "Demo AI result applied — review and Approve & Create Work.",
                { type: "success" }
            );
            await this.reloadTree();
            await this.loadGroupAnalyses();
        } catch (e) {
            this.notification.add(e.message || String(e), { type: "danger" });
        }
    }

    async loadConversationMessages(append = false) {
        this.state.loadingChildren = true;
        try {
            const filters = { ...this.rpcFilters() };
            if (this.state.expandedGroupJid) {
                filters.group_jid = this.state.expandedGroupJid;
            } else if (this.state.expandedConversationId) {
                filters.conversation_id = this.state.expandedConversationId;
            }
            const result = await this.orm.call(
                "whatsapp.message",
                "get_work_inbox_rows",
                [],
                {
                    filters,
                    cursor: append ? this.state.childCursor : null,
                    limit: 50,
                }
            );
            const incoming = result.rows || [];
            if (append) {
                const seen = new Set(this.state.childRows.map((r) => r.id));
                this.state.childRows = [
                    ...this.state.childRows,
                    ...incoming.filter((r) => !seen.has(r.id)),
                ];
            } else {
                const seen = new Set();
                this.state.childRows = incoming.filter((r) => {
                    if (seen.has(r.id)) {
                        return false;
                    }
                    seen.add(r.id);
                    return true;
                });
            }
            this.state.childCursor = result.next_cursor || false;
        } catch (e) {
            this.notification.add(e.message || String(e), { type: "danger" });
        } finally {
            this.state.loadingChildren = false;
        }
    }

    async loadMoreChildren() {
        if (!this.state.expandedKey || !this.state.childCursor) {
            return;
        }
        await this.loadConversationMessages(true);
    }

    async selectRow(ev) {
        const id = Number(ev.currentTarget?.dataset?.id || 0);
        if (!id) {
            return;
        }
        this.state.selectedId = id;
        this.state.primaryId = id;
        this.state.selectedContextIds = new Set([id]);
        this.state.rightTab = "chat";
        await this.loadContext(id);
    }

    async loadContext(messageId) {
        this.state.loadingContext = true;
        try {
            // Chat context stays full conversation window (not date-clipped).
            this.state.context = await this.orm.call(
                "whatsapp.message",
                "get_inbox_context",
                [messageId],
                { before: 20, after: 20 }
            );
        } catch (e) {
            this.notification.add(e.message || String(e), { type: "danger" });
        } finally {
            this.state.loadingContext = false;
        }
    }

    async loadOlder() {
        const ctx = this.state.context;
        if (!ctx?.older_cursor) {
            return;
        }
        const res = await this.orm.call("whatsapp.message", "load_inbox_context_older", [
            ctx.conversation_id,
            ctx.older_cursor,
            20,
        ]);
        const seen = new Set((ctx.messages || []).map((m) => m.id));
        const older = (res.messages || []).filter((m) => !seen.has(m.id));
        this.state.context = {
            ...ctx,
            messages: [...older, ...(ctx.messages || [])],
            has_older: res.has_older,
            older_cursor: res.older_cursor,
        };
    }

    async loadNewer() {
        const ctx = this.state.context;
        if (!ctx?.newer_cursor) {
            return;
        }
        const res = await this.orm.call("whatsapp.message", "load_inbox_context_newer", [
            ctx.conversation_id,
            ctx.newer_cursor,
            20,
        ]);
        const seen = new Set((ctx.messages || []).map((m) => m.id));
        const newer = (res.messages || []).filter((m) => !seen.has(m.id));
        this.state.context = {
            ...ctx,
            messages: [...(ctx.messages || []), ...newer],
            has_newer: res.has_newer,
            newer_cursor: res.newer_cursor,
        };
    }

    toggleContextSelect(ev) {
        const id = Number(ev.currentTarget?.dataset?.id || 0);
        if (!id) {
            return;
        }
        const set = new Set(this.state.selectedContextIds);
        if (set.has(id)) {
            set.delete(id);
        } else {
            set.add(id);
        }
        this.state.selectedContextIds = set;
        if (!this.state.primaryId || !set.has(this.state.primaryId)) {
            this.state.primaryId = [...set][0] || false;
        }
    }

    isSelected(id) {
        return this.state.selectedContextIds.has(id);
    }

    isHighlight(id) {
        return this.state.highlightIds.has(id) || id === this.state.selectedId;
    }

    isFocus(id) {
        return id === this.state.selectedId;
    }

    selectedIds() {
        return [...this.state.selectedContextIds];
    }

    async callState(method) {
        let ids = this.selectedIds();
        if (!ids.length && this.state.selectedId) {
            ids = [this.state.selectedId];
        }
        if (!ids.length) {
            this.notification.add("Select at least one message.", { type: "warning" });
            return;
        }
        try {
            await this.orm.call("whatsapp.message", method, [ids]);
            await this.reloadTree();
            if (this.state.selectedId) {
                await this.loadContext(this.state.selectedId);
            }
        } catch (e) {
            this.notification.add(e.message || String(e), { type: "danger" });
        }
    }

    ignoreSelected() {
        return this.callState("action_inbox_ignore");
    }
    restoreSelected() {
        return this.callState("action_inbox_restore");
    }
    pendingSelected() {
        return this.callState("action_inbox_set_pending");
    }
    actionedSelected() {
        return this.callState("action_inbox_set_actioned");
    }
    addToInboxSelected() {
        return this.callState("action_inbox_add");
    }

    async openCreateWork() {
        const ids = this.selectedIds();
        if (!ids.length) {
            this.notification.add("Select messages in the chat (checkboxes).", {
                type: "warning",
            });
            return;
        }
        try {
            const action = await this.orm.call(
                "whatsapp.message",
                "action_open_create_work_wizard",
                [ids]
            );
            await this.action.doAction(action);
        } catch (e) {
            this.notification.add(e.message || String(e), { type: "danger" });
        }
    }

    async openWork(ev) {
        const id = Number(ev.currentTarget?.dataset?.workId || 0);
        if (!id) {
            return;
        }
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "dev.work.item",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("devhub_whatsapp_work_inbox", DevhubWhatsappWorkInbox);
