/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

/**
 * LxMotorOnlyPicker
 * When "Motor Only" Control Type is selected, inject a pill-selector
 * (styled like the Control Type pills but smaller) to choose the
 * tubular motor variant.
 */
publicWidget.registry.LxMotorOnlyPicker = publicWidget.Widget.extend({
    selector: ".oe_website_sale",

    start() {
        const res = this._super(...arguments);
        this._motorVariants = null;
        this._rendered = false;

        this._onEvt = () => this._check();
        document.addEventListener("change", this._onEvt, true);
        document.addEventListener("click",  this._onEvt, true);

        // V19: active class changes on pills via class mutation
        const variantList = document.querySelector(".js_add_cart_variants");
        if (variantList) {
            this._mo = new MutationObserver(() => this._check());
            this._mo.observe(variantList, { attributes: true, attributeFilter: ["class"], subtree: true });
        }

        this._check();
        setTimeout(() => this._check(), 300);
        return res;
    },

    destroy() {
        if (this._mo) this._mo.disconnect();
        if (this._onEvt) {
            document.removeEventListener("change", this._onEvt, true);
            document.removeEventListener("click",  this._onEvt, true);
        }
        this._removeBox();
        return this._super(...arguments);
    },

    // ── detection ────────────────────────────────────────────────────────────

    _isMotorOnlySelected() {
        // Pills display type (V19): active class on the <li>
        const activePills = document.querySelectorAll(
            ".js_add_cart_variants li.o_variant_pills.active, " +
            ".js_add_cart_variants li.js_attribute_value:has(input:checked)"
        );
        for (const el of activePills) {
            const txt = (el.textContent || "").trim();
            if (/motor\s*only/i.test(txt)) return true;
        }

        // Checked radio/checkbox inputs
        for (const inp of document.querySelectorAll(".js_variant_change:checked")) {
            const val = (inp.getAttribute("data-value_name") || inp.getAttribute("data-value-name") || "").trim();
            if (/motor\s*only/i.test(val)) return true;
        }
        return false;
    },

    async _check() {
        if (this._isMotorOnlySelected()) {
            await this._showPicker();
        } else {
            this._removeBox();
        }
    },

    // ── fetch ─────────────────────────────────────────────────────────────────

    async _fetchVariants() {
        if (this._motorVariants) return this._motorVariants;
        try {
            const data = await rpc("/shop/lx_motor_variants", {});
            this._motorVariants = Array.isArray(data) ? data : [];
        } catch (_) {
            this._motorVariants = [];
        }
        return this._motorVariants;
    },

    // ── render ────────────────────────────────────────────────────────────────

    async _showPicker() {
        if (this._rendered) return;
        this._rendered = true;

        const variants = await this._fetchVariants();
        if (!variants.length) { this._rendered = false; return; }

        const anchor = this._findControlTypeAnchor();
        if (!anchor) { this._rendered = false; return; }

        const box = document.createElement("div");
        box.id = "lx-motor-picker";
        box.className = "lx-motor-picker-box";

        // Title — same style as attribute labels
        const title = document.createElement("p");
        title.className = "lx-motor-picker-title";
        title.textContent = "Select your tubular motor";
        box.appendChild(title);

        // Pill list — one pill per motor variant
        const ul = document.createElement("ul");
        ul.className = "lx-motor-pill-list";

        variants.forEach((v, i) => {
            const li = document.createElement("li");
            li.className = "lx-motor-pill" + (i === 0 ? " active" : "");
            li.dataset.variantId = v.id;
            li.dataset.variantLabel = v.label || v.code || "";
            li.textContent = v.label || v.code;

            li.addEventListener("click", () => {
                ul.querySelectorAll(".lx-motor-pill").forEach((p) => p.classList.remove("active"));
                li.classList.add("active");
                this._syncHidden(v.id, v.label || v.code || "");
            });

            ul.appendChild(li);
        });

        box.appendChild(ul);
        anchor.insertAdjacentElement("afterend", box);

        // Sync first option by default
        this._syncHidden(variants[0].id, variants[0].label || variants[0].code || "");
    },

    _removeBox() {
        const box = document.getElementById("lx-motor-picker");
        if (box) box.remove();
        for (const hidden of document.querySelectorAll(
            'form input[name="lx_motor_only_variant_id"], form input[name="lx_motor_variant_id"], form input[name="lx_motor_only_label"]'
        )) {
            hidden.remove();
        }
        this._rendered = false;
    },

    _findControlTypeAnchor() {
        for (const li of document.querySelectorAll(".js_add_cart_variants li.variant_attribute")) {
            const attrName = (
                li.getAttribute("data-attribute_name") ||
                li.getAttribute("data-attribute-name") || ""
            ).trim().toUpperCase();
            if (attrName === "CONTROL TYPE") return li;

            const h6 = li.querySelector("h6.attribute_name, strong.attribute_name, .attribute_name");
            if (h6) {
                const sp = h6.querySelector("span:not(.text-muted):not(.notificationmessage)");
                const txt = (sp ? sp.textContent : h6.textContent).trim().toUpperCase();
                if (/CONTROL\s*TYPE/.test(txt)) return li;
            }
        }
        return null;
    },

    _syncHidden(variantId, variantLabel = "") {
        const form = document.querySelector('#product_details form[action*="/shop/cart"]')
                  || document.querySelector("form.js_add_cart_json")
                  || document.querySelector(".oe_website_sale form");
        if (!form) return;
        const legacy = form.querySelector('input[name="lx_motor_variant_id"]');
        if (legacy) {
            legacy.remove();
        }
        let hidden = form.querySelector('input[name="lx_motor_only_variant_id"]');
        if (!hidden) {
            hidden = document.createElement("input");
            hidden.type = "hidden";
            hidden.name = "lx_motor_only_variant_id";
            form.appendChild(hidden);
        }
        hidden.value = variantId;

        let labelHidden = form.querySelector('input[name="lx_motor_only_label"]');
        if (!labelHidden) {
            labelHidden = document.createElement("input");
            labelHidden.type = "hidden";
            labelHidden.name = "lx_motor_only_label";
            form.appendChild(labelHidden);
        }
        labelHidden.value = variantLabel || "";
    },
});
