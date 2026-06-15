# -*- coding: utf-8 -*-
from odoo import api, fields, models


class LxScrap(models.Model):
    _name = 'lx.scrap'
    _description = "Chute de tissu"
    _order = 'id desc'

    name = fields.Char(
        string="Reference",
        required=True,
        default='/',
    )
    production_id = fields.Many2one(
        'mrp.production',
        string="OF source",
        ondelete='restrict',
    )
    lot_id = fields.Many2one(
        'stock.lot',
        string="Lot rouleau source",
    )
    product_id = fields.Many2one(
        'product.product',
        string="Fabric",
    )
    lx_scrap_width = fields.Float(
        string="Width Scrap (m)",
        digits=(10, 3),
    )
    lx_scrap_length = fields.Float(
        string="Height scrap (m)",
        digits=(10, 3),
    )
    lx_scrap_area = fields.Float(
        string="Scrap Size (m²)",
        digits=(10, 3),
        compute='_compute_area',
        store=True,
    )
    state = fields.Selection(
        [('available', 'Available'),
         ('used', 'Used'),
         ('discarded', 'Discarded')],
        string="Status",
        default='available',
    )
    notes = fields.Text(string="Notes")
    new_lot_id = fields.Many2one(
        'stock.lot',
        string="New Scrap Lot",
        help="Batch created in inventory for this reusable scrap",
    )

    def action_put_in_stock(self):
        """Crée un lot chute et met la quantité en stock (emplacement magasin)."""
        self.ensure_one()
        if self.state != 'available' or self.new_lot_id:
            return
        location = self.env.ref('stock.stock_location_stock', raise_if_not_found=False)
        if not location:
            location = self.product_id.company_id.warehouse_id.lot_stock_id
        lot = self.env['stock.lot'].create({
            'name': self.name,
            'product_id': self.product_id.id,
            'company_id': self.env.company.id,
        })
        lot.write({
            'lx_width': self.lx_scrap_width,
            'lx_is_scrap': True,
            'lx_origin_production_id': self.production_id.id,
        })
        self.env['stock.quant']._update_available_quantity(
            self.product_id, location, self.lx_scrap_length,
            lot_id=lot,
        )
        self.write({
            'new_lot_id': lot.id,
        })

    @api.depends('lx_scrap_width', 'lx_scrap_length')
    def _compute_area(self):
        for rec in self:
            rec.lx_scrap_area = (rec.lx_scrap_width or 0.0) * (rec.lx_scrap_length or 0.0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('lx.scrap') or '/'
            if vals.get('production_id'):
                production = self.env['mrp.production'].browse(vals['production_id'])
                fabric_move = production.move_raw_ids.filtered('lx_selected_lot_id')[:1]
                if not vals.get('product_id'):
                    if fabric_move:
                        vals['product_id'] = fabric_move.product_id.id
                    else:
                        vals['product_id'] = production.product_id.id
                if not vals.get('lot_id') and fabric_move:
                    vals['lot_id'] = fabric_move.lx_selected_lot_id.id
        return super().create(vals_list)
