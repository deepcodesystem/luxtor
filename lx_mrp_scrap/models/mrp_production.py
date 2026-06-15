# -*- coding: utf-8 -*-
import logging
from odoo import fields, models

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    lx_scrap_ids = fields.One2many(
        'lx.scrap',
        'production_id',
        string="Generated Scraps",
    )

    def _get_move_raw_values(self, product, product_uom_qty, product_uom, operation_id=False, bom_line=False):
        values = super()._get_move_raw_values(
            product, product_uom_qty, product_uom,
            operation_id=operation_id, bom_line=bom_line,
        )
        if bom_line and self.lx_width_m and self.lx_height_m:
            strategy = bom_line.product_id.categ_id.removal_strategy_id
            if strategy and strategy.method == 'fabric_roll_sunscreen':
                values['product_uom_qty'] = self.lx_height_m
        return values

    def _get_scrap_dimensions(self, mo, move, lot):
        """Détermine les dimensions de la chute selon la meilleure orientation."""
        store_width = mo.lx_width_m or 0.0
        store_height = mo.lx_height_m or 0.0
        consumed_qty = move.quantity or 0.0
        margin = 0.03

        # Orientation A : largeur rouleau >= largeur store, longueur >= hauteur
        valid_a = lot.lx_width >= store_width and consumed_qty >= store_height
        scrap_area_a = (lot.lx_width - store_width) * store_height if valid_a else float('inf')

        # Orientation B : largeur rouleau >= hauteur store, longueur >= largeur
        valid_b = lot.lx_width >= store_height and consumed_qty >= store_width
        scrap_area_b = (lot.lx_width - store_height) * store_width if valid_b else float('inf')

        if not valid_a and not valid_b:
            return (0.0, 0.0)

        if scrap_area_a <= scrap_area_b:
            return (lot.lx_width + margin - store_width, store_height)
        else:
            return (lot.lx_width + margin - store_height, store_width)

    def button_mark_done(self):
        res = super().button_mark_done()
        for mo in self:
            for move in mo.move_raw_ids.filtered('lx_selected_lot_id'):
                lot = move.lx_selected_lot_id
                if lot.lx_is_scrap:
                    continue
                scrap_width, scrap_length = self._get_scrap_dimensions(mo, move, lot)
                if scrap_width <= 0.0 or scrap_length <= 0.0:
                    continue
                if self.env['lx.scrap'].search_count([
                    ('production_id', '=', mo.id),
                    ('lot_id', '=', lot.id),
                ]):
                    continue
                try:
                    self.env['lx.scrap'].create({
                        'production_id': mo.id,
                        'lot_id': lot.id,
                        'product_id': move.product_id.id,
                        'lx_scrap_width': scrap_width,
                        'lx_scrap_length': scrap_length,
                    })
                except Exception as e:
                    _logger.warning(
                        "lx_mrp_scrap: échec création chute pour OF %s: %s",
                        mo.id, e,
                    )
        return res
