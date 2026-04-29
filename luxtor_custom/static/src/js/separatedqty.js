/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";


const WSS = publicWidget.registry.WebsiteSale;

function readDims(root) {
  const form = root && root.closest ? root.closest("form") : null;
  const get = (sel) => (form ? form.querySelector(sel) : document.querySelector(sel));
  const wEl = get("#lx_width_input")  || get("[name='lx_width_m']");
  const hEl = get("#lx_height_input") || get("[name='lx_height_m']");
  const w = (wEl && wEl.value && String(wEl.value).trim()) || "1";
  const h = (hEl && hEl.value && String(hEl.value).trim()) || "1";
  return { w, h };
}

if (WSS) {
  const _prep = WSS.prototype._prepareParams;
  WSS.prototype._prepareParams = function () {
    const params = _prep ? _prep.apply(this, arguments) : {};
    try {
      const { w, h } = readDims(this.el);
      params.lx_width_m  = w;
      params.lx_height_m = h;
    } catch (e) {}
    return params;
  };

  const _onClick = WSS.prototype._onClickAddToCart;
  WSS.prototype._onClickAddToCart = async function (ev) {
    try {
      const { w, h } = readDims(ev.currentTarget);
      await fetch("/lx/store_dims", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lx_width_m: w, lx_height_m: h }),
        credentials: "same-origin",
        keepalive: true,
      });
    } catch (e) {}
    return _onClick.apply(this, arguments);
  };
}


publicWidget.registry.LxLiveVariantWHPreview = publicWidget.Widget.extend({
  selector: ".oe_website_sale",
  start() {
    const r = this._super(...arguments);
    const form = document.querySelector("form[action*='/shop/cart']");
    let box = document.getElementById("lx-dim-preview");
    if (!box) {
      box = document.createElement("div");
      box.id = "lx-dim-preview";
      box.textContent = " ";
      
    }

    const readVariants = () => {
      const out = [];
      const radios = document.querySelectorAll(".js_variant_change[type='radio']:checked, .js_variant_change[type='checkbox']:checked");
      let i = 0;
      for (i = 0; i < radios.length; i += 1) {
        const el = radios[i];
        let v = el.getAttribute("data-value_name") || el.title || "";
        if (!v) {
          const lid = el.getAttribute("id");
          if (lid) {
            const lab = document.querySelector("label[for='" + lid + "']");
            if (lab) { v = (lab.textContent || "").trim(); }
          }
        }
        if (v) { out.push(v); }
      }
      const selects = document.querySelectorAll("select.js_variant_change");
      let j = 0;
      for (j = 0; j < selects.length; j += 1) {
        const s = selects[j];
        let t = "";
        if (s.selectedIndex >= 0) {
          const o = s.options[s.selectedIndex];
          if (o) { t = (o.text || "").trim(); }
        }
        if (t) { out.push(t); }
      }
      return out;
    };

    const update = () => {
      let name = "";
      const h1 = document.querySelector("h1[itemprop='name']");
      if (h1) { name = h1.textContent || ""; }

      let W = "1";
      let H = "1";
      const wi = document.querySelector("#lx_width_input");
      if (wi && wi.value) { W = wi.value; }
      const hi = document.querySelector("#lx_height_input");
      if (hi && hi.value) { H = hi.value; }

      const v = readVariants();
      const parts = [];
      if (name) { parts.push(name); }
      if (v.length) { parts.push(v.join(" · ")); }
      parts.push("(" + W + "m * " + H + "m)");

      box.textContent = parts.join(" - ");
    };

    document.addEventListener("input", function(){ update(); }, true);
    update();
    setTimeout(update, 50);
    setTimeout(update, 200);
    return r;
  },
});

export default publicWidget.registry.LxLiveVariantWHPreview;

publicWidget.registry.LxVariantAttributeFix = publicWidget.Widget.extend({
    selector: "#wrapwrap",

    start() {
        const res = this._super(...arguments);

        document.querySelectorAll(".variant_attribute").forEach((box) => {
            const title = box.querySelector(".attribute_name")?.textContent?.trim().toUpperCase();
            if (title) {
                box.setAttribute("data-attribute-name", title);
            }
        });

        return res;
    },
});

