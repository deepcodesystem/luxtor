/** @odoo-module **/

// ── V19 Interaction patch ─────────────────────────────────────────────────────
// V19 replaced the legacy WebsiteSale.addToCart with WebsiteSaleInteraction._updateRootProduct
// which builds a `rootProduct` object that flows via cart_service._makeRequest → /shop/cart/add.
// We patch _updateRootProduct to append lx_width_m, lx_height_m, lx_final_unit_price into it.
// These land in **kwargs of our LxCartController.add_to_cart → _inject_lx_kwargs → SOL.

import publicWidget from "@web/legacy/js/public/public_widget";
import { patch } from "@web/core/utils/patch";
import { WebsiteSale as WebsiteSaleInteraction } from "@website_sale/interactions/website_sale";


// ── Shared helpers ────────────────────────────────────────────────────────────

function readDims(root) {
  const form = root && root.closest ? root.closest("form") : null;
  const get = (sel) => (form ? form.querySelector(sel) : document.querySelector(sel));
  const wEl = get("#lx_width_input") || get("[name='lx_width_m']");
  const hEl = get("#lx_height_input") || get("[name='lx_height_m']");
  const w = (wEl && wEl.value && String(wEl.value).trim()) || "1";
  const h = (hEl && hEl.value && String(hEl.value).trim()) || "1";
  return { w, h };
}

function readVariants() {
  const out = [];
  const radios = document.querySelectorAll(
    ".js_variant_change[type='radio']:checked, .js_variant_change[type='checkbox']:checked"
  );
  for (let i = 0; i < radios.length; i += 1) {
    const el = radios[i];
    let v = el.getAttribute("data-value_name") || el.title || "";
    if (!v) {
      const lid = el.getAttribute("id");
      if (lid) {
        const lab = document.querySelector("label[for='" + lid + "']");
        if (lab) v = (lab.textContent || "").trim();
      }
    }
    if (v) out.push(v);
  }

  const selects = document.querySelectorAll("select.js_variant_change");
  for (let j = 0; j < selects.length; j += 1) {
    const s = selects[j];
    if (s.selectedIndex >= 0) {
      const o = s.options[s.selectedIndex];
      const t = (o?.text || "").trim();
      if (t) out.push(t);
    }
  }

  return out.map((v) => {
    if (v.includes("R-002-21")) return v.replace("R-002-21", "Futura");
    if (v.includes("R-002-22")) return v.replace("R-002-22", "Futura+");
    return v;
  });
}

const _lxNum = (v) => {
  const n = parseFloat(String(v ?? "").replace(",", "."));
  return Number.isFinite(n) && n > 0 ? n : 0;
};

const _lxReadDims = () => {
  const w = _lxNum(document.querySelector("#lx_width_input")?.value);
  const h = _lxNum(document.querySelector("#lx_height_input")?.value);
  return { w: w || 1, h: h || 1 };
};

const _lxReadLocationId = () => {
  const raw = (document.querySelector("#lx_location_input")?.value || "").trim();
  const loc = parseInt(raw || "0", 10);
  return Number.isFinite(loc) && loc > 0 ? loc : 0;
};

const _lxReadPrice = () => {
  const hid = document.querySelector("#lx_final_unit_price");
  const v = parseFloat((hid?.value || "").replace(",", "."));
  return Number.isFinite(v) && v > 0 ? v : 0;
};

const _lxReadMotorOnlySelection = (form) => {
  const scope = form || document;
  const idFromInput = parseInt(scope.querySelector('input[name="lx_motor_only_variant_id"]')?.value || "0", 10);
  const labelFromInput = (scope.querySelector('input[name="lx_motor_only_label"]')?.value || "").trim();
  const activePill = document.querySelector("#lx-motor-picker .lx-motor-pill.active");
  const idFromPill = parseInt(activePill?.dataset?.variantId || "0", 10);
  const labelFromPill = (activePill?.dataset?.variantLabel || activePill?.textContent || "").trim();

  return {
    id: Number.isFinite(idFromInput) && idFromInput > 0 ? idFromInput : (Number.isFinite(idFromPill) && idFromPill > 0 ? idFromPill : 0),
    label: labelFromInput || labelFromPill || "",
  };
};


// ── V19 Interaction patch: inject dims + price into rootProduct ───────────────

patch(WebsiteSaleInteraction.prototype, {
  _updateRootProduct(form) {
    super._updateRootProduct(form);
    try {
      const { w, h } = _lxReadDims();
      const loc = _lxReadLocationId();
      this.rootProduct.lx_width_m  = w.toFixed(6);
      this.rootProduct.lx_height_m = h.toFixed(6);
      if (loc > 0) {
        this.rootProduct.lx_location_id = loc;
      }

      // Store dims in session for server-side fallback
      fetch("/lx/store_dims", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          lx_width_m: String(w),
          lx_height_m: String(h),
          lx_location_id: loc ? String(loc) : "",
        }),
        credentials: "same-origin",
        keepalive: true,
      }).catch(() => {});

      const price = _lxReadPrice();
      if (price > 0) {
        this.rootProduct.lx_final_unit_price = price.toFixed(2);
        this.rootProduct.lx_price_override   = price.toFixed(2);
      }

      const motorOnly = _lxReadMotorOnlySelection(form);
      if (motorOnly.id > 0) {
        this.rootProduct.lx_motor_only_variant_id = motorOnly.id;
      }
      if (motorOnly.label) {
        this.rootProduct.lx_motor_only_label = motorOnly.label;
      }
    } catch (e) {
      // non-dimension product page — ignore
    }
  },
});


