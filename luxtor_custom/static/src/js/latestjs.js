/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

publicWidget.registry.LxDeliveryDynamic = publicWidget.Widget.extend({
    selector: ".oe_website_sale",

    start() {
        this._super(...arguments);

        this._busy = false;
        this._timer = null;
        this._lastSig = null;

        this._installDebugPanel();
        this._log("LX Shipping Debug: enabled");

        this._bindCaptureBlocker();
        this._bindEvents();
        this._computeOnLoad();

        return Promise.resolve();
    },

    _bindCaptureBlocker() {
        document.addEventListener(
            "click",
            (ev) => {
                const t = ev && ev.target ? ev.target : null;
                if (!t) return;

                if (t.matches("input[type='radio'][name='o_delivery_radio']")) {
                    ev.preventDefault();
                    ev.stopPropagation();
                    ev.stopImmediatePropagation();

                    t.checked = true;
                    const cid = this._carrierId(t);
                    if (cid) this._scheduleCompute(cid, "carrier_click");
                    return;
                }

                const label = t.closest("label[for^='o_delivery_']");
                if (label) {
                    const forId = label.getAttribute("for");
                    const r = forId ? document.getElementById(forId) : null;
                    if (r && r.matches("input[type='radio'][name='o_delivery_radio']")) {
                        ev.preventDefault();
                        ev.stopPropagation();
                        ev.stopImmediatePropagation();

                        r.checked = true;
                        const cid = this._carrierId(r);
                        if (cid) this._scheduleCompute(cid, "carrier_label_click");
                    }
                }
            },
            true
        );
    },

    _installDebugPanel() {
        if (document.getElementById("lx_ship_panel")) return;

        const box = document.createElement("div");
        box.id = "lx_ship_panel";
        box.style.position = "fixed";
        box.style.right = "14px";
        box.style.bottom = "14px";
        box.style.width = "420px";
        box.style.maxWidth = "92vw";
        box.style.maxHeight = "46vh";
        box.style.overflow = "auto";
        box.style.background = "#111827";
        box.style.color = "#fff";
        box.style.padding = "12px";
        box.style.borderRadius = "10px";
        box.style.boxShadow = "0 10px 25px rgba(0,0,0,.25)";
        box.style.fontSize = "12px";
        box.style.zIndex = "99999";

        const head = document.createElement("div");
        head.style.display = "flex";
        head.style.justifyContent = "space-between";
        head.style.alignItems = "center";
        head.style.marginBottom = "8px";

        const title = document.createElement("div");
        title.textContent = "LX Shipping Debug";
        title.style.fontWeight = "800";

        const btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = "Clear";
        btn.style.background = "#374151";
        btn.style.color = "#fff";
        btn.style.border = "0";
        btn.style.padding = "6px 10px";
        btn.style.borderRadius = "8px";
        btn.style.cursor = "pointer";
        btn.addEventListener("click", () => {
            const pre = document.getElementById("lx_ship_log");
            if (pre) pre.textContent = "";
        });

        const pre = document.createElement("pre");
        pre.id = "lx_ship_log";
        pre.style.whiteSpace = "pre-wrap";
        pre.style.wordBreak = "break-word";
        pre.style.margin = "0";

        head.appendChild(title);
        head.appendChild(btn);
        box.appendChild(head);
        box.appendChild(pre);

        document.body.appendChild(box);
    },

    _log(msg, obj) {
        const pre = document.getElementById("lx_ship_log");
        if (!pre) return;

        const line = obj ? msg + "\n" + JSON.stringify(obj, null, 2) : msg;
        pre.textContent = (line + "\n\n" + pre.textContent).slice(0, 30000);
    },

    _carrierId(el) {
        const v = (el && el.value) || (el && el.dataset ? el.dataset.dmId : "");
        const n = parseInt(v || "0", 10);
        return n > 0 ? n : 0;
    },

    _selectedCarrierId() {
        const el = document.querySelector("input[type='radio'][name='o_delivery_radio']:checked");
        return el ? this._carrierId(el) : 0;
    },

    _badge(carrierId) {
        return document.querySelector(
            ".o_wsale_delivery_price_badge[name='price'][data-carrier-id='" + carrierId + "']"
        );
    },

    _setBadge(carrierId, text) {
        const b = this._badge(carrierId);
        if (b) b.textContent = text;
    },

    _zipValue() {
        const z = document.querySelector("input[name='zip'], input[name='zipcode'], input[name='postal_code']");
        return z ? String(z.value || "").trim() : "";
    },

    _addrKey() {
        const sel =
            document.querySelector("select[name='shipping_address_id']") ||
            document.querySelector("select[name='partner_id']") ||
            document.querySelector("select[name='address_id']");
        return sel ? String(sel.value || "") : "";
    },

    _computeOnLoad() {
        const cid = this._selectedCarrierId();
        if (cid) this._scheduleCompute(cid, "on_load");
    },

    _bindEvents() {
        document.addEventListener("change", (ev) => {
            const t = ev && ev.target ? ev.target : null;
            if (!t) return;

            if (t.matches("select[name='partner_id'], select[name='shipping_address_id'], select[name='address_id']")) {
                const cid = this._selectedCarrierId();
                if (cid) this._scheduleCompute(cid, "address_change");
                return;
            }

            if (t.matches("input[name='zip'], input[name='zipcode'], input[name='postal_code']")) {
                const cid = this._selectedCarrierId();
                if (cid) this._scheduleCompute(cid, "zip_change");
                return;
            }
        });

        document.addEventListener("input", (ev) => {
            const t = ev && ev.target ? ev.target : null;
            if (!t) return;

            if (t.matches("input[name='zip'], input[name='zipcode'], input[name='postal_code']")) {
                const cid = this._selectedCarrierId();
                if (cid) this._scheduleCompute(cid, "zip_typing");
            }
        });
    },

    _scheduleCompute(carrierId, reason) {
        const sig = JSON.stringify({
            carrier: carrierId,
            zip: this._zipValue(),
            addr: this._addrKey(),
        });

        if (sig === this._lastSig && reason !== "carrier_click" && reason !== "carrier_label_click") {
            this._log("Skip same state", { reason, sig });
            return;
        }

        if (this._timer) clearTimeout(this._timer);
        this._timer = setTimeout(() => this._computeAndWrite(carrierId, sig, reason), 160);

        this._log("Schedule compute: " + reason, { sig });
    },

    async _computeAndWrite(carrierId, sig, reason) {
        if (this._busy) return;
        this._busy = true;

        try {
            this._setBadge(carrierId, "Calcul...");

            const res = await rpc("/shop/carrier_rate_shipment", { carrier_id: carrierId });
            this._log("RPC response", res);

            this._lastSig = sig;

            if (res && res.status === "success") {
                const amount = Number(res.new_amount_delivery || 0);
                const formatted = this._fmtMoneyFromRes(amount, res);

                this._setBadge(carrierId, formatted);
                this._setDeliveryLineText(formatted);
                await this._refreshCartTotalBlock();

                return;
            }

            this._setBadge(carrierId, "—");
        } catch (e) {
            this._log("RPC error", { message: e && e.message ? e.message : String(e), reason });
            this._setBadge(carrierId, "—");
        } finally {
            this._busy = false;
        }
    },

    _fmtMoneyFromRes(amount, res) {
        const cur = res && res.lx_debug && res.lx_debug.currency ? res.lx_debug.currency : null;
        const dp = cur && typeof cur.decimal_places === "number" ? cur.decimal_places : 2;
        const symbol = cur && cur.symbol ? cur.symbol : "DH";
        const pos = cur && cur.position ? cur.position : "after";

        const n = Number(amount || 0);
        const txt = n.toFixed(dp);

        return pos === "before" ? symbol + " " + txt : txt + " " + symbol;
    },

    _setDeliveryLineText(formatted) {
        const tr = document.getElementById("order_delivery");
        if (!tr) return;

        const no = tr.querySelector("#message_no_dm_set");
        if (no) return;

        const span = tr.querySelector("span.monetary_field");
        if (!span) return;

        span.textContent = formatted;
    },

    async _refreshCartTotalBlock() {
        try {
            const cur = document.getElementById("cart_total");
            if (!cur) {
                this._log("Cart total refresh: #cart_total not found on current page");
                return;
            }

            const url = window.location.href.split("#")[0];
            const html = await fetch(url, {
                method: "GET",
                credentials: "same-origin",
                headers: { "X-Requested-With": "XMLHttpRequest" },
            }).then((r) => r.text());

            const doc = new DOMParser().parseFromString(html, "text/html");
            const fresh = doc.getElementById("cart_total");

            if (!fresh) {
                this._log("Cart total refresh: #cart_total not found in fetched HTML");
                return;
            }

            cur.replaceWith(fresh);
            this._log("Cart total refreshed (#cart_total replaced)");
        } catch (e) {
            this._log("Cart total refresh error", { message: e && e.message ? e.message : String(e) });
        }
    },
});

