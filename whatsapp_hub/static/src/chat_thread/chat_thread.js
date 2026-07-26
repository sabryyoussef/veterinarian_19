/** @odoo-module **/

import { Component, onMounted, onWillStart, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const MEDIA_ICONS = {
    image: "fa-image",
    video: "fa-video-camera",
    audio: "fa-microphone",
    document: "fa-file-o",
    sticker: "fa-smile-o",
    reaction: "fa-heart-o",
    unknown: "fa-paperclip",
};

export class WhatsappHubConversationChat extends Component {
    static template = "whatsapp_hub.ConversationChat";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.threadRef = useRef("thread");
        const ctx = this.props.action?.context || {};
        this.conversationId =
            Number(ctx.conversation_id || ctx.active_id || 0) || 0;
        this.state = useState({
            loading: true,
            loadingOlder: false,
            error: null,
            conversationName: "",
            conversationType: "",
            remoteJid: "",
            groupName: "",
            total: 0,
            hasOlder: false,
            messages: [],
            hideNoise: true,
            showHidden: false,
            mediaFilter: "all",
            focusMessageId: Number(ctx.focus_message_id || 0) || 0,
            fetchingMediaId: null,
        });
        onWillStart(async () => {
            await this.load({ scrollBottom: true });
        });
        onMounted(() => {
            this._scrollToFocusOrBottom();
        });
    }

    mediaIcon(kind) {
        return MEDIA_ICONS[kind] || MEDIA_ICONS.unknown;
    }

    async load({ scrollBottom = false, beforeId = null } = {}) {
        if (!this.conversationId) {
            this.state.error = "No conversation selected.";
            this.state.loading = false;
            return;
        }
        if (beforeId) {
            this.state.loadingOlder = true;
        } else {
            this.state.loading = true;
        }
        this.state.error = null;
        try {
            const data = await this.orm.call(
                "whatsapp.conversation",
                "get_thread_messages",
                [this.conversationId],
                {
                    offset: 0,
                    limit: 50,
                    hide_noise: this.state.hideNoise,
                    show_hidden: this.state.showHidden,
                    media_filter: this.state.mediaFilter,
                    before_id: beforeId || null,
                    focus_message_id: beforeId
                        ? null
                        : this.state.focusMessageId || null,
                }
            );
            this.state.conversationName = data.conversation_name || "Chat";
            this.state.conversationType = data.conversation_type || "";
            this.state.remoteJid = data.remote_jid || "";
            this.state.groupName = data.group_name || "";
            this.state.total = data.total || 0;
            this.state.hasOlder = Boolean(data.has_older);
            if (beforeId) {
                const existing = new Set(this.state.messages.map((m) => m.id));
                const older = (data.messages || []).filter(
                    (m) => !existing.has(m.id)
                );
                this.state.messages = [...older, ...this.state.messages];
            } else {
                this.state.messages = data.messages || [];
                if (data.focus_message_id) {
                    this.state.focusMessageId = data.focus_message_id;
                }
            }
            if (scrollBottom) {
                queueMicrotask(() => this._scrollToFocusOrBottom());
            }
        } catch (e) {
            this.state.error = e.message || String(e);
        } finally {
            this.state.loading = false;
            this.state.loadingOlder = false;
        }
    }

    async reloadFilters() {
        this.state.focusMessageId = 0;
        await this.load({ scrollBottom: true });
    }

    async loadOlder() {
        if (!this.state.hasOlder || !this.state.messages.length) {
            return;
        }
        const firstId = this.state.messages[0].id;
        const el = this.threadRef.el;
        const prevHeight = el ? el.scrollHeight : 0;
        await this.load({ beforeId: firstId });
        if (el) {
            el.scrollTop = el.scrollHeight - prevHeight;
        }
    }

    _scrollToFocusOrBottom() {
        const el = this.threadRef.el;
        if (!el) {
            return;
        }
        if (this.state.focusMessageId) {
            const node = el.querySelector(
                `[data-message-id="${this.state.focusMessageId}"]`
            );
            if (node) {
                node.scrollIntoView({ block: "center" });
                return;
            }
        }
        el.scrollTop = el.scrollHeight;
    }

    bubbleClass(msg, index) {
        const classes = [
            "o_wa_chat_bubble",
            msg.direction === "out" ? "o_wa_out" : "o_wa_in",
        ];
        if (msg.id === this.state.focusMessageId) {
            classes.push("o_wa_focus");
        }
        const prev = this.state.messages[index - 1];
        if (
            prev &&
            prev.direction === msg.direction &&
            prev.sender === msg.sender
        ) {
            classes.push("o_wa_grouped");
        }
        return classes.join(" ");
    }

    showSender(msg, index) {
        if (msg.direction === "out") {
            return false;
        }
        const prev = this.state.messages[index - 1];
        return !(prev && prev.sender === msg.sender && prev.direction === "in");
    }

    formatTime(ts) {
        if (!ts) {
            return "";
        }
        // message_timestamp is stored as naive UTC SQL string
        const raw = String(ts).replace(" ", "T");
        const d = new Date(raw.endsWith("Z") ? raw : `${raw}Z`);
        if (Number.isNaN(d.getTime())) {
            return String(ts).slice(0, 16);
        }
        return d.toLocaleString(undefined, {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
        });
    }

    onToggleHideNoise() {
        this.state.hideNoise = !this.state.hideNoise;
        this.reloadFilters();
    }

    onToggleShowHidden() {
        this.state.showHidden = !this.state.showHidden;
        this.reloadFilters();
    }

    onMediaFilterChange(ev) {
        this.state.mediaFilter = ev.target.value;
        this.reloadFilters();
    }

    async hideMessage(msg) {
        try {
            await this.orm.call("whatsapp.message", "action_hide", [[msg.id]]);
            if (this.state.hideNoise || !this.state.showHidden) {
                this.state.messages = this.state.messages.filter(
                    (m) => m.id !== msg.id
                );
            } else {
                msg.is_hidden = true;
            }
        } catch (e) {
            this.notification.add(e.message || String(e), { type: "danger" });
        }
    }

    async fetchMedia(msg) {
        this.state.fetchingMediaId = msg.id;
        try {
            const result = await this.orm.call(
                "whatsapp.message",
                "action_fetch_media_preview",
                [[msg.id]]
            );
            if (result?.ok && result.preview_url) {
                msg.preview_url = result.preview_url;
                msg.has_cached_media = true;
            } else {
                this.notification.add(
                    result?.error || "Media preview unavailable",
                    { type: "warning" }
                );
            }
        } catch (e) {
            this.notification.add(e.message || String(e), { type: "danger" });
        } finally {
            this.state.fetchingMediaId = null;
        }
    }

    openMessageForm(msg) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "whatsapp.message",
            res_id: msg.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openConversationForm() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "whatsapp.conversation",
            res_id: this.conversationId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    isImage(msg) {
        return msg.media_kind === "image" || msg.media_kind === "sticker";
    }

    isAudio(msg) {
        return msg.media_kind === "audio";
    }

    isVideo(msg) {
        return msg.media_kind === "video";
    }
}

registry
    .category("actions")
    .add("whatsapp_hub_conversation_chat", WhatsappHubConversationChat);
