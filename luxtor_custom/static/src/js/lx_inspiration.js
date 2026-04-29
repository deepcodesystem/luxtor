/** @odoo-module **/
/**
 * LxInspirationFilters — Dynamic filter + gallery grid on the inspiration/gallery page.
 * Reads boot data from #lx_insp_boot JSON script tag, then filters via /inspiration/filter RPC.
 */

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

publicWidget.registry.LxInspirationFilters = publicWidget.Widget.extend({
    selector: "#wrapwrap",

    start() {
        this._super(...arguments);

        this._boot = this._readBoot();

        this._gridEl    = document.getElementById("lx_gallery_grid");
        this._countEl   = document.getElementById("lx_count_text");
        this._typeEl    = document.getElementById("lx_filter_type");
        this._subLabel  = document.getElementById("lx_sub_label");
        this._subSelect = document.getElementById("lx_sub_select");

        this._products   = (this._boot && Array.isArray(this._boot.products))   ? this._boot.products   : [];
        this._categories = (this._boot && Array.isArray(this._boot.categories)) ? this._boot.categories : [];
        this._spaces     = (this._boot && Array.isArray(this._boot.spaces))     ? this._boot.spaces     : [];

        this._bind();

        if (this._subLabel) this._subLabel.textContent = "Category";
        this._syncSubSelect({ keepLabelCategory: true });
        this._render(this._products);

        return Promise.resolve();
    },

    _readBoot() {
        const el = document.getElementById("lx_insp_boot");
        if (!el) return null;
        try {
            return JSON.parse((el.textContent || "").trim() || "{}");
        } catch (e) {
            return null;
        }
    },

    _bind() {
        if (this._typeEl) {
            this._typeEl.addEventListener("change", () => {
                this._syncSubSelect({ keepLabelCategory: true });
                this._apply();
            });
        }
        if (this._subSelect) {
            this._subSelect.addEventListener("change", () => this._apply());
        }
    },

    _syncSubSelect({ keepLabelCategory } = {}) {
        const type = this._typeEl && this._typeEl.value ? this._typeEl.value : "all";

        if (keepLabelCategory && this._subLabel) {
            this._subLabel.textContent = "Category";
        }
        if (this._subSelect) {
            this._subSelect.disabled = (type === "all");
        }

        let items = [];
        if (type === "category") items = this._categories;
        else if (type === "product") items = this._products;
        else if (type === "space") items = this._spaces;

        this._fillSelect(this._subSelect, items, "All", (x) => x.name);
        if (this._subSelect) this._subSelect.value = "";
    },

    _fillSelect(sel, items, firstLabel, getLabel) {
        if (!sel) return;
        sel.innerHTML = "";

        const opt0 = document.createElement("option");
        opt0.value = "";
        opt0.textContent = firstLabel;
        sel.appendChild(opt0);

        const list = (items || []).slice().sort((a, b) =>
            String(getLabel(a) || "").localeCompare(String(getLabel(b) || ""))
        );

        list.forEach((it) => {
            const opt = document.createElement("option");
            opt.value = String(it.id);
            opt.textContent = String(getLabel(it) || "");
            sel.appendChild(opt);
        });
    },

    async _apply() {
        const type = this._typeEl && this._typeEl.value ? this._typeEl.value : "all";

        if (type === "all") {
            this._render(this._products);
            return;
        }

        const filter_id = this._subSelect && this._subSelect.value
            ? parseInt(this._subSelect.value, 10)
            : 0;

        if (!filter_id) {
            this._render(this._products);
            return;
        }

        try {
            const res = await rpc("/inspiration/filter", { filter_type: type, filter_id });
            const products = res && Array.isArray(res.products) ? res.products : [];
            this._render(products);
        } catch (e) {
            this._render([]);
        }
    },

    _render(products) {
        if (!this._gridEl) return;

        const list = Array.isArray(products) ? products : [];
        this._gridEl.innerHTML = "";

        list.forEach((p) => {
            const a = document.createElement("a");
            a.className = "lx_card";
            a.href = p.url || "#";

            const imgWrap = document.createElement("div");
            imgWrap.className = "lx_img";

            const img = document.createElement("img");
            img.loading = "lazy";
            img.src = p.img || "";
            img.alt = p.name || "";

            const title = document.createElement("div");
            title.className = "lx_name";
            title.textContent = p.name || "";

            imgWrap.appendChild(img);
            a.appendChild(imgWrap);
            a.appendChild(title);
            this._gridEl.appendChild(a);
        });

        if (this._countEl) {
            this._countEl.textContent = String(list.length) + " item(s)";
        }
    },
});

export default publicWidget.registry.LxInspirationFilters;
