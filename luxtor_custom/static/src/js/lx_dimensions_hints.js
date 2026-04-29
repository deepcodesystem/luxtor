/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

publicWidget.registry.LxDimensionsHints = publicWidget.Widget.extend({
    selector: ".oe_website_sale",

    start() {
        this._super(...arguments);

        // Initial load
        this._refreshHints();

        // Live update when user types width — height max changes with width
        const widthInput = document.querySelector("#lx_width_input");
        if (widthInput) {
            widthInput.addEventListener("input",  () => this._refreshHints());
            widthInput.addEventListener("change", () => this._refreshHints());
        }

        // V18: product_id input fires a real 'change' event when variant changes
        document.addEventListener("change", (ev) => {
            if (ev.target && ev.target.name === "product_id") {
                this._refreshHints();
            }
        });

        // V19: Odoo updates the hidden product_id input programmatically (no 'change' event).
        // Watch it via MutationObserver on its value attribute, and also listen for
        // Odoo's own variant-update custom events.
        const pidInput = document.querySelector('input[name="product_id"]');
        if (pidInput) {
            this._pidObserver = new MutationObserver(() => this._refreshHints());
            this._pidObserver.observe(pidInput, { attributes: true, attributeFilter: ["value"] });
        }

        // V19 fires 'product_updated' / 'variant_change' on the form or document
        this._onVariantEvt = () => this._refreshHints();
        document.addEventListener("product_updated",  this._onVariantEvt, true);
        document.addEventListener("variant_change",   this._onVariantEvt, true);
        // Odoo website_sale also dispatches this after combination resolution
        document.addEventListener("combination_found", this._onVariantEvt, true);
    },

    destroy() {
        if (this._pidObserver) this._pidObserver.disconnect();
        if (this._onVariantEvt) {
            document.removeEventListener("product_updated",   this._onVariantEvt, true);
            document.removeEventListener("variant_change",    this._onVariantEvt, true);
            document.removeEventListener("combination_found", this._onVariantEvt, true);
        }
        return this._super(...arguments);
    },

    _currentVariantId() {
        const input = document.querySelector('input[name="product_id"]');
        return input ? parseInt(input.value || "0") : 0;
    },
    _currentTemplateId() {
        const input = document.querySelector('input[name="product_template_id"]');
        return input ? parseInt(input.value || "0") : 0;
    },

    _refreshHints() {
        // Debounce — avoid flooding the server on rapid keystrokes
        clearTimeout(this._refreshTimer);
        this._refreshTimer = setTimeout(() => this._doRefresh(), 180);
    },

    async _doRefresh() {
        const productId = this._currentVariantId();
        const tmplId    = this._currentTemplateId();
        const wInput    = document.querySelector("#lx_width_input");
        const hInput    = document.querySelector("#lx_height_input");
        const widthStr  = (wInput?.value || "").trim();
        const width     = widthStr ? parseFloat(widthStr) : null;

        try {
            const data = await rpc("/lx/dimensions/hints", {
                product_id:      productId || null,
                product_tmpl_id: tmplId    || null,
                width:           (width !== null && !isNaN(width)) ? width : null,
                unit:            "m",
            });

            const widthHintEl  = document.querySelector("#lx_width_hint");
            const heightHintEl = document.querySelector("#lx_height_hint");

            if (data?.ok) {
                // Update placeholders (visible hint text inside the input)
                if (wInput && data.width?.hint)  wInput.placeholder  = data.width.hint;
                if (hInput && data.height?.hint) hInput.placeholder  = data.height.hint;

                // Update native min/max so browser validation matches
                if (wInput) {
                    if (data.width?.min_m)  wInput.min = data.width.min_m;
                    if (data.width?.max_m)  wInput.max = data.width.max_m;
                }
                if (hInput) {
                    if (data.height?.min_m) hInput.min = data.height.min_m;
                    if (data.height?.max_m) hInput.max = data.height.max_m;
                }

                // Hint spans (hidden by default, shown as sub-text when needed)
                if (widthHintEl)  widthHintEl.textContent  = data.width?.hint  || "";
                if (heightHintEl) heightHintEl.textContent = data.height?.hint || "";
            }
        } catch (err) {
            // Silent — hints are UX only, never block the page
        }
    },
});
