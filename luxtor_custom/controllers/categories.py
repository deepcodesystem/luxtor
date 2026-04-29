# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale


class WebsiteSaleLx(WebsiteSale):
    """
    Extends the shop search domain with custom Luxtor filters.

    Expected query params:
      - lx_interest: new_in | weekly_deal | bestseller | trending
      - lx_location: id of luxtor.installation.space
      - lx_color:    id of lx.product.color
    """

    def _lx_safe_int(self, val):
        try:
            return int(val)
        except Exception:
            return 0

    def _lx_filters_domain(self):
        p = request.params
        domain = []

        # --- Interest toggles (on product.template) ---
        interest = (p.get("lx_interest") or "").strip()
        interest_map = {
            "new_in": "lx_is_new_in",
            "weekly_deal": "lx_is_weekly_deal",
            "bestseller": "lx_is_bestseller",
            "trending": "lx_is_trending",
        }
        field_name = interest_map.get(interest)
        if field_name:
            domain.append((field_name, "=", True))

        # --- Location (luxtor.installation.space) ---
        loc_id = self._lx_safe_int(p.get("lx_location"))
        if loc_id > 0:
            # field is Many2one on template
            domain.append(("lx_installation_space_id", "=", loc_id))

        # --- Color (lx.product.color) ---
        col_id = self._lx_safe_int(p.get("lx_color"))
        if col_id > 0:
            # field is Many2many on template
            domain.append(("lx_color_ids", "in", [col_id]))

        return domain

    def _get_search_domain(self, search, category, attrib_values, search_in_description=True):
        # Keep Odoo's default domain then extend it
        domain = super()._get_search_domain(
            search, category, attrib_values, search_in_description=search_in_description
        )

        lx_domain = self._lx_filters_domain()
        if lx_domain:
            # AND it with existing domain
            domain += lx_domain

        return domain



# class WebsiteSaleLx(WebsiteSale):

#     def _lx_filters_domain(self):
#         p = http.request.params
#         domain = []

#         interest = (p.get("lx_interest") or "").strip()
#         if interest == "new_in":
#             domain.append(("lx_is_new_in", "=", True))
#         elif interest == "weekly_deal":
#             domain.append(("lx_is_weekly_deal", "=", True))
#         elif interest == "bestseller":
#             domain.append(("lx_is_bestseller", "=", True))
#         elif interest == "trending":
#             domain.append(("lx_is_trending", "=", True))

#         # LOCATION (luxtor.installation.space)
#         loc = p.get("lx_location")
#         if loc and str(loc).isdigit():
#             domain.append(("lx_installation_space_id", "=", int(loc)))

#         # COLOR
#         col = p.get("lx_color")
#         if col and str(col).isdigit():
#             domain.append(("lx_color_ids", "in", int(col)))

#         return domain

#     def _get_search_domain(self, search, category, attrib_values, search_in_description=True):
#         domain = super()._get_search_domain(search, category, attrib_values, search_in_description=search_in_description)
#         domain += self._lx_filters_domain()
#         return domain
