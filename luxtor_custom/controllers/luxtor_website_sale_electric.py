# -*- coding: utf-8 -*-
import logging
from odoo import http, _
from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale
from .install_service import (
    _reapply_free_logic as _lx_reapply_service_logic,
    _invalidate_totals as _lx_invalidate_service_totals,
)

_logger = logging.getLogger(__name__)


def _lx_sale_get_order(force_create=False):
    """V19-compatible cart order getter."""
    try:
        return request.website.sale_get_order(force_create=force_create)
    except AttributeError:
        pass
    Order = request.env['sale.order'].sudo()
    order_id = request.session.get('sale_order_id')
    if order_id:
        order = Order.browse(int(order_id)).exists()
        if order:
            return order
    return Order.browse()


class WebsiteSaleElectric(WebsiteSale):
    """
    Extend website_sale cart routes to auto-sync LuxTor electric accessories
    after each cart change.

    Supports keeping accessory lines at qty=0 by context:
        lx_keep_zero_accessories=True
    """

    def _cart_update(self, product_id=None, add_qty=0, set_qty=0, **kw):
        res = super()._cart_update(product_id=product_id, add_qty=add_qty, set_qty=set_qty, **kw)
        self._lx_sync_post_cart_effects_safe(keep_zero=True)
        return res

    @http.route(['/shop/cart/update_json'], type='json', auth='public', website=True, csrf=False)
    def cart_update_json(self, product_id, line_id=None, add_qty=None, set_qty=None, display=True, **kw):
        res = super().cart_update_json(
            product_id, line_id=line_id, add_qty=add_qty, set_qty=set_qty, display=display, **kw
        )

        self._lx_sync_post_cart_effects_safe(keep_zero=True)

        # Prevent "Missing Record sale.order.line(X)" on frontend:
        # if the returned line_id got deleted by our sync, clear it.
        try:
            lid = res.get("line_id")
            if lid and not request.env["sale.order.line"].sudo().browse(lid).exists():
                res["line_id"] = False
        except Exception:
            _logger.exception("LuxTor: failed to sanitize cart_update_json response")

        order = _lx_sale_get_order(force_create=False)
        if order:
            order = order.sudo()
            res.update({
                "amount_total": order.amount_total,
                "amount_delivery": order.amount_delivery,
                "amount_untaxed": order.amount_untaxed,
                "amount_tax": order.amount_tax,
            })

        return res

    def _cart_update_all(self, product_ids, quantities, **kw):
        res = super()._cart_update_all(product_ids, quantities, **kw)
        self._lx_sync_post_cart_effects_safe(keep_zero=True)
        return res

    def _lx_sync_post_cart_effects_safe(self, keep_zero=False):
        self._lx_sync_accessories_safe(keep_zero=keep_zero)
        self._lx_sync_services_safe()

    def _lx_sync_accessories_safe(self, keep_zero=False):
        order = _lx_sale_get_order(force_create=False)
        if not order:
            return

        # Fast skip: if no electric blind lines, do nothing
        try:
            has_electric = any(
                (l.product_id and not l.display_type and l.product_id.lx_is_electric_variant())
                for l in order.order_line
            )
            if not has_electric:
                return
        except Exception:
            _logger.exception("LuxTor: failed pre-check for electric accessories sync")
            return

        ctx = dict(request.env.context or {})
        if keep_zero:
            ctx["lx_keep_zero_accessories"] = True

        try:
            with request.env.cr.savepoint():
                order.with_context(ctx)._lx_sync_electric_accessories()
        except Exception as e:
            _logger.exception("LuxTor: electric accessories sync failed on website cart: %s", e)

    def _lx_sync_services_safe(self):
        order = _lx_sale_get_order(force_create=False)
        if not order:
            return

        try:
            with request.env.cr.savepoint():
                order = order.sudo()
                _lx_reapply_service_logic(order)
                _lx_invalidate_service_totals(order)
        except Exception as e:
            _logger.exception("LuxTor: service line sync failed on website cart: %s", e)
            
# import logging
# from odoo import http, _
# from odoo.http import request
# from odoo.addons.website_sale.controllers.main import WebsiteSale

# _logger = logging.getLogger(__name__)


# class WebsiteSaleElectric(WebsiteSale):
#     """
#     Extend website_sale cart routes to auto-sync LuxTor electric accessories
#     (motor / remote / charger) after each cart change.

#     This version also supports "keep zero accessories" to display lines with qty=0
#     (e.g., to show 'not required') by calling the sync with context:
#         lx_keep_zero_accessories=True
#     """

#     # -- core cart entry points ------------------------------------------------
#     def _cart_update(self, product_id=None, add_qty=0, set_qty=0, **kw):
#         res = super()._cart_update(product_id=product_id, add_qty=add_qty, set_qty=set_qty, **kw)
#         self._lx_sync_accessories_safe(keep_zero=True)
#         return res

#     @http.route(['/shop/cart/update_json'], type='json', auth='public', website=True, csrf=False)
#     def cart_update_json(self, product_id, line_id=None, add_qty=None, set_qty=None, display=True, **kw):
#         res = super().cart_update_json(
#             product_id, line_id=line_id, add_qty=add_qty, set_qty=set_qty, display=display, **kw
#         )
#         self._lx_sync_accessories_safe(keep_zero=True)
#         return res

#     def _cart_update_all(self, product_ids, quantities, **kw):
#         res = super()._cart_update_all(product_ids, quantities, **kw)
#         self._lx_sync_accessories_safe(keep_zero=True)
#         return res

#     # -- optional: when optional products are added/removed via modal ----------
#     # @http.route(['/shop/cart/update_option'], type='http', auth='public', website=True, csrf=False)
#     # def cart_update_option(self, **kw):
#     #     res = super().cart_update_option(**kw)
#     #     self._lx_sync_accessories_safe(keep_zero=True)
#     #     return res

#     # -- helper ----------------------------------------------------------------
#     def _lx_sync_accessories_safe(self, keep_zero=False):
#         """
#         Safe accessory synchronization:
#         - Never breaks cart UX (savepoint + swallow exceptions)
#         - Skips fast if no electric blinds are present
#         - Optionally keeps accessory lines with qty=0 (to show "not required")
#         """
#         order = _lx_sale_get_order(force_create=False)
#         if not order:
#             return

#         # Fast skip: if no electric blind lines, do nothing
#         try:
#             has_electric = any(
#                 (l.product_id and not l.display_type and l.product_id.lx_is_electric_variant())
#                 for l in order.order_line
#             )
#             if not has_electric:
#                 return
#         except Exception:
#             _logger.exception("LuxTor: failed pre-check for electric accessories sync")
#             return

#         ctx = dict(request.env.context or {})
#         if keep_zero:
#             ctx["lx_keep_zero_accessories"] = True

#         # Do the sync inside a DB savepoint; never explode the cart UX
#         try:
#             with request.env.cr.savepoint():
#                 order.with_context(ctx)._lx_sync_electric_accessories()
#         except Exception as e:
#             _logger.exception("LuxTor: electric accessories sync failed on website cart: %s", e)
#             # Optional soft warning:
#             # request.session['website_sale_cart_warning'] = _("An accessory could not be updated automatically.")


