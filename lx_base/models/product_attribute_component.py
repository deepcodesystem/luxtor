# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProductAttributeComponent(models.Model):
    _name = 'product.attribute.component'
    _description = "Component (variant) linked to Attribute Value"
    _order = 'sequence, id'

    # ── Lien vers la valeur d'attribut ──────────────────────────────────────
    ptav_id = fields.Many2one(
        'product.template.attribute.value',
        string='Attribute Value',
        required=True,
        ondelete='cascade',
        index=True,
    )

    # ── Lien vers la VARIANTE du composant (product.product) ───────────────
    component_variant_id = fields.Many2one(
        'product.product',
        string='Component Variant',
        required=True,
        domain="[('product_tmpl_id.lx_is_component', '=', True)]",
        ondelete='restrict',
    )

    # ── Quantité utilisée ───────────────────────────────────────────────────
    quantity = fields.Float(
        string='Quantity',
        default=1.0,
        digits='Product Unit of Measure',
    )

    sequence = fields.Integer(string='Sequence', default=10)

    # ── Champs calculés pour le prix ────────────────────────────────────────
    component_standard_price = fields.Float(
        string='Unit Cost',
        related='component_variant_id.standard_price',
        store=True,
        readonly=True,
        help="Standard price of the component variant. Stored to trigger auto-update.",
    )

    # ── Marges du composant (récupérées depuis le template du composant) ────
    component_waste_rate = fields.Float(
        string='Waste Rate (%)',
        related='component_variant_id.product_tmpl_id.waste_rate',
        store=True,
        readonly=True,
        help="Waste rate from component template.",
    )

    component_added_margin = fields.Float(
        string='Added Margin (%)',
        related='component_variant_id.product_tmpl_id.added_margin',
        store=True,
        readonly=True,
        help="Added margin from component template.",
    )

    # ── Calculs intermédiaires ──────────────────────────────────────────────
    subtotal = fields.Float(
        string='Subtotal Base',
        compute='_compute_subtotal',
        store=True,
        help="Unit Cost × Quantity (sans marges)",
    )

    amount_with_margins = fields.Float(
        string='Amount with Margins',
        compute='_compute_amount_with_margins',
        store=True,
        help="Subtotal × (1 + waste_rate/100) × (1 + added_margin/100)",
    )

    # =========================================================================
    # COMPUTES
    # =========================================================================

    @api.depends('component_standard_price', 'quantity')
    def _compute_subtotal(self):
        for rec in self:
            rec.subtotal = (rec.component_standard_price or 0.0) * (rec.quantity or 0.0)

    @api.depends('subtotal', 'component_waste_rate', 'component_added_margin')
    def _compute_amount_with_margins(self):
        for rec in self:
            base = rec.subtotal or 0.0
            waste = float(rec.component_waste_rate or 0.0)
            margin = float(rec.component_added_margin or 0.0)

            # Formule : base × (1 + waste/100) × (1 + margin/100)
            factor = (1.0 + waste / 100.0) * (1.0 + margin / 100.0)
            rec.amount_with_margins = base * factor
