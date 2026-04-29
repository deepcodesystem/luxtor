/** @odoo-module **/
import publicWidget from "@web/legacy/js/public/public_widget";

/* =============================================================
   LxMutedRename — renames R-002-21/22 in span.text-muted
   ============================================================= */
publicWidget.registry.LxMutedRename = publicWidget.Widget.extend({
    selector: ".oe_website_sale",

    start() {
        const res = this._super(...arguments);

        this._parentMo = new MutationObserver(() => this._attachAll());
        this._parentMo.observe(this.el, { childList: true, subtree: true });

        this._attachAll();
        setTimeout(() => this._attachAll(), 400);

        return res;
    },

    destroy() {
        if (this._parentMo) this._parentMo.disconnect();
        document.querySelectorAll(
            ".js_add_cart_variants span.attribute_value[data-lx-watched]"
        ).forEach((span) => {
            if (span._lxMo) { span._lxMo.disconnect(); span._lxMo = null; }
            span.removeAttribute("data-lx-watched");
        });
        return this._super(...arguments);
    },

    _map(txt) {
        return (txt || "")
            .replace(/R-?002-?21/gi, "Futura")
            .replace(/R-?002-?22/gi, "Futura +");
    },

    _renameSpan(span) {
        const before = span.textContent || "";
        const after  = this._map(before);
        if (after !== before) span.textContent = after;
    },

    _attachAll() {
        document.querySelectorAll(
            ".js_add_cart_variants h6 span.text-muted span.attribute_value"
        ).forEach((span) => {
            if (span.dataset.lxWatched) return;
            span.dataset.lxWatched = "1";
            this._renameSpan(span);
            const mo = new MutationObserver(() => this._renameSpan(span));
            mo.observe(span, { characterData: true, childList: true, subtree: true });
            span._lxMo = mo;
        });
    },
});

/* =============================================================
   LxBadgeTooltips — injects "?" tooltip badges on attribute labels
   ============================================================= */
publicWidget.registry.LxBadgeTooltips = publicWidget.Widget.extend({
    selector: ".oe_website_sale",

    TOOLTIPS: {
        "CASSETTE":     "Select your type of cassette",
        "COLOR":        "Select the color of your blind",
        "CONTROL TYPE": "Select your type of control",
    },

    start() {
        const res = this._super(...arguments);

        this._run();
        setTimeout(() => this._run(), 400);
        setTimeout(() => this._run(), 850);

        this._mo = new MutationObserver(() => this._run());
        this._mo.observe(this.el, { childList: true, subtree: true });

        this._onEvt = () => this._run();
        document.addEventListener("combination_found", this._onEvt, true);
        document.addEventListener("change", this._onEvt, true);
        return res;
    },

    destroy() {
        if (this._mo) this._mo.disconnect();
        if (this._onEvt) {
            document.removeEventListener("combination_found", this._onEvt, true);
            document.removeEventListener("change", this._onEvt, true);
        }
        return this._super(...arguments);
    },

    _run() {
        document.querySelectorAll(".js_add_cart_variants li[data-attribute-name]").forEach((li) => {
            const name    = (li.getAttribute("data-attribute-name") || "").trim().toUpperCase();
            const tooltip = this.TOOLTIPS[name];
            if (!tooltip) return;

            const h6 = li.querySelector("h6.attribute_name")
                    || li.querySelector("strong.attribute_name")
                    || li.querySelector("label.attribute_name")
                    || li.querySelector(".attribute_name");
            if (!h6) return;

            const muted = h6.querySelector("span.text-muted");
            const badge = h6.querySelector(".notificationmessage");

            // Avoid MO loop: only act if badge is missing or in wrong position
            if (badge) {
                if (muted && muted.nextElementSibling === badge) return;
                if (!muted && h6.lastElementChild === badge) return;
                badge.remove();
            }

            const newBadge = document.createElement("span");
            newBadge.className = "notificationmessage";
            newBadge.setAttribute("data-tooltip", tooltip);
            newBadge.textContent = " ?";

            if (muted) {
                muted.insertAdjacentElement("afterend", newBadge);
            } else {
                h6.appendChild(newBadge);
            }
        });
    },
});
