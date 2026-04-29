/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

publicWidget.registry.LxPriorityToggle = publicWidget.Widget.extend({
    selector: "#lx_express_block",
    events: {
        "change #lx_express_yes": "_onYes",
        "change #lx_express_no": "_onNo",
    },

    init() {
        this._super(...arguments);
        this._baseline = null;
        this._enabled = false;
        this._unit = 0;
        this._qty = 0;
        this._lastAddon = 0;
        this._decimals = 2;
        this._usesComma = false;
        this._suffix = "";
    },

    async start() {
        const r = this._super.apply(this, arguments);
        this._snapshotBaseline();
        this._detectFormat();
        await this._fetchUnit();
        await this._fetchQty();
        this._renderUnit(this._unit);

        if (document.querySelector("#lx_express_yes")?.checked) {
            this._enabled = true;
            this._recompute();
        }

        const rebound = () => setTimeout(async () => {
            await this._fetchQty();
            if (this._enabled) this._recompute();
        }, 0);

        document.addEventListener("change", (ev) => { if (ev.target?.classList?.contains("js_quantity")) rebound(); });
        document.addEventListener("input",  (ev) => { if (ev.target?.classList?.contains("js_quantity")) rebound(); });

        return r;
    },

    async _fetchUnit() {
        try {
            const res = await rpc("/lx/get_price_by_code", { default_code: "PRIORITY_SERVICE" });
            this._unit = Number(res?.price ?? 0) || 0;
        } catch {
            this._unit = 0;
        }
    },

    async _fetchQty() {
        try {
            const res = await rpc("/lx/mrp_qty", {});
            this._qty = Number(res?.qty_total || 0) || 0;
        } catch {
            this._qty = 0;
        }
    },

    _onYes(ev) {
        if (!ev.currentTarget.checked) return;
        this._enabled = true;
        this._lastAddon = 0;
        this._recompute();
    },

    _onNo(ev) {
        if (!ev.currentTarget.checked) return;
        const cur = this._parse(this._currentTotalRaw());
        const base = cur - this._lastAddon;
        this._enabled = false;
        this._lastAddon = 0;
        this._apply(base);
        this._snapshotBaseline(true);
        this._renderUnit(this._unit);
    },

    _recompute() {
        const addon = (Number(this._unit)||0) * (Number(this._qty)||0);
        const cur = this._parse(this._currentTotalRaw());
        let base = cur - this._lastAddon;
        if (!Number.isFinite(base)) base = this._baseline?.value ?? cur ?? 0;
        this._apply(base + addon);
        this._lastAddon = addon;
        this._renderUnit(this._unit);
    },

    _renderUnit(u) {
        const el = document.querySelector("#lx_express_price");
        if (!el) return;
        el.textContent = `(+ ${(Number(u)||0).toFixed(2)} DH)`;
        el.classList.add("text-muted");
        el.style.direction = "ltr";
        el.style.textAlign = "left";
    },

    _snapshotBaseline(force=false) {
        const el = this._findTotal();
        if (!el) return;
        if (force) this._baseline = null;
        const raw = el.innerHTML;
        const val = this._parse(raw);
        this._baseline = { el, raw, value: val };
    },

    _currentTotalRaw() {
        const el = this._findTotal();
        return el ? el.innerHTML : (this._baseline?.raw || "");
    },

    _findTotal() {
        const sels = [
            "#order_total .monetary_field",
            ".js_cart_summary .oe_total .monetary_field",
            ".oe_total .oe_currency_value",
        ];
        for (const s of sels) {
            const el = document.querySelector(s);
            if (el) return el;
        }
        return null;
    },

    _apply(v) {
        const el = this._findTotal();
        if (!el || v == null) return;
        const raw = el.innerHTML;
        el.innerHTML = this._format(raw, v) + (this._suffix || "");
    },

    _detectFormat() {
        const raw = this._findTotal()?.innerHTML || "";
        const m = /[.,](\d+)/.exec(raw);
        this._decimals = m ? Math.min(Math.max(m[1].length, 0), 2) : 2;
        this._usesComma = raw.includes(",") && !raw.includes(".");
        const sym = document.querySelector(".oe_currency_symbol, .oe_currency");
        this._suffix = sym ? ` ${sym.textContent.trim()}` : " DH";
    },

    _parse(txt) {
        if (!txt) return 0;
        const only = txt.replace(/[^\d.,-]/g, "");
        const norm = (only.indexOf(",")>-1 && only.indexOf(".")===-1) ? only.replace(",", ".") : only.replace(/,/g, "");
        return parseFloat(norm) || 0;
    },

    _format(sample, value) {
        let s = (Number(value)||0).toFixed(this._decimals);
        if (this._usesComma) s = s.replace(".", ",");
        return s;
    },
});

