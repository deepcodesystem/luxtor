# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = 'stock.move'

    lx_selected_lot_id = fields.Many2one(
        'stock.lot',
        string="Rouleau sélectionné",
        domain="[('lx_width', '>', 0)]",
    )

    def _lx_find_best_fabric_lot(self):
        """Sélectionne le meilleur lot tissu selon l'ordre de priorité :
           1. Chutes réutilisables (lx_is_scrap) avec largeur suffisante
           2. Rouleaux standards avec largeur suffisante
           Dans les deux cas, on prend le lot dont lx_width est le plus proche
           de la largeur nécessaire (lx_width_m de l'OF).
        """
        self.ensure_one()
        production = self.raw_material_production_id
        if not production or not production.lx_width_m:
            return False
        needed_width = production.lx_width_m

        quants = self.env['stock.quant'].search([
            ('product_id', '=', self.product_id.id),
            ('location_id', 'child_of', self.location_id.id),
            ('quantity', '>', 0),
        ])
        if not quants:
            return False

        avail_by_lot = {}
        for q in quants:
            if not q.lot_id:
                continue
            available = q.quantity - q.reserved_quantity
            if available <= 0:
                continue
            avail_by_lot[q.lot_id] = avail_by_lot.get(q.lot_id, 0) + available

        candidates = self.env['stock.lot'].concat(*[
            lot for lot in avail_by_lot
            if lot.lx_width and lot.lx_width >= needed_width
        ])
        if not candidates:
            return False

        scrap = candidates.filtered('lx_is_scrap').sorted(key=lambda l: l.lx_width)
        if scrap:
            return scrap[0]
        regular = candidates.filtered(lambda l: not l.lx_is_scrap).sorted(key=lambda l: l.lx_width)
        if regular:
            return regular[0]
        return False

    def _update_reserved_quantity(self, need, location_id, lot_id=None, package_id=None, owner_id=None, strict=True):
        if not self.lx_selected_lot_id and not lot_id:
            strategy = self.product_id.categ_id.removal_strategy_id
            if strategy and strategy.method == 'fabric_roll':
                best = self._lx_find_best_fabric_lot()
                if best:
                    self.lx_selected_lot_id = best.id
        if self.lx_selected_lot_id and not lot_id:
            lot_id = self.lx_selected_lot_id
        return super()._update_reserved_quantity(
            need, location_id, lot_id=lot_id,
            package_id=package_id, owner_id=owner_id, strict=strict,
        )
