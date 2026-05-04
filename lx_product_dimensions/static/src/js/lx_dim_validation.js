/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

publicWidget.registry.LxDimensionsLiveValidation = publicWidget.Widget.extend({
    selector: ".oe_website_sale",

    init() {
        this._super(...arguments);
        this._ranges = { min_w: 0.60, max_w: 0, min_h: 0.90, max_h: 0 };
    },

    start() {
        this._super(...arguments);
        this._refreshHintsAndValidate();

        const w = document.querySelector("#lx_width_input");
        const h = document.querySelector("#lx_height_input");

        if (w) {
            w.addEventListener("input",  () => this._onLiveChange());
            w.addEventListener("change", () => this._onLiveChange());
        }
        if (h) {
            h.addEventListener("input",  () => this._onLiveChange());
            h.addEventListener("change", () => this._onLiveChange());
        }

        document.addEventListener("change", (ev) => {
            if (ev.target && ev.target.name === "product_id") {
                this._refreshHintsAndValidate();
            }
        });

        return Promise.resolve();
    },

    _currentVariantId() {
        const input = document.querySelector('input[name="product_id"]');
        return input ? parseInt(input.value || "0", 10) || 0 : 0;
    },
    _currentTemplateId() {
        const input = document.querySelector('input[name="product_template_id"]');
        return input ? parseInt(input.value || "0", 10) || 0 : 0;
    },

    _msgNodeFor(inputEl) {
        const id = inputEl.getAttribute("id") || "";
        let node = inputEl.parentElement.querySelector(`.lx-validate-msg[data-for="${id}"]`);
        if (!node) {
            node = document.createElement("div");
            node.className = "lx-validate-msg text-danger small mt-2";
            node.setAttribute("data-for", id);
            inputEl.parentElement.appendChild(node);
        }
        return node;
    },

    _clearFieldState(inputEl) {
        const node = this._msgNodeFor(inputEl);
        inputEl.classList.remove("is-invalid");
        node.textContent = "";
        node.style.display = "none";
        inputEl.setCustomValidity && inputEl.setCustomValidity("");
    },

    _setFieldError(inputEl, msg) {
        const node = this._msgNodeFor(inputEl);
        inputEl.classList.add("is-invalid");
        node.textContent = msg || "Invalid value";
        node.style.display = "block";
        inputEl.setCustomValidity && inputEl.setCustomValidity(msg || "Invalid");
    },

    _toggleCart(disabled) {
        const selectors = [
            '#add_to_cart',
            '.js_add_cart_json',
            'button[name="add_to_cart"]',
            '.o_wsale_product_btn .btn-primary',
        ];
        selectors.forEach((sel) => {
            document.querySelectorAll(sel).forEach((el) => {
                el.disabled = !!disabled;
                el.classList.toggle("disabled", !!disabled);
            });
        });
    },

    _num(v) {
        const n = parseFloat((v || "").toString().trim());
        return Number.isFinite(n) ? n : NaN;
    },

    _validateNow() {
        const wEl = document.querySelector("#lx_width_input");
        const hEl = document.querySelector("#lx_height_input");
        const { min_w, max_w, min_h, max_h } = this._ranges;
        let allOk = true;

        if (wEl) {
            const raw = (wEl.value || "").trim();
            if (!raw) {
                this._clearFieldState(wEl);
            } else {
                const w = this._num(raw);
                if (!Number.isFinite(w) || w <= 0) {
                    this._setFieldError(wEl, "Width must be greater than zero.");
                    allOk = false;
                } else if (w < min_w) {
                    this._setFieldError(wEl, `Minimum width is ${min_w.toFixed(2)} m.`);
                    allOk = false;
                } else if (max_w > 0 && w > max_w) {
                    this._setFieldError(wEl, `Maximum width is ${max_w.toFixed(2)} m.`);
                    allOk = false;
                } else {
                    this._clearFieldState(wEl);
                }
            }
        }

        if (hEl) {
            const raw = (hEl.value || "").trim();
            if (!raw) {
                this._clearFieldState(hEl);
            } else {
                const h = this._num(raw);
                if (!Number.isFinite(h) || h <= 0) {
                    this._setFieldError(hEl, "Height must be greater than zero.");
                    allOk = false;
                } else if (h < min_h) {
                    this._setFieldError(hEl, `Minimum height is ${min_h.toFixed(2)} m.`);
                    allOk = false;
                } else if (max_h > 0 && h > max_h) {
                    this._setFieldError(hEl, `Maximum height is ${max_h.toFixed(2)} m.`);
                    allOk = false;
                } else {
                    this._clearFieldState(hEl);
                }
            }
        }

        const bothEmpty = (!wEl || !(wEl.value || "").trim()) && (!hEl || !(hEl.value || "").trim());
        this._toggleCart(bothEmpty ? false : !allOk);
        return allOk;
    },

    async _refreshHintsAndValidate() {
        const productId = this._currentVariantId();
        const tmplId    = this._currentTemplateId();
        const widthStr  = (document.querySelector("#lx_width_input")?.value || "").trim();
        const width     = widthStr ? parseFloat(widthStr) : null;

        try {
            const data = await rpc("/lx/dimensions/hints", {
                product_id:      productId || null,
                product_tmpl_id: tmplId    || null,
                width:           isNaN(width) ? null : width,
                unit:            "m",
            });

            const widthHintEl  = document.querySelector("#lx_width_hint");
            const heightHintEl = document.querySelector("#lx_height_hint");

            if (data?.ok) {
                if (widthHintEl)  widthHintEl.textContent  = data.width?.hint  || "";
                if (heightHintEl) heightHintEl.textContent = data.height?.hint || "";
                const wInput = document.querySelector("#lx_width_input");
                const hInput = document.querySelector("#lx_height_input");
                if (wInput && data.width?.hint)  wInput.placeholder  = data.width.hint;
                if (hInput && data.height?.hint) hInput.placeholder  = data.height.hint;
                this._ranges = {
                    min_w: Number(data.width?.min_m  || 0.60),
                    max_w: Number(data.width?.max_m  || 0),
                    min_h: Number(data.height?.min_m || 0.90),
                    max_h: Number(data.height?.max_m || 0),
                };
            } else {
                if (widthHintEl)  widthHintEl.textContent  = "—";
                if (heightHintEl) heightHintEl.textContent = "—";
                this._ranges = { min_w: 0.60, max_w: 0, min_h: 0.90, max_h: 0 };
            }
        } catch (err) {
            console.error("[LxDimensionsLiveValidation] RPC failed", err);
            this._ranges = { min_w: 0.60, max_w: 0, min_h: 0.90, max_h: 0 };
        }

        this._validateNow();
    },

    _onLiveChange() {
        this._refreshHintsAndValidate();
    },
});