publicWidget.registry.LxInstallToggle = publicWidget.Widget.extend({
    selector: "#lx_express_block",
    events: {
        "change #lx_install_yes": "_onYes",
        "change #lx_install_no": "_onNo",
    },

    init() {
        this._super(...arguments);
        this._baseline = null;
        this._enabled = false;
        this._unit = 0;
        this._qty = 0;
        this._lastAddon = 0;
        this._decimals = 2;
        this._usesComma = false;
        this._suffix = "";
    },

    async start() {
        const r = this._super.apply(this, arguments);
        this._snapshotBaseline();
        this._detectFormat();
        await this._fetchUnit();
        await this._fetchQty();
        this._renderUnit(this._unit);

        if (document.querySelector("#lx_install_yes")?.checked) {
            this._enabled = true;
            this._recompute();
        }

        const rebound = () => setTimeout(async () => {
            await this._fetchQty();
            if (this._enabled) this._recompute();
        }, 0);

        document.addEventListener("change", (ev) => { if (ev.target?.classList?.contains("js_quantity")) rebound(); });
        document.addEventListener("input",  (ev) => { if (ev.target?.classList?.contains("js_quantity")) rebound(); });

        return r;
    },

    async _fetchUnit() {
        try {
            const res = await rpc("/lx/get_price_by_code", { default_code: "INSTALL_SERVICE" });
            this._unit = Number(res?.price ?? 0) || 0;
        } catch {
            this._unit = 0;
        }
    },

    async _fetchQty() {
        try {
            const res = await rpc("/lx/mrp_qty", {});
            this._qty = Number(res?.qty_total || 0) || 0;
        } catch {
            this._qty = 0;
        }
    },

    _onYes(ev) {
        if (!ev.currentTarget.checked) return;
        this._enabled = true;
        this._lastAddon = 0;
        this._recompute();
    },

    _onNo(ev) {
        if (!ev.currentTarget.checked) return;
        const cur = this._parse(this._currentTotalRaw());
        const base = cur - this._lastAddon;
        this._enabled = false;
        this._lastAddon = 0;
        this._apply(base);
        this._snapshotBaseline(true);
        this._renderUnit(this._unit);
    },

    _recompute() {
        const addon = (Number(this._unit)||0) * (Number(this._qty)||0);
        const cur = this._parse(this._currentTotalRaw());
        let base = cur - this._lastAddon;
        if (!Number.isFinite(base)) base = this._baseline?.value ?? cur ?? 0;
        this._apply(base + addon);
        this._lastAddon = addon;
        this._renderUnit(this._unit);
    },

    _renderUnit(u) {
        const el = document.querySelector("#lx_install_price");
        if (!el) return;
        const val = (Number(u)||0).toFixed(2);
        el.textContent = `(+ ${val}${this._suffix ? " " + this._suffix : ""})`;
        el.classList.add("text-muted");
        el.style.direction = "ltr";
        el.style.textAlign = "left";
    },

    _snapshotBaseline(force=false) {
        const el = this._findTotal();
        if (!el) return;
        if (force) this._baseline = null;
        const raw = el.innerHTML;
        const val = this._parse(raw);
        this._baseline = { el, raw, value: val };
    },

    _currentTotalRaw() {
        const el = this._findTotal();
        return el ? el.innerHTML : (this._baseline?.raw || "");
    },

    _findTotal() {
        const sels = [
            "#order_total .monetary_field",
            ".js_cart_summary .oe_total .monetary_field",
            ".oe_total .oe_currency_value",
            ".oe_cart .oe_total .monetary_field",
        ];
        for (const s of sels) {
            const el = document.querySelector(s);
            if (el) return el;
        }
        return null;
    },

    _apply(v) {
        const el = this._findTotal();
        if (!el || v == null) return;
        const raw = el.innerHTML;
        el.innerHTML = this._format(raw, v) + (this._suffix ? " " + this._suffix : "");
    },

    _detectFormat() {
        const raw = this._findTotal()?.innerHTML || "";
        const m = /[.,](\d+)/.exec(raw);
        this._decimals = m ? Math.min(Math.max(m[1].length, 0), 2) : 2;
        this._usesComma = raw.includes(",") && !raw.includes(".");
        const sym = document.querySelector(".oe_currency_symbol, .oe_currency");
        this._suffix = sym ? sym.textContent.trim() : " DH";
    },

    _parse(txt) {
        if (!txt) return 0;
        const only = txt.replace(/[^\d.,-]/g, "");
        const norm = (only.indexOf(",")>-1 && only.indexOf(".")===-1) ? only.replace(",", ".") : only.replace(/,/g, "");
        return parseFloat(norm) || 0;
    },

    _format(sample, value) {
        let s = (Number(value)||0).toFixed(this._decimals);
        if (this._usesComma) s = s.replace(".", ",");
        return s;
    },
});



