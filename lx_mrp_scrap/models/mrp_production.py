# -*- coding: utf-8 -*-
import logging
from odoo import fields, models

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    lx_scrap_ids = fields.One2many(
        'lx.scrap',
        'production_id',
        string="Chutes générées",
    )

    def action_confirm(self):
        res = super().action_confirm()
        for mo in self:
            for move in mo.move_raw_ids.filtered('lx_selected_lot_id'):
                lot = move.lx_selected_lot_id
                if lot.lx_cut_direction != 'height_fixed':
                    continue
                scrap_width = lot.lx_width - (mo.lx_width_m or 0.0)
                scrap_length = move.product_uom_qty or 0.0
                if scrap_width <= 0.0 or scrap_length <= 0.0:
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
