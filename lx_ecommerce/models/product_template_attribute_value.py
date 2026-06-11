from odoo import fields, models


class ProductTemplateAttributeValue(models.Model):
    _inherit = 'product.template.attribute.value'

    lx_associated_product_ids = fields.Many2many(
        comodel_name='product.product',
        relation='product_lx_associated_rel',
        column1='ptav_id',
        column2='product_id',
        string="Produits Associés",
        help="Produits suggérés lorsque cette valeur d'attribut est sélectionnée "
             "dans le panier (ventes incitatives & croisées).",
    )
