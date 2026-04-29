/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

/* ---------- utils ---------- */
function setRadioPair(yesSel, noSel, checked) {
    const yes = document.querySelector(yesSel);
    const no = document.querySelector(noSel);
    if (!yes || !no) return false;
    [yes, no].forEach((r) => {
        r.checked = false;
        r.removeAttribute("checked");
        const lab = r.nextElementSibling;
        if (lab) lab.setAttribute("aria-checked", "false");
    });
    const tgt = checked ? yes : no;
    tgt.checked = true;
    tgt.setAttribute("checked", "checked");
    const labT = tgt.nextElementSibling;
    if (labT) labT.setAttribute("aria-checked", "true");
    return checked;
}
function findTotalEl() {
    const sels = [
        "#order_total .monetary_field",
        ".js_cart_summary .oe_total .monetary_field",
        ".oe_total .oe_currency_value",
        ".oe_cart .oe_total .monetary_field",
    ];
    for (const s of sels) {
        const el = document.querySelector(s);
        if (el) return el;
    }
    return null;
}
function applyServerTotalFormatted(res) {
    const el = findTotalEl();
    if (el && res?.total_formatted) {
        el.innerHTML = res.total_formatted;
    }
}

/* ---------- widget ---------- */
publicWidget.registry.LxPriorityToggle = publicWidget.Widget.extend({
    selector: "#lx_express_block",
    events: {
        "change #lx_express_yes": "_onYes",
        "change #lx_express_no": "_onNo",
    },

    init() {
        this._super(...arguments);
        this._enabled = false;
        this._unit = 0;
        this._unitFormatted = "";
        this._qty = 0;
        this._op = 0;
        this._qtyWatchBound = false;
    },

    async start() {
        const r = this._super.apply(this, arguments);
        await this._fetchUnit();
        await this._fetchQty();
        this._renderUnitOnly();
        await this._syncInitialRadios();
        this._setupDomObservers();
        this._bindQtyWatcher();
        return r;
    },

    /* ---------- RPC wrappers ---------- */
    _rpcPrice() { return rpc("/lx/priority/price", {}); },
    _rpcMrpQty() { return rpc("/lx/priority/mrp_qty", {}); },
    _rpcHas()   { return rpc("/lx/priority/has", {}); },
    _rpcApply(enabled, qty) { return rpc("/lx/priority/apply", { enabled, qty }); },
    _rpcRemove() { return rpc("/lx/priority/remove", {}); },

    /* ---------- loaders ---------- */
    async _fetchUnit() {
        try {
            const res = await this._rpcPrice();
            if (res?.ok) {
                this._unit = Number(res.unit_price || 0);
                this._unitFormatted = res.unit_formatted || "";
            } else {
                this._unit = 0;
                this._unitFormatted = "";
            }
        } catch {
            this._unit = 0;
            this._unitFormatted = "";
        }
    },
    async _fetchQty() {
        try {
            const res = await this._rpcMrpQty();
            this._qty = Number(res?.qty_total || 0) || 0;
        } catch {
            this._qty = 0;
        }
    },

    /* ---------- radios ---------- */
    async _syncInitialRadios() {
        try {
            const res = await this._rpcHas();
            const present = !!(res && res.ok && res.enabled);
            setRadioPair("#lx_express_yes", "#lx_express_no", present);
            this._enabled = present;
            setTimeout(async () => {
                const r2 = await this._rpcHas();
                const p2 = !!(r2 && r2.ok && r2.enabled);
                setRadioPair("#lx_express_yes", "#lx_express_no", p2);
                this._enabled = p2;
            }, 150);
        } catch { /* ignore */ }
    },
    _setupDomObservers() {
        const resync = async () => {
            try {
                const res = await this._rpcHas();
                const present = !!(res && res.ok && res.enabled);
                setRadioPair("#lx_express_yes", "#lx_express_no", present);
                this._enabled = present;
            } catch { /* ignore */ }
        };
        const block = document.querySelector("#lx_express_block");
        if (block) {
            const mo = new MutationObserver(() => resync());
            mo.observe(block, { childList: true, subtree: true });
        }
    },

    /* ---------- render ---------- */
    _renderUnitOnly() {
        const el = document.querySelector("#lx_express_price");
        if (!el) return;
        el.textContent = this._unitFormatted || "";
        el.classList.add("text-muted");
        el.style.direction = "ltr";
        el.style.textAlign = "right";
        el.style.cssFloat = "right";
    },

    /* ---------- events ---------- */
    async _onYes(ev) {
        if (!ev.currentTarget.checked) return;
        setRadioPair("#lx_express_yes", "#lx_express_no", true);
        this._enabled = true;
        await this._fetchQty();
        this._renderUnitOnly();

        const op = ++this._op;
        const res = await this._rpcApply(true, this._qty);
        if (op !== this._op) return;
        if (res?.ok) {
            applyServerTotalFormatted(res);
            if (typeof res.unit_formatted === "string") this._unitFormatted = res.unit_formatted;
            this._renderUnitOnly();

            setTimeout(() => location.reload(), 400);
        }
    },

    async _onNo(ev) {
        if (!ev.currentTarget.checked) return;
        setRadioPair("#lx_express_yes", "#lx_express_no", false);
        this._enabled = false;

        const op = ++this._op;
        const res = await this._rpcRemove();
        if (op !== this._op) return;
        if (res?.ok) {
            applyServerTotalFormatted(res);
            setRadioPair("#lx_express_yes", "#lx_express_no", false);
            this._enabled = false;
            if (typeof res.unit_formatted === "string") this._unitFormatted = res.unit_formatted;
            this._renderUnitOnly();

            // 🔁 Force fast reload (sync totals and DOM)
            setTimeout(() => location.reload(), 400);
        }
    },

    _bindQtyWatcher() {
        if (this._qtyWatchBound) return;
        const rebound = () =>
            setTimeout(async () => {
                await this._fetchQty();
                if (this._enabled) {
                    const op = ++this._op;
                    const res = await this._rpcApply(true, this._qty);
                    if (op !== this._op) return;
                    if (res?.ok) {
                        applyServerTotalFormatted(res);
                        if (typeof res.unit_formatted === "string") this._unitFormatted = res.unit_formatted;
                        this._renderUnitOnly();

                        setTimeout(() => location.reload(), 400);
                    }
                }
            }, 0);

        document.addEventListener("change", (ev) => {
            if (ev.target?.classList?.contains("js_quantity")) rebound();
        });
        document.addEventListener("input", (ev) => {
            if (ev.target?.classList?.contains("js_quantity")) rebound();
        });
        this._qtyWatchBound = true;
    },
});

