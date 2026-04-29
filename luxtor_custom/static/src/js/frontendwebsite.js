/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";



/* ---------- widget ---------- */


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

// export default publicWidget.registry.LxCartExcelTips;

publicWidget.registry.LxInspirationFilters = publicWidget.Widget.extend({
    selector: "#wrapwrap",

    start() {
        this._super(...arguments);

        this._boot = this._readBoot();

        this._gridEl = document.getElementById("lx_gallery_grid");
        this._countEl = document.getElementById("lx_count_text");

        this._typeEl = document.getElementById("lx_filter_type");

        // unified subfilter
        this._subLabel = document.getElementById("lx_sub_label");
        this._subSelect = document.getElementById("lx_sub_select");

        this._products = (this._boot && Array.isArray(this._boot.products)) ? this._boot.products : [];
        this._categories = (this._boot && Array.isArray(this._boot.categories)) ? this._boot.categories : [];
        this._spaces = (this._boot && Array.isArray(this._boot.spaces)) ? this._boot.spaces : [];

        this._bind();

        // IMPORTANT: default sub label must always be "Category"
        if (this._subLabel) this._subLabel.textContent = "Category";

        // Fill once based on current type (All by default => disable but keep label)
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

        // Always keep the label "Category" (as requested)
        if (keepLabelCategory && this._subLabel) {
            this._subLabel.textContent = "Category";
        }

        // Disable when "All"
        if (this._subSelect) {
            this._subSelect.disabled = (type === "all");
        }

        // Items shown in sub-select depend on type
        let items = [];
        if (type === "category") items = this._categories;
        else if (type === "product") items = this._products;
        else if (type === "space") items = this._spaces;
        else items = [];

        this._fillSelect(this._subSelect, items, "All", (x) => x.name);

        // Reset to "All" whenever type changes
        if (this._subSelect) this._subSelect.value = "";
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

/* -----------------------------
   Small DOM helpers (safe)
----------------------------- */
function _qs(sel, root = document) {
    return root.querySelector(sel);
}

function _setText(sel, text) {
    const el = _qs(sel);
    if (el) el.textContent = text != null ? String(text) : "";
}

function _showRewardMsg(message) {
    const el = _qs("#lx_express_reward_msg");
    if (!el) return;
    const msg = (message || "").trim();
    if (msg) {
        el.textContent = msg;
        el.classList.remove("d-none");
    } else {
        el.textContent = "";
        el.classList.add("d-none");
    }
}

/**
 * When reward is active, we want to display FREE (0) on UI,
 * no matter what unit_formatted was before.
 * We do NOT change server behavior here, just presentation.
 */
function _applyRewardUi(rule) {
    // rule: { active: bool, priceText: string, message: string }
    if (!rule) return;
    if (rule.active) {
        const el = _qs("#lx_express_price");
        if (el) {
            el.textContent = rule.priceText || "+(0.00)";
            el.classList.add("text-muted");
            el.style.direction = "ltr";
            el.style.textAlign = "right";
            el.style.cssFloat = "right";
        }
        _showRewardMsg(rule.message || "");
    } else {
        _showRewardMsg("");
    }
}

function _formatZeroPriceFromPriceRes(pr) {
    const sym = pr?.currency || "DH";
    const dec = Number(pr?.decimals || 2);
    const val = Number(0).toFixed(dec);
    return `+(${val} ${sym})`;
}

/* ---------- widget ---------- */

/* -----------------------------
   Helpers (kept minimal, no side effects)
----------------------------- */

function _safeText(v) {
    return (typeof v === "string" ? v : "") || "";
}

function _zeroPriceTextFromRes(res) {
    const sym = _safeText(res?.currency) || "DH";
    const dec = Number(res?.decimals || 2);
    return `+(0.${"0".repeat(Math.max(0, dec))} ${sym})`.replace("0."+ "0".repeat(dec), Number(0).toFixed(dec));
}

function _applyRewardUi({ active, message }) {
    const el = document.querySelector("#lx_express_reward_msg");
    if (!el) return;

    if (active) {
        el.classList.remove("d-none");
        el.textContent = (message || "Congratulations! Express delivery is now free thanks to your review.").trim();
    } else {
        el.classList.add("d-none");
        el.textContent = "";
    }
}

function _applyRewardAlertOnce({ active, message }) {
    const key = "lx_reward_alert_once_v1";
    if (window.sessionStorage.getItem(key) === "1") return;
    window.sessionStorage.setItem(key, "1");

    if (active) {
        alert((message || "Review reward detected: Express delivery is free.").trim());
    } else {
        alert("No review reward detected.");
    }
}

/* ---------- widget ---------- */

function setRadioPair(yesSel, noSel, isYes) {
    const yes = document.querySelector(yesSel);
    const no = document.querySelector(noSel);
    if (yes) yes.checked = !!isYes;
    if (no) no.checked = !isYes;
}

function applyServerTotalFormatted(res) {
    if (!res || !res.ok) return;
    const totalStr = res.total_formatted || "";
    if (!totalStr) return;

    const totalEl =
        document.querySelector(".oe_website_sale .oe_cart .js_cart_summary .oe_subtotal .oe_currency_value") ||
        document.querySelector(".oe_website_sale .js_cart_summary .oe_currency_value") ||
        document.querySelector(".oe_website_sale .o_wsale_cart_summary .oe_currency_value");

    if (totalEl) totalEl.textContent = totalStr;
}



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

        this._rewardActive = false;
        this._rewardMessage = "";
        this._rewardBound = false;
    },

    async start() {
        const r = this._super.apply(this, arguments);
        await this._fetchUnit();
        await this._fetchQty();
        this._renderUnitOnly();
        this._renderRewardIfNeeded();
        await this._syncInitialRadios();
        this._setupDomObservers();
        this._bindQtyWatcher();
        this._bindRewardWatcher();
        return r;
    },

    /* ---------- RPC wrappers ---------- */
    _rpcPrice() { return rpc("/lx/priority/price", {}); },
    _rpcMrpQty() { return rpc("/lx/priority/mrp_qty", {}); },
    _rpcHas()   { return rpc("/lx/priority/has", {}); },
    _rpcApply(enabled, qty) { return rpc("/lx/priority/apply", { enabled, qty }); },
    _rpcRemove() { return rpc("/lx/priority/remove", {}); },
    _rpcReviewStatus() { return rpc("/lx/review/status", {}); },

    /* ---------- loaders ---------- */
    async _fetchUnit() {
        try {
            const res = await this._rpcPrice();
            if (res?.ok) {
                this._unit = Number(res.unit_price || 0);
                this._unitFormatted = res.unit_formatted || "";

                this._rewardActive = !!res.reward_express_free || (Number(res.unit_price || 0) === 0);
                this._rewardMessage = res.reward_message || "";
            } else {
                this._unit = 0;
                this._unitFormatted = "";
                this._rewardActive = false;
                this._rewardMessage = "";
            }
        } catch {
            this._unit = 0;
            this._unitFormatted = "";
            this._rewardActive = false;
            this._rewardMessage = "";
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

    _renderRewardIfNeeded() {
        const box = document.querySelector("#lx_express_reward_msg");
        if (!box) return;

        const isFree = !!this._rewardActive && Number(this._unit || 0) === 0;

        if (isFree) {
            box.textContent = "Congratulations! Priority Service has been successfully applied.";
            box.classList.remove("d-none");
        } else {
            box.textContent = "";
            box.classList.add("d-none");
        }
    },

    async _refreshRewardFromServer() {
        try {
            const p = await this._rpcPrice();
            if (p?.ok) {
                this._rewardActive = !!p.reward_express_free || (Number(p.unit_price || 0) === 0);
                this._rewardMessage = p.reward_message || "";
                this._unit = Number(p.unit_price || 0);
                this._unitFormatted = p.unit_formatted || this._unitFormatted;
                this._renderUnitOnly();
                this._renderRewardIfNeeded();
                return;
            }
        } catch { /* ignore */ }

        try {
            const s = await this._rpcReviewStatus();
            if (s?.ok) {
                this._rewardActive = !!s.active;
                this._renderRewardIfNeeded();
            }
        } catch { /* ignore */ }
    },

    /* ---------- events ---------- */
    async _onYes(ev) {
        if (!ev.currentTarget.checked) return;
        setRadioPair("#lx_express_yes", "#lx_express_no", true);
        this._enabled = true;

        await this._fetchUnit();
        await this._fetchQty();
        this._renderUnitOnly();
        this._renderRewardIfNeeded();

        const op = ++this._op;
        const res = await this._rpcApply(true, this._qty);
        if (op !== this._op) return;

        if (res?.ok) {
            applyServerTotalFormatted(res);

            if (typeof res.unit_formatted === "string") this._unitFormatted = res.unit_formatted;
            this._unit = Number(res.unit_price || this._unit);
            this._rewardActive = !!res.reward_express_free || (Number(res.unit_price || 0) === 0);
            this._rewardMessage = res.reward_message || this._rewardMessage;

            this._renderUnitOnly();
            this._renderRewardIfNeeded();

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
            this._unit = Number(res.unit_price || this._unit);
            this._rewardActive = !!res.reward_express_free || (Number(res.unit_price || 0) === 0);
            this._rewardMessage = res.reward_message || this._rewardMessage;

            this._renderUnitOnly();
            this._renderRewardIfNeeded();

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
                        this._unit = Number(res.unit_price || this._unit);
                        this._rewardActive = !!res.reward_express_free || (Number(res.unit_price || 0) === 0);
                        this._rewardMessage = res.reward_message || this._rewardMessage;

                        this._renderUnitOnly();
                        this._renderRewardIfNeeded();

                        setTimeout(() => location.reload(), 400);
                    }
                } else {
                    this._refreshRewardFromServer();
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

    _bindRewardWatcher() {
        if (this._rewardBound) return;

        const refresh = () => setTimeout(() => this._refreshRewardFromServer(), 0);

        document.addEventListener("submit", (ev) => {
            const f = ev.target;
            if (!f) return;
            const hint =
                (f.classList && (f.classList.contains("o_portal_chatter_composer_form") || f.classList.contains("o_rating_rate_form"))) ||
                (f.getAttribute && (f.getAttribute("action") || "").includes("rating"));
            if (hint) refresh();
        }, true);

        document.addEventListener("click", (ev) => {
            const t = ev.target;
            if (!t) return;
            if (t.matches && (t.matches("button[type='submit']") || t.matches(".o_portal_chatter_composer_btn"))) refresh();
        }, true);

        const block = document.querySelector("#lx_express_block");
        if (block) {
            const mo = new MutationObserver(() => refresh());
            mo.observe(block, { childList: true, subtree: true });
        }

        this._rewardBound = true;
    },
});

// export default publicWidget.registry.LxPriorityToggle;

/* =========================
   Freez check stock
   ========================= */

function ensureStyleOnce() {
  if (document.getElementById("lx-freeze-style")) return;
  const style = document.createElement("style");
  style.id = "lx-freeze-style";
  style.textContent = `
    .lx-freeze-banner{
      margin-top:10px;
      padding:10px 12px;
      border-radius:10px;
      font-weight:900;
      font-size:14px;
      background:rgba(220,53,69,.10);
      border:1px solid rgba(220,53,69,.35);
      color:#b02a37;
      text-transform:uppercase;
      line-height:1.25;
    }
    .lx-freeze-disabled{
      opacity:.55 !important;
      pointer-events:none !important;
      cursor:not-allowed !important;
      filter:grayscale(25%);
    }
  `;
  document.head.appendChild(style);
}

/* =========================
   HARD BLOCK legacy message
   ========================= */
function killLegacyAvailabilityBox() {
  document.querySelectorAll(
    "#lx-availability-box, .lx-availability-text"
  ).forEach((el) => el.remove());
}

/* =========================
   DOM helpers
   ========================= */
function getTemplateId() {
  const h = document.querySelector("[data-product-template-id]");
  if (h) return parseInt(h.getAttribute("data-product-template-id")) || 0;
  const i = document.querySelector("input[name='product-template-id']");
  return i ? parseInt(i.value) || 0 : 0;
}

function findBottomAnchor() {
  return (
    document.querySelector("#product_details .css_quantity") ||
    document.querySelector("#product_details .o_wsale_product_quantity") ||
    document.querySelector("#add_to_cart") ||
    document.querySelector("#product_details") ||
    document.body
  );
}

function getAddToCartButtons() {
  return Array.from(
    document.querySelectorAll(
      "#add_to_cart,button.js_add_cart_json,a.js_add_cart_json,.o_wsale_product_btn,button[name='add']"
    )
  );
}

/* =========================
   Banner (ONLY allowed msg)
   ========================= */
function getOrCreateBanner() {
  ensureStyleOnce();
  killLegacyAvailabilityBox();

  let el = document.getElementById("lx-freeze-banner");
  if (el) return el;

  el = document.createElement("div");
  el.id = "lx-freeze-banner";
  el.className = "lx-freeze-banner";
  el.setAttribute("role", "status");
  el.setAttribute("aria-live", "polite");

  const anchor = findBottomAnchor();
  anchor.insertAdjacentElement("afterend", el);
  return el;
}

function showFreeze(msg) {
  killLegacyAvailabilityBox();
  const el = getOrCreateBanner();
  el.textContent =
    msg || "You can’t continue: the related fabric is not enough in stock.";
  el.style.display = "";
}

function hideFreeze() {
  killLegacyAvailabilityBox();
  const el = document.getElementById("lx-freeze-banner");
  if (el) el.style.display = "none";
}

function disableEls(els, disabled) {
  els.forEach((el) => {
    if (!el) return;
    if (disabled) {
      el.classList.add("lx-freeze-disabled");
      el.setAttribute("disabled", "disabled");
    } else {
      el.classList.remove("lx-freeze-disabled");
      el.removeAttribute("disabled");
    }
  });
}

/* =========================
   RPC
   ========================= */
async function checkFreezeTemplate(tmplId) {
  if (!tmplId) return { ok: false, freeze: false };
  try {
    return await rpc("/shop/lx_freeze_check", {
      product_template_id: tmplId,
    });
  } catch {
    return { ok: false, freeze: false };
  }
}

/* =====================================================
   MAIN WIDGET — PRODUCT PAGE
   ===================================================== */
publicWidget.registry.LxFreezeFinal = publicWidget.Widget.extend({
  selector: ".oe_website_sale",

  start() {
    const r = this._super(...arguments);

    /* Kill legacy box constantly (even if recreated) */
    this._mo = new MutationObserver(() => {
      killLegacyAvailabilityBox();
      const banner = document.getElementById("lx-freeze-banner");
      if (banner) {
        const anchor = findBottomAnchor();
        if (banner.previousElementSibling !== anchor) {
          anchor.insertAdjacentElement("afterend", banner);
        }
      }
    });

    this._mo.observe(document.body, { childList: true, subtree: true });

    /* Block Add to Cart */
    this._clickHandler = async (e) => {
      const btn = e.target.closest(
        "#add_to_cart,button.js_add_cart_json,a.js_add_cart_json,.o_wsale_product_btn,button[name='add']"
      );
      if (!btn) return;

      const res = await checkFreezeTemplate(getTemplateId());
      if (res?.ok && res.freeze) {
        e.preventDefault();
        e.stopPropagation();
        showFreeze(res.msg);
        disableEls(getAddToCartButtons(), true);
        return false;
      } else {
        hideFreeze();
        disableEls(getAddToCartButtons(), false);
      }
    };

    document.addEventListener("click", this._clickHandler, true);

    /* Variant change */
    this._changeHandler = async (e) => {
      if (!e.target.matches(".js_variant_change")) return;
      const res = await checkFreezeTemplate(getTemplateId());
      if (res?.ok && res.freeze) {
        showFreeze(res.msg);
        disableEls(getAddToCartButtons(), true);
      } else {
        hideFreeze();
        disableEls(getAddToCartButtons(), false);
      }
    };

    document.addEventListener("change", this._changeHandler, true);

    /* Initial check */
    setTimeout(async () => {
      const res = await checkFreezeTemplate(getTemplateId());
      if (res?.ok && res.freeze) {
        showFreeze(res.msg);
        disableEls(getAddToCartButtons(), true);
      }
    }, 0);

    return r;
  },

  destroy() {
    if (this._mo) this._mo.disconnect();
    if (this._clickHandler)
      document.removeEventListener("click", this._clickHandler, true);
    if (this._changeHandler)
      document.removeEventListener("change", this._changeHandler, true);
    this._super(...arguments);
  },
});

// export default publicWidget.registry.LxFreezeFinal;

