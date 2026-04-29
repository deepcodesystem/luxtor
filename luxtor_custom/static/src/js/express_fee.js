/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

publicWidget.registry.ExpressPriceFromBackendFinal = publicWidget.Widget.extend({
    selector: "#lx_express_block",
    events: {
        "change #lx_express_yes": "_onYes",
        "change #lx_express_no": "_onNo",
    },

    init() {
        this._super.apply(this, arguments);
        this._baseline = null;
        this._enabled = false;
        this._unitPrice = 0;
        this._currencySuffix = "";
        this._decimals = 2;
        this._usesComma = false;
        this._lastAddon = 0;
        this._suppressMO = false;
    },

    start() {
        const res = this._super.apply(this, arguments);
        this._snapshotBaselineTotal();
        this._detectCurrencyAndFormat();

        this._fetchExpressUnitPrice().then(() => {
            this._renderMutedText(this._unitPrice);
        });

        const rebound = () => setTimeout(() => this._onQtyChanged(), 0);
        document.addEventListener("change", (ev) => {
            if (ev.target?.classList?.contains("js_quantity")) rebound();
        });
        document.addEventListener("input", (ev) => {
            if (ev.target?.classList?.contains("js_quantity")) rebound();
        });

        return res;
    },

    // ==== Events ====
    _onYes(ev) {
        if (!ev.currentTarget.checked) return;
        this._enabled = true;
        this._lastAddon = 0;
        this._recomputeAndApply();
    },

    _onNo(ev) {
        if (!ev.currentTarget.checked) return;
        const cur = this._parseNumber(this._currentTotalRaw());
        const serverBase = cur - this._lastAddon;
        this._enabled = false;
        this._lastAddon = 0;
        this._suppress(() => this._applyTotal(serverBase));
        this._snapshotBaselineTotal(true);
        this._renderMutedText(this._unitPrice);
    },

    _onQtyChanged() {
        if (this._enabled) this._recomputeAndApply();
    },

    // ==== Core ====
    async _fetchExpressUnitPrice() {
        try {
            const resp = await fetch("/lx/get_price_by_code", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    jsonrpc: "2.0",
                    method: "call",
                    params: { default_code: "PRIORITY_SERVICE" },
                }),
            });
            const txt = await resp.text();
            const json = (() => { try { return JSON.parse(txt); } catch { return null; } })();
            this._unitPrice = Number(json?.result?.price ?? 0) || 0;
        } catch {
            this._unitPrice = 0;
        }
    },

    _recomputeAndApply() {
        const qty = this._currentCartQty();
        const newAddon = (Number(this._unitPrice) || 0) * qty;
        const cur = this._parseNumber(this._currentTotalRaw());
        let serverBase = cur - this._lastAddon;
        if (!Number.isFinite(serverBase)) {
            serverBase = this._baseline?.value ?? cur ?? 0;
        }
        this._suppress(() => this._applyTotal(serverBase + newAddon));
        this._lastAddon = newAddon;
        this._renderMutedText(this._unitPrice); // affiche juste le prix
    },

    // ==== UI ====
    _renderMutedText(unit) {
        const box = document.querySelector("#lx_express_price");
        if (!box) return;
        const u = this._fmt(unit);
        box.textContent = `(+ ${u} DH)`; //  plus de qty
        box.classList.add("text-muted");
        box.style.direction = "ltr";
        box.style.textAlign = "left";
    },

    _applyTotal(value) {
        const el = this._findTotalEl();
        if (!el || value == null) return;
        const raw = el.innerHTML;
        el.innerHTML = this._formatLike(raw, value) + (this._currencySuffix || "");
    },

    // ==== DOM ====
    _snapshotBaselineTotal(force = false) {
        const el = this._findTotalEl();
        if (!el) return;
        if (force) this._baseline = null;
        const raw = el.innerHTML;
        const val = this._parseNumber(raw);
        this._baseline = { el, raw, value: val };
    },

    _currentTotalRaw() {
        const el = this._findTotalEl();
        return el ? el.innerHTML : (this._baseline?.raw || "");
    },

    _findTotalEl() {
        const selectors = [
            "#order_total .monetary_field",
            ".js_cart_summary .oe_total .monetary_field",
            ".oe_total .oe_currency_value",
        ];
        for (const s of selectors) {
            const el = document.querySelector(s);
            if (el) return el;
        }
        return null;
    },


    _currentCartQty() {
        let total = 0;
        document.querySelectorAll(".o_cart_product[data-is-dim='1']").forEach((row) => {
            const inp = row.querySelector(".js_quantity");
            if (!inp) return;
            const v = parseFloat(String(inp.value || "").replace(",", ".")) || 0;
            total += v;
        });
        return total;
    },
    

    _detectCurrencyAndFormat() {
        const raw = this._findTotalEl()?.innerHTML || "";
        const m = /[.,](\d+)/.exec(raw);
        this._decimals = m ? Math.min(Math.max(m[1].length, 0), 2) : 2;
        this._usesComma = raw.includes(",") && !raw.includes(".");
        const symEl = document.querySelector(".oe_currency_symbol, .oe_currency");
        this._currencySuffix = symEl ? ` ${symEl.textContent.trim()}` : "";
    },

    // ==== utils ====
    _suppress(fn) {
        this._suppressMO = true;
        try { fn(); } finally {
            setTimeout(() => (this._suppressMO = false), 0);
        }
    },

    _parseNumber(txt) {
        if (!txt) return 0;
        const onlyNum = txt.replace(/[^\d.,-]/g, "");
        const normalized =
            onlyNum.indexOf(",") > -1 && onlyNum.indexOf(".") === -1
                ? onlyNum.replace(",", ".")
                : onlyNum.replace(/,/g, "");
        return parseFloat(normalized) || 0;
    },

    _formatLike(raw, value) {
        let s = (Number(value) || 0).toFixed(this._decimals);
        if (this._usesComma) s = s.replace(".", ",");
        return s;
    },

    _fmt(value) {
        return (Number(value) || 0).toFixed(2);
    },
});

