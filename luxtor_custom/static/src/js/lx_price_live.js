/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

publicWidget.registry.LxVirtualPriceDebug = publicWidget.Widget.extend({
    selector: ".oe_website_sale",

    events: {
        "input  #lx_width_input":  "_onDimsChange",
        "change #lx_width_input":  "_onDimsChange",
        "input  #lx_height_input": "_onDimsChange",
        "change #lx_height_input": "_onDimsChange",
        "change #lx_location_input": "_onLocationChange",
        "change input[name='product_id']": "_onVariantChange",
    },

    start() {
        const res = this._super(...arguments);
        this._ensureDebugBox();
        this._ensureLocationField();
        this._loadLocationOptions();
        this._refresh();
        return res;
    },

    // ------- helpers -------
    _ensureDebugBox() {
        const host = document.querySelector("#lx_dims_express") || this.el;
        let box = host.querySelector("#lx_price_debug");
        if (!box) {
            box = document.createElement("div");
            box.id = "lx_price_debug";
            // Always start hidden — only revealed explicitly for debug purposes
            box.className = "alert alert-info d-none mt-3";
            box.style.whiteSpace = "pre-line";
            host.appendChild(box);
        }
    },

    _ensureLocationField() {
        const host = document.querySelector("#lx_dims_express");
        if (!host || host.querySelector("#lx_location_input")) {
            return;
        }
        const widthField = host.querySelector("#lx_width_input")?.closest(".lx-dim-field");
        if (!widthField) {
            return;
        }

        const wrapper = document.createElement("div");
        wrapper.className = "lx-dim-field";
        wrapper.innerHTML = `
            <h6 class="attribute_name mb-2 lx-dim-heading"
                style="display:block !important;text-transform:uppercase !important;font-size:0.82rem !important;font-weight:700 !important;letter-spacing:0.05em !important;color:#6b7280 !important;margin:0 0 0.5rem 0 !important;line-height:1.2 !important;padding:0 !important;border:0 !important;background:transparent !important;font-style:normal !important;font-family:'Poppins', 'Odoo Unicode Support Noto', sans-serif !important;text-align:left !important;box-shadow:none !important;">
              <span>LOCATION</span><span class="notificationmessage" data-tooltip="Enter your room"> ?</span>
            </h6>
            <label for="lx_location_input" class="visually-hidden">Location</label>
            <select id="lx_location_input"
                    name="lx_location_id"
                    class="form-select js-lx-location lx-dim-input"
                    data-lx-location-loaded="0">
              <option value="">Loading locations...</option>
            </select>
        `;
        host.insertBefore(wrapper, widthField);
    },

    _ensureFinalPriceInput() {
        const form =
            document.querySelector('#product_details form[action*="/shop/cart"]') ||
            document.querySelector('form.js_add_cart_json') ||
            document.querySelector('.oe_website_sale form');

        if (!form) return null;

        let inp = form.querySelector('input[name="lx_final_unit_price"]');
        if (!inp) {
            inp = document.createElement('input');
            inp.type = 'hidden';
            inp.name = 'lx_final_unit_price';
            inp.id = 'lx_final_unit_price';
            form.appendChild(inp);
        }
        return inp;
    },


    _currentVariantId() {
        const input = document.querySelector('input[name="product_id"]');
        return input ? parseInt(input.value || "0", 10) || 0 : 0;
    },

    _readDims() {
        const w = parseFloat((document.querySelector("#lx_width_input")?.value || "").trim());
        const h = parseFloat((document.querySelector("#lx_height_input")?.value || "").trim());
        return {
            width: Number.isFinite(w) ? w : 0,
            height: Number.isFinite(h) ? h : 0,
        };
    },

    _readLocationId() {
        const raw = (document.querySelector("#lx_location_input")?.value || "").trim();
        const loc = parseInt(raw || "0", 10);
        return Number.isFinite(loc) && loc > 0 ? loc : 0;
    },

    async _loadLocationOptions() {
        this._ensureLocationField();
        const select = document.querySelector("#lx_location_input");
        if (!select) {
            return;
        }
        if (select.dataset.lxLocationLoaded === "1" && select.options.length) {
            this._storeDimsInSession();
            return;
        }
        try {
            const locations = await rpc("/lx/configurator/locations", {});
            if (!Array.isArray(locations) || !locations.length) {
                return;
            }
            const currentValue = parseInt(select.value || "0", 10) || 0;
            const other = locations.find(
                (location) => (location.name || "").trim().toLowerCase() === "other"
            );
            const selectedValue = currentValue
                || (other && other.id)
                || locations[0].id;

            select.innerHTML = "";
            for (const location of locations) {
                const option = document.createElement("option");
                option.value = String(location.id);
                option.textContent = location.name;
                if (location.id === selectedValue) {
                    option.selected = true;
                }
                select.appendChild(option);
            }
            select.dataset.lxLocationLoaded = "1";
            this._storeDimsInSession();
        } catch (e) {
            console.warn("[LxVirtualPriceDebug] location load failed", e);
        }
    },

    async _refresh() {
        this._ensureDebugBox();
        const box = document.querySelector("#lx_price_debug");
        const pid = this._currentVariantId();
        let { width, height } = this._readDims();

        // Fallbacks: if user clears inputs, use safe size = 1 (unit price)
        let usedDefaults = false;
        if (!width && !height) {                 // both empty
            width = 1; height = 1; usedDefaults = true;
        } else {
            if (!width)  { width  = 1; usedDefaults = true; }   // one empty -> 1
            if (!height) { height = 1; usedDefaults = true; }
        }

        try {
            const data = await rpc("/shop/lx_virtual_price", {
                product_id: pid,
                width,
                height,
            });

            if (!data || !data.ok) {
                const txt = (data && data.message) || "Error.";
                return;
            }
            
            

            const msg =
                `Virtual unit price (w=1.00): ${data.unit_virtual.toFixed(2)}\n` +
                `Width: ${data.width_m.toFixed(2)} m, Height: ${data.height_m.toFixed(2)} m\n` +
                `Size: ${data.size.toFixed(2)} m²\n` +
                `Final unit price = ${data.unit_virtual.toFixed(2)} × ${data.size.toFixed(2)} = ${data.final_unit_price.toFixed(2)}`;

            const hidden = this._ensureFinalPriceInput();
            if (hidden) hidden.value = Number(data.final_unit_price || 0).toFixed(2);

            if (data.final_unit_price && Number(data.final_unit_price) > 0) {
                  this._updatePagePrice(data.final_unit_price);
              }
        } catch (e) {
            // Silent fail — hide the debug box; don't show an error banner on the page
            if (box) box.classList.add("d-none");
        }
    },

    _show(box, text, isError) {
        box.classList.remove("d-none", "alert-info", "alert-danger");
        box.classList.add(isError ? "alert-danger" : "alert-info");
        box.textContent = text;
    },
    
    // Locate the price value node — tries V19 selectors first, then V18 fallbacks.
    _priceNode() {
        return (
            // V19: monetary_field span inside the product price block
            document.querySelector('.o_wsale_product_details_content_section_price .oe_currency_value') ||
            document.querySelector('.o_wsale_product_details_content_section_price .o_currency_value') ||
            document.querySelector('.o_wsale_product_price .oe_currency_value') ||
            document.querySelector('.o_wsale_product_price .o_currency_value') ||
            // V18 / legacy fallbacks
            document.querySelector('#product_details .oe_price .oe_currency_value') ||
            document.querySelector('#product_details [itemprop="price"]') ||
            document.querySelector('#product_details .monetary_field .oe_currency_value') ||
            null
        );
    },
    
    // ADD: update page price if > 0 (keeps everything else intact)
    _updatePagePrice(newPrice) {
        const node = this._priceNode();
        const v = Number(newPrice);
        if (!node || !Number.isFinite(v) || v <= 0) return;
    
        // write numeric value (currency symbol/format usually handled around this span)
        node.textContent = v.toFixed(2);
    
        // also update schema.org price content if present
        const schemaPrice = document.querySelector('#product_details [itemprop="price"]');
        if (schemaPrice && schemaPrice.hasAttribute('content')) {
            schemaPrice.setAttribute('content', v.toFixed(2));
        }
    },

    // ------- event handlers -------
    _onDimsChange() {
        this._refresh();
        // Keep session dims in sync so the server-side price fallback
        // always has current values when V19 configurator bypasses the JS patch
        this._storeDimsInSession();
    },

    _storeDimsInSession() {
        const { width, height } = this._readDims();
        const loc = this._readLocationId();
        const w = Number.isFinite(width)  && width  > 0 ? width  : 1;
        const h = Number.isFinite(height) && height > 0 ? height : 1;
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
    },

    // paste this right after _onDimsChange()
    _onVariantChange(ev) {
        setTimeout(() => this._refresh(), 60);
    },

    _onLocationChange() {
        this._storeDimsInSession();
    },
});

