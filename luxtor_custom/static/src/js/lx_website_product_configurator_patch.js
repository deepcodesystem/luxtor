/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { rpc } from "@web/core/network/rpc";
import { ProductConfiguratorDialog } from "@sale/js/product_configurator_dialog/product_configurator_dialog";

function _readDimensionInputs() {
    const widthEl =
        document.querySelector("#lx_width_input") ||
        document.querySelector("input[name='lx_width_m']");
    const heightEl =
        document.querySelector("#lx_height_input") ||
        document.querySelector("input[name='lx_height_m']");

    if (!widthEl && !heightEl) {
        return null;
    }

    const toPositiveFloat = (value) => {
        const parsed = parseFloat(String(value ?? "").replace(",", "."));
        return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
    };

    const width = toPositiveFloat(widthEl?.value) || 1;
    const height = toPositiveFloat(heightEl?.value) || 1;

    return { width, height };
}

function _getFallbackVariantId() {
    const productInput = document.querySelector("input[name='product_id']");
    const productId = parseInt(productInput?.value || "0", 10);
    return Number.isFinite(productId) && productId > 0 ? productId : 0;
}

async function _fetchConfiguredWebsitePrice(productId, width, height) {
    if (!productId || width <= 0 || height <= 0) {
        return 0;
    }

    try {
        const result = await rpc("/shop/lx_virtual_price", {
            product_id: productId,
            width,
            height,
        });
        const finalPrice = Number(result?.final_unit_price || 0);
        return result?.ok && finalPrice > 0 ? finalPrice : 0;
    } catch (_) {
        return 0;
    }
}

patch(ProductConfiguratorDialog.prototype, {
    async _loadData(onlyMainProduct) {
        const data = await super._loadData(...arguments);
        await this._lxSyncMainProductWebsitePrice(data?.products || []);
        return data;
    },

    async _updateCombination(product, quantity, uomId) {
        const values = await super._updateCombination(...arguments);
        return await this._lxOverrideConfiguredPrice(product, values);
    },

    async _lxSyncMainProductWebsitePrice(products) {
        const mainProduct = (products || []).find(
            (product) => product.product_tmpl_id === this.env.mainProductTmplId
        );
        if (!mainProduct) {
            return;
        }

        const overriddenValues = await this._lxOverrideConfiguredPrice(mainProduct, mainProduct);
        if (overriddenValues?.price > 0) {
            mainProduct.price = parseFloat(overriddenValues.price);
        }
    },

    async _lxOverrideConfiguredPrice(product, values) {
        if (!product || !values || product.product_tmpl_id !== this.env.mainProductTmplId) {
            return values;
        }

        const dims = _readDimensionInputs();
        if (!dims) {
            return values;
        }

        const productId = values.id || product.id || _getFallbackVariantId();
        const configuredPrice = await _fetchConfiguredWebsitePrice(
            productId,
            dims.width,
            dims.height
        );

        if (!(configuredPrice > 0)) {
            return values;
        }

        return {
            ...values,
            price: configuredPrice,
        };
    },
});
