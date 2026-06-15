# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = 'stock.move'

    lx_selected_lot_id = fields.Many2one(
        'stock.lot',
        string="Selected roll",
        domain="[('lx_width', '>', 0)]",
    )
    def _prepare_move_line_vals(self, quantity=None, reserved_quant=None):
        vals = super()._prepare_move_line_vals(quantity=quantity, reserved_quant=reserved_quant)
        lot = reserved_quant and reserved_quant.lot_id or self.lx_selected_lot_id
        if lot and lot.lx_width:
            vals['lx_lot_width'] = lot.lx_width
        return vals

    lx_orientation = fields.Selection([
        ('widthwise', 'By width'),
        ('heightwise', 'By Height'),
    ], string="Cutting direction")

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

    def _lx_find_best_fabric_lot_sunscreen(self):
        """Sélectionne le meilleur lot pour store screen (coupe libre).
        Teste les deux orientations et minimise la surface de chute.
        Retourne le dict du meilleur candidat ou False.
        """
        candidates = self._lx_get_sunscreen_candidates()
        if not candidates:
            return False
        best = candidates[0]
        self.write({'lx_orientation': 'heightwise' if best['orientation'] == 'A' else 'widthwise'})
        return best['lot']

    def _lx_get_sunscreen_candidates(self):
        """Retourne la liste triée des candidats pour la stratégie fabric_roll_sunscreen.
        Chaque élément est un dict :
          lot, lot_id, lot_name, orientation, scrap_width,
          scrap_length, scrap_area, is_scrap, available_qty
        """
        self.ensure_one()
        production = self.raw_material_production_id
        if not production or not production.lx_width_m or not production.lx_height_m:
            return []

        quants = self.env['stock.quant'].search([
            ('product_id', '=', self.product_id.id),
            ('location_id', 'child_of', self.location_id.id),
            ('quantity', '>', 0),
        ])
        if not quants:
            return []

        avail_by_lot = {}
        for q in quants:
            if not q.lot_id:
                continue
            available = q.quantity - q.reserved_quantity
            if available <= 0:
                continue
            avail_by_lot[q.lot_id] = avail_by_lot.get(q.lot_id, 0) + available

        store_width = production.lx_width_m
        store_height = production.lx_height_m
        candidates = []

        for lot, available_qty in avail_by_lot.items():
            if not lot.lx_width or lot.lx_width <= 0:
                continue
            if available_qty <= 0:
                continue

            best = {}

            # Orientation A (sens normal) : largeur rouleau >= largeur store, longueur >= hauteur
            if lot.lx_width >= store_width and available_qty >= store_height:
                sw = lot.lx_width - store_width
                sl = store_height
                sa = sw * sl
                if not best or sa < best['scrap_area']:
                    best.update(orientation='A', scrap_width=sw, scrap_length=sl, scrap_area=sa)

            # Orientation B (pivoté 90°) : largeur rouleau >= hauteur store, longueur >= largeur
            if lot.lx_width >= store_height and available_qty >= store_width:
                sw = lot.lx_width - store_height
                sl = store_width
                sa = sw * sl
                if not best or sa < best['scrap_area']:
                    best.update(orientation='B', scrap_width=sw, scrap_length=sl, scrap_area=sa)

            if not best:
                continue

            candidates.append({
                'lot': lot,
                'lot_id': lot.id,
                'lot_name': lot.name,
                'orientation': best['orientation'],
                'scrap_width': best['scrap_width'],
                'scrap_length': best['scrap_length'],
                'scrap_area': best['scrap_area'],
                'is_scrap': lot.lx_is_scrap,
                'available_qty': available_qty,
            })

        candidates.sort(key=lambda c: (
            not c['is_scrap'],
            c['scrap_area'],
            c['available_qty'],
        ))
        return candidates

    def _update_reserved_quantity(self, need, location_id, lot_id=None, package_id=None, owner_id=None, strict=True):
        if not lot_id:
            strategy = self.product_id.categ_id.removal_strategy_id
            if strategy:
                if strategy.method == 'fabric_roll':
                    self.lx_selected_lot_id = False
                    best = self._lx_find_best_fabric_lot()
                    if best:
                        self.lx_selected_lot_id = best.id
                elif strategy.method == 'fabric_roll_sunscreen':
                    self.lx_selected_lot_id = False
                    best = self._lx_find_best_fabric_lot_sunscreen()
                    if best:
                        self.lx_selected_lot_id = best.id
                        production = self.raw_material_production_id
                        if production and self.lx_orientation == 'widthwise':
                            self.product_uom_qty = production.lx_width_m
                            need = self.product_uom_qty
        if self.lx_selected_lot_id and not lot_id:
            lot_id = self.lx_selected_lot_id
        return super()._update_reserved_quantity(
            need, location_id, lot_id=lot_id,
            package_id=package_id, owner_id=owner_id, strict=strict,
        )
