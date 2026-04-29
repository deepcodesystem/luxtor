/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

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
  if (!WS) return void setTimeout(patch, 0);
  if (WS.prototype._lxDimsPricePatched) return;

  const _orig = WS.prototype.addToCart;

  const num = (v) => { const n = parseFloat(String(v ?? "").replace(",", ".")); return Number.isFinite(n) ? n : 0; };
  const fb  = (w, h) => (!w && !h ? { w: 1, h: 1 } : { w: w || 1, h: h || 1 });

  const pickForm = (params) =>
    (params && params.$form && params.$form[0]) ||
    document.activeElement?.closest?.('form') ||
    document.querySelector('#product_details form[action*="/shop/cart"]') ||
    document.querySelector('form.js_add_cart_json') ||
    document.querySelector('.oe_website_sale form');

  const ensureHidden = (form, name, value) => {
    if (!form) return;
    let el = form.querySelector(`input[name="${name}"]`);
    if (!el) { el = document.createElement("input"); el.type = "hidden"; el.name = name; form.appendChild(el); }
    el.disabled = false;
    el.value = String(value);
  };

  const currentVariantId = () => {
    const input = document.querySelector('input[name="product_id"]');
    return input ? (parseInt(input.value || "0", 10) || 0) : 0;
  };

  const fetchVirtualPrice = async (pid, w, h) => {
    alert(`fetchVirtualPrice:start pid=${pid}, w=${w}, h=${h}`);
    try {
      const data = await rpc("/shop/lx_virtual_price", { product_id: pid, width: w, height: h });
      alert(`fetchVirtualPrice:resp ${JSON.stringify(data)}`);
      if (data && data.ok && Number(data.final_unit_price) > 0) return Number(data.final_unit_price);
    } catch (e) {
      alert(`fetchVirtualPrice:error ${e}`);
    }
    return 0;
  };

  WS.prototype.addToCart = async function (params = {}) {
    alert("addToCart:start");
    const form = pickForm(params);

    const wRaw = document.querySelector("#lx_width_input")?.value;
    const hRaw = document.querySelector("#lx_height_input")?.value;
    alert(`raw dims → wRaw=${wRaw}, hRaw=${hRaw}`);

    let w = num(wRaw);
    let h = num(hRaw);
    ({ w, h } = fb(w, h));
    alert(`dims after fb → w=${w}, h=${h}`);

    const w6 = w.toFixed(6);
    const h6 = h.toFixed(6);

    ensureHidden(form, "lx_width_m",  w6);
    ensureHidden(form, "lx_height_m", h6);
    ensureHidden(form, "lx_width_id",  w6);
    ensureHidden(form, "lx_height_id", h6);

    params.lx_width_m   = w6;
    params.lx_height_m  = h6;
    params.lx_width_id  = w6;
    params.lx_height_id = h6;

    const pid = currentVariantId();
    alert(`currentVariantId → ${pid}`);

    const price = await fetchVirtualPrice(pid, w, h);
    if (price > 0) {
      const f6 = price.toFixed(6);
      ensureHidden(form, "lx_final_unit_price", f6);
      ensureHidden(form, "lx_price_override",   f6);
      params.lx_final_unit_price = f6;
      params.lx_price_override   = f6;
      alert(`price set → ${f6}`);
    } else {
      alert("price skipped (<=0)");
    }

    const ret = await _orig.call(this, params);
    alert(`addToCart:ret → ${JSON.stringify(ret)}`);

    if (ret && ret.line_id) {
      const payload = {
        line_id: ret.line_id,
        set_qty: ret.quantity,
        lx_width_m:  w6,
        lx_height_m: h6,
        lx_width_id:  w6,
        lx_height_id: h6,
      };
      if (price > 0) {
        const f6 = price.toFixed(2);
        payload.lx_price_override = f6;
        payload.lx_final_unit_price = f6;
      }
      alert(`cart/update_json payload → ${JSON.stringify(payload)}`);
      ajax.jsonRpc("/shop/cart/update_json", "call", payload)
        .then((r) => alert(`cart/update_json resp → ${JSON.stringify(r)}`))
        .catch((e) => alert(`cart/update_json error → ${e}`));
    }

    alert("addToCart:end");
    return ret;
  };

  WS.prototype._lxDimsPricePatched = true;
})();

