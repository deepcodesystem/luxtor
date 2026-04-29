/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

/* =============================================================
   Helpers partagés
   ============================================================= */
function readDims(root) {
    const form = root && root.closest ? root.closest("form") : null;
    const get = (sel) => (form ? form.querySelector(sel) : document.querySelector(sel));
    const wEl = get("#lx_width_input")  || get("[name='lx_width_m']");
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
        let v = el.getAttribute("data-value_name") || el.getAttribute("data-value-name") || el.title || "";
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
        if (v.includes("R-002-22")) return v.replace("R-002-22", "Futura +");
        return v;
    });
}

/* =============================================================
   LxMrpCustomDetailTitle
   ============================================================= */
publicWidget.registry.LxMrpCustomDetailTitle = publicWidget.Widget.extend({
    selector: ".oe_website_sale",

    start() {
        const res = this._super(...arguments);
        if (!document.getElementById("lx_dims_express")) return res;

        const nameH1 = document.querySelector("h1[itemprop='name']")
                    || document.querySelector('#product_details h1')
                    || document.querySelector('#o_wsale_product_details_content h1')
                    || document.querySelector('.js_main_product h1');
        if (!nameH1) return res;

        let box = document.getElementById("lx-custom-detail-title");
        if (!box) {
            box = document.createElement("div");
            box.id = "lx-custom-detail-title";
            box.className = "mt-1 mb-2";
            nameH1.insertAdjacentElement("afterend", box);
        }

        const render = () => {
        const productName = (nameH1.textContent || "").trim();
        const variants = readVariants();
        const { w, h } = readDims(box);
        const variantLine = `${productName}${variants.length ? " " + variants.join(", ") : ""}`;
        const wf = parseFloat(w) || 1;
        const hf = parseFloat(h) || 1;
        const dimsLine    = `Width: ${wf.toFixed(2)}m, Height: ${hf.toFixed(2)}m`;
                box.innerHTML =
                    `<p class="lx-title-variants mb-0">${variantLine}</p>` +
                    `<p class="lx-title-dims mb-0">${dimsLine}</p>`;
            };

        document.addEventListener("input",  render, true);
        document.addEventListener("change", render, true);
        window.addEventListener("hashchange", render);
        document.addEventListener("combination_found", render, true);

        this._h1Observer = new MutationObserver(render);
        this._h1Observer.observe(nameH1, { childList: true, subtree: true, characterData: true });

        const variantList = document.querySelector('.js_add_cart_variants');
        if (variantList) {
            this._varObserver = new MutationObserver(render);
            this._varObserver.observe(variantList, { childList: true, subtree: true, characterData: true });
        }

        render();
        setTimeout(render, 300);
        return res;
    },

    destroy() {
        if (this._h1Observer)  this._h1Observer.disconnect();
        if (this._varObserver) this._varObserver.disconnect();
        return this._super(...arguments);
    },
});

export default publicWidget.registry.LxMrpCustomDetailTitle;


/* =============================================================
   LxHeadrailTitles — PORTÉ DE v18 VERS v19
   Gère l'affichage "Futura" / "Futura +" dans les CARTES IMAGE
   via data-value_name sur les inputs.
   Logique identique à v18 : find → map → create/update span.lx-var-title
   ============================================================= */
