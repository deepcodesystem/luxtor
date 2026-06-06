# -*- coding: utf-8 -*-
from odoo import api, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.model
    def create(self, vals_list):
        """
        Lors de la création d'une ligne, si c'est un service d'installation lié,
        synchroniser sa quantité avec celle de la ligne liée.
        """
        lines = super().create(vals_list)

        for line in lines:
            if line.linked_line_id and line.product_id.product_tmpl_id.lx_is_installation_service:
                # Synchroniser la quantité avec la ligne liée
                line.product_uom_qty = line.linked_line_id.product_uom_qty

        return lines

    def write(self, vals):
        """
        Quand la quantité d'une ligne change, synchroniser automatiquement
        la quantité des services d'installation liés.
        """
        result = super().write(vals)

        # Si la quantité a changé
        if 'product_uom_qty' in vals:
            for line in self:
                # Trouver tous les services d'installation liés à cette ligne
                installation_services = line.linked_line_ids.filtered(
                    lambda l: l.product_id.product_tmpl_id.lx_is_installation_service
                )

                if installation_services:
                    # Synchroniser leur quantité avec la ligne principale
                    # On utilise _origin pour éviter une boucle infinie
                    installation_services.with_context(skip_installation_sync=True).write({
                        'product_uom_qty': line.product_uom_qty
                    })

        return result

    def unlink(self):
        """
        Quand une ligne produit est supprimée, supprimer aussi ses services liés.
        """
        # Trouver tous les services d'installation liés
        installation_services = self.env['sale.order.line']
        for line in self:
            installation_services |= line.linked_line_ids.filtered(
                lambda l: l.product_id.product_tmpl_id.lx_is_installation_service
            )

        # Supprimer d'abord les services liés
        if installation_services:
            installation_services.unlink()

        # Puis supprimer la ligne principale
        return super().unlink()
