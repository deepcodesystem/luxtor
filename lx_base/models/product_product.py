# -*- coding: utf-8 -*-
from odoo import models


class ProductProduct(models.Model):
    _inherit = 'product.product'

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
            # On utilise _compute_lx_computed_price puis write
            for ptav in ptavs:
                ptav._compute_lx_computed_price()
                # On force la mise à jour si le prix a changé
                computed = ptav.lx_computed_price
                current = ptav.price_extra
                if abs(computed - current) > 0.01:
                    # Éviter boucle infinie avec context
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
