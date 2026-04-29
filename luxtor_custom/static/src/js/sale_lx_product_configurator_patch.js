/** @odoo-module **/
/**
 * Luxtor — sale.Product patch
 *
 * Based on the working version (doc 23) with Motor Only feature added.
 *
 * ADDED:
 *   - lxMotorVariantStore: plain module-level store (same pattern as lxLocationStore)
 *     immune to OWL proxy issues, holds the selected motor variant id.
 *   - lxState.isMotorOnly: boolean, shows/hides the motor radio buttons
 *   - lxState.motorVariants: [{id, name, code}] loaded once on mount
 *   - lxState.lx_motor_variant_id: reactive, drives radio button checked state
 *   - _lxCheckMotorOnly(productId): RPC call to detect Motor Only variant
 *   - _lxFetchMotorVariants(): RPC call to load motor variants once
 *   - lxOnMotorVariantChange(ev): handler for radio button change
 *   - onWillUpdateProps: calls _lxCheckMotorOnly when variant changes
 */

import { patch } from "@web/core/utils/patch";
import { rpc }   from "@web/core/network/rpc";
import { Product } from "@sale/js/product/product";
import { ProductConfiguratorDialog } from "@sale/js/product_configurator_dialog/product_configurator_dialog";
import { useState, onMounted, onWillUnmount, onWillUpdateProps } from "@odoo/owl";

/** Reactive state store — used by payload patch for width/height */
export const lxDimStore = {};

/** Plain location store — immune to OWL proxy issues */
export const lxLocationStore = {};

/** Plain motor variant store — immune to OWL proxy issues */
export const lxMotorVariantStore = {};

export const lxConfiguratorContext = {
    orderId: 0,
};

const LX_PC_DEBUG = true;

function lxPcLog(...args) {
    if (LX_PC_DEBUG) {
        console.log("[LX-PC]", ...args);
    }
}

function lxGetBestState() {
    const allDims = Object.values(lxDimStore || {});
    let dims = null;
    let bestScore = -1;
    for (const state of allDims) {
        const score =
            ((state?.lx_motor_variant_id || 0) > 0 ? 4 : 0) +
            ((state?.lx_location_id || 0) > 0 ? 3 : 0) +
            ((state?.lx_width_m || 0) > 0 ? 2 : 0) +
            ((state?.lx_height_m || 0) > 0 ? 1 : 0);
        if (score > bestScore) {
            bestScore = score;
            dims = state;
        }
    }
    return dims || allDims[allDims.length - 1] || null;
}

