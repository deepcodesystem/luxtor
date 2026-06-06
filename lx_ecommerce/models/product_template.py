# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    lx_service_product_ids = fields.Many2many(
        comodel_name='product.product',
        relation='product_lx_service_rel',
        column1='src_id',
        column2='dest_id',
        string="Services Associés",
        check_company=True,
        help="Services que le client peut ajouter à son panier depuis le frontend "
             "(ventes incitatives & croisées). Ces services apparaissent dans la "
             "section 'Services Associés' lors de la consultation du panier.",
    )

    lx_is_installation_service = fields.Boolean(
        string="Service d'Installation",
        default=False,
        help="Si coché, la quantité de ce service sera automatiquement synchronisée "
             "avec la quantité du produit principal auquel il est lié. "
             "Le prix total sera donc: prix unitaire × quantité du produit.",
    )