export default publicWidget.registry.LxPriorityToggle;

function findTotalEl() {
    const sels = [
        "#order_total .monetary_field",
        ".js_cart_summary .oe_total .monetary_field",
        ".oe_total .oe_currency_value",
        ".oe_cart .oe_total .monetary_field",
    ];
    for (const s of sels) {
        const el = document.querySelector(s);
        if (el) return el;
    }
    return null;
}
function applyServerTotalFormatted(res) {
    const el = findTotalEl();
    if (el && res?.total_formatted) {
        el.innerHTML = res.total_formatted;
    }
}
function setRadioPair(yesSel, noSel, checked) {
    const yes = document.querySelector(yesSel);
    const no = document.querySelector(noSel);
    if (!yes || !no) return false;
    [yes, no].forEach((r) => {
        r.checked = false;
        r.removeAttribute("checked");
        const lab = r.nextElementSibling;
        if (lab) lab.setAttribute("aria-checked", "false");
    });
    const tgt = checked ? yes : no;
    tgt.checked = true;
    tgt.setAttribute("checked", "checked");
    const labT = tgt.nextElementSibling;
    if (labT) labT.setAttribute("aria-checked", "true");
    return checked;
}

/* ---------- widget ---------- */
publicWidget.registry.LxInstallToggle = publicWidget.Widget.extend({
    selector: "#lx_express_block", // radios: #lx_install_yes / #lx_install_no
    events: {
        "change #lx_install_yes": "_onYes",
        "change #lx_install_no": "_onNo",
    },

    init() {
        this._super(...arguments);
        this._enabled = false;
        this._unitFormatted = "";
        this._qty = 0;
        this._op = 0;
        this._qtyWatchBound = false;
    },

    async start() {
        const r = this._super.apply(this, arguments);
        await this._fetchUnit();
        await this._fetchQty();
        this._renderUnitOnly();
        await this._syncInitialRadios();
        this._setupDomObservers();
        this._bindQtyWatcher();
        return r;
    },

    /* ---------- RPC wrappers ---------- */
    _rpcPrice() { return rpc("/lx/install/price", {}); },
    _rpcMrpQty() { return rpc("/lx/install/mrp_qty", {}); },
    _rpcHas()   { return rpc("/lx/install/has", {}); },
    _rpcApply(enabled, qty) { return rpc("/lx/install/apply", { enabled, qty }); },
    _rpcRemove() { return rpc("/lx/install/remove", {}); },

    /* ---------- loaders ---------- */
    async _fetchUnit() {
        try {
            const res = await this._rpcPrice();
            this._unitFormatted = res?.ok ? (res.unit_formatted || "") : "";
        } catch { this._unitFormatted = ""; }
    },
    async _fetchQty() {
        try {
            const res = await this._rpcMrpQty();
            this._qty = Number(res?.qty_total || 0) || 0;
        } catch { this._qty = 0; }
    },

    /* ---------- radios ---------- */
    async _syncInitialRadios() {
        try {
            const res = await this._rpcHas();
            const present = !!(res && res.ok && res.enabled);
            setRadioPair("#lx_install_yes", "#lx_install_no", present);
            this._enabled = present;
            setTimeout(async () => {
                const r2 = await this._rpcHas();
                const p2 = !!(r2 && r2.ok && r2.enabled);
                setRadioPair("#lx_install_yes", "#lx_install_no", p2);
                this._enabled = p2;
            }, 150);
        } catch { /* ignore */ }
    },
    _setupDomObservers() {
        const resync = async () => {
            try {
                const res = await this._rpcHas();
                const present = !!(res && res.ok && res.enabled);
                setRadioPair("#lx_install_yes", "#lx_install_no", present);
                this._enabled = present;
            } catch { /* ignore */ }
        };
        const block = document.querySelector("#lx_express_block");
        if (block) {
            const mo = new MutationObserver(() => resync());
            mo.observe(block, { childList: true, subtree: true });
        }
        const cart = document.getElementById("cart_products");
        if (cart) {
            const mo2 = new MutationObserver(() => resync());
            mo2.observe(cart, { childList: true, subtree: true });
        }
    },

    /* ---------- render ---------- */
    _renderUnitOnly() {
        const el = document.querySelector("#lx_install_price");
        if (!el) return;
        // unit only, no qty
        el.textContent = this._unitFormatted || "";
        el.classList.add("text-muted");
        el.style.direction = "ltr";
        el.style.textAlign = "right";
        el.style.cssFloat = "right";
    },

    /* ---------- events ---------- */
    async _onYes(ev) {
        if (!ev.currentTarget.checked) return;
        setRadioPair("#lx_install_yes", "#lx_install_no", true);
        this._enabled = true;

        await this._fetchQty();
        const op = ++this._op;
        const res = await this._rpcApply(true, this._qty);
        if (op !== this._op) return;
        if (res?.ok) {
            applyServerTotalFormatted(res);
            if (typeof res.unit_formatted === "string") this._unitFormatted = res.unit_formatted;
            this._renderUnitOnly();
            // Force full sync (lines/discounts/delivery)
            setTimeout(() => location.reload(), 400);
        }
    },

    async _onNo(ev) {
        if (!ev.currentTarget.checked) return;
        setRadioPair("#lx_install_yes", "#lx_install_no", false);
        this._enabled = false;

        const op = ++this._op;
        const res = await this._rpcRemove();
        if (op !== this._op) return;
        if (res?.ok) {
            applyServerTotalFormatted(res);
            if (typeof res.unit_formatted === "string") this._unitFormatted = res.unit_formatted;
            this._renderUnitOnly();
            setTimeout(() => location.reload(), 400);
        }
    },

    _bindQtyWatcher() {
        if (this._qtyWatchBound) return;
        const rebound = () => setTimeout(async () => {
            await this._fetchQty();
            if (this._enabled) {
                const op = ++this._op;
                const res = await this._rpcApply(true, this._qty);
                if (op !== this._op) return;
                if (res?.ok) {
                    applyServerTotalFormatted(res);
                    if (typeof res.unit_formatted === "string") this._unitFormatted = res.unit_formatted;
                    this._renderUnitOnly();
                    setTimeout(() => location.reload(), 400);
                }
            }
        }, 0);
        document.addEventListener("change", (ev) => {
            if (ev.target?.classList?.contains("js_quantity")) rebound();
        });
        document.addEventListener("input", (ev) => {
            if (ev.target?.classList?.contains("js_quantity")) rebound();
        });
        this._qtyWatchBound = true;
    },
});
