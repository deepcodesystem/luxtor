import VariantMixin from '@website_sale/js/variant_mixin';
import { WebsiteSale } from '@website_sale/interactions/website_sale';

const originalOnChangeCombination = WebsiteSale.prototype._onChangeCombination;
const originalHandleCustomValues = WebsiteSale.prototype.handleCustomValues;

function lxGetCustomValues(parent) {
    var customValues = {};
    parent.querySelectorAll('.variant_custom_value').forEach(function (input) {
        var ptavId = input.dataset.customProductTemplateAttributeValueId;
        if (ptavId && input.value) {
            customValues[ptavId] = input.value;
        }
    });
    return customValues;
}

function lxGetOptionalCombinationInfoParam(parent) {
    var customValues = lxGetCustomValues(parent);
    if (Object.keys(customValues).length) {
        return { custom_values: customValues };
    }
    return {};
}

function lxHandleCustomValues(el) {
    originalHandleCustomValues.call(this, el);
    if (!el.matches('input[type=radio]:checked, select')) {
        return;
    }
    var variantContainer = el.matches('select')
        ? el.closest('li')
        : el.closest('ul').closest('li');
    if (!variantContainer) {
        return;
    }
    var input = variantContainer.querySelector('.variant_custom_value');
    var ptavId = input && input.dataset.customProductTemplateAttributeValueId;
    if (input && !input.dataset.lxListenerAttached) {
        input.dataset.lxListenerAttached = '1';
        input.addEventListener('input', function () {
            var radio = variantContainer.querySelector(
                'input[type=radio][value="' + ptavId + '"]'
            );
            if (radio) {
                radio.setAttribute('previous_custom_value', this.value);
                radio.dispatchEvent(new Event('change', { bubbles: true }));
            }
        });
    }
}

WebsiteSale.prototype._onChangeCombination = function (ev, parent, combination) {
    originalOnChangeCombination.call(this, ev, parent, combination);
    var priceEl = parent.querySelector('.oe_price .oe_currency_value');
    if (priceEl) {
        priceEl.textContent = this._priceToStr(combination.price, combination.currency_precision || 2);
    }
};

WebsiteSale.prototype._getOptionalCombinationInfoParam = lxGetOptionalCombinationInfoParam;
WebsiteSale.prototype.handleCustomValues = lxHandleCustomValues;

VariantMixin._getOptionalCombinationInfoParam = lxGetOptionalCombinationInfoParam;
VariantMixin.handleCustomValues = lxHandleCustomValues;
