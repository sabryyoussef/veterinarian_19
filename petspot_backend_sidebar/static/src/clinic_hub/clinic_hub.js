/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { _t } from "@web/core/l10n/translation";

/**
 * Nav items for Clinic Hub.
 * Missing XML IDs are hidden safely after loadAction fails.
 */
const NAV_ITEMS = [
    {
        id: "dashboard",
        label: "Dashboard",
        icon: "fa-home",
        kind: "dashboard",
    },
    {
        id: "appointments",
        label: "Appointments",
        icon: "fa-calendar",
        actionXmlId: "pet_management.action_pet_appointment",
        groups: [
            "pet_management.group_pet_appointments_user_own",
            "pet_management.group_pet_appointments_user_all",
            "pet_management.group_pet_appointments_admin",
            "pet_management.group_pet_staff_appointments",
            "pet_management.group_pet_operations_user_all",
        ],
    },
    {
        id: "pets",
        label: "Pets",
        icon: "fa-paw",
        actionXmlId: "pet_management.action_pet_pet",
        groups: [
            "pet_management.group_pet_core_user_own",
            "pet_management.group_pet_core_user_all",
            "pet_management.group_pet_core_admin",
            "pet_management.group_pet_staff_core",
        ],
    },
    {
        id: "medical_visits",
        label: "Medical Visits",
        icon: "fa-stethoscope",
        actionXmlId: "pet_management.action_pet_medical_visit",
        groups: [
            "pet_management.group_pet_health_user_own",
            "pet_management.group_pet_health_user_all",
            "pet_management.group_pet_health_admin",
            "pet_management.group_pet_staff_health",
        ],
    },
    {
        id: "wa_intake",
        label: "WA Intake",
        icon: "fa-comments",
        actionXmlId: "petspot_wa_intake.action_petspot_wa_intake",
    },
    {
        id: "clinic_portal",
        label: "Clinic Portal",
        icon: "fa-mobile",
        actionXmlId: "petspot_clinic_portal.action_petspot_portal_token",
    },
    {
        id: "sales",
        label: "Sales",
        icon: "fa-shopping-cart",
        actionXmlId: "sale.action_orders",
        groups: ["sales_team.group_sale_salesman", "sales_team.group_sale_manager"],
    },
    {
        id: "pos",
        label: "Point of Sale",
        icon: "fa-shopping-basket",
        actionXmlId: "point_of_sale.action_pos_config_kanban",
        groups: ["point_of_sale.group_pos_user", "point_of_sale.group_pos_manager"],
    },
    {
        id: "inventory",
        label: "Inventory",
        icon: "fa-cubes",
        actionXmlId: "stock.action_picking_tree_all",
        groups: ["stock.group_stock_user", "stock.group_stock_manager"],
    },
    {
        id: "accounting",
        label: "Accounting",
        icon: "fa-book",
        actionXmlId: "account.action_move_out_invoice_type",
        groups: ["account.group_account_invoice", "account.group_account_manager"],
    },
    {
        id: "crm",
        label: "CRM",
        icon: "fa-handshake-o",
        actionXmlId: "crm.crm_lead_action_pipeline",
        groups: ["sales_team.group_sale_salesman", "sales_team.group_sale_manager"],
    },
    {
        id: "reports",
        label: "Reports",
        icon: "fa-bar-chart",
        actionXmlId: "pet_management.action_pet_vet_performance_report",
        groups: [
            "pet_management.group_pet_operations_user_own",
            "pet_management.group_pet_operations_user_all",
            "pet_management.group_pet_operations_admin",
            "pet_management.group_pet_health_user_all",
        ],
    },
    {
        id: "settings",
        label: "Settings",
        icon: "fa-cog",
        actionXmlId: "base.action_res_company_form",
        groups: ["base.group_system"],
    },
    {
        id: "all_apps",
        label: "All Apps",
        icon: "fa-th",
        kind: "home_menu",
    },
];

export class PetspotClinicHub extends Component {
    static template = "petspot_backend_sidebar.ClinicHub";
    static props = { ...standardActionServiceProps };
    static displayName = "Clinic Hub";

