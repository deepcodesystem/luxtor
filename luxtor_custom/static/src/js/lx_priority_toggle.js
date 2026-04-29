/** @odoo-module **/
/**
 * LxPriorityToggle — Priority (express) service yes/no radios on cart/checkout.
 * Handles /lx/priority/* RPC endpoints + review reward detection.
 */

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

/* ---------- DOM helpers ---------- */

function _setRadioPair(yesSel, noSel, isYes) {
    const yes = document.querySelector(yesSel);
    const no  = document.querySelector(noSel);
    if (yes) yes.checked = !!isYes;
    if (no)  no.checked  = !isYes;
}

function _applyServerTotalFormatted(res) {
    if (!res || !res.ok) return;
    const totalStr = res.total_formatted || "";
    if (!totalStr) return;

    const totalEl =
        document.querySelector(".oe_website_sale .oe_cart .js_cart_summary .oe_subtotal .oe_currency_value") ||
        document.querySelector(".oe_website_sale .js_cart_summary .oe_currency_value") ||
        document.querySelector(".oe_website_sale .o_wsale_cart_summary .oe_currency_value");

    if (totalEl) totalEl.textContent = totalStr;
}

function _showRewardMsg(message) {
    const el = document.querySelector("#lx_express_reward_msg");
    if (!el) return;
    const msg = (message || "").trim();
    if (msg) {
        el.textContent = msg;
        el.classList.remove("d-none");
    } else {
        el.textContent = "";
        el.classList.add("d-none");
    }
}

function _applyRewardUi({ active, message }) {
    const el = document.querySelector("#lx_express_reward_msg");
    if (!el) return;
    if (active) {
        el.classList.remove("d-none");
        el.textContent = (message || "Congratulations! Express delivery is now free thanks to your review.").trim();
    } else {
        el.classList.add("d-none");
        el.textContent = "";
    }
}

/* ---------- widget ---------- */

