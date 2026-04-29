/** @odoo-module **/
/**
 * LxInstallToggle — Installation service yes/no radios on cart/checkout.
 * Handles /lx/install/* RPC endpoints.
 */

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

function _findTotalEl() {
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

function _applyServerTotalFormatted(res) {
    const el = _findTotalEl();
    if (el && res?.total_formatted) {
        el.innerHTML = res.total_formatted;
    }
}

function _setRadioPair(yesSel, noSel, checked) {
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

publicWidget.registry.LxInstallToggle = publicWidget.Widget.extend({
    selector: "#lx_express_block",
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
        this._isFree = false;
    },

    async start() {
        const r = this._super.apply(this, arguments);
        await this._fetchUnit();
        await this._fetchQty();
        this._renderUnitOnly();
        await this._syncInitialRadios();
        await this._syncInstallRewardMsg();
        this._setupDomObservers();
        this._bindQtyWatcher();
        return r;
    },

    _rpcPrice()              { return rpc("/lx/install/price", {}); },
    _rpcMrpQty()             { return rpc("/lx/install/mrp_qty", {}); },
    _rpcHas()                { return rpc("/lx/install/has", {}); },
    _rpcApply(enabled, qty)  { return rpc("/lx/install/apply", { enabled, qty }); },
    _rpcRemove()             { return rpc("/lx/install/remove", {}); },
    _rpcFlags()              { return rpc("/lx/debug/flags", {}); },

    async _fetchUnit() {
        try {
            const res = await this._rpcPrice();
            this._unitFormatted = res?.ok ? (res.unit_formatted || "") : "";
            this._isFree = !!(res?.ok && res.is_free);
        } catch {
            this._unitFormatted = "";
            this._isFree = false;
        }
    },

    async _fetchQty() {
        try {
            const res = await this._rpcMrpQty();
            this._qty = Number(res?.qty_total || 0) || 0;
        } catch { this._qty = 0; }
    },

    async _syncInstallRewardMsg() {
        const el = document.getElementById("lx_install_reward_msg");
        if (!el) return;
        try {
            const res = await this._rpcFlags();
            const freeApplies = !!(res && res.ok && res.flags && res.flags.lx_free_applies);
            const show = !!(this._enabled && freeApplies);
            el.classList.toggle("d-none", !show);
        } catch {
            el.classList.add("d-none");
        }
    },

    async _syncInitialRadios() {
        try {
            const res = await this._rpcHas();
            const present = !!(res && res.ok && (res.enabled || res.is_free));
            _setRadioPair("#lx_install_yes", "#lx_install_no", present);
            this._enabled = present;
            this._isFree = !!(res && res.ok && res.is_free);
            await this._syncInstallRewardMsg();

            setTimeout(async () => {
                const r2 = await this._rpcHas();
                const p2 = !!(r2 && r2.ok && (r2.enabled || r2.is_free));
                _setRadioPair("#lx_install_yes", "#lx_install_no", p2);
                this._enabled = p2;
                this._isFree = !!(r2 && r2.ok && r2.is_free);
                await this._syncInstallRewardMsg();
            }, 150);
        } catch { }
    },

    _setupDomObservers() {
        const resync = async () => {
            try {
                const res = await this._rpcHas();
                const present = !!(res && res.ok && (res.enabled || res.is_free));
                _setRadioPair("#lx_install_yes", "#lx_install_no", present);
                this._enabled = present;
                this._isFree = !!(res && res.ok && res.is_free);
                await this._syncInstallRewardMsg();
            } catch { }
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

    _renderUnitOnly() {
        const el = document.querySelector("#lx_install_price");
        if (!el) return;
        const txt = this._isFree ? "Free" : (this._unitFormatted || "").replace(/[()]/g, "");
        el.textContent = txt;
        el.classList.add("text-muted");
        el.style.direction = "ltr";
        el.style.textAlign = "right";
        el.style.cssFloat = "right";
    },

    async _onYes(ev) {
        if (!ev.currentTarget.checked) return;
        _setRadioPair("#lx_install_yes", "#lx_install_no", true);
        this._enabled = true;
        await this._syncInstallRewardMsg();
        await this._fetchQty();
        const op = ++this._op;
        const res = await this._rpcApply(true, this._qty);
        if (op !== this._op) return;
        if (res?.ok) {
            _applyServerTotalFormatted(res);
            if (typeof res.unit_formatted === "string") this._unitFormatted = res.unit_formatted;
            this._isFree = !!res.is_free;
            this._renderUnitOnly();
            await this._syncInstallRewardMsg();
            setTimeout(() => location.reload(), 400);
        }
    },

    async _onNo(ev) {
        if (!ev.currentTarget.checked) return;
        _setRadioPair("#lx_install_yes", "#lx_install_no", false);
        this._enabled = false;
        await this._syncInstallRewardMsg();
        const op = ++this._op;
        const res = await this._rpcRemove();
        if (op !== this._op) return;
        if (res?.ok) {
            _applyServerTotalFormatted(res);
            if (typeof res.unit_formatted === "string") this._unitFormatted = res.unit_formatted;
            this._isFree = !!res.is_free;
            this._renderUnitOnly();
            await this._syncInstallRewardMsg();
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
                    _applyServerTotalFormatted(res);
                    if (typeof res.unit_formatted === "string") this._unitFormatted = res.unit_formatted;
                    this._isFree = !!res.is_free;
                    this._renderUnitOnly();
                    await this._syncInstallRewardMsg();
                    setTimeout(() => location.reload(), 400);
                }
            } else {
                await this._syncInstallRewardMsg();
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

export default publicWidget.registry.LxInstallToggle;
