/** @odoo-module **/
/**
 * Luxtor — Configurator Payload Injection
 *
 * Two-phase write for lx_motor_only_variant_id:
 *
 * Phase 1 (pre-save): record._update() BEFORE originalSave so the value
 *   is in the dirty set if applyProduct respects existing dirty fields.
 *
 * Phase 2 (post-save): direct call_kw write AFTER originalSave to guarantee
 *   the value reaches the server even if the product_id onchange wipes Phase 1.
 *   After the write, reload the model so the new motor child lines are visible.
 *
 * dims selection: scan ALL lxDimStore entries and prefer the one that has
 *   a non-zero lx_motor_variant_id (main product component), falling back to
 *   the last entry.  This handles dialogs with optional-product cards that
 *   each create their own lxState entry.
 */

import { patch } from "@web/core/utils/patch";
import { rpc }   from "@web/core/network/rpc";
import { SaleOrderLineProductField } from "@sale/js/sale_product_field";
import { lxConfiguratorContext, lxDimStore, lxLocationStore, lxMotorVariantStore }
    from "./sale_lx_product_configurator_patch";

const LX_PC_DEBUG = true;

function lxPcLog(...args) {
    if (LX_PC_DEBUG) {
        console.log("[LX-PC]", ...args);
    }
}

function lxPcWarn(...args) {
    if (LX_PC_DEBUG) {
        console.warn("[LX-PC]", ...args);
    }
}

function lxPcM2O(id, label) {
    const parsed = parseInt(id, 10) || 0;
    if (!parsed) {
        return false;
    }
    return [parsed, label || String(parsed)];
}

function lxSleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

