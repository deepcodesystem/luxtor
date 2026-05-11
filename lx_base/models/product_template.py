# -*- coding: utf-8 -*-
import re
import logging
from odoo import api, fields, models
from ..utils import (
    ICP_BROWSER_FACTOR,
    lx_float,
)

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # ── Type composant BOM (liste déroulante) ─────────────────────────────────
    lx_component_type = fields.Selection(
        selection=[
            ('mounting_bracket', 'Mounting Bracket'),
            ('fabric', 'Fabric'),
            ('cassette', 'Cassette'),
            ('roller_tube', 'Roller Tube'),
            ('bottom_rail', 'Bottom Rail'),
            ('inner_tube', 'Inner Tube'),
            ('adhesive_tape', 'Adhesive Tape'),
            ('plastic_chain', 'Plastic Chain'),
            ('roller_mechanism', 'Roller Mechanism'),
        ],
        string="Component Type",
    )

    # ── Flags composants BOM (calculés depuis lx_component_type) ─────────────
    is_mounting_bracket = fields.Boolean(compute='_compute_component_flags', store=True)
    lx_is_fabric = fields.Boolean(compute='_compute_component_flags', store=True)
    lx_is_cassette = fields.Boolean(compute='_compute_component_flags', store=True)
    lx_is_roller_tube = fields.Boolean(compute='_compute_component_flags', store=True)
    lx_is_bottom_rail = fields.Boolean(compute='_compute_component_flags', store=True)
    lx_is_inner_tube = fields.Boolean(compute='_compute_component_flags', store=True)
    lx_is_adhesive_tape = fields.Boolean(compute='_compute_component_flags', store=True)
    lx_is_plastic_chain = fields.Boolean(compute='_compute_component_flags', store=True)
    lx_is_roller_mechanism = fields.Boolean(compute='_compute_component_flags', store=True)
    lx_is_day_night = fields.Boolean(string="Day & Night", default=False)

    # ── Paramètres calcul BOM ─────────────────────────────────────────────────
    waste_rate = fields.Float(string="Waste Rate (%)", default=0.0)
    added_margin = fields.Float(string="Added Margin (%)", default=0.0)
    maximum_load = fields.Float(string="Maximum Load (g)")
    fabric_allowance = fields.Float(string="Fabric Allowance (cm)", default=20.0)
    remenant_threshold = fields.Float(string="Remenant Threshold (cm)", default=50.0)
    remenant_tolerence = fields.Float(string="Remenant Tolerance (cm)", default=150.0, digits=(16, 0))

    # ── Propriétés tissu ──────────────────────────────────────────────────────
    lx_weight = fields.Float(string="Weight (g/m²)")
    lx_qty_by_width = fields.Boolean(string="Qty by Width", default=False)
    lx_qty_by_height = fields.Boolean(string="Qty by Height", default=False)
    composition = fields.Text(string="Composition (text)")

    # ── Liens auxiliaires ─────────────────────────────────────────────────────
    openness_factor_id = fields.Many2one('product.openness.factor', string="Openness Factor", ondelete='set null')
    color_fastness_id = fields.Many2one('product.color.fastness', string="Color Fastness", ondelete='set null')
    composition_id = fields.Many2one('product.composition', string="Composition", ondelete='set null')

    # ── Largeurs rouleau ──────────────────────────────────────────────────────
    roller_width_ids = fields.Many2many(
        'roller.width',
        'lx_base_product_tmpl_roller_width_rel',
        'product_tmpl_id',
        'roller_width_id',
        string='Roller Width Tags',
    )

    # ── Référence tissu ───────────────────────────────────────────────────────
    lx_fabric_ref_id = fields.Many2one(
        'product.template',
        string="Fabric Reference",
        default=lambda self: self._lx_default_fabric_ref(),
    )

    # ── Classification produit ────────────────────────────────────────────────
    lx_is_store = fields.Boolean(string="Store", default=False)
    lx_is_component = fields.Boolean(string="Composant", default=False)

    # ── Dimensions produit ────────────────────────────────────────────────────
    is_dimension_product = fields.Boolean(string="Dimension Product", default=False)

    width_cm = fields.Float(
        string="Max Width (cm)",
        compute='_compute_width_cm',
        store=True,
    )
    max_height = fields.Float(
        string="Max Height (m)",
        compute='_compute_max_height',
        store=True,
    )

    # ── Orientation coupe ─────────────────────────────────────────────────────
    orientation = fields.Selection(
        [('widthwise', 'Widthwise'), ('width_heightwise', 'Widthwise & Heightwise')],
        string="Orientation",
        default='widthwise',
    )

    # =========================================================================
    # DEFAULTS / HELPERS PRIVÉS
    # =========================================================================

    @api.model
    def _lx_default_fabric_ref(self):
        name = (self.env.context.get('default_name') or '').strip()
        code = self._lx_code_from_roller_name(name)
        if not code:
            return False
        return (
            self.search([('default_code', '=', code)], limit=1).id or
            self.search([('name', 'ilike', f"Fabric ({code})")], limit=1).id or
            False
        )

    @staticmethod
    def _lx_code_from_roller_name(name):
        """Extrait le code tissu depuis '[CODE] Roller Blind'."""
        if not name:
            return False
        m = re.search(r'\[([^\]]+)\]\s*Roller\s*Blind', name or '', re.IGNORECASE)
        return m.group(1).strip() if m else False

    def _lx_get_max_width_cm_from_tags(self, tags):
        vals = [float(t.value_cm or 0.0) for t in tags if t.value_cm]
        return max(vals) if vals else 0.0

    def _lx_search_fabric_by_code(self, code):
        if not code:
            return self.env['product.template']
        return (
            self.search([('default_code', '=', code)], limit=1) or
            self.search([('name', 'ilike', f"Fabric ({code})")], limit=1)
        )

    def _lx_browser_factor(self):
        """Retourne lx_browser_factor_pct / 100 depuis ir.config_parameter."""
        raw = self.env['ir.config_parameter'].sudo().get_param(ICP_BROWSER_FACTOR, default='100')
        return lx_float(raw, 100.0) / 100.0

    # =========================================================================
    # COMPUTES
    # =========================================================================

    @api.depends('lx_component_type')
    def _compute_component_flags(self):
        mapping = {
            'mounting_bracket': 'is_mounting_bracket',
            'fabric': 'lx_is_fabric',
            'cassette': 'lx_is_cassette',
            'roller_tube': 'lx_is_roller_tube',
            'bottom_rail': 'lx_is_bottom_rail',
            'inner_tube': 'lx_is_inner_tube',
            'adhesive_tape': 'lx_is_adhesive_tape',
            'plastic_chain': 'lx_is_plastic_chain',
            'roller_mechanism': 'lx_is_roller_mechanism',
        }
        for tmpl in self:
            ct = tmpl.lx_component_type
            for val, fname in mapping.items():
                tmpl[fname] = (ct == val)

    @api.depends('roller_width_ids', 'roller_width_ids.value_cm',
                 'lx_fabric_ref_id', 'lx_fabric_ref_id.roller_width_ids',
                 'lx_fabric_ref_id.roller_width_ids.value_cm')
    def _compute_width_cm(self):
        for tmpl in self:
            tags = tmpl.lx_fabric_ref_id.roller_width_ids if tmpl.lx_fabric_ref_id else tmpl.roller_width_ids
            tmpl.width_cm = tmpl._lx_get_max_width_cm_from_tags(tags)

    @api.depends('width_cm', 'lx_fabric_ref_id.lx_weight', 'lx_weight', 'lx_is_day_night',
                 'lx_fabric_ref_id.lx_is_day_night')
    def _compute_max_height(self):
        mech = self.search([('lx_is_roller_mechanism', '=', True)], limit=1)
        load = float(mech.maximum_load or 0.0)
        for tmpl in self:
            w_cm = max(0.0, float(tmpl.width_cm or 0.0))
            fabric = tmpl.lx_fabric_ref_id
            weight = float(getattr(fabric, 'lx_weight', 0.0) or tmpl.lx_weight or 0.0)
            if load and w_cm and weight:
                # h_m = load(g) × 100 / (w_cm × weight_g/m²)
                h = (load * 100.0) / (w_cm * weight)
                if tmpl.lx_is_day_night:
                    h /= 2.0
                tmpl.max_height = h
            else:
                tmpl.max_height = 0.0

    # =========================================================================
    # ONCHANGES
    # =========================================================================

    @api.onchange('name')
    def _onchange_name_autofill_fabric(self):
        for tmpl in self:
            if tmpl.lx_fabric_ref_id:
                continue
            code = self._lx_code_from_roller_name(tmpl.name)
            if code:
                fabric = tmpl._lx_search_fabric_by_code(code)
                if fabric:
                    tmpl.lx_fabric_ref_id = fabric

    # =========================================================================
    # API PUBLIQUE — utilisée par lx_sales, lx_mrp, lx_website_dims
    # =========================================================================

    def lx_max_width_m(self):
        """Retourne {tmpl_id: max_width_m} pour chaque template."""
        res = {}
        for tmpl in self:
            fabric = tmpl.lx_fabric_ref_id
            if not fabric:
                code = self._lx_code_from_roller_name(tmpl.name or '')
                if code:
                    fabric = self.sudo()._lx_search_fabric_by_code(code)
            tags = fabric.roller_width_ids if fabric else tmpl.roller_width_ids
            w_cm = tmpl._lx_get_max_width_cm_from_tags(tags)
            if not w_cm:
                w_cm = float(tmpl.width_cm or 0.0)
            res[tmpl.id] = round(max(0.0, w_cm) / 100.0, 4)
        return res

    def lx_max_height_m(self, width_m=None):
        """Retourne {tmpl_id: max_height_m} en tenant compte de la largeur si fournie."""
        mech = self.search([('lx_is_roller_mechanism', '=', True)], limit=1)
        load = float(mech.maximum_load or 0.0)
        res = {}
        for tmpl in self:
            divisor = 2.0 if tmpl.lx_is_day_night else 1.0
            fabric = tmpl.lx_fabric_ref_id
            weight = float(getattr(fabric, 'lx_weight', 0.0) or tmpl.lx_weight or 0.0)
            w_cm = (float(width_m) * 100.0) if width_m else float(tmpl.width_cm or 0.0)
            if w_cm > 0.0 and weight > 0.0 and load > 0.0:
                # h_m = load(g) × 100 / (w_cm × weight_g/m²)
                h_m = (load * 100.0) / (w_cm * weight) / divisor
                res[tmpl.id] = max(0.0, round(h_m, 4))
            else:
                res[tmpl.id] = float(tmpl.max_height or 0.0)
        return res

    def lx_dims_hints(self, width_m=None):
        """Retourne un dict hints min/max width + height pour la fiche produit."""
        self.ensure_one()
        from ..utils import LX_MIN_WIDTH_M, LX_MIN_HEIGHT_M
        max_w = self.lx_max_width_m().get(self.id, 0.0)
        if width_m and float(width_m) > 0:
            max_h = self.lx_max_height_m(float(width_m)).get(self.id, 0.0)
        else:
            max_h = self.lx_max_height_m().get(self.id, 0.0)
        return {
            'min_width_m': LX_MIN_WIDTH_M,
            'max_width_m': max_w,
            'min_height_m': LX_MIN_HEIGHT_M,
            'max_height_m': max_h,
        }
