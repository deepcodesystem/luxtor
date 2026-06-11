# -*- coding: utf-8 -*-
import random
from odoo import models, Command


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _merch_total_excl_services(self):
        """Total marchandise hors services d'installation et livraison."""
        total = 0.0
        for line in self.order_line:
            if line.display_type:
                continue
            if getattr(line, 'is_delivery', False):
                continue
            if line.product_id.product_tmpl_id.lx_is_installation_service:
                continue
            total += float(line.price_total or 0.0)
        return total

    def _reapply_free_install_logic(self):
        """Vérifie le seuil pour tous les services d'installation de la commande
        et applique (ou retire) la gratuité via discount=100%."""
        for line in self.order_line.filtered(
            lambda l: l.product_id.product_tmpl_id.lx_is_installation_service
        ):
            line._apply_free_install_logic()

    def _free_install_status(self):
        """Retourne un dict {product_id: bool} indiquant si chaque service
        d'installation est gratuit pour cette commande."""
        status = {}
        for line in self.order_line:
            tmpl = line.product_id.product_tmpl_id
            if tmpl.lx_is_installation_service:
                threshold = tmpl.lx_install_free_threshold
                if threshold:
                    status[line.product_id.id] = self._merch_total_excl_services() >= threshold
        return status

    def _add_associated_products(self, line):
        if not line or not line.exists() or line.product_uom_qty <= 0 or not line.product_id:
            return
        ptavs = line.product_id.product_template_attribute_value_ids
        associated = self.env['product.product']
        for ptav in ptavs:
            associated |= ptav.lx_associated_product_ids
        for assoc_product in associated:
            existing = self.order_line.filtered(
                lambda l: l.product_id == assoc_product
                and l.linked_line_id == line
            )
            if not existing:
                self.env['sale.order.line'].create({
                    'order_id': self.id,
                    'product_id': assoc_product.id,
                    'product_uom_qty': line.product_uom_qty,
                    'product_uom_id': assoc_product.uom_id.id,
                    'price_unit': assoc_product.lst_price,
                    'tax_ids': [Command.set(assoc_product.taxes_id.filtered(
                        lambda tax: tax.company_id in (False, self.company_id)
                    ).ids)],
                    'linked_line_id': line.id,
                    'lx_auto_associated_line': True,
                })

    def _cart_add(self, product_id=0, quantity=1.0, *, uom_id=None, **kwargs):
        values = super()._cart_add(product_id, quantity, uom_id=uom_id, **kwargs)
        self._add_associated_products(
            self.env['sale.order.line'].browse(values.get('line_id'))
        )
        return values

    def _cart_update(self, product_id=None, line_id=None, add_qty=0, set_qty=0, **kwargs):
        values = super()._cart_update(product_id, line_id, add_qty, set_qty, **kwargs)
        self._add_associated_products(
            self.env['sale.order.line'].browse(values.get('line_id'))
        )
        return values

    def _cart_lx_associated_products(self):
        """Suggest associated products based on attribute values of products in cart"""
        product_ids = set(self.website_order_line.product_id.ids)
        all_associated = self.env['product.product']

        for line in self.website_order_line.filtered('product_id'):
            ptavs = line.product_id.product_template_attribute_value_ids
            for ptav in ptavs:
                associated = ptav.lx_associated_product_ids
                if associated:
                    combination = line.product_id.product_template_attribute_value_ids + line.product_no_variant_attribute_value_ids
                    all_associated |= associated.filtered(lambda p:
                        p.id not in product_ids
                        and p._website_show_quick_add()
                        and p.filtered_domain(self.env['product.product']._check_company_domain(line.company_id))
                        and p._is_variant_possible(parent_combination=combination)
                        and (
                            not self.website_id.prevent_zero_price_sale
                            or p._get_contextual_price()
                        )
                    )

        return random.sample(all_associated, len(all_associated))

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
