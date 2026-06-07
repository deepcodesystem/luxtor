from odoo.http import request, route
from odoo.addons.website_sale.controllers.variant import WebsiteSaleVariantController


class LxWebsiteSaleVariantController(WebsiteSaleVariantController):

    @route('/website_sale/get_combination_info', type='jsonrpc', auth='public', methods=['POST'], website=True, readonly=True)
    def get_combination_info_website(self, product_template_id, product_id, combination, add_qty, uom_id=None, **kwargs):
        custom_values = kwargs.pop('custom_values', {})
        combination_info = super().get_combination_info_website(
            product_template_id, product_id, combination, add_qty, uom_id, **kwargs
        )
        if not custom_values:
            return combination_info
        product_template = request.env['product.template'].browse(int(product_template_id))
        if not product_template.is_dimension_product:
            return combination_info
        combination_ptavs = request.env['product.template.attribute.value'].browse(combination)
        height_attr = request.env.ref('lx_base.product_attribute_height_m')
        width_attr = request.env.ref('lx_base.product_attribute_width_m')
        height_ptav = combination_ptavs.filtered(lambda p: p.attribute_id == height_attr)
        width_ptav = combination_ptavs.filtered(lambda p: p.attribute_id == width_attr)
        if height_ptav and width_ptav:
            try:
                height = float(custom_values.get(str(height_ptav.id), 0))
                width = float(custom_values.get(str(width_ptav.id), 0))
                if height and width:
                    combination_info['price'] *= height * width
                    combination_info['list_price'] *= height * width
            except (ValueError, TypeError):
                pass
        return combination_info