/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

function fmt(n, d, comma) {
    let s = (Number(n) || 0).toFixed(d);
    if (comma) s = s.replace(".", ",");
    return s;
}
function $total() {
    return document.querySelector(
        "#order_total .monetary_field, " +
        ".js_cart_summary .oe_total .monetary_field, " +
        ".oe_total .oe_currency_value, " +
        ".oe_cart .oe_total .monetary_field"
    );
}
async function callApply(code, enabled, qty) {
    return rpc("/lx/service/apply", { code, enabled, qty });
}
async function callRemove(code) {
    return rpc("/lx/service/remove", { code });
}
function _hasServiceLine(code) {
    return !!document.querySelector(`#cart_products [data-default-code="${code}"]`);
}
function _removeServiceLine(code) {
    document.querySelectorAll(`#cart_products [data-default-code="${code}"]`).forEach(n => n.remove());
}

/* STRICT radio sync: always uncheck both first, then check the target */
function _setRadioPair(yesSel, noSel, checked) {
    const yes = document.querySelector(yesSel);
    const no  = document.querySelector(noSel);
    if (!yes || !no) return false;

    // hard reset both states (property + attribute for some browsers/themes)
    [yes, no].forEach(r => {
        r.checked = false;
        r.removeAttribute("checked");
        const lab = r.nextElementSibling;
        if (lab) lab.setAttribute("aria-checked", "false");
    });

    const tgt = checked ? yes : no;
    tgt.checked = true;
    tgt.setAttribute("checked", "checked");
    const labT = tgt.nextElementSibling;
    if (labT) labT.setAttribute("aria-checked", "true");

    return checked;
}

