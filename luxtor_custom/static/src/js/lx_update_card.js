/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

(function patch() {
    const WS = publicWidget.registry.WebsiteSale;
    if (!WS) return void setTimeout(patch, 0);
    if (WS.prototype._lxPriceDomPatched) return;

    const _orig = WS.prototype.addToCart;

    const parse = (s) => {
        if (s == null) return 0;
        let x = String(s).trim().replace(/\s/g, "");
        const m = x.match(/-?(?:\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,]\d+)?/);
        if (!m) return 0;
        let n = m[0];
        if (n.includes(",") && n.includes(".")) {
            const dec = n.lastIndexOf(",") > n.lastIndexOf(".") ? "," : ".";
            const thou = dec === "," ? "." : ",";
            n = n.replace(new RegExp("\\" + thou, "g"), "").replace(dec, ".");
        } else if (n.includes(",")) {
            n = n.replace(",", ".");
        }
        const f = parseFloat(n);
        return Number.isFinite(f) ? f : 0;
    };

    const readPrice = () => {
        const hid = document.querySelector("#lx_final_unit_price");
        let v = parse(hid?.value);
        if (v > 0) return v;
        const node =
            document.querySelector('.o_wsale_product_details_content_section_price .oe_currency_value') ||
            document.querySelector('.o_wsale_product_details_content_section_price .o_currency_value') ||
            document.querySelector('.o_wsale_product_price .oe_currency_value') ||
            document.querySelector('#product_details .oe_price .oe_currency_value') ||
            document.querySelector('#product_details [itemprop="price"]') ||
            document.querySelector('#product_details .o_wsale_product_price .oe_currency_value');
        if (node) {
            v = parse(node.textContent);
            if (v > 0) return v;
            v = parse(node.getAttribute?.("content"));
            if (v > 0) return v;
        }
        return 0;
    };

    const setHidden = (name, value) => {
        const form =
            document.querySelector('#product_details form[action*="/shop/cart"]') ||
            document.querySelector("form.js_add_cart_json") ||
            document.querySelector(".oe_website_sale form");
        if (!form) return;
        let el = form.querySelector(`input[name="${name}"]`);
        if (!el) {
            el = document.createElement("input");
            el.type = "hidden";
            el.name = name;
            form.appendChild(el);
        }
        el.value = value;
    };

    WS.prototype.addToCart = function (params = {}) {
        const v = readPrice();
        if (v > 0) {
            const f = v.toFixed(6);
            setHidden("lx_final_unit_price", f);
            setHidden("lx_price_override", f);
            params.lx_final_unit_price = f;
            params.lx_price_override = f;
        }
        return _orig.call(this, params);
    };

    WS.prototype._lxPriceDomPatched = true;
})();
