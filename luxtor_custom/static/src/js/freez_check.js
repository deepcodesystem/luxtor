/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

/* ---------- CSS (message + état disabled) ---------- */
function ensureStyleOnce() {
  if (document.getElementById("lx-availability-style")) return;
  const style = document.createElement("style");
  style.id = "lx-availability-style";
  style.textContent = `
    .lx-availability-text {
      font-size: 15px !important;
      font-weight: 900 !important;
      color: #b26a00 !important;
      margin-top: 6px !important;
      margin-bottom: 8px !important;     
      margin-right: 12px !important;

      line-height: 1.25 !important;
    }
    /* Force afficher si masqué par un thème */
    .lx-force-visible { display: inline-flex !important; }

    /* États désactivés — lisibilité + UX */
    a.js_add_cart_json[disabled],
    button.js_add_cart_json[disabled],
    #add_to_cart[disabled],
    .o_wsale_product_btn[disabled],
    button[name="add"][disabled],
    .disabled.lx-disabled-btn {
      opacity: 0.55;
      cursor: not-allowed !important;
      pointer-events: none !important;
      filter: grayscale(30%);
    }
    .css_quantity input[disabled],
    input[name="quantity"][disabled],
    .lx-disabled-input {
      opacity: 0.6;
      cursor: not-allowed !important;
      background-color: rgba(0,0,0,0.04) !important;
    }
  `;
  document.head.appendChild(style);
}

/* ---------- helpers DOM ---------- */
function getTemplateId() {
  const holder = document.querySelector("[data-product-template-id]");
  if (holder) {
    const v = holder.getAttribute("data-product-template-id");
    if (v && String(v).trim()) return parseInt(v, 10) || 0;
  }
  const alt = document.querySelector("input[name='product-template-id']");
  if (alt && alt.value) return parseInt(alt.value, 10) || 0;
  return 0;
}

function findQtyContainer() {
  return (
    document.querySelector("#product_details .o_wsale_product_quantity") ||
    document.querySelector("#product_details .css_quantity") ||
    document.querySelector("form[action*='/shop/cart'] .o_wsale_product_quantity") ||
    document.querySelector("form[action*='/shop/cart'] .css_quantity") ||
    document.getElementById("lx-availability-anchor") ||
    null
  );
}

function getOrCreateAvailabilityBoxNearQty() {
  let el = document.getElementById("lx-availability-box");
  if (el) return el;
  const afterEl = findQtyContainer();
  el = document.createElement("div");
  el.id = "lx-availability-box";
  el.className = "lx-availability-text";
  el.setAttribute("role", "status");
  el.setAttribute("aria-live", "polite");
  if (afterEl && afterEl.parentNode) {
    afterEl.insertAdjacentElement("afterend", el);
  } else {
    (document.querySelector("#product_details") || document.body).appendChild(el);
  }
  return el;
}

function availabilityOn(msg) {
  ensureStyleOnce();
  const el = getOrCreateAvailabilityBoxNearQty();
  el.textContent = msg || "Not enough Inventory !";
}
function availabilityOff() {
  const el = document.getElementById("lx-availability-box");
  if (el) el.textContent = "";
}

function getActionButtons() {
  return Array.from(
    document.querySelectorAll(
      [
        "#add_to_cart",
        "button.js_add_cart_json",
        "a.js_add_cart_json",
        ".o_wsale_product_btn",
        "button[name='add']",
      ].join(",")
    )
  );
}
function getQtyInputs() {
  return Array.from(
    document.querySelectorAll(
      [
        "input[name='quantity']",
        "input[name='add_qty']",
        "#product_details .css_quantity input",
        "form[action*='/shop/cart'] .css_quantity input",
      ].join(",")
    )
  );
}

function forceVisible(el) {
  if (!el) return;
  ensureStyleOnce();
  el.classList.add("lx-force-visible");
  el.style.removeProperty("display");
  el.classList.remove("d-none", "o_hidden");
  el.removeAttribute("hidden");
  el.setAttribute("aria-hidden", "false");
}