patch(SaleOrderLineProductField.prototype, {

    async _openProductConfigurator(edit = false, selectedComboItems = []) {
        const originalAdd = this.dialog.add.bind(this.dialog);

        this.dialog.add = (DialogClass, props, options) => {
            this.dialog.add = originalAdd;

            if (props && typeof props.save === "function") {
                const originalSave = props.save;
                const solRecord    = this.props.record;
                const currentOrderId = solRecord.model?.root?.resId || 0;
                lxConfiguratorContext.orderId = currentOrderId;
                props.lx_order_id = currentOrderId;

                props.save = async (mainProduct, optionalProducts, saveOptions) => {
                    // ── Snapshot BEFORE any await (components still mounted) ───
                    // Prefer the lxState entry that has a motor variant selected.
                    // Falls back to last entry (single-product dialogs).
                    const allDims = Object.values(lxDimStore);
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
                    dims = dims || allDims[allDims.length - 1] || null;

                    const locationInput = document.getElementById("lx_cfg_location");
                    const domLocId = locationInput?.value ? parseInt(locationInput.value, 10) || 0 : 0;
                    const locationStoreVals = Object.values(lxLocationStore).filter(v => v > 0);
                    const locId = (domLocId > 0 ? domLocId : 0)
                               || (dims?.lx_location_id > 0 ? dims.lx_location_id : 0)
                               || (locationStoreVals.length ? locationStoreVals[locationStoreVals.length - 1] : 0);
                    const locationOption = Array.isArray(dims?.locationOptions)
                        ? dims.locationOptions.find(loc => loc.id === locId)
                        : null;
                    const locationM2O = lxPcM2O(locId, locationOption?.name || "");

                    // Motor variant: prefer lxState (reactive), then plain store
                    const mtrStoreVals = Object.values(lxMotorVariantStore).filter(v => v > 0);
                    const mtrId = (dims?.lx_motor_variant_id > 0 ? dims.lx_motor_variant_id : 0)
                               || (mtrStoreVals.length ? Math.max(...mtrStoreVals) : 0);
                    const motorVariant = Array.isArray(dims?.motorVariants)
                        ? dims.motorVariants.find(v => v.id === mtrId)
                        : null;
                    const motorM2O = lxPcM2O(mtrId, motorVariant?.name || motorVariant?.label || "");

                    lxPcLog("confirm.start", {
                        dialogLocationValue: locationInput?.value || "",
                        domLocId,
                        locId,
                        locationM2O,
                        mtrId,
                        motorM2O,
                        dims: dims ? {
                            lx_width_m: dims.lx_width_m || 0,
                            lx_height_m: dims.lx_height_m || 0,
                            lx_location_id: dims.lx_location_id || 0,
                            lx_motor_variant_id: dims.lx_motor_variant_id || 0,
                            livePrice: dims.livePrice || 0,
                        } : null,
                        mainProduct,
                        optionalProducts,
                        saveOptions,
                        solRecordResId: solRecord.resId || null,
                        solRecordData: solRecord.data || null,
                        lxLocationStore: { ...lxLocationStore },
                        lxMotorVariantStore: { ...lxMotorVariantStore },
                    });

                    if (mainProduct && typeof mainProduct === "object") {
                        mainProduct.lx_location_id = locationM2O || false;
                        mainProduct.lx_motor_only_variant_id = motorM2O || false;
                        mainProduct.lx_width_m = dims?.lx_width_m || false;
                        mainProduct.lx_height_m = dims?.lx_height_m || false;
                    }
                    if (saveOptions && typeof saveOptions === "object") {
                        saveOptions.lx_location_id = locationM2O || false;
                        saveOptions.lx_motor_only_variant_id = motorM2O || false;
                        saveOptions.lx_width_m = dims?.lx_width_m || false;
                        saveOptions.lx_height_m = dims?.lx_height_m || false;
                    }

                    // ── Phase 1: dirty-state write BEFORE originalSave ─────────
                    const pendingOrderId = solRecord.model?.root?.resId || 0;
                    const pendingProductTmplId =
                        mainProduct?.product_tmpl_id
                        || solRecord.data?.product_template_id?.[0]
                        || solRecord.data?.product_template_id
                        || 0;
                    if (pendingOrderId && pendingProductTmplId) {
                        try {
                            lxPcLog("pending.store.request", {
                                order_id: pendingOrderId,
                                product_tmpl_id: pendingProductTmplId,
                                lx_location_id: locId || 0,
                                lx_motor_only_variant_id: mtrId || 0,
                                lx_width_m: dims?.lx_width_m || 0,
                                lx_height_m: dims?.lx_height_m || 0,
                                price_unit: dims?.livePrice || 0,
                            });
                            const pendingResp = await rpc("/lx/configurator/pending", {
                                order_id: pendingOrderId,
                                product_tmpl_id: pendingProductTmplId,
                                lx_location_id: locId || 0,
                                lx_motor_only_variant_id: mtrId || 0,
                                lx_width_m: dims?.lx_width_m || 0,
                                lx_height_m: dims?.lx_height_m || 0,
                                price_unit: dims?.livePrice || 0,
                            });
                            lxPcLog("pending.store.response", pendingResp);
                        } catch (error) {
                            lxPcWarn("pending.store.error", error);
                        }
                    }

                    const updateVals = {};
                    if (dims?.lx_width_m  > 0) updateVals.lx_width_m  = dims.lx_width_m;
                    if (dims?.lx_height_m > 0) updateVals.lx_height_m = dims.lx_height_m;
                    if (locationM2O) updateVals.lx_location_id = locationM2O;
                    if (motorM2O) updateVals.lx_motor_only_variant_id = motorM2O;
                    // Send the dialog price (W=1 per-m² unit price) directly so
                    // the SOL has the value even before server-side recalc runs.
                    if (dims?.livePrice > 0) {
                        updateVals.price_unit = dims.livePrice;
                    }

                    if (Object.keys(updateVals).length > 0) {
                        lxPcLog("record._update.before_save", updateVals);
                        await solRecord._update(updateVals);
                    }

                    // ── Standard applyProduct ──────────────────────────────────
                    const saveResult = await originalSave(mainProduct, optionalProducts, saveOptions);
                    lxPcLog("confirm.after_originalSave", {
                        mainProduct,
                        saveOptions,
                        solRecordResId: solRecord.resId || null,
                        solRecordData: solRecord.data || null,
                    });

                    // ── Phase 2: post-save direct write for motor variant ──────
                    // Needed when product_id onchange inside originalSave wipes
                    // the Phase-1 dirty value before the form auto-saves.
                    const postSaveVals = {};
                    if (dims?.lx_width_m > 0) postSaveVals.lx_width_m = dims.lx_width_m;
                    if (dims?.lx_height_m > 0) postSaveVals.lx_height_m = dims.lx_height_m;
                    if (locId > 0) postSaveVals.lx_location_id = locId;
                    if (mtrId > 0) postSaveVals.lx_motor_only_variant_id = mtrId;
                    if (dims?.livePrice > 0) {
                        postSaveVals.price_unit = dims.livePrice;
                    }

                    if (Object.keys(postSaveVals).length > 0) {
                        void (async () => {
                        // Resolve the SOL database id.
                        // For existing lines solRecord.resId is already set.
                        // For new lines, ask the backend to find the latest
                        // matching parent line using product + dimensions.
                        let solId = solRecord.resId || null;
                        const orderId = solRecord.model?.root?.resId;
                        const productId =
                            mainProduct?.product_id
                            || mainProduct?.id
                            || solRecord.data?.product_id?.[0]
                            || solRecord.data?.product_id
                            || 0;

                        if (!solId && orderId) {
                            try {
                                lxPcLog("server.locate_line.request", {
                                    orderId,
                                    productId,
                                    lx_width_m: dims?.lx_width_m || 0,
                                    lx_height_m: dims?.lx_height_m || 0,
                                    lx_location_id: locId || 0,
                                    lx_motor_only_variant_id: mtrId || 0,
                                    price_unit: postSaveVals.price_unit || 0,
                                });
                                solId = await rpc("/web/dataset/call_kw", {
                                    model: "sale.order.line",
                                    method: "lx_apply_configurator_values",
                                    args: [],
                                    kwargs: {
                                        order_id: orderId,
                                        product_id: productId,
                                        lx_width_m: dims?.lx_width_m || 0,
                                        lx_height_m: dims?.lx_height_m || 0,
                                        lx_location_id: locId || 0,
                                        lx_motor_only_variant_id: mtrId || 0,
                                        price_unit: postSaveVals.price_unit || 0,
                                    },
                                });
                                lxPcLog("server.locate_line.response", { solId });
                            } catch (error) {
                                lxPcWarn("server.locate_line.error", error);
                            }
                        }

                        if (!solId && orderId) {
                            for (let attempt = 1; attempt <= 10 && !solId; attempt++) {
                                await lxSleep(400);
                                try {
                                    lxPcLog("server.locate_line.retry.request", {
                                        attempt,
                                        orderId,
                                        productId,
                                        lx_width_m: dims?.lx_width_m || 0,
                                        lx_height_m: dims?.lx_height_m || 0,
                                        lx_location_id: locId || 0,
                                        lx_motor_only_variant_id: mtrId || 0,
                                        price_unit: postSaveVals.price_unit || 0,
                                    });
                                    solId = await rpc("/web/dataset/call_kw", {
                                        model: "sale.order.line",
                                        method: "lx_apply_configurator_values",
                                        args: [],
                                        kwargs: {
                                            order_id: orderId,
                                            product_id: productId,
                                            lx_width_m: dims?.lx_width_m || 0,
                                            lx_height_m: dims?.lx_height_m || 0,
                                            lx_location_id: locId || 0,
                                            lx_motor_only_variant_id: mtrId || 0,
                                            price_unit: postSaveVals.price_unit || 0,
                                        },
                                    });
                                    lxPcLog("server.locate_line.retry.response", {
                                        attempt,
                                        solId,
                                    });
                                } catch (error) {
                                    lxPcWarn("server.locate_line.retry.error", {
                                        attempt,
                                        error,
                                    });
                                }
                            }
                        }

                        if (solId) {
                            try {
                                lxPcLog("sale.order.line.write.request", {
                                    solId,
                                    postSaveVals,
                                });
                                await rpc("/web/dataset/call_kw", {
                                    model:  "sale.order.line",
                                    method: "write",
                                    args:   [[solId], postSaveVals],
                                    kwargs: {},
                                });
                                const readBack = await rpc("/web/dataset/call_kw", {
                                    model: "sale.order.line",
                                    method: "read",
                                    args: [[solId], [
                                        "id",
                                        "product_id",
                                        "lx_location_id",
                                        "lx_motor_only_variant_id",
                                        "lx_width_m",
                                        "lx_height_m",
                                        "price_unit",
                                    ]],
                                    kwargs: {},
                                });
                                lxPcLog("sale.order.line.write.readback", readBack?.[0] || null);
                                if (typeof solRecord.model?.load === "function") {
                                    await solRecord.model.load();
                                } else if (typeof solRecord.model?.root?.load === "function") {
                                    await solRecord.model.root.load();
                                }
                            } catch (e) {
                                lxPcWarn("configurator post-save write error", e);
                            }
                        } else {
                            lxPcWarn("no persisted sale.order.line id found after confirm", {
                                postSaveVals,
                                solRecordResId: solRecord.resId || null,
                            });
                        }
                        })();
                    }

                    // ── Cleanup ────────────────────────────────────────────────
                    for (const k of Object.keys(lxLocationStore))
                        lxLocationStore[k]     = 0;
                    for (const k of Object.keys(lxMotorVariantStore))
                        lxMotorVariantStore[k] = 0;
                    return saveResult;
                };
            }

            return originalAdd(DialogClass, props, options);
        };

        return super._openProductConfigurator(edit, selectedComboItems);
    },
});
