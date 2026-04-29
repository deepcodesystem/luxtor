# -*- coding: utf-8 -*-
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class LxConfigurator(http.Controller):

    # ── helpers ───────────────────────────────────────────────────────────────

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

    def _lx_price_for_variant(self, tmpl, product, width_m, partner,
                              motor_variant_id=None):
        """
        Compute virtual unit price for a specific variant.
        Returns raw amount * partner_factor — NO rounding applied.

        When motor_variant_id is given the BOM is exploded with only the
        matching idler (skip_tubular_motor=True), giving the correct Motor
        Only price instead of the price that includes both idler variants.
        """
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

        # Resolve idler for the selected motor variant (Motor Only products)
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
                'company_id': env.company.id,  # required for BOM explosion
                'product_id': variant.id,
                'bom_id':     bom.id,
                'lx_width_m': float(width_m or 1.0),
            })
            _cost, amount = mo._lx_virtual_calculate(
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
        """Match the backend configurator unit price to the real sale order line."""
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
                    line._lx_apply_vendor_markdown()
                    price = float(line.price_unit or 0.0)
            return round(price, 2) if price > 0.0 else 0.0
        except Exception:
            _logger.exception(
                "[LX-PC] failed to compute sale dialog unit price | order_id=%s product_id=%s motor_variant_id=%s",
                order.id,
                variant.id,
                motor_variant_id or False,
            )
            return 0.0

    # ── /lx/configurator/info ─────────────────────────────────────────────────

    @http.route('/lx/configurator/info', type='json', auth='user')
    def lx_configurator_info(self, product_tmpl_id, width, product_id=None,
                             motor_variant_id=None, order_id=None):
        try:
            tmpl_id = int(product_tmpl_id or 0)
            pid     = int(product_id or 0)
            oid     = int(order_id or 0)
        except (TypeError, ValueError):
            return {"ok": False, "error": "bad_id"}

        if not tmpl_id:
            return {"ok": False, "error": "missing_tmpl_id"}

        env  = request.env
        tmpl = env['product.template'].sudo().browse(tmpl_id)
        if not tmpl.exists():
            return {"ok": False, "error": "not_found"}

        product = None
        if pid:
            p = env['product.product'].sudo().browse(pid)
            if p.exists() and p.product_tmpl_id.id == tmpl_id:
                product = p

        # Auto-select first tubular motor when the product is a Motor Only
        # variant and no motor_variant_id was specified by the caller.
        # This ensures the initial price fetch (before any JS interaction)
        # already returns the correct single-idler price.
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
        fabric  = tmpl.lx_fabric_ref_id
        if fabric and fabric.roller_width_ids:
            vals = [t.value_cm for t in fabric.roller_width_ids if t.value_cm]
            if vals:
                raw_max = max(vals) / 100.0
        max_width = round(raw_max - 0.03, 2) if raw_max > 0 else 0.0

        max_height = self._lx_max_height_for_width(tmpl, width_m)

        try:
            if order:
                price = self._lx_sale_dialog_unit_price(
                    order,
                    tmpl,
                    product or tmpl.product_variant_id,
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
            "ok":                   True,
            "is_dimension_product": is_dim,
            "width_min":            0.60,
            "width_max":            max_width,
            "height_min":           0.90,
            "height_max":           round(max_height, 2),
            "price":                price,
        }

    # ── /lx/configurator/locations ────────────────────────────────────────────

    @http.route('/lx/configurator/locations', type='json', auth='public', website=True)
    def lx_configurator_locations(self):
        Space = request.env['luxtor.installation.space'].sudo()
        # Ensure 'Other' always exists so the JS auto-select works on first use
        if not Space.search([('name', '=', 'Other')], limit=1):
            Space.create({'name': 'Other'})
        spaces = Space.search([], order='name asc')
        return [{'id': s.id, 'name': s.name} for s in spaces]

    # ── /lx/configurator/is_motor_only ───────────────────────────────────────
    # NEW: returns {"is_motor_only": bool} for a given product.product id.
    # Called by the configurator JS on every variant change to show/hide
    # the motor radio buttons.

    @http.route('/lx/configurator/is_motor_only', type='json', auth='user')
    def lx_configurator_is_motor_only(self, product_id):
        try:
            pid = int(product_id or 0)
        except (TypeError, ValueError):
            return {"is_motor_only": False}

        if not pid:
            return {"is_motor_only": False}

        product = request.env['product.product'].sudo().browse(pid)
        if not product.exists():
            return {"is_motor_only": False}

        is_motor_only = False
        for ptav in product.product_template_attribute_value_ids:
            if (ptav.attribute_id.name or "").strip() == "Control Type":
                if (ptav.product_attribute_value_id.name or "").strip() == "Motor Only":
                    is_motor_only = True
                    break

        return {"is_motor_only": is_motor_only}

    # ── /lx/configurator/motor_variants ──────────────────────────────────────
    # NEW: returns [{id, name, code}] for all tubular motor variants.
    # Called once on mount to populate the radio buttons.

    @http.route('/lx/configurator/motor_variants', type='json', auth='user')
    def lx_configurator_motor_variants(self):
        PT = request.env['product.template'].sudo()
        motor_tmpl = PT.search([('lx_is_tubular_motor', '=', True)], limit=1)
        if not motor_tmpl:
            return []

        result = []
        for variant in motor_tmpl.product_variant_ids:
            code  = ""
            label = ""
            # Single pass: extract code and friendly label from the "Code" PTAV
            for ptav in variant.product_template_attribute_value_ids:
                if (ptav.attribute_id.name or "").strip() == "Code":
                    code  = (ptav.product_attribute_value_id.name or "").strip()
                    label = getattr(ptav, 'lx_motor_label', False) or code
                    break

            result.append({
                "id":    variant.id,
                "name":  variant.display_name,
                "code":  code,
                "label": label or code,   # friendly label for the configurator dialog
            })

        result.sort(key=lambda x: x["code"])
        return result

    @http.route('/lx/configurator/pending', type='json', auth='user')
    def lx_configurator_pending(self, order_id, product_tmpl_id,
                                lx_location_id=None, lx_motor_only_variant_id=None,
                                lx_width_m=None, lx_height_m=None, price_unit=None):
        try:
            order_id = int(order_id or 0)
            product_tmpl_id = int(product_tmpl_id or 0)
            location_id = int(lx_location_id or 0)
            motor_id = int(lx_motor_only_variant_id or 0)
            width = float(lx_width_m or 0.0)
            height = float(lx_height_m or 0.0)
            unit_price = float(price_unit or 0.0)
        except (TypeError, ValueError):
            return {"ok": False, "error": "bad_payload"}

        if not order_id or not product_tmpl_id:
            return {"ok": False, "error": "missing_ids"}

        Pending = request.env["lx.configurator.pending"].sudo()
        stale = Pending.search([
            ("order_id", "=", order_id),
            ("user_id", "=", request.env.user.id),
            ("product_tmpl_id", "=", product_tmpl_id),
        ])
        if stale:
            stale.unlink()

        rec = Pending.create({
            "order_id": order_id,
            "user_id": request.env.user.id,
            "product_tmpl_id": product_tmpl_id,
            "lx_location_id": location_id or False,
            "lx_motor_only_variant_id": motor_id or False,
            "lx_width_m": width,
            "lx_height_m": height,
            "price_unit": unit_price,
        })
        _logger.warning(
            "[LX-PC] pending stored | pending_id=%s order_id=%s tmpl_id=%s location_id=%s "
            "motor_id=%s width=%s height=%s price_unit=%s",
            rec.id, order_id, product_tmpl_id, location_id or False,
            motor_id or False, width, height, unit_price,
        )
        return {"ok": True, "pending_id": rec.id}