/* ---------- widget ---------- */
publicWidget.registry.LxPriorityToggle = publicWidget.Widget.extend({
    selector: "#lx_express_block",
    events: {
        "change #lx_express_yes": "_onYes",
        "change #lx_express_no": "_onNo",
    },

    init() {
        this._super(...arguments);
        this._enabled = false;
        this._unit = 0;
        this._unitFormatted = "";
        this._qty = 0;
        this._op = 0;
        this._qtyWatchBound = false;
    },

    async start() {
        const r = this._super.apply(this, arguments);
        await this._fetchUnit();
        await this._fetchQty();
        this._renderUnitOnly();
        await this._syncInitialRadios();
        this._setupDomObservers();
        this._bindQtyWatcher();
        return r;
    },

    /* ---------- RPC wrappers ---------- */
    _rpcPrice() { return rpc("/lx/priority/price", {}); },
    _rpcMrpQty() { return rpc("/lx/priority/mrp_qty", {}); },
    _rpcHas()   { return rpc("/lx/priority/has", {}); },
    _rpcApply(enabled, qty) { return rpc("/lx/priority/apply", { enabled, qty }); },
    _rpcRemove() { return rpc("/lx/priority/remove", {}); },

    /* ---------- loaders ---------- */
    async _fetchUnit() {
        try {
            const res = await this._rpcPrice();
            if (res?.ok) {
                this._unit = Number(res.unit_price || 0);
                this._unitFormatted = res.unit_formatted || "";
            } else {
                this._unit = 0;
                this._unitFormatted = "";
            }
        } catch {
            this._unit = 0;
            this._unitFormatted = "";
        }
    },
    async _fetchQty() {
        try {
            const res = await this._rpcMrpQty();
            this._qty = Number(res?.qty_total || 0) || 0;
        } catch {
            this._qty = 0;
        }
    },

    /* ---------- radios ---------- */
    async _syncInitialRadios() {
        try {
            const res = await this._rpcHas();
            const present = !!(res && res.ok && res.enabled);
            setRadioPair("#lx_express_yes", "#lx_express_no", present);
            this._enabled = present;
            setTimeout(async () => {
                const r2 = await this._rpcHas();
                const p2 = !!(r2 && r2.ok && r2.enabled);
                setRadioPair("#lx_express_yes", "#lx_express_no", p2);
                this._enabled = p2;
            }, 150);
        } catch { /* ignore */ }
    },
    _setupDomObservers() {
        const resync = async () => {
            try {
                const res = await this._rpcHas();
                const present = !!(res && res.ok && res.enabled);
                setRadioPair("#lx_express_yes", "#lx_express_no", present);
                this._enabled = present;
            } catch { /* ignore */ }
        };
        const block = document.querySelector("#lx_express_block");
        if (block) {
            const mo = new MutationObserver(() => resync());
            mo.observe(block, { childList: true, subtree: true });
        }
    },

    /* ---------- render ---------- */
    _renderUnitOnly() {
        const el = document.querySelector("#lx_express_price");
        if (!el) return;
        el.textContent = this._unitFormatted || "";
        el.classList.add("text-muted");
        el.style.direction = "ltr";
        el.style.textAlign = "right";
        el.style.cssFloat = "right";
    },

    /* ---------- events ---------- */
    async _onYes(ev) {
        if (!ev.currentTarget.checked) return;
        setRadioPair("#lx_express_yes", "#lx_express_no", true);
        this._enabled = true;
        await this._fetchQty();
        this._renderUnitOnly();

        const op = ++this._op;
        const res = await this._rpcApply(true, this._qty);
        if (op !== this._op) return;
        if (res?.ok) {
            applyServerTotalFormatted(res);
            if (typeof res.unit_formatted === "string") this._unitFormatted = res.unit_formatted;
            this._renderUnitOnly();

            setTimeout(() => location.reload(), 400);
        }
    },

    async _onNo(ev) {
        if (!ev.currentTarget.checked) return;
        setRadioPair("#lx_express_yes", "#lx_express_no", false);
        this._enabled = false;

        const op = ++this._op;
        const res = await this._rpcRemove();
        if (op !== this._op) return;
        if (res?.ok) {
            applyServerTotalFormatted(res);
            setRadioPair("#lx_express_yes", "#lx_express_no", false);
            this._enabled = false;
            if (typeof res.unit_formatted === "string") this._unitFormatted = res.unit_formatted;
            this._renderUnitOnly();

            // 🔁 Force fast reload (sync totals and DOM)
            setTimeout(() => location.reload(), 400);
        }
    },

    _bindQtyWatcher() {
        if (this._qtyWatchBound) return;
        const rebound = () =>
            setTimeout(async () => {
                await this._fetchQty();
                if (this._enabled) {
                    const op = ++this._op;
                    const res = await this._rpcApply(true, this._qty);
                    if (op !== this._op) return;
                    if (res?.ok) {
                        applyServerTotalFormatted(res);
                        if (typeof res.unit_formatted === "string") this._unitFormatted = res.unit_formatted;
                        this._renderUnitOnly();

                        setTimeout(() => location.reload(), 400);
                    }
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
});

export default publicWidget.registry.LxPriorityToggle;

function findTotalEl() {
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
}
function applyServerTotalFormatted(res) {
    const el = findTotalEl();
    if (el && res?.total_formatted) {
        el.innerHTML = res.total_formatted;
    }
}
function setRadioPair(yesSel, noSel, checked) {
    const yes = document.querySelector(yesSel);
    const no = document.querySelector(noSel);
    if (!yes || !no) return false;
    [yes, no].forEach((r) => {
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

/* ---------- widget ---------- */
publicWidget.registry.LxInstallToggle = publicWidget.Widget.extend({
    selector: "#lx_express_block", // radios: #lx_install_yes / #lx_install_no
    events: {
        "change #lx_install_yes": "_onYes",
        "change #lx_install_no": "_onNo",
    },

    init() {
        this._super(...arguments);
        this._enabled = false;
        this._unitFormatted = "";
        this._qty = 0;
        this._op = 0;
        this._qtyWatchBound = false;
    },

    async start() {
        const r = this._super.apply(this, arguments);
        await this._fetchUnit();
        await this._fetchQty();
        this._renderUnitOnly();
        await this._syncInitialRadios();
        this._setupDomObservers();
        this._bindQtyWatcher();
        return r;
    },

    /* ---------- RPC wrappers ---------- */
    _rpcPrice() { return rpc("/lx/install/price", {}); },
    _rpcMrpQty() { return rpc("/lx/install/mrp_qty", {}); },
    _rpcHas()   { return rpc("/lx/install/has", {}); },
    _rpcApply(enabled, qty) { return rpc("/lx/install/apply", { enabled, qty }); },
    _rpcRemove() { return rpc("/lx/install/remove", {}); },

    /* ---------- loaders ---------- */
    async _fetchUnit() {
        try {
            const res = await this._rpcPrice();
            this._unitFormatted = res?.ok ? (res.unit_formatted || "") : "";
        } catch { this._unitFormatted = ""; }
    },
    async _fetchQty() {
        try {
            const res = await this._rpcMrpQty();
            this._qty = Number(res?.qty_total || 0) || 0;
        } catch { this._qty = 0; }
    },

    /* ---------- radios ---------- */
    async _syncInitialRadios() {
        try {
            const res = await this._rpcHas();
            const present = !!(res && res.ok && res.enabled);
            setRadioPair("#lx_install_yes", "#lx_install_no", present);
            this._enabled = present;
            setTimeout(async () => {
                const r2 = await this._rpcHas();
                const p2 = !!(r2 && r2.ok && r2.enabled);
                setRadioPair("#lx_install_yes", "#lx_install_no", p2);
                this._enabled = p2;
            }, 150);
        } catch { /* ignore */ }
    },
    _setupDomObservers() {
        const resync = async () => {
            try {
                const res = await this._rpcHas();
                const present = !!(res && res.ok && res.enabled);
                setRadioPair("#lx_install_yes", "#lx_install_no", present);
                this._enabled = present;
            } catch { /* ignore */ }
        };
        const block = document.querySelector("#lx_express_block");
        if (block) {
            const mo = new MutationObserver(() => resync());
            mo.observe(block, { childList: true, subtree: true });
        }
        const cart = document.getElementById("cart_products");
        if (cart) {
            const mo2 = new MutationObserver(() => resync());
            mo2.observe(cart, { childList: true, subtree: true });
        }
    },

    /* ---------- render ---------- */
    _renderUnitOnly() {
        const el = document.querySelector("#lx_install_price");
        if (!el) return;
        // unit only, no qty
        el.textContent = this._unitFormatted || "";
        el.classList.add("text-muted");
        el.style.direction = "ltr";
        el.style.textAlign = "right";
        el.style.cssFloat = "right";
    },

    /* ---------- events ---------- */
    async _onYes(ev) {
        if (!ev.currentTarget.checked) return;
        setRadioPair("#lx_install_yes", "#lx_install_no", true);
        this._enabled = true;

        await this._fetchQty();
        const op = ++this._op;
        const res = await this._rpcApply(true, this._qty);
        if (op !== this._op) return;
        if (res?.ok) {
            applyServerTotalFormatted(res);
            if (typeof res.unit_formatted === "string") this._unitFormatted = res.unit_formatted;
            this._renderUnitOnly();
            // Force full sync (lines/discounts/delivery)
            setTimeout(() => location.reload(), 400);
        }
    },

    async _onNo(ev) {
        if (!ev.currentTarget.checked) return;
        setRadioPair("#lx_install_yes", "#lx_install_no", false);
        this._enabled = false;

        const op = ++this._op;
        const res = await this._rpcRemove();
        if (op !== this._op) return;
        if (res?.ok) {
            applyServerTotalFormatted(res);
            if (typeof res.unit_formatted === "string") this._unitFormatted = res.unit_formatted;
            this._renderUnitOnly();
            setTimeout(() => location.reload(), 400);
        }
    },

    _bindQtyWatcher() {
        if (this._qtyWatchBound) return;
        const rebound = () => setTimeout(async () => {
            await this._fetchQty();
            if (this._enabled) {
                const op = ++this._op;
                const res = await this._rpcApply(true, this._qty);
                if (op !== this._op) return;
                if (res?.ok) {
                    applyServerTotalFormatted(res);
                    if (typeof res.unit_formatted === "string") this._unitFormatted = res.unit_formatted;
                    this._renderUnitOnly();
                    setTimeout(() => location.reload(), 400);
                }
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
});

publicWidget.registry.LxHeadrailTitles = publicWidget.Widget.extend({
    selector: '.oe_website_sale',

    start() {
        this._applyTitles();

        this._onChange = this._applyTitles.bind(this);
        this.el.addEventListener('change', this._onChange, { passive: true });
        this.el.addEventListener('click', this._onChange, { passive: true });

        const root = this.el.querySelector('.js_add_cart_variants') || this.el;
        this._observer = new MutationObserver(() => this._applyTitles());
        this._observer.observe(root, { childList: true, subtree: true });

        return this._super(...arguments);
    },

    destroy() {
        if (this._observer) this._observer.disconnect();
        if (this._onChange) {
            this.el.removeEventListener('change', this._onChange);
            this.el.removeEventListener('click', this._onChange);
        }
        return this._super(...arguments);
    },

    _mapPrettyName(name) {
        const n = (name || '').trim();
        if (/R-?002-?21/i.test(n)) return 'Futura';
        if (/R-?002-?22/i.test(n)) return 'Futura +';
        return n;
    },

    _applyTitles() {
        const variants = this.el.querySelector('.js_add_cart_variants');
        if (!variants) return;

        // Only FIRST variant group (Headrail)
        const firstAttr = variants.querySelector('li.variant_attribute');
        if (!firstAttr) return;

        firstAttr.querySelectorAll('li.list-inline-item').forEach((item) => {
            const label = item.querySelector('label.css_attribute_color');
            const input = item.querySelector('input.js_variant_change');
            if (!label || !input) return;

            // Read value name from input and prettify
            const raw = input.getAttribute('data-value_name') || input.dataset.value_name || '';
            const pretty = this._mapPrettyName(raw);

            // Card scaffolding styles (inline to survive re-renders)
            label.style.display = 'grid';
            label.style.gridTemplateRows = '1fr auto';
            label.style.placeItems = 'center';

            // Title
            let span = label.querySelector('.lx-var-title');
            if (!span) {
                span = document.createElement('span');
                span.className = 'lx-var-title';
                label.appendChild(span);
            }
            if (span.textContent !== pretty) {
                span.textContent = pretty;
            }

            // Add a subtle image pad wrapper if not present (keeps image from touching border)
            let pad = label.querySelector('.lx-img-pad');
            if (!pad) {
                pad = document.createElement('div');
                pad.className = 'lx-img-pad';
                // move label’s ::before visual into this pad effect via CSS
                label.insertBefore(pad, span);
            }
        });
    },
});

publicWidget.registry.LxAttributeInfoMessages = publicWidget.Widget.extend({
    selector: ".js_add_cart_variants",

    start() {
        this._applyInfo();
        this._bindObserver();
        return this._super(...arguments);
    },

    _norm(s) {
        return (s || "").trim().toUpperCase();
    },

    _applyInfo() {
        const root = this.el || document;
        const items = root.querySelectorAll("li.variant_attribute[data-attribute_name]");

        items.forEach((li) => {
            const attrName = this._norm(li.getAttribute("data-attribute_name"));
            let tooltip = "";

            if (attrName === "VALANCE") {
                tooltip = "Select your type of valance";
            } else if (attrName === "COLOR") {
                tooltip = "Select the color of your valance";
            } else if (attrName == "CONTROL TYPE") {
                tooltip = "Select your type of control";
            } else {
                return;
            }

            const titleEl = li.querySelector("strong.attribute_name");
            if (!titleEl) return;

            // prevent duplicates
            if (titleEl.querySelector(".notificationmessage")) return;

            const span = document.createElement("span");
            span.className = "notificationmessage";
            span.setAttribute("data-tooltip", tooltip);
            span.textContent = " ?";

            titleEl.appendChild(span);
        });
    },

    _bindObserver() {
        this._mo = new MutationObserver(() => this._applyInfo());
        this._mo.observe(this.el, { childList: true, subtree: true });

        this._onEvt = () => this._applyInfo();
        document.addEventListener("change", this._onEvt, true);
        document.addEventListener("input", this._onEvt, true);
        window.addEventListener("hashchange", this._onEvt);
    },

    destroy() {
        if (this._mo) this._mo.disconnect();
        if (this._onEvt) {
            document.removeEventListener("change", this._onEvt, true);
            document.removeEventListener("input", this._onEvt, true);
            window.removeEventListener("hashchange", this._onEvt);
        }
        return this._super(...arguments);
    },
});

publicWidget.registry.LxAttributeInfoMessages;

publicWidget.registry.LxStaticNotifAfterAttributes = publicWidget.Widget.extend({
    selector: ".js_add_cart_variants",

    start() {
        const res = this._super(...arguments);
        this._injectStaticNote();
        this._bindObserver();
        return res;
    },

    _injectStaticNote() {
        // avoid duplicates
        if (document.getElementById("lx-static-attributes-note")) return;

        // Optional: only on configurator products (same logic you use with lx_dims_express)
        // if (!document.getElementById("lx_dims_express")) return;

        const box = document.createElement("div");
        box.id = "lx-static-attributes-note";
        box.className = "lx-static-note";

        box.innerHTML = `

        
          <ul class="lx-info-list">
            <li>One Remote can control up to <strong>5 Roller Blinds</strong></li>
            <li>One ZigBee Gateway can manage up to <strong>30 Roller Blinds</strong></li>
            <li>One Charger can power <strong>all your devices</strong></li>
          </ul>
        
          <div class="lx-info-tip">
            💡 Tip: Choose <strong>“Motor Only”</strong> option to prevent excess charges.
          </div>
        `;


        // insert AFTER the attributes list
        this.el.insertAdjacentElement("afterend", box);
    },

    _bindObserver() {
        // If variants rerender, reinject if needed
        this._mo = new MutationObserver(() => this._injectStaticNote());
        this._mo.observe(this.el.parentNode || document.body, { childList: true, subtree: true });
    },

    destroy() {
        if (this._mo) this._mo.disconnect();
        return this._super(...arguments);
    },
});

publicWidget.registry.LxStaticNotifAfterAttributes;


const CART_TIPS = {
  REMOTE: `
    <div class="lx-bullet">Not required, one Remote controls up to <strong>5 Roller blinds</strong>.</div>
    <div class="lx-tipline">
      Tip: For installation on another floor or in another home, please add the necessary remotes in the
      <strong>"Available options"</strong> section.
    </div>
  `,
  ZIGBEE: `
    <div class="lx-bullet">Not required, one ZigBee Gateway can manage up to <strong>30 Roller blinds</strong>.</div>
    <div class="lx-tipline">
      Tip: For installation on another floor or in another home, please add the necessary ZigBee Gateways in the
      <strong>"Available options"</strong> section.
    </div>
  `,
  CHARGER: `
    <div class="lx-bullet">Not required, one Charger can power all devices.</div>
    <div class="lx-tipline">
      Tip: For installation on another floor or in another home, please add the necessary chargers in the
      <strong>"Available options"</strong> section.
    </div>
  `,
};

function addCartTooltip(h6, key, html) {
  if (!h6 || h6.querySelector(".lx-cart-tipwrap")) return;

  const wrap = document.createElement("span");
  wrap.className = "lx-cart-tipwrap";

  const q = document.createElement("span");
  q.className = "lx-cart-q";
  q.textContent = "?";

  const box = document.createElement("div");
  box.className = "lx-cart-tipbox";
  box.innerHTML = html;

  wrap.appendChild(q);
  wrap.appendChild(box);

  // Insert inline before <br> if exists
  const br = h6.querySelector("br");
  if (br) {
    h6.insertBefore(wrap, br);
  } else {
    h6.appendChild(wrap);
  }

  // ensure inline layout
  h6.style.display = "inline-flex";
  h6.style.alignItems = "center";
  h6.style.gap = "6px";
}

function decorateCartLines(root) {
  root.querySelectorAll(".o_cart_product h6").forEach((h6) => {
    const text = (h6.textContent || "").toUpperCase();

    if (text.includes("REMOTE CONTROL ")) {
      addCartTooltip(h6, "REMOTE", CART_TIPS.REMOTE);
    } else if (text.includes("ZIGBEE")) {
      addCartTooltip(h6, "ZIGBEE", CART_TIPS.ZIGBEE);
    } else if (text.includes("CHARGER")) {
      addCartTooltip(h6, "CHARGER", CART_TIPS.CHARGER);
    }
  });
}

publicWidget.registry.LxCartExcelTips = publicWidget.Widget.extend({
  selector: "#cart_products",

  start() {
    const res = this._super(...arguments);

    decorateCartLines(this.el);

    // Cart updates dynamically → observe changes
    const obs = new MutationObserver(() => decorateCartLines(this.el));
    obs.observe(this.el, { childList: true, subtree: true });

    this._observer = obs;
    return res;
  },

  destroy() {
    if (this._observer) this._observer.disconnect();
    return this._super(...arguments);
  },
});

export default publicWidget.registry.LxCartExcelTips;

publicWidget.registry.LxInspirationFilters = publicWidget.Widget.extend({
    selector: "#wrapwrap",

    start() {
        this._super(...arguments);

        this._boot = this._readBoot();

        this._gridEl = document.getElementById("lx_gallery_grid");
        this._countEl = document.getElementById("lx_count_text");

        this._typeEl = document.getElementById("lx_filter_type");

        this._rowCategory = document.getElementById("lx_row_category");
        this._rowProduct = document.getElementById("lx_row_product");
        this._rowSpace = document.getElementById("lx_row_space");

        this._selCategory = document.getElementById("lx_category_select");
        this._selProduct = document.getElementById("lx_product_select");
        this._selSpace = document.getElementById("lx_space_select");

        this._products = (this._boot && Array.isArray(this._boot.products)) ? this._boot.products : [];
        this._categories = (this._boot && Array.isArray(this._boot.categories)) ? this._boot.categories : [];
        this._spaces = (this._boot && Array.isArray(this._boot.spaces)) ? this._boot.spaces : [];

        this._fillSelects();
        this._bind();
        this._syncRows();

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
                this._syncRows();
                this._apply();
            });
        }
        if (this._selCategory) this._selCategory.addEventListener("change", () => this._apply());
        if (this._selProduct) this._selProduct.addEventListener("change", () => this._apply());
        if (this._selSpace) this._selSpace.addEventListener("change", () => this._apply());
    },

    _syncRows() {
        const type = this._typeEl && this._typeEl.value ? this._typeEl.value : "all";

        if (this._rowCategory) this._rowCategory.classList.toggle("d-none", type !== "category");
        if (this._rowProduct) this._rowProduct.classList.toggle("d-none", type !== "product");
        if (this._rowSpace) this._rowSpace.classList.toggle("d-none", type !== "space");

        if (type !== "category" && this._selCategory) this._selCategory.value = "";
        if (type !== "product" && this._selProduct) this._selProduct.value = "";
        if (type !== "space" && this._selSpace) this._selSpace.value = "";
    },

    _fillSelects() {
        this._fillSelect(this._selCategory, this._categories, "All", (x) => x.name);
        this._fillSelect(this._selProduct, this._products, "All", (x) => x.name);
        this._fillSelect(this._selSpace, this._spaces, "All", (x) => x.name);
    },

    _fillSelect(sel, items, firstLabel, getLabel) {
        if (!sel) return;

        sel.innerHTML = "";

        const opt0 = document.createElement("option");
        opt0.value = "";
        opt0.textContent = firstLabel;
        sel.appendChild(opt0);

        const list = (items || []).slice().sort((a, b) => {
            return String(getLabel(a) || "").localeCompare(String(getLabel(b) || ""));
        });

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

        let filter_type = type;
        let filter_id = null;

        if (type === "category") {
            filter_id = this._selCategory && this._selCategory.value ? parseInt(this._selCategory.value, 10) : null;
        } else if (type === "product") {
            filter_id = this._selProduct && this._selProduct.value ? parseInt(this._selProduct.value, 10) : null;
        } else if (type === "space") {
            filter_id = this._selSpace && this._selSpace.value ? parseInt(this._selSpace.value, 10) : null;
        }

        if (!filter_id) {
            this._render(this._products);
            return;
        }

        try {
            const res = await rpc("/inspiration/filter", { filter_type, filter_id });
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





