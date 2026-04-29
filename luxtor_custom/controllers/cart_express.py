# # -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

class ProductPriceController(http.Controller):

    @http.route('/lx/get_price_by_code', type='json', auth='public', website=True, csrf=False)
    def get_price_by_code(self, default_code=None, **kw):
        if not default_code:
            return {"ok": False, "error": "Missing default_code"}
        prod = request.env['product.product'].sudo().search([
            ('default_code', '=', default_code)], limit=1)
        if not prod:
            return {"ok": False, "error": f"No product found for code: {default_code}"}
        price = prod.lst_price  # Or .list_price
        return {"ok": True, "default_code": default_code, "price": price}