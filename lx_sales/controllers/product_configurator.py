# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

class LxProductConfiguratorController(http.Controller):

    @http.route('/lx/product_configurator/get_dimension_constraints',
                type='jsonrpc', auth='user')
    def get_dimension_constraints(self, product_template_id, **kwargs):
        tmpl = request.env['product.template'].browse(product_template_id)
        if not tmpl.exists() or not tmpl.is_dimension_product:
            return {}
        # lx_dims_hints sans width pour avoir les limites globales
        hints = tmpl.lx_dims_hints()
        return {
            'is_dimension_product': True,
            'min_width_m':  0.10,  # LX_MIN_WIDTH_M — adapte selon ta constante
            'min_height_m': 0.10,  # LX_MIN_HEIGHT_M
            'max_width_m':  hints.get('max_width_m', 0.0),
            'max_height_m': hints.get('max_height_m', 0.0),
        }