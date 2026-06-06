# -*- coding: utf-8 -*-
import random
from odoo import models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _cart_lx_services(self):
        """Suggest services based on 'Services Associés' of products in cart"""
        product_ids = set(self.website_order_line.product_id.ids)
        all_service_products = self.env['product.product']

        for line in self.website_order_line.filtered('product_id'):
            service_products = line.product_id.product_tmpl_id.lx_service_product_ids
            if service_products:
                # Filter services similarly to accessory products
                combination = line.product_id.product_template_attribute_value_ids + line.product_no_variant_attribute_value_ids
                all_service_products |= service_products.filtered(lambda product:
                    product.id not in product_ids
                    and product._website_show_quick_add()
                    and product.filtered_domain(self.env['product.product']._check_company_domain(line.company_id))
                    and product._is_variant_possible(parent_combination=combination)
                    and (
                        not self.website_id.prevent_zero_price_sale
                        or product._get_contextual_price()
                    )
                )

        return random.sample(all_service_products, len(all_service_products))

    def _get_main_product_line_for_service(self):
        """
        Retourne la ligne du produit principal (store) du panier.
        Utilisé pour lier les services d'installation au bon produit.

        Logique: On cherche la première ligne qui est un produit physique (consu/combo)
        et qui n'est pas déjà un service lié.
        """
        self.ensure_one()

        # Chercher les lignes de produits principaux (pas des services)
        main_lines = self.order_line.filtered(
            lambda l: l.product_id
            and l.product_id.type in ['consu', 'combo']
            and not l.linked_line_id  # Pas une ligne liée
            and not l.product_id.product_tmpl_id.lx_is_installation_service
        )

        # Retourner la première ligne trouvée (ou vide si aucune)
        return main_lines[:1] if main_lines else self.env['sale.order.line']

    def _prepare_order_line_values(
        self,
        product_id,
        quantity,
        uom_id,
        *,
        linked_line_id=False,
        **kwargs
    ):
        """
        Override pour lier automatiquement les services d'installation
        au produit principal du panier.
        """
        values = super()._prepare_order_line_values(
            product_id, quantity, uom_id, linked_line_id=linked_line_id, **kwargs
        )

        # Si c'est un service d'installation et qu'il n'est pas déjà lié
        product = self.env['product.product'].browse(product_id)
        if (
            product.product_tmpl_id.lx_is_installation_service
            and not linked_line_id
        ):
            # Trouver le produit principal dans le panier
            main_line = self._get_main_product_line_for_service()
            if main_line:
                # Lier le service au produit principal
                values['linked_line_id'] = main_line.id
                # Ajuster la quantité initiale pour correspondre au produit
                values['product_uom_qty'] = main_line.product_uom_qty

        return values