function lxGetCurrentOrderId() {
    const parsed = parseInt(lxConfiguratorContext.orderId || 0, 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

async function lxFetchBackendDialogUnitPrice({ productTmplId, productId, width, motorVariantId, orderId }) {
    const tmplId = parseInt(productTmplId || 0, 10) || 0;
    const variantId = parseInt(productId || 0, 10) || 0;
    if (!tmplId && !variantId) {
        return 0;
    }
    try {
        const res = await rpc("/lx/configurator/info", {
            product_tmpl_id: tmplId,
            product_id: variantId,
            width: width || 1,
            motor_variant_id: motorVariantId || 0,
            order_id: orderId || 0,
        });
        const price = Number(res?.price || 0);
        return res?.ok && price > 0 ? price : 0;
    } catch (error) {
        console.warn("[LX-PC]", "dialog.unit_price.fetch.error", error);
        return 0;
    }
}

function lxFormatDialogAmount(amount) {
    const parsed = Number(amount || 0);
    const safe = Number.isFinite(parsed) ? parsed : 0;
    return `${safe.toFixed(2)} DH`;
}

function lxFindOpenConfiguratorDialog() {
    return document.querySelector(".modal.show .modal-content")
        || document.querySelector(".o_dialog .modal-content")
        || document.querySelector(".modal .modal-content");
}

function lxSyncRenderedDialogTotal(totalAmount) {
    const dialog = lxFindOpenConfiguratorDialog();
    const footer = dialog?.querySelector(".modal-footer");
    if (!footer) {
        return;
    }

    for (const node of footer.childNodes) {
        if (node.nodeType === Node.TEXT_NODE && /total\s*:/i.test((node.textContent || "").trim())) {
            node.textContent = "";
        }
    }

    for (const node of footer.querySelectorAll("*")) {
        if (
            node.id !== "lx_configurator_total_display"
            && /total\s*:/i.test((node.textContent || "").trim())
            && !node.closest("#lx_configurator_total_display")
        ) {
            node.style.display = "none";
        }
    }

    let totalEl = footer.querySelector("#lx_configurator_total_display");
    if (!totalEl) {
        totalEl = document.createElement("span");
        totalEl.id = "lx_configurator_total_display";
        totalEl.className = "fw-bold ms-3";
        totalEl.style.whiteSpace = "nowrap";
        totalEl.style.display = "none";
        const cancelBtn = footer.querySelector(".btn.btn-secondary, .btn-outline-secondary");
        if (cancelBtn?.nextSibling) {
            footer.insertBefore(totalEl, cancelBtn.nextSibling);
        } else {
            footer.appendChild(totalEl);
        }
    }
    totalEl.textContent = `Total: ${lxFormatDialogAmount(totalAmount)}`;
}

patch(Product.prototype, {

    setup() {
        super.setup(...arguments);

        this.lxState = useState({
            lx_width_m:          0,
            lx_height_m:         0,
            lx_location_id:      0,
            locationOptions:     [],
            widthPlaceholder:    "min: 0.60 m",
            heightPlaceholder:   "min: 0.90 m",
            widthError:          "",
            heightError:         "",
            min_w: 0.60,
            max_w: 0,
            min_h: 0.90,
            max_h: 0,
            livePrice:           null,
            isDimensionProduct:  false,  // true when product has fabric/dimension config
            // Motor Only
            isMotorOnly:         false,
            motorVariants:       [],   // [{id, name, code}]
            lx_motor_variant_id: 0,
        });

        this._lxSeq       = 0;
        this._lxTimer     = null;
        this._lxLastPrice = null;
        this._lxUid       = `lx_${Date.now()}_${Math.floor(Math.random() * 1e9)}`;

        onMounted(() => {
            lxDimStore[this._lxUid]          = this.lxState;
            lxLocationStore[this._lxUid]     = 0;
            lxMotorVariantStore[this._lxUid] = 0;
            lxPcLog("product.mount", {
                uid: this._lxUid,
                productId: this.props.id || 0,
                productTmplId: this.props.product_tmpl_id || 0,
            });
            this._lxFetchInfo(1, this.props.id || null);
            this._lxFetchLocations();
            this._lxFetchMotorVariants();
            this._lxCheckMotorOnly(this.props.id);
        });

        onWillUpdateProps((nextProps) => {
            const variantChanged = nextProps.id !== this.props.id;
            const tmplChanged    = nextProps.product_tmpl_id !== this.props.product_tmpl_id;
            const qtyChanged     = nextProps.quantity !== this.props.quantity;
            const priceWasReset  = nextProps.price !== this.props.price;

            if (variantChanged || tmplChanged) {
                setTimeout(() => {
                    this._lxFetchInfo(
                        this.lxState.lx_width_m || 1,
                        nextProps.id || null,
                        nextProps.product_tmpl_id
                    );
                    // Check if the new variant is Motor Only
                    this._lxCheckMotorOnly(nextProps.id);
                }, 0);
            } else if ((qtyChanged || priceWasReset) && this._lxLastPrice) {
                setTimeout(() => {
                    this._lxSyncDialogPrice(this._lxLastPrice);
                }, 0);
            }
        });

        onWillUnmount(() => {
            if (this._lxTimer !== null) clearTimeout(this._lxTimer);
            delete lxDimStore[this._lxUid];
            // Keep lxLocationStore and lxMotorVariantStore entries
            // Payload patch reads them after unmount. Cleaned up on next mount cycle.
        });
    },

    // ── Check if current variant is Motor Only ────────────────────────────────
    async _lxCheckMotorOnly(productId) {
        if (!productId) {
            this.lxState.isMotorOnly = false;
            return;
        }
        try {
            const res = await rpc("/lx/configurator/is_motor_only", {
                product_id: productId,
            });
            this.lxState.isMotorOnly = res?.is_motor_only || false;
            // Reset motor selection when switching away from Motor Only
            if (!this.lxState.isMotorOnly) {
                this.lxState.lx_motor_variant_id  = 0;
                lxMotorVariantStore[this._lxUid]  = 0;
            } else {
                // Auto-select first motor if variants already loaded
                this._lxMaybeAutoSelectMotor();
            }
        } catch (e) {
            console.warn("[Luxtor] _lxCheckMotorOnly:", e);
            this.lxState.isMotorOnly = false;
        }
    },

    // ── Fetch motor variants once ─────────────────────────────────────────────
    async _lxFetchMotorVariants() {
        try {
            const res = await rpc("/lx/configurator/motor_variants", {});
            if (Array.isArray(res)) {
                this.lxState.motorVariants = res;
                lxPcLog("motor_variants.loaded", {
                    uid: this._lxUid,
                    count: res.length,
                    values: res,
                });
                // Auto-select first motor if product is already confirmed Motor Only
                this._lxMaybeAutoSelectMotor();
            }
        } catch (e) {
            console.warn("[Luxtor] _lxFetchMotorVariants:", e);
        }
    },

    // ── Auto-select first motor variant (called when both isMotorOnly and ─────
    // ── motorVariants are ready, whichever arrives last)  ────────────────────
    _lxMaybeAutoSelectMotor() {
        if (this.lxState.isMotorOnly
                && this.lxState.motorVariants.length > 0
                && !this.lxState.lx_motor_variant_id) {
            this.lxSetMotorVariant(this.lxState.motorVariants[0].id);
        }
    },

    // ── Fetch locations ───────────────────────────────────────────────────────
    async _lxFetchLocations() {
        try {
            const res = await rpc("/lx/configurator/locations", {});
            if (Array.isArray(res)) {
                this.lxState.locationOptions = res;
                lxPcLog("locations.loaded", {
                    uid: this._lxUid,
                    values: res,
                });
                this._lxAutoSelectLocation();
            }
        } catch (err) {
            console.warn("[Luxtor] _lxFetchLocations:", err);
        }
    },

    // ── Auto-select "Other" when isDimensionProduct and no location set ────────
    _lxAutoSelectLocation() {
        if (!this.lxState.isDimensionProduct) return;
        if (this.lxState.lx_location_id > 0) return;   // already chosen
        const options = this.lxState.locationOptions || [];
        if (!options.length) return;
        const other = options.find(
            o => (o.name || "").trim().toLowerCase() === "other"
        );
        if (other) {
            this.lxState.lx_location_id  = other.id;
            lxLocationStore[this._lxUid] = other.id;
            lxPcLog("location.auto_selected", {
                uid: this._lxUid,
                locationId: other.id,
                locationName: other.name,
            });
        }
    },

    // ── RPC: price + dimension limits ─────────────────────────────────────────
    async _lxFetchInfo(widthForQuery, productId, overrideTmplId) {
        const seq    = ++this._lxSeq;
        const tmplId = overrideTmplId || this.props.product_tmpl_id || 0;
        const pid    = (productId !== undefined) ? productId : (this.props.id || null);
        const orderId = lxGetCurrentOrderId();

        if (!tmplId && !pid) return;

        try {
            const res = await rpc("/lx/configurator/info", {
                product_tmpl_id:  tmplId || 0,
                product_id:       pid    || 0,
                width:            widthForQuery || 1,
                motor_variant_id: this.lxState.lx_motor_variant_id || 0,
                order_id:         orderId || 0,
            });

            if (seq !== this._lxSeq) return;
            if (!res?.ok) {
                this.lxState.isDimensionProduct = false;
                return;
            }

            const minW = Number(res.width_min  || 0.60);
            const maxW = Number(res.width_max  || 0);
            const minH = Number(res.height_min || 0.90);
            const maxH = Number(res.height_max || 0);

            let wPh = `min: ${minW.toFixed(2)} m`;
            if (maxW > 0) wPh += ` / max: ${maxW.toFixed(2)} m`;
            let hPh = `min: ${minH.toFixed(2)} m`;
            if (maxH > 0) hPh += ` / max: ${maxH.toFixed(2)} m`;

            this.lxState.widthPlaceholder  = wPh;
            this.lxState.heightPlaceholder = hPh;
            this.lxState.min_w = minW;
            this.lxState.max_w = maxW;
            this.lxState.min_h = minH;
            this.lxState.max_h = maxH;

            // Update dimension product flag, then auto-select default location
            this.lxState.isDimensionProduct = res.is_dimension_product || false;
            if (this.lxState.isDimensionProduct) {
                this._lxAutoSelectLocation();
            }

            if (res.price > 0) {
                this.lxState.livePrice  = Number(res.price);
                this._lxLastPrice       = Number(res.price);
                this._lxSyncDialogPrice(Number(res.price));
            }

            this._lxValidate();
        } catch (err) {
            if (seq !== this._lxSeq) return;
            console.warn("[Luxtor] _lxFetchInfo:", err);
        }
    },

    // ── Validation ────────────────────────────────────────────────────────────
    _lxValidate() {
        const { lx_width_m: w, lx_height_m: h, min_w, max_w, min_h, max_h } = this.lxState;
        this.lxState.widthError = w > 0
            ? (w < min_w ? `Minimum: ${min_w.toFixed(2)} m`
              : max_w > 0 && w > max_w ? `Maximum: ${max_w.toFixed(2)} m` : "")
            : "";
        this.lxState.heightError = h > 0
            ? (h < min_h ? `Minimum: ${min_h.toFixed(2)} m`
              : max_h > 0 && h > max_h ? `Maximum: ${max_h.toFixed(2)} m` : "")
            : "";
    },

    // ── Input / change handlers ───────────────────────────────────────────────
    lxOnWidthInput(ev) {
        const w = ev.target.value !== "" ? parseFloat(ev.target.value) : 0;
        this.lxState.lx_width_m = Number.isFinite(w) ? w : 0;
        this._lxValidate();
        if (this._lxTimer !== null) clearTimeout(this._lxTimer);
        this._lxTimer = setTimeout(() => {
            this._lxTimer = null;
            this._lxFetchInfo(this.lxState.lx_width_m || 1, this.props.id || null);
        }, 300);
    },

    lxOnHeightInput(ev) {
        const h = ev.target.value !== "" ? parseFloat(ev.target.value) : 0;
        this.lxState.lx_height_m = Number.isFinite(h) ? h : 0;
        this._lxValidate();
    },

    lxOnLocationChange(ev) {
        const val    = ev.target.value;
        const parsed = val ? parseInt(val, 10) : 0;
        this.lxState.lx_location_id  = parsed;
        lxLocationStore[this._lxUid] = parsed;
        const option = (this.lxState.locationOptions || []).find(loc => loc.id === parsed);
        lxPcLog("location.changed", {
            uid: this._lxUid,
            rawValue: val,
            parsed,
            option: option || null,
        });
    },

    lxOnMotorVariantChange(ev) {
        const val    = ev.target.value;
        const parsed = val ? parseInt(val, 10) : 0;
        this.lxState.lx_motor_variant_id  = parsed;
        lxMotorVariantStore[this._lxUid]  = parsed;
        const variant = (this.lxState.motorVariants || []).find(v => v.id === parsed);
        lxPcLog("motor_variant.changed", {
            uid: this._lxUid,
            rawValue: val,
            parsed,
            variant: variant || null,
        });
        // Refresh price at W=1: _compute_amount already multiplies price_unit
        // by (size * qty) where size = width * height, so the unit price must
        // be the per-m² rate computed at W=1 (same as _lx_compute_price_unit_like_wizard).
        this._lxFetchInfo(1, this.props.id || null);
    },

    // Called by t-on-click on the label — more reliable than change on the
    // hidden btn-check input in some OWL / browser combinations.
    lxSetMotorVariant(variantId) {
        const parsed = parseInt(variantId, 10) || 0;
        this.lxState.lx_motor_variant_id  = parsed;
        lxMotorVariantStore[this._lxUid]  = parsed;
        // Fetch price at W=1 (per-m² unit price, same convention as regular blinds)
        this._lxFetchInfo(1, this.props.id || null);
    },

    _lxSyncDialogPrice(price) {
        const parsedPrice = Number(price || 0);
        if (!(parsedPrice > 0)) {
            return;
        }
        if (this.props && "price" in this.props) {
            try { this.props.price = parsedPrice; } catch (_) {}
        }
        const envProducts = Array.isArray(this.env?.products) ? this.env.products : null;
        if (envProducts?.length) {
            const mainProduct = envProducts.find(
                (product) => product.product_tmpl_id === this.env?.mainProductTmplId
            );
            if (mainProduct) {
                try { mainProduct.price = parsedPrice; } catch (_) {}
            }
        }
        if (this.env?.mainProduct && typeof this.env.mainProduct === "object") {
            try { this.env.mainProduct.price = parsedPrice; } catch (_) {}
        }
        const qty = Number(this.props?.quantity || this.env?.mainProduct?.quantity || 1) || 1;
        lxSyncRenderedDialogTotal(parsedPrice * qty);
        lxPcLog("dialog.total.sync", {
            unitPrice: parsedPrice,
            quantity: qty,
            total: parsedPrice * qty,
        });
    },
});

patch(ProductConfiguratorDialog.prototype, {
    async _loadData(onlyMainProduct) {
        const data = await super._loadData(...arguments);
        await this._lxSyncMainProductDialogPrice(data?.products || []);
        return data;
    },

    async _updateCombination(product, quantity, uomId) {
        const values = await super._updateCombination(...arguments);
        const overriddenValues = await this._lxOverrideDialogPrice(product, values);
        this._lxSyncRenderedDialogPrice(product, overriddenValues, quantity);
        return overriddenValues;
    },

    async _lxSyncMainProductDialogPrice(products) {
        const mainProduct = (products || []).find(
            (product) => product.product_tmpl_id === this.env.mainProductTmplId
        );
        if (!mainProduct) {
            return;
        }
        const overriddenValues = await this._lxOverrideDialogPrice(mainProduct, mainProduct);
        if (overriddenValues?.price > 0) {
            mainProduct.price = parseFloat(overriddenValues.price);
            this._lxSyncRenderedDialogPrice(mainProduct, overriddenValues, mainProduct.quantity || 1);
        }
    },

    async _lxOverrideDialogPrice(product, values) {
        if (!product || !values || product.product_tmpl_id !== this.env.mainProductTmplId) {
            return values;
        }

        const dims = lxGetBestState();
        const configuredPrice = await lxFetchBackendDialogUnitPrice({
            orderId: this.props?.lx_order_id || lxGetCurrentOrderId(),
            productTmplId: product.product_tmpl_id || values.product_tmpl_id || this.env.mainProductTmplId,
            productId: values.id || product.id || 0,
            width: dims?.lx_width_m > 0 ? dims.lx_width_m : 1,
            motorVariantId: dims?.lx_motor_variant_id || 0,
        });
        if (!(configuredPrice > 0)) {
            return values;
        }

        if (dims) {
            dims.livePrice = configuredPrice;
        }

        const finalValues = {
            ...values,
            price: configuredPrice,
        };
        lxPcLog("dialog.price.override", {
            productId: product.id || values.id || 0,
            quantity: product.quantity || values.quantity || 0,
            configuredPrice,
        });
        return finalValues;
    },

    _lxSyncRenderedDialogPrice(product, values, quantity) {
        const unitPrice = Number(values?.price || product?.price || 0);
        const qty = Number(
            quantity
            || values?.quantity
            || product?.quantity
            || this.env?.mainProduct?.quantity
            || 1
        ) || 1;
        if (!(unitPrice > 0)) {
            return;
        }
        lxSyncRenderedDialogTotal(unitPrice * qty);
    },
});