/* -------------------------
   PRIORITY SERVICE TOGGLE
------------------------- */
publicWidget.registry.LxPriorityToggle = publicWidget.Widget.extend({
    selector: "#lx_express_block",
    events: {
        "change #lx_express_yes": "_onYes",
        "change #lx_express_no": "_onNo",
    },

    init() {
        this._super(...arguments);
        this._baseline = null;
        this._enabled = false;
        this._unit = 0;
        this._qty = 0;
        this._lastAddon = 0;
        this._decimals = 2;
        this._usesComma = false;
        this._suffix = "";
        this._code = "PRIORITY_SERVICE";
        this._op = 0;
        this._qtyWatchBound = false;
    },

    async start() {
        const r = this._super.apply(this, arguments);
        this._snapshotBaseline();
        this._detectFormat();
        await this._fetchUnit();
        await this._fetchQty();
        this._renderUnit(this._unit);

        const present = _hasServiceLine(this._code);
        _setRadioPair("#lx_express_yes", "#lx_express_no", present);

        if (present) {
            this._enabled = true;
            this._recompute();
            await this._syncApply();
        } else {
            this._enabled = false;
            await this._syncRemove();
        }
        this._bindQtyWatcher();
        return r;
    },

    _bindQtyWatcher() {
        if (this._qtyWatchBound) return;
        const rebound = () => setTimeout(async () => {
            await this._fetchQty();
            if (this._enabled) {
                this._recompute();
                await this._syncApply();
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

    async _fetchUnit() {
        try {
            const res = await rpc("/lx/get_price_by_code", { default_code: this._code });
            this._unit = Number(res?.price ?? 0) || 0;
        } catch { this._unit = 0; }
    },
    async _fetchQty() {
        try {
            const res = await rpc("/lx/mrp_qty", {});
            this._qty = Number(res?.qty_total || 0) || 0;
        } catch { this._qty = 0; }
    },

    async _onYes(ev) {
        if (!ev.currentTarget.checked) return;
        _setRadioPair("#lx_express_yes", "#lx_express_no", true);
        this._enabled = true;
        this._lastAddon = 0;
        this._recompute();
        await this._syncApply();
    },
    async _onNo(ev) {
        if (!ev.currentTarget.checked) return;
        _setRadioPair("#lx_express_yes", "#lx_express_no", false);
        this._enabled = false;
        this._lastAddon = 0;
        await this._syncRemove();
        _removeServiceLine(this._code);
    },

    _recompute() {
        const addon = (Number(this._unit) || 0) * (Number(this._qty) || 0);
        const cur = this._parse(this._currentTotalRaw());
        let base = cur - this._lastAddon;
        if (!Number.isFinite(base)) base = this._baseline?.value ?? cur ?? 0;
        this._apply(base + addon);
        this._lastAddon = addon;
        this._renderUnit(this._unit);
    },

    async _syncApply() {
        const op = ++this._op;
        const res = await callApply(this._code, true, this._qty);
        if (op !== this._op) return;
        if (res?.ok) this._applyServerTotal(res);
    },
    async _syncRemove() {
        const op = ++this._op;
        const res = await callRemove(this._code);
        if (op !== this._op) return;
        if (res?.ok) {
            this._applyServerTotal(res);
            _removeServiceLine(this._code);
        }
    },

    _applyServerTotal(res) {
        const el = $total();
        const dec = res.decimals != null ? res.decimals : this._decimals;
        const suf = res.currency ? `${res.currency}` : this._suffix;
        if (el) el.innerHTML = fmt(res.total, dec, this._usesComma) + suf;
        this._decimals = dec;
        this._suffix = suf;
        this._snapshotBaseline(true);
        this._renderUnit(this._unit);
    },

    _renderUnit(u) {
        const el = document.querySelector("#lx_express_price");
        if (!el) return;
        el.textContent = `+ ${fmt(u, 2, false)}${this._suffix}`;
        el.classList.add("text-muted");
        el.style.direction = "ltr";
        el.style.textAlign = "left";
    },

    _snapshotBaseline(force = false) {
        const el = this._findTotal();
        if (!el) return;
        if (force) this._baseline = null;
        const raw = el.innerHTML;
        const val = this._parse(raw);
        this._baseline = { el, raw, value: val };
    },
    _currentTotalRaw() {
        const el = this._findTotal();
        return el ? el.innerHTML : (this._baseline?.raw || "");
    },
    _findTotal() {
        const sels = [
            "#order_total .monetary_field",
            ".js_cart_summary .oe_total .monetary_field",
            ".oe_total .oe_currency_value",
            ".oe_cart .oe_total .monetary_field",
        ];
        for (const s of sels) {
            const el = document.querySelector(s);
            if (el) return el;
        }
        return null;
    },
    _apply(v) {
        const el = this._findTotal();
        if (!el || v == null) return;
        el.innerHTML = fmt(v, this._decimals, this._usesComma) + (this._suffix || "");
    },
    _detectFormat() {
        const raw = this._findTotal()?.innerHTML || "";
        const m = /[.,](\d+)/.exec(raw);
        this._decimals = m ? Math.min(Math.max(m[1].length, 0), 2) : 2;
        this._usesComma = raw.includes(",") && !raw.includes(".");
        const sym = document.querySelector(".oe_currency_symbol, .oe_currency");
        this._suffix = sym ? `${sym.textContent.trim()}` : " DH";
    },
    _parse(txt) {
        if (!txt) return 0;
        const only = txt.replace(/[^\d.,-]/g, "");
        const norm = (only.indexOf(",") > -1 && only.indexOf(".") === -1)
            ? only.replace(",", ".")
            : only.replace(/,/g, "");
        return parseFloat(norm) || 0;
    },
});

/* -------------------------
   INSTALLATION SERVICE TOGGLE
------------------------- */
publicWidget.registry.LxInstallToggle = publicWidget.Widget.extend({
    selector: "#lx_express_block",
    events: {
        "change #lx_install_yes": "_onYes",
        "change #lx_install_no": "_onNo",
    },

    init() {
        this._super(...arguments);
        this._baseline = null;
        this._enabled = false;
        this._unit = 0;
        this._qty = 0;
        this._lastAddon = 0;
        this._decimals = 2;
        this._usesComma = false;
        this._suffix = "";
        this._code = "INSTALL_SERVICE";
        this._op = 0;
        this._qtyWatchBound = false;
    },

    async start() {
        const r = this._super.apply(this, arguments);
        this._snapshotBaseline();
        this._detectFormat();
        await this._fetchUnit();
        await this._fetchQty();
        this._renderUnit(this._unit);

        const present = _hasServiceLine(this._code);
        _setRadioPair("#lx_install_yes", "#lx_install_no", present);

        if (present) {
            this._enabled = true;
            this._recompute();
            await this._syncApply();
        } else {
            this._enabled = false;
            await this._syncRemove();
        }
        this._bindQtyWatcher();
        return r;
    },

    _bindQtyWatcher() {
        if (this._qtyWatchBound) return;
        const rebound = () => setTimeout(async () => {
            await this._fetchQty();
            if (this._enabled) {
                this._recompute();
                await this._syncApply();
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

    async _fetchUnit() {
        try {
            const res = await rpc("/lx/get_price_by_code", { default_code: this._code });
            this._unit = Number(res?.price ?? 0) || 0;
        } catch { this._unit = 0; }
    },
    async _fetchQty() {
        try {
            const res = await rpc("/lx/mrp_qty", {});
            this._qty = Number(res?.qty_total || 0) || 0;
        } catch { this._qty = 0; }
    },

    async _onYes(ev) {
        if (!ev.currentTarget.checked) return;
        _setRadioPair("#lx_install_yes", "#lx_install_no", true);
        this._enabled = true;
        this._lastAddon = 0;
        this._recompute();
        await this._syncApply();
    },
    async _onNo(ev) {
        if (!ev.currentTarget.checked) return;
        _setRadioPair("#lx_install_yes", "#lx_install_no", false);
        this._enabled = false;
        this._lastAddon = 0;
        await this._syncRemove();
        _removeServiceLine(this._code);
    },

    _recompute() {
        const addon = (Number(this._unit) || 0) * (Number(this._qty) || 0);
        const cur = this._parse(this._currentTotalRaw());
        let base = cur - this._lastAddon;
        if (!Number.isFinite(base)) base = this._baseline?.value ?? cur ?? 0;
        this._apply(base + addon);
        this._lastAddon = addon;
        this._renderUnit(this._unit);
    },

    async _syncApply() {
        const op = ++this._op;
        const res = await callApply(this._code, true, this._qty);
        if (op !== this._op) return;
        if (res?.ok) this._applyServerTotal(res);
    },
    async _syncRemove() {
        const op = ++this._op;
        const res = await callRemove(this._code);
        if (op !== this._op) return;
        if (res?.ok) {
            this._applyServerTotal(res);
            _removeServiceLine(this._code);
        }
    },

    _applyServerTotal(res) {
        const el = $total();
        const dec = res.decimals != null ? res.decimals : this._decimals;
        const suf = res.currency ? `${res.currency}` : this._suffix;
        if (el) el.innerHTML = fmt(res.total, dec, this._usesComma) + suf;
        this._decimals = dec;
        this._suffix = suf;
        this._snapshotBaseline(true);
        this._renderUnit(this._unit);
    },

    _renderUnit(u) {
        const el = document.querySelector("#lx_install_price");
        if (!el) return;
        el.textContent = `+ ${fmt(u, 2, false)}${this._suffix}`;
        el.classList.add("text-muted");
        el.style.direction = "ltr";
        el.style.textAlign = "left";
    },

    _snapshotBaseline(force = false) {
        const el = this._findTotal();
        if (!el) return;
        if (force) this._baseline = null;
        const raw = el.innerHTML;
        const val = this._parse(raw);
        this._baseline = { el, raw, value: val };
    },
    _currentTotalRaw() {
        const el = this._findTotal();
        return el ? el.innerHTML : (this._baseline?.raw || "");
    },
    _findTotal() {
        const sels = [
            "#order_total .monetary_field",
            ".js_cart_summary .oe_total .monetary_field",
            ".oe_total .oe_currency_value",
            ".oe_cart .oe_total .monetary_field",
        ];
        for (const s of sels) {
            const el = document.querySelector(s);
            if (el) return el;
        }
        return null;
    },
    _apply(v) {
        const el = this._findTotal();
        if (!el || v == null) return;
        el.innerHTML = fmt(v, this._decimals, this._usesComma) + (this._suffix || "");
    },
    _detectFormat() {
        const raw = this._findTotal()?.innerHTML || "";
        const m = /[.,](\d+)/.exec(raw);
        this._decimals = m ? Math.min(Math.max(m[1].length, 0), 2) : 2;
        this._usesComma = raw.includes(",") && !raw.includes(".");
        const sym = document.querySelector(".oe_currency_symbol, .oe_currency");
        this._suffix = sym ? `${sym.textContent.trim()}` : " DH";
    },
    _parse(txt) {
        if (!txt) return 0;
        const only = txt.replace(/[^\d.,-]/g, "");
        const norm = (only.indexOf(",") > -1 && only.indexOf(".") === -1)
            ? only.replace(",", ".")
            : only.replace(/,/g, "");
        return parseFloat(norm) || 0;
    },
});
