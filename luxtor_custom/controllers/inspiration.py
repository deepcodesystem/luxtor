# -*- coding: utf-8 -*-
import json
from odoo import http
from odoo.http import request


class LuxtorInspirationController(http.Controller):

    # -------------------------
    # Base helpers
    # -------------------------
    def _base_domain(self):
        return [
            ("website_published", "=", True),
            ("active", "=", True),
        ]

    def _img_url(self, tmpl_id):
        return f"/web/image/product.template/{tmpl_id}/image_1024"

    def _product_payload(self, products):
        payload = []
        for p in products:
            payload.append({
                "id": p.id,
                "name": p.name or "",
                "url": p.website_url or ("/shop/product/%s" % p.id),
                "img": self._img_url(p.id),
                "categ_id": p.categ_id.id if p.categ_id else False,
                "space_id": p.lx_installation_space_id.id if p.lx_installation_space_id else False,
            })
        return payload

    def _boot_json(self, data):
        s = json.dumps(data, ensure_ascii=False)
        return s.replace("</", "<\\/")

    def _leaf_categories_from_products(self, products):
        Category = request.env["product.category"].sudo()
        categs = Category.browse(products.mapped("categ_id").ids).exists()
        categs = categs.filtered(lambda c: not c.child_id)  # leaf only
        return categs.sorted(lambda c: (c.name or ""))

    def _all_spaces(self):
        Space = request.env["luxtor.installation.space"].sudo()
        return Space.search([("active", "=", True)], order="name,id")

    # -------------------------
    # Routes
    # -------------------------
    @http.route(["/inspiration"], type="http", auth="public", website=True, sitemap=True)
    def inspiration_page(self, **kw):
        env = request.env
        ProductT = env["product.template"].sudo()

        products = ProductT.search(self._base_domain(), limit=300)

        categories = self._leaf_categories_from_products(products)
        spaces = self._all_spaces()  # IMPORTANT: all locations, not only used ones

        boot = {
            "products": self._product_payload(products),
            "categories": [
                {"id": c.id, "name": (c.complete_name or c.name).split(" / ")[-1]}
                for c in categories
            ],
            "spaces": [{"id": s.id, "name": s.name or ""} for s in spaces],
        }

        return request.render("website.inspiration", {
            "boot_json": self._boot_json(boot),
        })

    @http.route("/inspiration/filter", type="json", auth="public", website=True, csrf=False)
    def inspiration_filter(self, filter_type="all", filter_id=None, **kw):
        ProductT = request.env["product.template"].sudo()
        domain = self._base_domain()

        try:
            fid = int(filter_id or 0)
        except Exception:
            fid = 0

        if filter_type == "category" and fid:
            domain.append(("categ_id", "=", fid))
        elif filter_type == "product" and fid:
            domain.append(("id", "=", fid))
        elif filter_type == "space" and fid:
            domain.append(("lx_installation_space_id", "=", fid))

        products = ProductT.search(domain, limit=300)
        return {"products": self._product_payload(products), "count": len(products)}




# class LuxtorInspirationController(http.Controller):

#     def _base_domain(self):
#         return [
#             ("website_published", "=", True),
#             ("active", "=", True),
#         ]

#     def _img_url(self, tmpl_id):
#         return f"/web/image/product.template/{tmpl_id}/image_1024"

#     def _product_payload(self, products):
#         payload = []
#         for p in products:
#             payload.append({
#                 "id": p.id,
#                 "name": p.name or "",
#                 "url": p.website_url or ("/shop/product/%s" % p.id),
#                 "img": self._img_url(p.id),
#                 "categ_id": p.categ_id.id if p.categ_id else False,
#                 "space_id": p.lx_installation_space_id.id if p.lx_installation_space_id else False,
#             })
#         return payload

#     def _boot_json(self, data):
#         s = json.dumps(data, ensure_ascii=False)
#         return s.replace("</", "<\\/")

#     @http.route(["/inspiration"], type="http", auth="public", website=True, sitemap=True)
#     def inspiration_page(self, **kw):
#         env = request.env
#         ProductT = env["product.template"].sudo()
#         Space = env["luxtor.installation.space"].sudo()

#         products = ProductT.search(self._base_domain(), limit=300)

#         # Categories: only leaf categories used by displayed products
#         categ_ids = list(set(products.mapped("categ_id").ids))
#         categories = env["product.category"].sudo().browse(categ_ids).exists()

#         # keep only leaf (latest child)
#         categories = categories.filtered(lambda c: not c.child_id)

#         # sort by label
#         categories = categories.sorted(lambda c: c.name or "")

#         boot = {
#             "products": self._product_payload(products),
#             "categories": [{"id": c.id, "name": (c.complete_name or c.name).split(" / ")[-1]} for c in categories],
#             "spaces": [{"id": s.id, "name": s.name} for s in Space],
#         }

#         return request.render("website.inspiration", {
#             "boot_json": self._boot_json(boot),
#         })

#     @http.route("/inspiration/filter", type="json", auth="public", website=True, csrf=False)
#     def inspiration_filter(self, filter_type="all", filter_id=None, **kw):
#         env = request.env
#         ProductT = env["product.template"].sudo()
#         domain = self._base_domain()

#         fid = int(filter_id) if filter_id else 0

#         if filter_type == "category" and fid:
#             domain.append(("categ_id", "=", fid))

#         elif filter_type == "product" and fid:
#             domain.append(("id", "=", fid))

#         elif filter_type == "space" and fid:
#             domain.append(("lx_installation_space_id", "=", fid))

#         products = ProductT.search(domain, limit=300)
#         return {"products": self._product_payload(products), "count": len(products)}
