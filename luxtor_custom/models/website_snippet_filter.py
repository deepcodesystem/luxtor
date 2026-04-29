# -*- coding: utf-8 -*-
from odoo import models
from odoo.osv import expression

class WebsiteSnippetFilter(models.Model):
    _inherit = 'website.snippet.filter'

    def _get_products_lx_weekly_deal(self, website, limit, domain, **kwargs):
        domain = expression.AND([domain, [('lx_is_weekly_deal', '=', True)]])
        return self.env['product.product'].with_context(display_default_code=False).search(domain, limit=limit)

    def _get_products_lx_new_in(self, website, limit, domain, **kwargs):
        domain = expression.AND([domain, [('lx_is_new_in', '=', True)]])
        return self.env['product.product'].with_context(display_default_code=False).search(domain, limit=limit)
