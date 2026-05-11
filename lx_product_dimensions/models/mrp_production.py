# -*- coding: utf-8 -*-
import math
import logging
from odoo import fields, models

_logger = logging.getLogger(__name__)

# ─── Plastic chain BOM codes ──────────────────────────────────────────────────
PLASTIC_CHAIN_150_CODE = "BFPC-150"
PLASTIC_CHAIN_200_CODE = "BFPC-200"


def lx_truncate_2(value):
    """Truncate to 2 decimal places (floor, not round)."""
    return math.floor((value or 0.0) * 100.0) / 100.0


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    lx_width_m = fields.Float(string="Width (m)", digits=(16, 4))
    lx_height_m = fields.Float(string="Height (m)", digits=(16, 4))

    # ── Plastic chain helpers ─────────────────────────────────────────────────

    def _lx_get_chain_code_value(self, product):
        """Return BFPC-150 / BFPC-200 from the product's 'Code' attribute, or False."""
        if not product:
            return False
        for ptav in product.product_template_attribute_value_ids:
            attr = (ptav.attribute_id.name or "").strip()
            val = (ptav.product_attribute_value_id.name or "").strip()
            if attr == "Code" and val in (PLASTIC_CHAIN_150_CODE, PLASTIC_CHAIN_200_CODE):
                return val
        return False

    def _is_plastic_chain(self, product):
        if not product:
            return False
        tmpl = product.product_tmpl_id
        if not tmpl or not getattr(tmpl, "lx_is_plastic_chain", False):
            return False
        return bool(self._lx_get_chain_code_value(product))

    def _is_chain_150(self, product):
        if not self._is_plastic_chain(product):
            return False
        return self._lx_get_chain_code_value(product) == PLASTIC_CHAIN_150_CODE

    def _is_chain_200(self, product):
        if not self._is_plastic_chain(product):
            return False
        return self._lx_get_chain_code_value(product) == PLASTIC_CHAIN_200_CODE

    def _want_chain_150(self, height_m=None):
        """height <= 2.70 m → chain 150, else chain 200."""
        h = float(height_m if height_m is not None else (self.lx_height_m or 0.0))
        return h <= 2.70

    # ── Virtual cost calculator ───────────────────────────────────────────────

    def _lx_virtual_calculate(self, width_m=0.0, height_m=None,
                               idler_variant_id=None, skip_tubular_motor=False):
        """
        Simule l'explosion de la BOM pour calculer (coût, montant) à l'unité.
        Retourne (total_cost, total_amount) tronqués à 2 décimales.
        Ne crée aucun enregistrement — appeler sur un record `.new()`.
        """
        self.ensure_one()
        if not self.bom_id:
            return 0.0, 0.0

        total_cost = 0.0
        total_amount = 0.0
        Product = self.env['product.product']

        try:
            raw_vals_list = super(MrpProduction, self)._get_moves_raw_values() or []
        except Exception:
            _logger.warning('[lx_virtual_calculate] _get_moves_raw_values failed', exc_info=True)
            return 0.0, 0.0

        want_150 = self._want_chain_150(height_m if height_m is not None else self.lx_height_m)

        for vals in raw_vals_list:
            product = Product.browse(vals.get('product_id'))
            if not product:
                continue

            # Plastic chain filtering
            if self._is_chain_150(product) and not want_150:
                continue
            if self._is_chain_200(product) and want_150:
                continue

            tmpl = product.product_tmpl_id

            # Skip tubular motor (electric module context)
            if skip_tubular_motor and getattr(tmpl, 'lx_is_tubular_motor', False):
                continue

            # Idler filtering
            if getattr(tmpl, 'lx_is_idler', False):
                if not idler_variant_id or product.id != idler_variant_id:
                    if skip_tubular_motor:
                        continue

            qty = float(vals.get('product_uom_qty') or 0.0)

            # Mounting bracket: qty depends on width
            if getattr(tmpl, 'is_mounting_bracket', False):
                v_w = max(float(width_m or self.lx_width_m or 1.0), 0.0)
                try:
                    qty = max(math.floor(((v_w - 0.3) / 0.95) + 2), 0)
                except ZeroDivisionError:
                    qty = 2

            unit = float(product.standard_price or 0.0)
            cost = unit * qty
            total_cost += lx_truncate_2(cost)

            waste_pct = max(float(getattr(tmpl, 'waste_rate', 0.0) or 0.0) / 100.0, 0.0)
            extra_pct = max(float(getattr(tmpl, 'added_margin', 0.0) or 0.0) / 100.0, 0.0)
            raw_amount = cost * (1.0 + waste_pct + extra_pct)
            total_amount += lx_truncate_2(raw_amount)

        return lx_truncate_2(total_cost), lx_truncate_2(total_amount)

