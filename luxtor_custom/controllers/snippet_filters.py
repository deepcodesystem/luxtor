# -*- coding: utf-8 -*-
import logging

from odoo import http
from odoo.http import request
from odoo.osv import expression
from odoo.addons.website_sale.controllers.main import WebsiteSale
from odoo.addons.website.controllers.main import QueryURL
from odoo.tools import lazy

_logger = logging.getLogger(__name__)


def _slides(recordset, size=4):
    """Split a recordset into a list of slices for carousel slides."""
    n = len(recordset)
    return [recordset[i:i + size] for i in range(0, n, size)] if n else []


def _product_grid_slides(recordset, size=4):
    """Build homepage slides with the same product cell shape as the shop grid."""
    slides = []
    for products in _slides(recordset, size=size):
        slides.append([
            {
                "product": product,
                "x": 1,
                "y": 1,
                "ribbon": product.sudo().website_ribbon_id,
            }
            for product in products
        ])
    return slides


class LuxtorHome(WebsiteSale):

    @http.route(["/", "/accueil"], type="http", auth="public", website=True, sitemap=True)
    def luxtor_home(self, **kw):
        website = request.website

        PT = request.env["product.template"].sudo().with_context(
            display_default_code=False,
            website_id=website.id,
        )

        base_domain = expression.AND([
            website.website_domain(),
            [("is_published", "=", True)],
            [("company_id", "in", [False, website.company_id.id])],
        ])

        new_in = PT.search(
            expression.AND([base_domain, [("lx_is_new_in", "=", True)]]),
            limit=16,
            order="website_sequence asc, id desc",
        )
        weekly = PT.search(
            expression.AND([base_domain, [("lx_is_weekly_deal", "=", True)]]),
            limit=16,
            order="website_sequence asc, id desc",
        )
        ppg = 4
        ppr = 4
        gap = website.shop_gap or "16px"
        homepage_products = new_in | weekly
        homepage_prices = homepage_products._get_sales_prices(website) if homepage_products else {}
        product_query_params = self._get_product_query_params(**kw)
        grouped_attributes_values = {}
        variants = request.env["product.product"].sudo().browse(
            product._get_first_possible_variant_id() for product in homepage_products
        ) if homepage_products else request.env["product.product"]
        variants.fetch()
        product_variants = dict(zip(homepage_products, variants))
        installed_modules = set(
            request.env["ir.module.module"].sudo().search([
                ("name", "in", ["website_sale_wishlist", "website_sale_comparison"]),
                ("state", "=", "installed"),
            ]).mapped("name")
        )
        wishlist_enabled = "website_sale_wishlist" in installed_modules
        compare_enabled = "website_sale_comparison" in installed_modules
        products_in_wishlist = PT.browse()
        if wishlist_enabled:
            products_in_wishlist = request.env["product.wishlist"].current().mapped("product_id.product_tmpl_id")

        _logger.info(
            "LX HOME: new_in=%s weekly=%s (website=%s)",
            len(new_in), len(weekly), website.id,
        )

        return request.render("luxtor_custom.lx_homepage", {
            "new_in_products": new_in,
            "weekly_products": weekly,
            "new_in_slides": _product_grid_slides(new_in, size=ppg),
            "weekly_slides": _product_grid_slides(weekly, size=ppg),
            "get_product_prices": lambda product: homepage_prices.get(product.id, {}),
            "products_in_wishlist": products_in_wishlist,
            "keep": QueryURL(""),
            "pager": {"page": {"num": 1}},
            "selected_attributes_hash": "",
            "ppg": ppg,
            "ppr": ppr,
            "gap": gap,
            "layout_mode": "grid",
            "shop_path": "/shop",
            "product_query_params": product_query_params,
            "grouped_attributes_values": grouped_attributes_values,
            "auto_assign_ribbons": request.env["product.ribbon"].sudo().search([("assign", "!=", "manual")]),
            "product_variants": product_variants,
            "previewed_attribute_values": lazy(
                lambda: homepage_products._get_previewed_attribute_values(False, product_query_params)
            ) if homepage_products else {},
            "lx_wishlist_enabled": wishlist_enabled,
            "lx_compare_enabled": compare_enabled,
        })