// ── publicWidgets ─────────────────────────────────────────────────────────────

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


publicWidget.registry.LxVariantAttributeFix = publicWidget.Widget.extend({
  selector: "#wrapwrap",
  start() {
    const res = this._super(...arguments);
    document.querySelectorAll(".variant_attribute").forEach((box) => {
      const title = box.querySelector(".attribute_name")?.textContent?.trim().toUpperCase();
      if (title) box.setAttribute("data-attribute-name", title);
    });
    return res;
  },
});


publicWidget.registry.LxMrpCustomDetailTitle = publicWidget.Widget.extend({
  selector: ".oe_website_sale",
  start() {
    const res = this._super(...arguments);

    if (!document.getElementById("lx_dims_express")) return res;

    const nameH1 = document.querySelector("h1[itemprop='name']");
    if (!nameH1) return res;

    let customH2 = document.getElementById("lx-custom-detail-title");
    if (!customH2) {
      customH2 = document.createElement("h5");
      customH2.id = "lx-custom-detail-title";
      customH2.className = "mt-2 fw-bold";
      nameH1.insertAdjacentElement("afterend", customH2);
    }

    let dimsH5 = document.getElementById("lx-custom-detail-dims");
    if (!dimsH5) {
      dimsH5 = document.createElement("h5");
      dimsH5.id = "lx-custom-detail-dims";
      dimsH5.className = "mt-2 fw-bold";
      customH2.insertAdjacentElement("afterend", dimsH5);
    }

    const render = () => {
      const productName = (nameH1.textContent || "").trim();
      const variants = readVariants();
      const { w, h } = readDims(customH2);

      const firstLine = `${productName} ${variants.length ? variants.join(", ") : ""}`;
      const secondLine = `Width: ${(Number(w) || 1).toFixed(2)}m, Height: ${(Number(h) || 1).toFixed(2)}m`;

      customH2.textContent = firstLine;
      dimsH5.textContent = secondLine;
    };

    document.addEventListener("input", render, true);
    document.addEventListener("change", render, true);
    window.addEventListener("hashchange", render);

    render();
    setTimeout(render, 50);
    setTimeout(render, 200);

    return res;
  },
});


publicWidget.registry.LxVariantRename = publicWidget.Widget.extend({
  selector: '.js_add_cart_variants',
  start() {
    this._renameVariants();
  },
  _renameVariants() {
    document.querySelectorAll(
      'li.variant_attribute:first-of-type label.css_attribute_color,' +
      'li.variant_attribute:first-of-type label.css_attribute_image,' +
      'li.variant_attribute:first-of-type li.list-inline-item,' +
      'li.variant_attribute:first-of-type input.js_variant_change'
    ).forEach(el => {
      el.removeAttribute('title');
      el.removeAttribute('data-bs-original-title');
    });
  },
});


publicWidget.registry.LxControlTypeAddons = publicWidget.Widget.extend({
  selector: ".js_add_cart_variants",
  start() {
    this._decoratePills();
    return this._super(...arguments);
  },
  _decoratePills() {
    document.querySelectorAll(".o_variant_pills.btn").forEach((pill) => {
      const labelEl =
        pill.querySelector(".o_variant_pills_input_value") ||
        pill.querySelector(".radio_input_value") ||
        pill;
      const raw = (labelEl.textContent || "").trim();
      let addon = "";
      if (raw === "Motorized, Remote controlled") {
        addon = "Motor, Remote & Charger";
      } else if (raw === "Motorized, Smartphone controlled") {
        addon = "Motor, ZigBee Gateway & Charger";
      }
      if (addon && !pill.querySelector(".lx-pill-addon")) {
        const span = document.createElement("span");
        span.className = "lx-pill-addon";
        span.textContent = addon;
        pill.appendChild(span);
      }
    });
  },
});


document.addEventListener("DOMContentLoaded", () => {
  const selector =
    "#wrapwrap .js_add_cart_variants > li.variant_attribute:first-of-type label.css_attribute_color," +
    "#wrapwrap .js_add_cart_variants > li.variant_attribute:first-of-type label.css_attribute_image";

  function injectTitles() {
    document.querySelectorAll(selector).forEach(label => {
      label.removeAttribute("title");
      label.removeAttribute("data-bs-original-title");
      const old = label.querySelector(".lx-title");
      if (old) old.remove();
    });
  }

  injectTitles();
  setTimeout(injectTitles, 500);
  document.addEventListener("shop_variants_loaded", injectTitles);
});
