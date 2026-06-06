# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ProductTemplateAttributeValue(models.Model):
    _inherit = 'product.template.attribute.value'

    # ── Composants liés ─────────────────────────────────────────────────────
    lx_component_ids = fields.One2many(
        'product.attribute.component',
        'ptav_id',
        string='Components',
        help="Component variants used to calculate the price_extra automatically.",
    )

    # ── Mode de calcul du prix ──────────────────────────────────────────────
    lx_price_mode = fields.Selection(
        [('auto', 'Automatic from Components'),
         ('manual', 'Manual Entry')],
        string='Price Mode',
        default='manual',
        required=True,
        help="Auto: price_extra calculated from components. Manual: enter price_extra manually.",
    )

    # ── Prix calculé automatiquement ────────────────────────────────────────
    lx_computed_price = fields.Float(
        string='Computed Price',
        compute='_compute_lx_computed_price',
        store=True,
        help="Automatic price based on component costs with margins: "
             "Σ(component_cost × qty × (1 + waste_rate/100) × (1 + added_margin/100))\n"
             "Note: waste_rate and added_margin come from each component's template.",
    )

    # =========================================================================
    # COMPUTES
    # =========================================================================

    @api.depends('lx_component_ids.amount_with_margins')
    def _compute_lx_computed_price(self):
        """
        Calcule le prix total en sommant les montants avec marges de chaque composant.
        Chaque composant applique ses propres waste_rate et added_margin.
        """
        for ptav in self:
            # Somme des montants avec marges de chaque composant
            total = sum(ptav.lx_component_ids.mapped('amount_with_margins'))

            # Debug logging
            if ptav.lx_component_ids:
                _logger.debug(
                    "Computing price for PTAV '%s': %d component(s), total=%.2f",
                    ptav.name, len(ptav.lx_component_ids), total
                )
                for comp in ptav.lx_component_ids:
                    _logger.debug(
                        "  - %s: qty=%.2f, price=%.2f, waste=%.1f%%, margin=%.1f%%, amount=%.2f",
                        comp.component_variant_id.display_name,
                        comp.quantity,
                        comp.component_standard_price,
                        comp.component_waste_rate,
                        comp.component_added_margin,
                        comp.amount_with_margins
                    )

            ptav.lx_computed_price = total

    # =========================================================================
    # WRITE OVERRIDE
    # =========================================================================

    def write(self, vals):
        res = super().write(vals)

        # Si mode auto et que lx_computed_price a changé, synchroniser price_extra
        # On évite les boucles infinies en vérifiant si price_extra diffère
        for ptav in self:
            if ptav.lx_price_mode == 'auto':
                computed = ptav.lx_computed_price
                current = ptav.price_extra
                # Tolérance de 0.01 pour éviter les boucles dues aux arrondis
                if abs(computed - current) > 0.01:
                    super(ProductTemplateAttributeValue, ptav).write({
                        'price_extra': computed
                    })

        return res

    # =========================================================================
    # ONCHANGE
    # =========================================================================

    @api.onchange('lx_price_mode', 'lx_computed_price')
    def _onchange_price_mode(self):
        """Synchroniser price_extra quand on passe en mode auto."""
        if self.lx_price_mode == 'auto':
            self.price_extra = self.lx_computed_price
