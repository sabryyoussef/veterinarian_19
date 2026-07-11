/** @odoo-module **/

/**
 * Apply a global TEST UI skin only on the test host/DB.
 * Detection is hostname/port based so production never picks this up
 * even though both services share the same addons path.
 */
import { whenReady } from "@odoo/owl";

const TEST_HOST_HINTS = ["test.drpaws.ai", "test."];
const TEST_PORTS = new Set(["8028", "18028"]);

function isPetspotTestEnvironment() {
    try {
        const host = (window.location.hostname || "").toLowerCase();
        const port = String(window.location.port || "");
        if (TEST_PORTS.has(port)) {
            return true;
        }
        if (TEST_HOST_HINTS.some((hint) => host === hint || host.startsWith(hint))) {
            return true;
        }
        // Local direct access by Host header already covered; also accept query override for debug.
        const params = new URLSearchParams(window.location.search || "");
        if (params.get("petspot_test_ui") === "1") {
            return true;
        }
    } catch (_err) {
        // ignore
    }
    return false;
}

function ensureTestRibbon() {
    if (document.getElementById("petspot_test_ui_ribbon")) {
        return;
    }
    const ribbon = document.createElement("div");
    ribbon.id = "petspot_test_ui_ribbon";
    ribbon.className = "o_petspot_test_ribbon";
    ribbon.setAttribute("role", "status");
    ribbon.textContent = "TEST DATABASE — test.drpaws.ai — do not use for live clinic work / قاعدة الاختبار";
    document.body.prepend(ribbon);
}

function applyTestUi() {
    if (!isPetspotTestEnvironment()) {
        return;
    }
    document.documentElement.classList.add("o_petspot_test_ui");
    document.body.classList.add("o_petspot_test_ui");
    ensureTestRibbon();
    const prefix = "[TEST] ";
    if (!document.title.startsWith(prefix)) {
        document.title = prefix + document.title;
    }
    // Keep title prefix as Odoo updates document.title during navigation.
    const titleEl = document.querySelector("title");
    if (titleEl && !titleEl._petspotTestTitleObserver) {
        const observer = new MutationObserver(() => {
            if (!document.title.startsWith(prefix)) {
                document.title = prefix + document.title.replace(/^\[TEST\]\s*/, "");
            }
        });
        observer.observe(titleEl, { childList: true, characterData: true, subtree: true });
        titleEl._petspotTestTitleObserver = observer;
    }
}

whenReady(() => {
    applyTestUi();
    // Re-apply after webclient mounts (body may be replaced/late).
    setTimeout(applyTestUi, 500);
    setTimeout(applyTestUi, 2000);
});
