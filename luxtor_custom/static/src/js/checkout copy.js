/** @odoo-module */

import publicWidget from "@web/legacy/js/public/public_widget";

publicWidget.registry.LxTotalWatcherPoll = publicWidget.Widget.extend({
    selector: "#wrapwrap",

    init() {
        this._super(...arguments);
        this._mode = "reload";
        this._lastNum = null;    // last numeric total we used
        this._lastText = null;   // legacy text total (fallback)
        this._timer = null;
        this._intervalMs = 100;
        this._limit = 5000;      // default; can be overridden by DOM
        this._eventCache = null; // last {untaxed, tax, total} from lx:cart:totals
    },

    start() {
        const res = this._super(...arguments);

        // Pick up limit from DOM if present
        const root = document.getElementById("lx-limit-root");
        const domLimit = root && parseFloat(root.dataset.lxLimit || "");
        if (Number.isFinite(domLimit) && domLimit > 0) {
            this._limit = domLimit;
        }

        // Listen to calculator’s live totals (from LxEditLineSubtotalOnly)
        window.addEventListener("lx:cart:totals", (e) => {
            this._eventCache = e?.detail || null;
            if (this._eventCache && Number.isFinite(this._eventCache.total)) {
                const n = this._eventCache.total;
                //this._enforceLimitFromNumber(n);
                this._maybeReact(n);
            }
        });

        // Initial read: prefer event/line-sum; fallback to legacy total text
        const firstNum = this._readSmartTotalNumber();
        if (Number.isFinite(firstNum)) {
            this._lastNum = firstNum;
            //this._enforceLimitFromNumber(firstNum);
        } else {
            this._lastText = this._readTotalText();
            if (this._lastText) this._enforceLimitFromText(this._lastText);
        }

        // Poll as a safety net (theme re-renders, Ajax, etc.)
        this._timer = setInterval(() => this._check(), this._intervalMs);

        // Typical cart events
        document.addEventListener("change", (e) => {
            if (e.target?.classList?.contains("js_quantity")) {
                setTimeout(() => this._check(), 300);
            }
        });
        document.addEventListener("click", (e) => {
            if (
                e.target?.classList?.contains("js_add_cart_json") ||
                e.target?.classList?.contains("a-submit") ||
                e.target?.closest?.(".a-submit")
            ) {
                setTimeout(() => this._check(), 500);
            }
        });

        // Recheck after our forms submit (if page stays)
        ["lx-send-form", "lx-validate-form"].forEach((id) => {
            const f = document.getElementById(id);
            if (f) {
                f.addEventListener("submit", () => setTimeout(() => this._check(), 800));
            }
        });

        return res;
    },

    // --- core ---
    _check() {
        // Prefer our computed total (event or line-sum). Legacy text is last.
        const curNum = this._readSmartTotalNumber();
        if (Number.isFinite(curNum)) {
            //this._enforceLimitFromNumber(curNum);
            this._maybeReact(curNum);
            return;
        }

        const curText = this._readTotalText();
        if (!curText) return;

        // Always enforce (even if unchanged) for legacy path
        this._enforceLimitFromText(curText);

        if (this._lastText === null) {
            this._lastText = curText;
            return;
        }
        if (curText !== this._lastText) {
            if (this._mode === "reload") {
                location.reload();
            } else {
                this._activateFeature(curText, this._lastText);
            }
            this._lastText = curText;
        }
    },

    _maybeReact(newNum) {
        if (this._lastNum === null) {
            this._lastNum = newNum;
            return;
        }
        if (newNum !== this._lastNum) {
            if (this._mode === "reload") {
                location.reload();
            } else {
                this._activateFeature(newNum.toFixed(2), this._lastNum.toFixed(2));
            }
            this._lastNum = newNum;
        }
    },

    _activateFeature(newVal, oldVal) {
        console.log("[LxTotalWatcherPoll] total changed:", oldVal, "→", newVal);
        let flash = document.getElementById("lx-test-flash");
        if (!flash) {
            flash = document.createElement("div");
            flash.id = "lx-test-flash";
            flash.className = "alert alert-info";
            flash.style.position = "fixed";
            flash.style.right = "12px";
            flash.style.bottom = "12px";
            flash.style.zIndex = "9999";
            document.body.appendChild(flash);
        }
        flash.textContent = `Total changed: ${oldVal} → ${newVal}`;
        setTimeout(() => flash.remove(), 1800);
    },

    // --- helpers (smart read order) ---
    _readSmartTotalNumber() {
        // 1) Fresh event totals from calculator
        if (this._eventCache && Number.isFinite(this._eventCache.total)) {
            return this._eventCache.total;
        }
        // 2) Sum current line subtotals (which LxEdit rewrote already)
        const sum = this._sumCurrentLineSubtotals();
        if (sum > 0) return sum;
        // 3) Legacy total text
        const txt = this._readTotalText();
        return txt ? this._parseAmount(txt) : NaN;
    },

    _sumCurrentLineSubtotals() {
        const lines = document.querySelectorAll(".o_cart_product");
        let acc = 0;
        lines.forEach((line) => {
            const el = this._priceEl(line);
            if (el) acc += this._parseAmount(el.textContent);
        });
        return acc;
    },

    _priceEl(line) {
        const container = line.querySelector('[name="website_sale_cart_line_price"]') || line;
        const monies = container.querySelectorAll(".oe_currency_value, .monetary_field");
        if (monies.length) return monies[monies.length - 1];
        return container;
    },

    // --- legacy DOM text reading (fallback) ---
    _readTotalText() {
        const candidates = [
            ".o_wsale_cart_summary .oe_total .oe_currency_value",
            ".o_wsale_cart_summary .oe_total .monetary_field",
            ".js_cart_summary .oe_total .oe_currency_value",
            ".js_cart_summary .oe_total .monetary_field",
            "#amount_total_summary.monetary_field",
            "#order_total .monetary_field",
            "span.oe_currency_value.oe_total",
        ];
        for (const sel of candidates) {
            const el = document.querySelector(sel);
            if (el && el.textContent?.trim()) return el.textContent.trim();
        }
        const labels = Array.from(document.querySelectorAll("td,th,div,span"))
            .filter((el) => /\bTotal\b/i.test((el.textContent || "").trim()));
        for (const lab of labels) {
            const sib = lab.nextElementSibling;
            if (sib && sib.textContent?.trim()) return sib.textContent.trim();
        }
        return null;
    },

    // --- enforcement ---
    _enforceLimitFromNumber(n) {
        const over = Number.isFinite(n) && n > this._limit;
        const btns = document.querySelectorAll(
            'a[name="website_sale_main_button"], .js_proceed_to_checkout, a.btn-primary[href*="/shop/checkout"]'
        );
        
    },

    _enforceLimitFromText(txt) {
        const n = this._parseAmount(txt);
        //this._enforceLimitFromNumber(n);
    },

    // --- parsing ---
    _parseAmount(txt) {
        if (!txt) return 0;
        let v = txt.replace(/[^\d,.\-]/g, "");
        if (v.includes(",") && v.includes(".") && v.lastIndexOf(",") > v.lastIndexOf(".")) {
            v = v.replace(/\./g, "").replace(",", ".");
        } else if (v.includes(",") && !v.includes(".")) {
            v = v.replace(",", ".");
        } else {
            v = v.replace(/,/g, "");
        }
        const n = parseFloat(v);
        return Number.isFinite(n) ? n : 0;
    },

    destroy() {
        if (this._timer) clearInterval(this._timer);
        this._super(...arguments);
    },
});