publicWidget.registry.LxPriorityToggle = publicWidget.Widget.extend({
    selector: "#lx_express_block",
    events: {
        "change #lx_express_yes": "_onYes",
        "change #lx_express_no":  "_onNo",
    },

    init() {
        this._super(...arguments);
        this._enabled = false;
        this._unit = 0;
        this._unitFormatted = "";
        this._qty = 0;
        this._op = 0;
        this._qtyWatchBound = false;
        this._rewardActive = false;
        this._rewardMessage = "";
        this._rewardBound = false;
        this._isFree = false;
    },

    async start() {
        const r = this._super.apply(this, arguments);
        await this._fetchUnit();
        await this._fetchQty();
        this._renderUnitOnly();
        this._renderRewardIfNeeded();
        await this._syncInitialRadios();
        this._setupDomObservers();
        this._bindQtyWatcher();
        this._bindRewardWatcher();
        return r;
    },

    /* ---------- RPC wrappers ---------- */
    _rpcPrice()              { return rpc("/lx/priority/price", {}); },
    _rpcMrpQty()             { return rpc("/lx/priority/mrp_qty", {}); },
    _rpcHas()                { return rpc("/lx/priority/has", {}); },
    _rpcApply(enabled, qty)  { return rpc("/lx/priority/apply", { enabled, qty }); },
    _rpcRemove()             { return rpc("/lx/priority/remove", {}); },
    _rpcReviewStatus()       { return rpc("/lx/review/status", {}); },

    /* ---------- loaders ---------- */
    async _fetchUnit() {
        try {
            const res = await this._rpcPrice();
            if (res?.ok) {
                this._unit = Number(res.unit_price || 0);
                this._unitFormatted = res.unit_formatted || "";
                this._isFree = !!res.is_free || Number(res.unit_price || 0) === 0;
                this._rewardActive  = !!res.reward_express_free || (Number(res.unit_price || 0) === 0);
                this._rewardMessage = res.reward_message || "";
            } else {
                this._unit = 0;
                this._unitFormatted = "";
                this._isFree = false;
                this._rewardActive  = false;
                this._rewardMessage = "";
            }
        } catch {
            this._unit = 0;
            this._unitFormatted = "";
            this._isFree = false;
            this._rewardActive  = false;
            this._rewardMessage = "";
        }
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
            const present = !!(res && res.ok && (res.enabled || res.is_free));
            _setRadioPair("#lx_express_yes", "#lx_express_no", present);
            this._enabled = present;

            setTimeout(async () => {
                const r2 = await this._rpcHas();
                const p2 = !!(r2 && r2.ok && (r2.enabled || r2.is_free));
                _setRadioPair("#lx_express_yes", "#lx_express_no", p2);
                this._enabled = p2;
            }, 150);
        } catch { }
    },

    _setupDomObservers() {
        const resync = async () => {
            try {
                const res = await this._rpcHas();
                const present = !!(res && res.ok && (res.enabled || res.is_free));
                _setRadioPair("#lx_express_yes", "#lx_express_no", present);
                this._enabled = present;
            } catch { }
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
        const txt = this._isFree ? "Free" : (this._unitFormatted || "").replace(/[()]/g, "");
        el.textContent = txt;
        el.classList.add("text-muted");
        el.style.direction = "ltr";
        el.style.textAlign = "right";
        el.style.cssFloat = "right";
    },

    _renderRewardIfNeeded() {
        const box = document.querySelector("#lx_express_reward_msg");
        if (!box) return;
        const isFree = !!this._rewardActive && Number(this._unit || 0) === 0;
        if (isFree) {
            box.textContent = "Congratulations! Priority Service has been successfully applied.";
            box.classList.remove("d-none");
        } else {
            box.textContent = "";
            box.classList.add("d-none");
        }
    },

    async _refreshRewardFromServer() {
        try {
            const p = await this._rpcPrice();
            if (p?.ok) {
                this._rewardActive  = !!p.reward_express_free || (Number(p.unit_price || 0) === 0);
                this._rewardMessage = p.reward_message || "";
                this._isFree = !!p.is_free || Number(p.unit_price || 0) === 0;
                this._unit = Number(p.unit_price || 0);
                this._unitFormatted = p.unit_formatted || this._unitFormatted;
                this._renderUnitOnly();
                this._renderRewardIfNeeded();
                return;
            }
        } catch { }

        try {
            const s = await this._rpcReviewStatus();
            if (s?.ok) {
                this._rewardActive = !!s.active;
                this._renderRewardIfNeeded();
            }
        } catch { }
    },

    /* ---------- events ---------- */
    async _onYes(ev) {
        if (!ev.currentTarget.checked) return;
        _setRadioPair("#lx_express_yes", "#lx_express_no", true);
        this._enabled = true;
        await this._fetchUnit();
        await this._fetchQty();
        this._renderUnitOnly();
        this._renderRewardIfNeeded();
        const op = ++this._op;
        const res = await this._rpcApply(true, this._qty);
        if (op !== this._op) return;
            if (res?.ok) {
                _applyServerTotalFormatted(res);
                if (typeof res.unit_formatted === "string") this._unitFormatted = res.unit_formatted;
                this._isFree = !!res.is_free || Number(res.unit_price || 0) === 0;
                this._unit = Number(res.unit_price || this._unit);
                this._rewardActive  = !!res.reward_express_free || (Number(res.unit_price || 0) === 0);
                this._rewardMessage = res.reward_message || this._rewardMessage;
            this._renderUnitOnly();
            this._renderRewardIfNeeded();
            setTimeout(() => location.reload(), 400);
        }
    },

    async _onNo(ev) {
        if (!ev.currentTarget.checked) return;
        _setRadioPair("#lx_express_yes", "#lx_express_no", false);
        this._enabled = false;
        const op = ++this._op;
        const res = await this._rpcRemove();
        if (op !== this._op) return;
        if (res?.ok) {
            _applyServerTotalFormatted(res);
            _setRadioPair("#lx_express_yes", "#lx_express_no", false);
            this._enabled = false;
            if (typeof res.unit_formatted === "string") this._unitFormatted = res.unit_formatted;
            this._isFree = !!res.is_free || Number(res.unit_price || 0) === 0;
            this._unit = Number(res.unit_price || this._unit);
            this._rewardActive  = !!res.reward_express_free || (Number(res.unit_price || 0) === 0);
            this._rewardMessage = res.reward_message || this._rewardMessage;
            this._renderUnitOnly();
            this._renderRewardIfNeeded();
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
                    this._isFree = !!res.is_free || Number(res.unit_price || 0) === 0;
                    this._unit = Number(res.unit_price || this._unit);
                    this._rewardActive  = !!res.reward_express_free || (Number(res.unit_price || 0) === 0);
                    this._rewardMessage = res.reward_message || this._rewardMessage;
                    this._renderUnitOnly();
                    this._renderRewardIfNeeded();
                    setTimeout(() => location.reload(), 400);
                }
            } else {
                this._refreshRewardFromServer();
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

    _bindRewardWatcher() {
        if (this._rewardBound) return;

        const refresh = () => setTimeout(() => this._refreshRewardFromServer(), 0);

        document.addEventListener("submit", (ev) => {
            const f = ev.target;
            if (!f) return;
            const hint =
                (f.classList && (f.classList.contains("o_portal_chatter_composer_form") || f.classList.contains("o_rating_rate_form"))) ||
                (f.getAttribute && (f.getAttribute("action") || "").includes("rating"));
            if (hint) refresh();
        }, true);

        document.addEventListener("click", (ev) => {
            const t = ev.target;
            if (!t) return;
            if (t.matches && (t.matches("button[type='submit']") || t.matches(".o_portal_chatter_composer_btn"))) refresh();
        }, true);

        const block = document.querySelector("#lx_express_block");
        if (block) {
            const mo = new MutationObserver(() => refresh());
            mo.observe(block, { childList: true, subtree: true });
        }

        this._rewardBound = true;
    },
});

export default publicWidget.registry.LxPriorityToggle;
