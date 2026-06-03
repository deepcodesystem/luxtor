from odoo import fields, models


class RemnantCategoryRule(models.Model):
    _name = "remnant.category.rule"
    _description = "Remnant Category Rule"
    _order = "sequence, name"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    product_category_id = fields.Many2one(
        "product.category",
        string="Product Category",
        help="Optional product category used to auto-detect this remnant rule.",
    )
    orientation = fields.Selection(
        [
            ("widthwise", "Widthwise"),
            ("heightwise", "Heightwise"),
            ("both", "Widthwise & Heightwise"),
        ],
        required=True,
        default="widthwise",
    )
    layer_count = fields.Integer(required=True, default=1)
    tolerance = fields.Float(
        default=1.5,
        required=True,
        help="Maximum acceptable oversize multiplier. Example: 1.5 means 150%.",
    )
    active = fields.Boolean(default=True)
