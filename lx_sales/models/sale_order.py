from odoo import models, api
from odoo.exceptions import UserError

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.model
    def _get_manufacture_route(self):
        return self.env.ref(
            'mrp.route_warehouse0_manufacture',
            raise_if_not_found=False
        )

    def action_confirm(self):
        res = super().action_confirm()
        manufacture_route = self._get_manufacture_route()

        if not manufacture_route:
            return res

        for order in self:
            for line in order.order_line:
                if not line.product_id:
                    continue

                # route_ids est un Many2many sur sale.order.line (module sale_stock)
                line_routes = line.route_ids or line.product_id.route_ids
                if manufacture_route not in line_routes:
                    continue

                bom = line.bom_id
                if not bom:
                    raise UserError(
                        f"Aucun BOM sélectionné pour le produit "
                        f"'{line.product_id.display_name}' "
                        f"sur la commande {order.name}."
                    )

                production_vals = order._prepare_manufacturing_order(line, bom)
                self.env['mrp.production'].create(production_vals)

        return res

    def _prepare_manufacturing_order(self, line, bom):
        self.ensure_one()
        return {
            'product_id': line.product_id.id,
            'product_qty': line.product_uom_qty,
            'product_uom_id': line.product_uom_id.id,
            'bom_id': bom.id,
            'origin': self.name,
            'sale_id': self.id,          # si tu as le champ Many2one côté mrp.production
            'company_id': self.company_id.id,
            'user_id': self.user_id.id,
            # Variante du produit
            'product_tmpl_id': line.product_id.product_tmpl_id.id,
            'lx_width_m': line.lx_width_m,
            'lx_height_m': line.lx_height_m,
        }

    def _cart_update(self, product_id=None, line_id=None, add_qty=0, set_qty=0, **kwargs):
        """Surcharge pour récupérer les dimensions depuis le configurateur"""
        values = super()._cart_update(
            product_id=product_id,
            line_id=line_id,
            add_qty=add_qty,
            set_qty=set_qty,
            **kwargs
        )

        # Si des dimensions sont passées dans kwargs, les appliquer
        if line_id and (kwargs.get('lx_width_m') or kwargs.get('lx_height_m')):
            line = self.env['sale.order.line'].browse(line_id)
            if line.exists():
                line.write({
                    'lx_width_m': float(kwargs.get('lx_width_m', 0)),
                    'lx_height_m': float(kwargs.get('lx_height_m', 0)),
                })

        return values