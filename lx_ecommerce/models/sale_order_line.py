# -*- coding: utf-8 -*-
from odoo import api, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _apply_free_install_logic(self):
        """Applique (ou retire) la gratuité sur ce service d'installation
        selon le seuil configuré sur le template produit."""
        self.ensure_one()
        if not self.product_id.product_tmpl_id.lx_is_installation_service:
            return
        threshold = self.product_id.product_tmpl_id.lx_install_free_threshold
        if not threshold:
            return
        order = self.order_id
        merch_total = order._merch_total_excl_services()
        if merch_total >= threshold and self.discount < 100:
            self.with_context(skip_free_install=True).discount = 100.0
        elif merch_total < threshold and self.discount >= 100:
            self.with_context(skip_free_install=True).discount = 0.0

    @api.model
    def create(self, vals_list):
        """
        Lors de la création d'une ligne, si c'est un service d'installation lié,
        synchroniser sa quantité avec celle de la ligne liée.
        """
        lines = super().create(vals_list)

        for line in lines:
            if line.linked_line_id and line.product_id.product_tmpl_id.lx_is_installation_service:
                line.product_uom_qty = line.linked_line_id.product_uom_qty

        # Réappliquer la logique de gratuité pour les commandes concernées
        orders = lines.mapped('order_id')
        for order in orders:
            order._reapply_free_install_logic()

        return lines

    def write(self, vals):
        """
        Quand la quantité d'une ligne change, synchroniser automatiquement
        la quantité des services d'installation liés et réappliquer la gratuité.
        """
        if self._context.get('skip_free_install'):
            return super().write(vals)

        result = super().write(vals)

        if 'product_uom_qty' in vals:
            for line in self:
                installation_services = line.linked_line_ids.filtered(
                    lambda l: l.product_id.product_tmpl_id.lx_is_installation_service
                )
                if installation_services:
                    installation_services.with_context(skip_installation_sync=True).write({
                        'product_uom_qty': line.product_uom_qty
                    })

                line.order_id._reapply_free_install_logic()

        return result

    def unlink(self):
        """
        Quand une ligne produit est supprimée, supprimer aussi ses services liés
        et réappliquer la logique de gratuité.
        """
        orders = self.mapped('order_id')

        installation_services = self.env['sale.order.line']
        for line in self:
            installation_services |= line.linked_line_ids.filtered(
                lambda l: l.product_id.product_tmpl_id.lx_is_installation_service
            )

        if installation_services:
            installation_services.unlink()

        result = super().unlink()

        for order in orders:
            order._reapply_free_install_logic()

        return result
