# -*- coding: utf-8 -*-
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class LxConfiguratorInfo(http.Controller):

    def _lx_max_height_for_width(self, tmpl, width_m):
        try:
            width_cm = float(width_m or 0.0) * 100.0
            if width_cm <= 0:
                return float(tmpl.max_height or 0.0)
            fabric = tmpl.lx_fabric_ref_id
            weight = float(
                getattr(fabric, 'lx_weight', 0.0) or tmpl.lx_weight or 0.0
            )
            mech = request.env['product.template'].sudo().search(
                [('lx_is_roller_mechanism', '=', True)], limit=1
            )
            load = float(getattr(mech, 'maximum_load', 0.0) or 0.0)
            if not (load and weight):
                return float(tmpl.max_height or 0.0)
            h = (load / (width_cm * weight)) * 100_000.0
            if tmpl.lx_is_day_night:
                h /= 2.0
            return round(max(0.0, h), 2)
        except Exception:
            return float(tmpl.max_height or 0.0)

    def _lx_price_for_variant(self, tmpl, product, width_m, partner, motor_variant_id=None):
        """Virtual unit price for a variant. Returns amount * partner_factor."""
        env = request.env
        Mrp = env['mrp.production'].sudo()
        Bom = env['mrp.bom'].sudo()

        variant = product or tmpl.product_variant_id
        if not variant or not variant.exists():
            return 0.0

        bom = Bom.search([('product_id', '=', variant.id)], order='sequence', limit=1)
        if not bom:
            bom = Bom.search([
                ('product_tmpl_id', '=', tmpl.id),
                ('product_id', '=', False),
            ], order='sequence', limit=1)
        if not bom:
            return 0.0

        idler_variant_id = None
        skip_tubular_motor = False
        if motor_variant_id:
            try:
                motor_var = env['product.product'].sudo().browse(int(motor_variant_id))
                if motor_var.exists() and motor_var.lx_idler_variant_id:
                    idler_variant_id = motor_var.lx_idler_variant_id.id
                    skip_tubular_motor = True
            except Exception:
                pass

        try:
            mo = Mrp.new({
                'company_id': env.company.id,
                'product_id': variant.id,
                'bom_id': bom.id,
                'lx_width_m': float(width_m or 1.0),
            })
            calc = getattr(mo, '_lx_virtual_calculate', None)
            if not calc:
                return 0.0
            _cost, amount = calc(
                width_m=float(width_m or 1.0),
                idler_variant_id=idler_variant_id,
                skip_tubular_motor=skip_tubular_motor,
            )
        except Exception:
            return 0.0

        factor = 1.0
        if partner and hasattr(partner, 'lx_account_type_id') and partner.lx_account_type_id:
            try:
                factor = float(partner.lx_account_type_id.rank or 100.0) / 100.0
            except Exception:
                factor = 1.0

        return amount * factor

    def _lx_sale_dialog_unit_price(self, order, tmpl, product, motor_variant_id=None):
        env = request.env
        variant = product or tmpl.product_variant_id
        if not order or not variant or not variant.exists():
            return 0.0
        line = env["sale.order.line"].with_context(
            lx_syncing_accessories=True,
            lx_skip_dimension_reprice=True,
        ).new({
            "order_id": order.id,
            "product_id": variant.id,
            "product_uom_qty": 1.0,
            "lx_width_m": 1.0,
            "lx_height_m": 1.0,
        })
        if motor_variant_id:
            try:
                motor_var = env["product.product"].sudo().browse(int(motor_variant_id))
                if motor_var.exists():
                    line.lx_motor_only_variant_id = motor_var
            except Exception:
                pass
        try:
            if (
                hasattr(variant, "lx_is_motor_only_variant")
                and variant.lx_is_motor_only_variant()
                and line.lx_motor_only_variant_id
            ):
                price = float(line._lx_compute_motor_only_price() or 0.0)
            else:
                price = float(line._lx_compute_price_unit_like_wizard() or 0.0)
                if price > 0.0:
                    line.price_unit = price
                    if hasattr(line, '_lx_apply_vendor_markdown'):
                        line._lx_apply_vendor_markdown()
                    price = float(line.price_unit or 0.0)
            return round(price, 2) if price > 0.0 else 0.0
        except Exception:
            _logger.exception(
                "[LX-PC] sale dialog unit price failed | order=%s product=%s",
                order.id, variant.id,
            )
            return 0.0

    @http.route('/lx/configurator/info', type='json', auth='user')
    def lx_configurator_info(self, product_tmpl_id, width, product_id=None,
                             motor_variant_id=None, order_id=None):
        try:
            tmpl_id = int(product_tmpl_id or 0)
            pid = int(product_id or 0)
            oid = int(order_id or 0)
        except (TypeError, ValueError):
            return {"ok": False, "error": "bad_id"}

        if not tmpl_id:
            return {"ok": False, "error": "missing_tmpl_id"}

        env = request.env
        tmpl = env['product.template'].sudo().browse(tmpl_id)
        if not tmpl.exists():
            return {"ok": False, "error": "not_found"}

        product = None
        if pid:
            p = env['product.product'].sudo().browse(pid)
            if p.exists() and p.product_tmpl_id.id == tmpl_id:
                product = p

        # Auto-select first tubular motor for Motor Only without explicit selection
        if not motor_variant_id and product:
            for ptav in product.product_template_attribute_value_ids:
                if (ptav.attribute_id.name or "").strip() == "Control Type":
                    if (ptav.product_attribute_value_id.name or "").strip() == "Motor Only":
                        motor_tmpl = env['product.template'].sudo().search(
                            [('lx_is_tubular_motor', '=', True)], limit=1
                        )
                        if motor_tmpl and motor_tmpl.product_variant_ids:
                            motor_variant_id = motor_tmpl.product_variant_ids[0].id
                    break

        order = env["sale.order"].sudo().browse(oid).exists() if oid else env["sale.order"]
        partner = order.partner_id if order else request.env.user.partner_id
        width_m = float(width or 1.0)

        raw_max = 0.0
        fabric = tmpl.lx_fabric_ref_id
        if fabric and fabric.roller_width_ids:
            vals = [t.value_cm for t in fabric.roller_width_ids if t.value_cm]
            if vals:
                raw_max = max(vals) / 100.0
        max_width = round(raw_max - 0.03, 2) if raw_max > 0 else 0.0
        max_height = self._lx_max_height_for_width(tmpl, width_m)

        try:
            if order:
                price = self._lx_sale_dialog_unit_price(
                    order, tmpl, product or tmpl.product_variant_id,
                    motor_variant_id=motor_variant_id,
                )
            else:
                price = self._lx_price_for_variant(
                    tmpl, product, width_m, partner,
                    motor_variant_id=motor_variant_id,
                )
        except Exception:
            price = 0.0

        is_dim = bool(
            getattr(tmpl, 'lx_fabric_ref_id', False)
            or getattr(tmpl, 'is_dimension_product', False)
        )

        return {
            "ok": True,
            "is_dimension_product": is_dim,
            "width_min": 0.60,
            "width_max": max_width,
            "height_min": 0.90,
            "height_max": round(max_height, 2),
            "price": price,
        }