publicWidget.registry.LxHeadrailTitles = publicWidget.Widget.extend({
    selector: '.oe_website_sale',

    start() {
        const res = this._super(...arguments);

        this._applyTitles();
        setTimeout(() => this._applyTitles(), 350);
        setTimeout(() => this._applyTitles(), 850);

        // Listeners change + click comme v18
        this._onChange = () => this._applyTitles();
        this.el.addEventListener('change', this._onChange, { passive: true });
        this.el.addEventListener('click',  this._onChange, { passive: true });

        // combination_found = événement Odoo après sélection variante
        this._onCombination = () => this._applyTitles();
        document.addEventListener('combination_found', this._onCombination, true);

        // MutationObserver sur la zone variantes
        const root = this.el.querySelector('.js_add_cart_variants') || this.el;
        this._observer = new MutationObserver(() => this._applyTitles());
        this._observer.observe(root, { childList: true, subtree: true });

        return res;
    },

    destroy() {
        if (this._observer) this._observer.disconnect();
        if (this._onChange) {
            this.el.removeEventListener('change', this._onChange);
            this.el.removeEventListener('click',  this._onChange);
        }
        if (this._onCombination) {
            document.removeEventListener('combination_found', this._onCombination, true);
        }
        return this._super(...arguments);
    },

    /* Même logique que v18 */
    _mapPrettyName(name) {
        const n = (name || '').trim();
        if (/R-?002-?21/i.test(n)) return 'Futura';
        if (/R-?002-?22/i.test(n)) return 'Futura +';
        return n;
    },

    _stripHoverTitles(scope) {
        const root = scope || this.el;
        root.querySelectorAll(
            '.js_add_cart_variants li.variant_attribute:first-of-type li.list-inline-item,' +
            '.js_add_cart_variants li.variant_attribute:first-of-type label.css_attribute_image,' +
            '.js_add_cart_variants li.variant_attribute:first-of-type label.css_attribute_color,' +
            '.js_add_cart_variants li.variant_attribute:first-of-type label.css_attribute_image *,' +
            '.js_add_cart_variants li.variant_attribute:first-of-type label.css_attribute_color *,' +
            '.js_add_cart_variants li.variant_attribute:first-of-type input.js_variant_change'
        ).forEach((node) => {
            node.removeAttribute('title');
            node.removeAttribute('data-bs-original-title');
        });
    },

    _applyTitles() {
        const variants = this.el.querySelector('.js_add_cart_variants');
        if (!variants) return;

        // Toutes les variantes de type css_attribute_color (cartes image)
        // v18 ne ciblait que le premier groupe ; en v19 on traite tous les groupes
        // pour couvrir CASSETTE (renommé depuis VALANCE) et autres
        variants.querySelectorAll('li.variant_attribute').forEach((attrGroup) => {
            attrGroup.querySelectorAll('li.list-inline-item').forEach((item) => {
                // V18: css_attribute_color | V19 image display type: css_attribute_image
                const label = item.querySelector('label.css_attribute_color, label.css_attribute_image');
                const input = item.querySelector('input.js_variant_change');
                if (!label || !input) return;

                // Strip inline border-color Odoo injects from attribute html_color
                label.style.removeProperty('border-color');
                label.style.removeProperty('border');

                // Lire le nom depuis data-value_name (même source que v18)
                const raw = input.getAttribute('data-value_name')
                         || input.getAttribute('data-value-name')
                         || input.dataset.value_name
                         || '';
                const pretty = this._mapPrettyName(raw);
                if (!pretty) return;

                label.removeAttribute('title');
                item.removeAttribute('title');
                input.removeAttribute('title');

                // Styles carte (identiques à v18 — inline pour survivre aux re-renders)
                label.style.display = 'grid';
                label.style.gridTemplateRows = '1fr auto';
                label.style.placeItems = 'center';

                // Créer ou mettre à jour le span titre (comme v18)
                let span = label.querySelector('.lx-var-title');
                if (!span) {
                    span = document.createElement('span');
                    span.className = 'lx-var-title';
                    label.appendChild(span);
                }
                if (span.textContent !== pretty) {
                    span.textContent = pretty;
                }

                // Pad image (identique à v18)
                let pad = label.querySelector('.lx-img-pad');
                if (!pad) {
                    pad = document.createElement('div');
                    pad.className = 'lx-img-pad';
                    label.insertBefore(pad, span);
                }
            });
        });

        this._stripHoverTitles(variants);
    },
});

publicWidget.registry.LxHeadrailTitles;


/* =============================================================
   LxControlTypeAddons
   ============================================================= */
publicWidget.registry.LxControlTypeAddons = publicWidget.Widget.extend({
    selector: ".oe_website_sale",

    start() {
        const res = this._super(...arguments);
        this._decoratePills();
        setTimeout(() => this._decoratePills(), 400);
        setTimeout(() => this._decoratePills(), 900);

        this._mo = new MutationObserver(() => this._decoratePills());
        this._mo.observe(this.el, { childList: true, subtree: true });

        this._onEvt = () => this._decoratePills();
        document.addEventListener("combination_found", this._onEvt, true);
        return res;
    },

    destroy() {
        if (this._mo) this._mo.disconnect();
        if (this._onEvt) document.removeEventListener("combination_found", this._onEvt, true);
        return this._super(...arguments);
    },

    _decoratePills() {
        document.querySelectorAll(".o_variant_pills.btn").forEach((pill) => {
            const labelEl =
                pill.querySelector(".o_variant_pills_input_value") ||
                pill.querySelector(".radio_input_value") ||
                pill;
            const raw = (labelEl.textContent || "").trim().toLowerCase();
            let addon = "";
            if (raw.includes("remote controlled") || raw.includes("remote control")) {
                addon = "Motor, Remote & Charger";
            } else if (raw.includes("smartphone") || raw.includes("zigbee")) {
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

publicWidget.registry.LxControlTypeAddons;


// LxAttributeInfoMessages and LxMutedRename moved to lx_variant_ui.js


/* =============================================================
   LxStaticNotifAfterAttributes
   ============================================================= */
publicWidget.registry.LxStaticNotifAfterAttributes = publicWidget.Widget.extend({
    selector: ".oe_website_sale",

    start() {
        const res = this._super(...arguments);
        this._injectStaticNote();
        setTimeout(() => this._injectStaticNote(), 400);
        setTimeout(() => this._injectStaticNote(), 900);

        this._mo = new MutationObserver(() => this._injectStaticNote());
        this._mo.observe(this.el, { childList: true, subtree: true });

        this._onEvt = () => this._injectStaticNote();
        document.addEventListener("combination_found", this._onEvt, true);
        return res;
    },

    destroy() {
        if (this._mo) this._mo.disconnect();
        if (this._onEvt) document.removeEventListener("combination_found", this._onEvt, true);
        return this._super(...arguments);
    },

    _injectStaticNote() {
        if (document.getElementById("lx-static-attributes-note")) return;

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
            💡 Tip: Choose <strong>"Motor Only"</strong> option to prevent excess charges.
          </div>
        `;

        const variantList = document.querySelector(".js_add_cart_variants");
        const anchor = variantList || document.querySelector("#o_wsale_product_details_content");
        if (anchor) anchor.insertAdjacentElement("afterend", box);
    },
});

publicWidget.registry.LxStaticNotifAfterAttributes;
