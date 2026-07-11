/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { onMounted } from "@odoo/owl";
import { FormController } from "@web/views/form/form_controller";
import { CalendarController } from "@web/views/calendar/calendar_controller";
import { AttendeeCalendarController } from "@calendar/views/attendee_calendar/attendee_calendar_controller";

/**
 * Calendar / Appointment UI opens calendar.event with a hardcoded act_window
 * (does not call get_formview_action). Route linked clinic meetings to pet.appointment.
 */
async function openMeetingOrPet(orm, actionService, resId, extraContext = {}) {
    if (!resId) {
        return false;
    }
    const action = await orm.call("calendar.event", "action_open_meeting_or_pet", [resId], {
        context: extraContext,
    });
    return actionService.doAction(action);
}

patch(AttendeeCalendarController.prototype, {
    setup() {
        super.setup(...arguments);
        this._petOrm = useService("orm");
        this._petActionService = useService("action");
    },
    async goToFullEvent(resId, additionalContext = {}) {
        if (resId) {
            return openMeetingOrPet(this._petOrm, this._petActionService, resId, {
                ...this.props.context,
                ...additionalContext,
            });
        }
        return super.goToFullEvent(resId, additionalContext);
    },
});

patch(CalendarController.prototype, {
    setup() {
        super.setup(...arguments);
        this._petOrm = useService("orm");
        this._petActionService = useService("action");
    },
    async editRecord(record, context = {}) {
        if (this.model.resModel === "calendar.event" && record?.id) {
            return openMeetingOrPet(
                this._petOrm,
                this._petActionService,
                record.id,
                { ...this.props.context, ...context }
            );
        }
        return super.editRecord(record, context);
    },
});

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
        this._petOrm = useService("orm");
        this._petActionService = useService("action");
        if (this.props.resModel === "calendar.event") {
            onMounted(() => {
                this._redirectLinkedPetAppointment();
            });
        }
    },
    async _redirectLinkedPetAppointment() {
        if (this.props.context?.calendar_event_keep_form) {
            return;
        }
        const root = this.model?.root;
        if (!root?.resId || this._petAppointmentRedirected) {
            return;
        }
        const petField = root.data?.pet_appointment_id;
        const petId = Array.isArray(petField) ? petField[0] : petField;
        if (!petId) {
            return;
        }
        this._petAppointmentRedirected = true;
        await this._petActionService.doAction(
            {
                type: "ir.actions.act_window",
                name: "Pet Appointment",
                res_model: "pet.appointment",
                res_id: petId,
                views: [[false, "form"]],
                target: "current",
            },
            { stackPosition: "replaceCurrentAction" }
        );
    },
});
