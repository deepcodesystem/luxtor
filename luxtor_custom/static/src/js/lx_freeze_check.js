/** @odoo-module **/
/**
 * LxFreezeFinal — Blocks Add to Cart when related fabric stock is frozen.
 * Calls /shop/lx_freeze_check and shows a banner; disables ATC buttons.
 */

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

/* ---------- Styles (injected once) ---------- */
function ensureStyleOnce() {
    if (document.getElementById("lx-freeze-style")) return;
    const style = document.createElement("style");
    style.id = "lx-freeze-style";
    style.textContent = `
        .lx-freeze-banner{
            margin-top: 10px;
            padding: 10px 12px;
            border-radius: 10px;
            font-weight: 900;
            font-size: 14px;
            background: rgba(220,53,69,.10);
            border: 1px solid rgba(220,53,69,.35);
            color: #b02a37;
            text-transform: uppercase;
            line-height: 1.25;
        }
        .lx-freeze-disabled{
            opacity: .55 !important;
            pointer-events: none !important;
            cursor: not-allowed !important;
            filter: grayscale(25%);
        }
    `;
    document.head.appendChild(style);
}

/* ---------- Legacy cleanup ---------- */
function killLegacyAvailabilityBox() {
    document.querySelectorAll("#lx-availability-box, .lx-availability-text").forEach((el) => el.remove());
}

/* ---------- DOM helpers ---------- */
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
    el.textContent = msg || "You can't continue: the related fabric is not enough in stock.";
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

/* ---------- RPC ---------- */
async function checkFreezeTemplate(tmplId) {
    if (!tmplId) return { ok: false, freeze: false };
    try {
        return await rpc("/shop/lx_freeze_check", { product_template_id: tmplId });
    } catch {
        return { ok: false, freeze: false };
    }
}

/* ---------- Widget ---------- */
publicWidget.registry.LxFreezeFinal = publicWidget.Widget.extend({
    selector: ".oe_website_sale",

    start() {
        const r = this._super(...arguments);

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
        if (this._clickHandler)  document.removeEventListener("click",  this._clickHandler,  true);
        if (this._changeHandler) document.removeEventListener("change", this._changeHandler, true);
        this._super(...arguments);
    },
});

export default publicWidget.registry.LxFreezeFinal;