publicWidget.registry.LxSyncDimsInUrl = publicWidget.Widget.extend({
  selector: ".oe_website_sale",
  start() {
    const res = this._super(...arguments);
    const wi = document.querySelector("#lx_width_input");
    const hi = document.querySelector("#lx_height_input");

    const read = () => ({
      w: (wi && wi.value || "").trim(),
      h: (hi && hi.value || "").trim(),
    });

    const applyToUrl = ({ w, h }) => {
      const u = new URL(window.location.href);
      w ? u.searchParams.set("lx_w", w) : u.searchParams.delete("lx_w");
      h ? u.searchParams.set("lx_h", h) : u.searchParams.delete("lx_h");
      const next = u.pathname + (u.search || "") + (u.hash || "");
      const cur = window.location.pathname + window.location.search + window.location.hash;
      if (next !== cur) history.replaceState(null, "", next);
    };

    const applyToLinks = ({ w, h }) => {
      const params = [];
      if (w) params.push(["lx_w", w]);
      if (h) params.push(["lx_h", h]);
      if (!params.length) return;
      document.querySelectorAll("a[href*='/shop/']").forEach((a) => {
        const raw = a.getAttribute("href") || "";
        const [pathAndQuery, hash = ""] = raw.split("#");
        const u = new URL(pathAndQuery, window.location.origin);
        params.forEach(([k, v]) => u.searchParams.set(k, v));
        a.setAttribute("href", u.pathname + (u.search || "") + (hash ? "#" + hash : ""));
      });
    };

    const sync = () => {
      const v = read();
      applyToUrl(v);
      applyToLinks(v);
    };

    sync();
    wi && wi.addEventListener("input", sync);
    wi && wi.addEventListener("change", sync);
    hi && hi.addEventListener("input", sync);
    hi && hi.addEventListener("change", sync);
    document.addEventListener("change", (e) => { if (e.target && e.target.name === "product_id") sync(); });
    window.addEventListener("hashchange", sync);

    return res;
  },
});


publicWidget.registry.LxPrefillDimsFromUrl = publicWidget.Widget.extend({
  selector: ".oe_website_sale",
  start() {
    const res = this._super(...arguments);
    const p = new URLSearchParams(window.location.search);
    const w = (p.get("lx_w") || "").trim();
    const h = (p.get("lx_h") || "").trim();
    const wi = document.querySelector("#lx_width_input");
    const hi = document.querySelector("#lx_height_input");
    if (wi && w) { wi.value = w; wi.dispatchEvent(new Event("input")); wi.dispatchEvent(new Event("change")); }
    if (hi && h) { hi.value = h; hi.dispatchEvent(new Event("input")); hi.dispatchEvent(new Event("change")); }
    return res;
  },
});


publicWidget.registry.LxCartLinkDims = publicWidget.Widget.extend({
  selector: ".js_cart, #cart_products",
  start() {
    const res = this._super(...arguments);
    const rows = this.el.querySelectorAll(".o_cart_product, tr.cart_line");
    rows.forEach((row) => {
      const w = (row.querySelector("[data-lx-w]")?.dataset.lxW || "").trim();
      const h = (row.querySelector("[data-lx-h]")?.dataset.lxH || "").trim();
      if (!w && !h) return;
      const a = row.querySelector("a.o_line_product, a[href*='/shop/']");
      if (!a) return;
      const href = a.getAttribute("href") || "";
      const [pathAndQuery, hash = ""] = href.split("#");
      const url = new URL(pathAndQuery, window.location.origin);
      if (w) url.searchParams.set("lx_w", w);
      if (h) url.searchParams.set("lx_h", h);
      a.setAttribute("href", url.pathname + url.search + (hash ? "#" + hash : ""));
    });
    return res;
  },
});

