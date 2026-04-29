/** @odoo-module **/

import { patch } from "@web/core/utils/patch";

// Odoo selection_badge field (OWL)
import { SelectionBadgeField } from "@web/views/fields/selection_badge/selection_badge_field";

function applyLuxtorStateClass(rootEl, value) {
    if (!rootEl) return;

    // badge element (Odoo uses one of these depending on version)
    const badge =
        rootEl.querySelector(".o_selection_badge") ||
        rootEl.querySelector(".badge") ||
        rootEl;

    if (!badge) return;

    badge.classList.remove("lx_state_not_started", "lx_state_in_works", "lx_state_complete");

    if (value === "not_started") badge.classList.add("lx_state_not_started");
    else if (value === "in_works") badge.classList.add("lx_state_in_works");
    else if (value === "complete") badge.classList.add("lx_state_complete");
}

patch(SelectionBadgeField.prototype, "luxtor_selection_badge_colors", {
    mounted() {
        if (super.mounted) super.mounted();
        applyLuxtorStateClass(this.el, this.props.value);
    },
    patched() {
        if (super.patched) super.patched();
        applyLuxtorStateClass(this.el, this.props.value);
    },
});
