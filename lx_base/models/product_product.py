# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProductProduct(models.Model):
    _inherit = 'product.product'

    lx_adjusted_cost = fields.Float(
        string='Adjusted Cost',
        compute='_compute_lx_adjusted_cost',
        store=True,
        digits='Product Price',
        help="Standard price × (1 + waste_rate/100 + added_margin/100). "
             "Centralise le calcul des marges pour éviter de le répéter.",
    )

    @api.depends('standard_price', 'product_tmpl_id.waste_rate', 'product_tmpl_id.added_margin')
    def _compute_lx_adjusted_cost(self):
        for p in self:
            tmpl = p.product_tmpl_id
            waste = float(tmpl.waste_rate or 0.0) / 100.0
            margin = float(tmpl.added_margin or 0.0) / 100.0
            p.lx_adjusted_cost = (p.standard_price or 0.0) * (1.0 + waste + margin)

    def write(self, vals):
        """
        Surcharge write pour propager automatiquement les changements de
        standard_price aux attributs qui utilisent ces variantes comme composants.
        """
        res = super().write(vals)

        # Si standard_price change, propager aux attributs concernés
        if 'standard_price' in vals and not self.env.context.get('lx_skip_auto_price_sync'):
            # Trouver tous les product.attribute.component qui utilisent ces variantes
            ComponentLink = self.env['product.attribute.component']
            components = ComponentLink.search([
                ('component_variant_id', 'in', self.ids)
            ])

            if not components:
                return res

            # Récupérer les PTAVs en mode auto concernés
            ptavs = components.mapped('ptav_id').filtered(
                lambda p: p.lx_price_mode == 'auto'
            )

            if not ptavs:
                return res

            # Forcer recalcul et synchronisation du price_extra
            for ptav in ptavs:
                ptav._compute_lx_computed_price()
                computed = ptav.lx_computed_price
                current = ptav.price_extra
                if abs(computed - current) > 0.01:
                    ptav.with_context(lx_skip_auto_price_sync=True).write({
                        'price_extra': computed
                    })

        return res

    def lx_sync_attribute_prices_from_components(self):
        """
        Méthode appelée depuis product.product (variante).
        Délègue au product.template correspondant.
        """
        self.ensure_one()
        if self.product_tmpl_id:
            return self.product_tmpl_id.lx_sync_attribute_prices_from_components()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': 'No template found for this variant.',
                'type': 'warning',
                'sticky': False,
            }
        }