    setup() {
        this.actionService = useService("action");
        this.orm = useService("orm");
        this.notification = useService("notification");
        // Depends on web_enterprise (home_menu service).
        this.homeMenu = useService("home_menu");

        this.state = useState({
            activeId: "dashboard",
            items: [],
            missingXmlIds: [],
            loading: true,
            kpis: {
                appointmentsToday: null,
                incompleteVisits: null,
                waIntakeDrafts: null,
            },
            mobileNavOpen: false,
        });

        onWillStart(async () => {
            await this._prepareNav();
            await this._loadKpis();
            this.state.loading = false;
        });
    }

    async _userInAnyGroup(groups) {
        if (!groups || !groups.length) {
            return true;
        }
        for (const g of groups) {
            try {
                if (await user.hasGroup(g)) {
                    return true;
                }
            } catch {
                // unknown group xml id — ignore
            }
        }
        return false;
    }

    async _prepareNav() {
        const visible = [];
        const missing = [];
        for (const item of NAV_ITEMS) {
            if (item.groups && !(await this._userInAnyGroup(item.groups))) {
                continue;
            }
            if (item.kind === "dashboard" || item.kind === "home_menu") {
                visible.push({ ...item, available: true });
                continue;
            }
            if (!item.actionXmlId) {
                continue;
            }
            try {
                await this.actionService.loadAction(item.actionXmlId);
                visible.push({ ...item, available: true });
            } catch (err) {
                missing.push(item.actionXmlId);
                console.warn(
                    `[Clinic Hub] hiding nav item "${item.id}" — missing/inaccessible action: ${item.actionXmlId}`,
                    err
                );
            }
        }
        this.state.items = visible;
        this.state.missingXmlIds = missing;
        if (missing.length) {
            this.notification.add(
                _t("Some Clinic Hub links were hidden (missing actions). See browser console."),
                { type: "warning" }
            );
        }
    }

    async _loadKpis() {
        const today = new Date();
        const y = today.getFullYear();
        const m = String(today.getMonth() + 1).padStart(2, "0");
        const d = String(today.getDate()).padStart(2, "0");
        const dayStart = `${y}-${m}-${d} 00:00:00`;
        const dayEnd = `${y}-${m}-${d} 23:59:59`;

        const safeCount = async (model, domain) => {
            try {
                return await this.orm.searchCount(model, domain);
            } catch {
                return null;
            }
        };

        this.state.kpis.appointmentsToday = await safeCount("pet.appointment", [
            ["start_datetime", ">=", dayStart],
            ["start_datetime", "<=", dayEnd],
            ["state", "not in", ["cancelled"]],
        ]);
        this.state.kpis.incompleteVisits = await safeCount("pet.medical.visit", [
            ["is_case_complete", "=", false],
            ["status", "=", "completed"],
        ]);
        this.state.kpis.waIntakeDrafts = await safeCount("petspot.wa.intake", [
            ["state", "=", "draft"],
        ]);
    }

    async onNavClick(item) {
        this.state.activeId = item.id;
        this.state.mobileNavOpen = false;

        if (item.kind === "dashboard") {
            await this._loadKpis();
            return;
        }
        if (item.kind === "home_menu") {
            if (this.homeMenu) {
                await this.homeMenu.toggle(true);
            } else {
                this.notification.add(_t("App grid is not available in this client."), {
                    type: "warning",
                });
            }
            return;
        }
        if (item.actionXmlId) {
            try {
                await this.actionService.doAction(item.actionXmlId, {
                    clearBreadcrumbs: true,
                });
            } catch (err) {
                console.error("[Clinic Hub] doAction failed", item.actionXmlId, err);
                this.notification.add(_t("Could not open that screen."), { type: "danger" });
            }
        }
    }

    toggleMobileNav() {
        this.state.mobileNavOpen = !this.state.mobileNavOpen;
    }

    async openAction(xmlId) {
        try {
            await this.actionService.doAction(xmlId, { clearBreadcrumbs: true });
        } catch (err) {
            console.error("[Clinic Hub] card action failed", xmlId, err);
            this.notification.add(_t("Could not open that screen."), { type: "danger" });
        }
    }
}

registry.category("actions").add("petspot_clinic_hub", PetspotClinicHub);
