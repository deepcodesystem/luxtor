/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

publicWidget.registry.LxFabricFreezeWatcher = publicWidget.Widget.extend({
    selector: "#wrapwrap",

    init() {
        this._super(...arguments);
        this._tmplId = null;
        this._freeze = false;
        this._msg = "";
        this._ratio = null;
        this._lastCheck = 0;
        this._cacheDelay = 3000; // ms
        this._intervalMs = 250;  // fast poll
        this._timer = null;
        this._debug = new URL(window.location.href).searchParams.get("lx_dbg") === "1";
    },

    start() {
        const res = this._super(...arguments);
        this._tmplId = this._getTemplateId();
        this._checkAndApply();
        this._poll();
        document.addEventListener("change", () => this._checkAndApply(), true);
        document.addEventListener("input", () => this._checkAndApply(), true);
        return res;
    },

    destroy() {
        if (this._timer) clearInterval(this._timer);
        return this._super(...arguments);
    },

    _poll() {
        if (this._timer) clearInterval(this._timer);
        this._timer = setInterval(() => this._checkAndApply(), this._intervalMs);
    },

    _getTemplateId() {
        const holder = document.querySelector("[data-product-template-id]");
        if (holder) {
            const v = holder.getAttribute("data-product-template-id");
            if (v && v.trim()) return parseInt(v, 10) || 0;
        }
        const alt = document.querySelector("input[name='product-template-id']");
        if (alt && alt.value) return parseInt(alt.value, 10) || 0;
        return 0;
    },

    async _checkFreeze(tmplId) {
        if (!tmplId) return { ok: false, freeze: false };
        const now = Date.now();
        if (this._lastCheck && now - this._lastCheck < this._cacheDelay) {
            return { ok: true, freeze: this._freeze, msg: this._msg, ratio: this._ratio };
        }
        try {
            const res = await rpc("/shop/lx_freeze_check", { product_template_id: tmplId });
            this._lastCheck = Date.now();
            this._freeze = !!res.freeze;
            this._msg = res.msg || "";
            this._ratio = res.ratio;
            return res;
        } catch {
            return { ok: false, freeze: false };
        }
    },

    async _checkAndApply() {
        const tmplId = this._tmplId || this._getTemplateId();
        if (!tmplId) return;
        const res = await this._checkFreeze(tmplId);
        if (res && res.ok && res.freeze) this._applyFreeze(res.msg);
        else this._restoreNormal();
        if (this._debug) this._renderDebug(tmplId, res);
    },

    _applyFreeze(msg) {
        this._toggle("#add_to_cart", false);
        this._toggle("#css_quantity", false);
        this._toggle("#wsale_save_for_later_button", true);
        const box = this._ensureMsgBox();
        box.textContent = msg || "Temporarily unavailable.";
    },

    _restoreNormal() {
        this._toggle("#add_to_cart", true);
        this._toggle("#css_quantity", true);
        this._toggle("#wsale_save_for_later_button", false);
        const box = document.getElementById("lx-availability-box");
        if (box) box.textContent = "";
    },

    _toggle(sel, show) {
        const el = document.querySelector(sel);
        if (el) el.style.display = show ? "" : "none";
    },

    _ensureMsgBox() {
        let el = document.getElementById("lx-availability-box");
        if (!el) {
            const ref = document.querySelector("#product_details .o_wsale_product_quantity")
                || document.querySelector("#product_details .css_quantity")
                || document.body;
            el = document.createElement("div");
            el.id = "lx-availability-box";
            el.className = "lx-availability-text";
            ref.insertAdjacentElement("afterend", el);
            const style = document.createElement("style");
            style.textContent = `
                .lx-availability-text {
                    font-size:14px;
                    font-weight:500;
                    color:#b26a00;
                    margin-top:6px;
                    margin-bottom:8px;
                }
            `;
            document.head.appendChild(style);
        }
        return el;
    },

    _renderDebug(tmplId, res) {
        let panel = document.getElementById("lx-freeze-debug");
        if (!panel) {
            panel = document.createElement("div");
            panel.id = "lx-freeze-debug";
            Object.assign(panel.style, {
                position: "fixed",
                right: "10px",
                bottom: "10px",
                zIndex: "9999",
                background: "rgba(0,0,0,0.8)",
                color: "#fff",
                padding: "8px 12px",
                fontSize: "12px",
                borderRadius: "8px",
                whiteSpace: "pre-wrap",
            });
            document.body.appendChild(panel);
        }
        const ratio = res?.ratio ? res.ratio.toFixed(2) + "%" : "n/a";
        panel.textContent = `[${new Date().toLocaleTimeString()}] tmplId=${tmplId} freeze=${!!res.freeze} ratio=${ratio}`;
    },
});

publicWidget.registry.LxWelcomeBannerDeduper = publicWidget.Widget.extend({
    selector: "#wrapwrap",

    start() {
        const res = this._super(...arguments);
        this._dedupeWelcomeBanners();
        this._welcomeBannerObserver = new MutationObserver(() => this._dedupeWelcomeBanners());
        this._welcomeBannerObserver.observe(this.el, { childList: true, subtree: true });
        return res;
    },

    destroy() {
        if (this._welcomeBannerObserver) {
            this._welcomeBannerObserver.disconnect();
        }
        return this._super(...arguments);
    },

    _dedupeWelcomeBanners() {
        const banners = Array.from(document.querySelectorAll(".lx-welcome-banner"));
        if (banners.length <= 1) {
            return;
        }
        const seenKinds = new Set();
        banners.forEach((banner) => {
            const kind = banner.dataset.lxBannerKind || "default";
            if (seenKinds.has(kind)) {
                banner.remove();
                return;
            }
            seenKinds.add(kind);
        });
    },
});

export default publicWidget.registry.LxFabricFreezeWatcher;