(function patch() {
  const WS = publicWidget.registry.WebsiteSale;
  if (!WS) { setTimeout(patch, 0); return; }
  if (WS.prototype._lxDimsPricePatched) return;

  const _orig = WS.prototype.addToCart;

  const num = (v) => {
    const n = parseFloat(String(v ?? "").replace(",", "."));
    return Number.isFinite(n) ? n : 0;
  };
  const fb = (w, h) => (!w && !h ? { w: 1, h: 1 } : { w: w || 1, h: h || 1 });

  const pickForm = (params) =>
    (params && params.$form && params.$form[0]) ||
    (document.activeElement && document.activeElement.closest && document.activeElement.closest("form")) ||
    document.querySelector('#product_details form[action*="/shop/cart"]') ||
    document.querySelector("form.js_add_cart_json") ||
    document.querySelector(".oe_website_sale form");

  const ensureHidden = (form, name, value) => {
    if (!form) return;
    let el = form.querySelector(`input[name="${name}"]`);
    if (!el) {
      el = document.createElement("input");
      el.type = "hidden";
      el.name = name;
      form.appendChild(el);
    }
    el.disabled = false;
    el.value = String(value);
  };

  const currentVariantId = () => {
    const input = document.querySelector('input[name="product_id"]');
    const v = input ? parseInt(input.value || "0", 10) : 0;
    return Number.isFinite(v) ? v : 0;
  };

  const fetchVirtualPrice = async (pid, w, h) => {
    alert(`fetchVirtualPrice:start pid=${pid}, w=${w}, h=${h}`);
    try {
      const data = await rpc("/shop/lx_virtual_price", { product_id: pid, width: w, height: h });
      alert(`fetchVirtualPrice:resp ${JSON.stringify(data)}`);
      if (data && data.ok && Number(data.final_unit_price) > 0) {
        return Number(data.final_unit_price);
      }
    } catch (e) {
      alert(`fetchVirtualPrice:error ${e}`);
    }
    return 0;
  };
  
  const setHidden = (name, value) => {
        const form =
            document.querySelector('#product_details form[action*="/shop/cart"]') ||
            document.querySelector("form.js_add_cart_json") ||
            document.querySelector(".oe_website_sale form");
        if (!form) return;
        let el = form.querySelector(`input[name="${name}"]`);
        if (!el) {
            el = document.createElement("input");
            el.type = "hidden";
            el.name = name;
            form.appendChild(el);
        }
        el.value = value;
    };
  
  const parse = (s) => {
        if (s == null) return 0;
        let x = String(s).trim().replace(/\s/g, "");
        const m = x.match(/-?(?:\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,]\d+)?/);
        if (!m) return 0;
        let n = m[0];
        if (n.includes(",") && n.includes(".")) {
            const dec = n.lastIndexOf(",") > n.lastIndexOf(".") ? "," : ".";
            const thou = dec === "," ? "." : ",";
            n = n.replace(new RegExp("\\" + thou, "g"), "").replace(dec, ".");
        } else if (n.includes(",")) {
            n = n.replace(",", ".");
        }
        const f = parseFloat(n);
        return Number.isFinite(f) ? f : 0;
    };

    const readPrice = () => {
        const hid = document.querySelector("#lx_final_unit_price");
        let v = parse(hid?.value);
        if (v > 0) return v;
        const node =
            document.querySelector('#product_details .oe_price .oe_currency_value') ||
            document.querySelector('#product_details [itemprop="price"]') ||
            document.querySelector('#product_details .o_wsale_product_price .oe_currency_value');
        if (node) {
            v = parse(node.textContent);
            if (v > 0) return v;
            v = parse(node.getAttribute?.("content"));
            if (v > 0) return v;
        }
        return 0;
    };

  WS.prototype.addToCart = async function (params = {}) {
    const form = pickForm(params);
    alert("addToCart:start");

    const wRaw = document.querySelector("#lx_width_input")?.value;
    const hRaw = document.querySelector("#lx_height_input")?.value;
    alert(`raw dims → wRaw=${wRaw}, hRaw=${hRaw}`);

    let w = num(wRaw);
    let h = num(hRaw);
    ({ w, h } = fb(w, h));
    alert(`dims after fb → w=${w}, h=${h}`);

    const w6 = w.toFixed(2);
    const h6 = h.toFixed(2);

    ensureHidden(form, "lx_width_m",  w6);
    ensureHidden(form, "lx_height_m", h6);
    ensureHidden(form, "lx_width_id",  w6);
    ensureHidden(form, "lx_height_id", h6);

    const pid = currentVariantId();
    alert(`currentVariantId → ${pid}`);

    const price = readPrice();
    if (price > 0) {
      const f = price.toFixed(6);
      ensureHidden(form, "lx_final_unit_price", f);
      ensureHidden(form, "lx_price_override", f);
      setHidden("lx_width_m", w6);
      setHidden("lx_height_m", h6);
      setHidden("lx_width_id", w6);
      setHidden("lx_height_id", h6);
      setHidden("lx_final_unit_price", f);
      setHidden("lx_price_override", f);

      params.lx_width_m          = w6;
      params.lx_height_m         = h6;
      params.lx_width_id         = w6;
      params.lx_height_id        = h6;

      params.lx_final_unit_price = f;
      params.lx_price_override = f;
      
      alert(`price set → ${f}`);
      alert(`params $ →  ${JSON.stringify(params)}`);
    } 

    alert("addToCart:end");
    return _orig.call(this, params);
  };

  WS.prototype._lxDimsPricePatched = true;
})();