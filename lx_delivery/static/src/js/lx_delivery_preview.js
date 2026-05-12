/** @odoo-module **/
/**
 * LxDeliveryPreviewAllCarriers
 * Pré-calcule et affiche les prix de livraison sur le checkout avant sélection.
 * Appelle /lx/shipping/preview_prices et met à jour les badges .o_wsale_delivery_price_badge.
 *
 * LxHideFromAfterVariantChange
 * Masque le label "From" après sélection de variante ou saisie de dimensions.
 */

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

/* =====================================================
   LxDeliveryPreviewAllCarriers
   ===================================================== */
publicWidget.registry.LxDeliveryPreviewAllCarriers = publicWidget.Widget.extend({
    selector: "#shop_checkout, .oe_website_sale",

    init() {
        this._super(...arguments);
        this._pollMs   = 450;
        this._cacheMs  = 2500;
        this._timer    = null;
        this._mo       = null;
        this._lastFetch       = 0;
        this._cachedPreview   = null;
        this._lastRendered    = Object.create(null);
        this._lastSyncedCarrier = null;
        this._refreshing      = false;
        this._ignoreMutations = false;
        this._freeAppliedLast = null;
        this._decidedOnce     = false;
    },

    start() {
        const res = this._super(...arguments);
        this._ensureStyles();
        this._scheduleRefresh({ force: true }, 0);
        window.addEventListener("load", () => this._scheduleRefresh({ force: true }, 0), { once: true });
        this._bindWatchers();
        return res;
    },

    destroy() {
        if (this._timer) clearTimeout(this._timer);
        if (this._mo) this._mo.disconnect();
        this._super(...arguments);
    },

    _bindWatchers() {
        const trigger = () => {
            if (this._ignoreMutations) return;
            this._scheduleRefresh({}, this._pollMs);
        };
        this.el.addEventListener("change", trigger, true);
        this.el.addEventListener("input",  trigger, true);
        this._mo = new MutationObserver(trigger);
        this._mo.observe(this.el, { childList: true, subtree: true });
    },

    _scheduleRefresh(meta = {}, delayMs = 0) {
        if (this._timer) clearTimeout(this._timer);
        this._timer = setTimeout(() => this._refresh(meta), delayMs);
    },

    async _refresh(meta = {}) {
        if (this._refreshing) return;
        this._refreshing = true;
        this._ignoreMutations = true;

        try {
            await this._syncSelectedCarrierOnce();
            const preview = await this._getPreview(meta);
            if (!preview || preview.status !== "success") return;

            const inputs = this._getCarrierInputs();
            for (const input of inputs) {
                const dmId = this._readDmId(input);
                if (!dmId) continue;
                const price = preview.prices?.[dmId];
                this._renderBadgeOnce(input, dmId, price, preview);
            }

            const isFree = !!preview?.free_flags?.lx_free_applies;
            this._applyFreeUi(isFree);
        } finally {
            this._ignoreMutations = false;
            this._refreshing = false;
        }
    },

    async _syncSelectedCarrierOnce() {
        const selected = this._getSelectedCarrierInput();
        if (!selected) return;
        const dmId = this._readDmId(selected);
        if (!dmId || this._lastSyncedCarrier === dmId) return;
        try {
            await rpc("/shop/carrier_rate_shipment", { carrier_id: dmId });
            this._lastSyncedCarrier = dmId;
            this._lastFetch = 0;
        } catch (_) {}
    },

    async _getPreview(meta = {}) {
        const now = Date.now();
        if (!meta.force && this._cachedPreview && (now - this._lastFetch) < this._cacheMs) {
            return this._cachedPreview;
        }
        try {
            const payload = await rpc("/lx/shipping/preview_prices", {});
            this._cachedPreview = payload;
            this._lastFetch = now;
            return payload;
        } catch (_) {
            return null;
        }
    },

    _getCarrierInputs() {
        return Array.from(document.querySelectorAll('input[name="o_delivery_radio"][data-dm-id]'));
    },

    _getSelectedCarrierInput() {
        return document.querySelector('input[name="o_delivery_radio"][data-dm-id]:checked');
    },

    _readDmId(input) {
        const v = input?.getAttribute("data-dm-id");
        const id = parseInt(v, 10);
        return Number.isFinite(id) ? id : null;
    },

    _findBadge(input) {
        const root =
            input.closest(".d-flex")?.parentElement ||
            input.closest(".d-flex") ||
            input.parentElement;
        return root?.querySelector(".o_wsale_delivery_price_badge, .lx-delivery-price-badge") || null;
    },

    _renderBadgeOnce(input, dmId, price, preview) {
        const badge = this._findBadge(input);
        if (!badge) return;

        const currency = preview?.currency || {};
        const carrierDebug = preview?.lx_debug?.by_carrier?.[dmId] || {};
        const freeApplies = !!preview?.free_flags?.lx_free_applies;
        const val = (typeof price === "number") ? price : 0.0;
        let formatted = this._formatMoney(val, currency);
        let isMuted = false;
        let isFree = false;

        if (freeApplies && val <= 0) {
            formatted = "Gratuit";
            isFree = true;
        } else if (carrierDebug?.ok === false && carrierDebug?.reason === "no_shipping_rate_for_zip") {
            formatted = "Renseignez votre adresse pour calculer";
            isMuted = true;
        } else if (carrierDebug?.ok === false && carrierDebug?.reason === "unsupported_carrier_preview") {
            formatted = "Sélectionnez pour calculer";
            isMuted = true;
        }

        if (this._lastRendered[dmId] === formatted) return;
        this._lastRendered[dmId] = formatted;
        badge.textContent = formatted;
        badge.classList.toggle("text-muted", isMuted);
        badge.classList.toggle("lx-delivery-price-free", isFree);
    },

    _formatMoney(amount, currency) {
        const dp     = Number.isFinite(currency?.decimal_places) ? currency.decimal_places : 2;
        const symbol = currency?.symbol || "";
        const pos    = currency?.position || "after";
        const fixed  = Number(amount || 0).toFixed(dp);
        return symbol ? (pos === "before" ? `${symbol} ${fixed}` : `${fixed} ${symbol}`) : fixed;
    },

    _applyFreeUi(isFree) {
        if (this._freeAppliedLast === isFree && this._decidedOnce) return;
        this._freeAppliedLast = isFree;
        this._decidedOnce = true;
        // Afficher/masquer le bandeau free si présent dans le DOM
        const banner = document.querySelector(".lx-info-banner");
        if (banner) {
            banner.style.display = isFree ? "block" : "none";
        }
    },

    _ensureStyles() {
        if (document.getElementById("lx_free_delivery_styles")) return;
        const style = document.createElement("style");
        style.id = "lx_free_delivery_styles";
        style.textContent = `
            .lx-info-banner{
                display: block;
                padding: 14px 16px;
                border: 1px solid rgba(17,24,39,.14);
                border-radius: 10px;
                background: rgba(59,130,246,.08);
                color: #111827;
                font-size: 16px;
                line-height: 1.35;
            }
            .lx-delivery-price-free{
                color: #15803d !important;
                font-weight: 600;
            }
        `;
        document.head.appendChild(style);
    },
});

/* =====================================================
   LxHideFromAfterVariantChange
   ===================================================== */
publicWidget.registry.LxHideFromAfterVariantChange = publicWidget.Widget.extend({
    selector: ".oe_website_sale",

    start() {
        this._super(...arguments);
        this.$el.one(
            "change",
            ".js_variant_change, input[name='lx_width_m'], input[name='lx_height_m']",
            () => {
                const el = this.el.querySelector(".lx_from_label");
                if (el) el.style.display = "none";
            }
        );
        return Promise.resolve();
    },
});

export default publicWidget.registry.LxDeliveryPreviewAllCarriers;

