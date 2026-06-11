# -*- coding: utf-8 -*-
from odoo import api, models


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    @api.model
    def _get_removal_strategy_order(self, removal_strategy):
        if removal_strategy == 'fabric_roll':
            return 'in_date ASC, id'
        if removal_strategy == 'fabric_roll_sunscreen':
            return 'in_date ASC, id'
        return super()._get_removal_strategy_order(removal_strategy)