function setDisabledState(disabled) {
  ensureStyleOnce();

  const btns = getActionButtons();
  const qtys = getQtyInputs();

  btns.forEach((b) => {
    forceVisible(b);
    if (disabled) {
      b.setAttribute("disabled", "disabled");
      b.setAttribute("aria-disabled", "true");
      b.classList.add("disabled", "lx-disabled-btn");
      b.style.pointerEvents = "none";
    } else {
      b.removeAttribute("disabled");
      b.removeAttribute("aria-disabled");
      b.classList.remove("disabled", "lx-disabled-btn");
      b.style.pointerEvents = "";
    }
  });

  qtys.forEach((q) => {
    const wrap = q.closest(".css_quantity");
    if (wrap) forceVisible(wrap);
    if (disabled) {
      q.setAttribute("disabled", "disabled");
      q.classList.add("lx-disabled-input");
    } else {
      q.removeAttribute("disabled");
      q.classList.remove("lx-disabled-input");
    }
  });
}

/* ---------- RPC ---------- */
async function checkFreeze(tmplId) {
  if (!tmplId) return { ok: false, freeze: false, msg: "", ratio: null };
  try {
    const res = await rpc("/shop/lx_freeze_check", { product_template_id: tmplId });
    return res || { ok: false, freeze: false, msg: "", ratio: null };
  } catch {
    return { ok: false, freeze: false, msg: "", ratio: null };
  }
}

/* ---------- DÉSactivation instantanée dès que possible (onload ultra-rapide) ---------- */
/* Pré-désactiver dès que le DOM est prêt (avant même le widget), pour éviter tout flicker */
(function instantPreDisable() {
  const run = () => {
    ensureStyleOnce();
    setDisabledState(true);
  };
  if (document.readyState === "complete" || document.readyState === "interactive") {
    // synchronisé si le DOM est déjà prêt
    run();
  } else {
    document.addEventListener("DOMContentLoaded", run, { once: true, passive: true });
  }
})();

/* ---------- Widget principal ---------- */
publicWidget.registry.LxFabricFreezeInstant = publicWidget.Widget.extend({
  selector: ".oe_website_sale",

  start() {
    const r = this._super(...arguments);

    // 1) On garantit un état visuel immédiat (déjà fait par instantPreDisable).
    // 2) On lance la vérification le plus tôt possible (microtask/RAF).
    const applyNow = () => this._apply(getTemplateId());
    (window.requestAnimationFrame ? requestAnimationFrame(applyNow) : setTimeout(applyNow, 0));

    // Variantes / quantité → réponse rapide
    this._changeHandler = (e) => {
      const t = e && e.target;
      if (
        t &&
        t.matches(
          ".js_variant_change, select.js_variant_change, input[name='quantity'], input[name='add_qty']"
        )
      ) {
        setDisabledState(true);
        this._apply(getTemplateId());
      }
    };
    document.addEventListener("change", this._changeHandler, true);

    // Bloque les clics si disabled
    this._clickBlocker = (e) => {
      const el = e.target.closest("a, button");
      if (el && (el.getAttribute("aria-disabled") === "true" || el.hasAttribute("disabled"))) {
        e.preventDefault();
        e.stopPropagation();
      }
    };
    document.addEventListener("click", this._clickBlocker, true);

    // Si le DOM est re-rendu, on force visibilité
    this._mo = new MutationObserver(() => {
      getActionButtons().forEach(forceVisible);
      getQtyInputs().forEach((q) => forceVisible(q.closest(".css_quantity") || q));
    });
    const root = document.querySelector("#product_details") || document.body;
    this._mo.observe(root, { childList: true, subtree: true });

    return r;
  },

  destroy() {
    if (this._changeHandler) document.removeEventListener("change", this._changeHandler, true);
    if (this._clickBlocker) document.removeEventListener("click", this._clickBlocker, true);
    if (this._mo) this._mo.disconnect();
    this._super(...arguments);
  },

  async _apply(tmplId) {
    const res = await checkFreeze(tmplId);
    if (res && res.ok && res.freeze) {
      availabilityOn(res.msg || "Not enough Inventory !");
      setDisabledState(true);
    } else {
      availabilityOff();
      setDisabledState(false);
    }
  },
});

export default publicWidget.registry.LxFabricFreezeInstant;
