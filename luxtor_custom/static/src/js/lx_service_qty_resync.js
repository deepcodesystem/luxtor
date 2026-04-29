/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

const LX_SERVICE_PATHS = new Set([
    "/shop/cart",
    "/shop/service",
    "/shop/services",
    "/shop/checkout",
    "/shop/payment",
]);

function isRelevantQtyTarget(target) {
    if (!target?.classList?.contains("js_quantity")) {
        return false;
    }
    const row = target.closest("[data-default-code]");
    const code = (row?.dataset?.defaultCode || "").toUpperCase();
    return !["PRIORITY_SERVICE", "INSTALL_SERVICE"].includes(code);
}

function isRelevantPage() {
    return LX_SERVICE_PATHS.has(window.location.pathname);
}

publicWidget.registry.LxServiceQtyResync = publicWidget.Widget.extend({
    selector: "#wrapwrap",

    init() {
        this._super(...arguments);
        this._debounceTimer = null;
        this._reloadTimer = null;
        this._syncToken = 0;
    },

    start() {
        const res = this._super(...arguments);
        if (!isRelevantPage()) {
            return res;
        }

        this._qtyListener = (ev) => {
            if (!isRelevantQtyTarget(ev.target)) {
                return;
            }
            this._scheduleResync();
        };

        document.addEventListener("change", this._qtyListener, true);
        document.addEventListener("input", this._qtyListener, true);
        return res;
    },

    destroy() {
        if (this._qtyListener) {
            document.removeEventListener("change", this._qtyListener, true);
            document.removeEventListener("input", this._qtyListener, true);
        }
        if (this._debounceTimer) {
            clearTimeout(this._debounceTimer);
        }
        if (this._reloadTimer) {
            clearTimeout(this._reloadTimer);
        }
        return this._super(...arguments);
    },

    _scheduleResync() {
        if (this._debounceTimer) {
            clearTimeout(this._debounceTimer);
        }
        this._debounceTimer = setTimeout(() => this._resyncActiveServices(), 700);
    },

    async _resyncActiveServices() {
        const token = ++this._syncToken;
        let result;
        try {
            result = await rpc("/lx/services/resync_active", {});
        } catch {
            return;
        }

        if (token !== this._syncToken || !result?.ok || !result.resynced) {
            return;
        }

        if (this._reloadTimer) {
            clearTimeout(this._reloadTimer);
        }
        this._reloadTimer = setTimeout(() => window.location.reload(), 200);
    },
});

export default publicWidget.registry.LxServiceQtyResync;
