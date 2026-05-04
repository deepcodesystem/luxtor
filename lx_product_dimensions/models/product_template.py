# -*- coding: utf-8 -*-
import re
from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # ------------------------------------------------------------------
    # COMPONENT FLAGS
    # ------------------------------------------------------------------
    is_mounting_bracket = fields.Boolean(string="Is Mounting Bracket", default=False)
    lx_is_fabric = fields.Boolean(string="Is Fabric", default=False)
    lx_is_cassette = fields.Boolean(string="Is Cassette", default=False)
    lx_is_roller_tube = fields.Boolean(string="Is Roller Tube", default=False)
    lx_is_bottom_rail = fields.Boolean(string="Is Bottom Rail", default=False)
    lx_is_inner_tube = fields.Boolean(string="Is Inner Tube", default=False)
    lx_is_adhesive_tape = fields.Boolean(string="Is Adhesive Tape", default=False)
    lx_is_day_night = fields.Boolean(string="Is Day & Night")
    lx_is_plastic_chain = fields.Boolean(string="Is Plastic Chain", default=False)
    lx_is_roller_mechanism = fields.Boolean(string="Is Roller Mechanism")

    # ------------------------------------------------------------------
    # COMPUTATION PARAMS
    # ------------------------------------------------------------------
    waste_rate = fields.Float(string="Waste Ratio", default=0.0)
    added_margin = fields.Float(string="Profit Ratio", default=0.0)
    maximum_load = fields.Float(string="Maximum Load")
    composition = fields.Text(string="Composition")
    fabric_allowance = fields.Float(string="Fabric Allowance", default=20.0)
    remenant_threshold = fields.Float(string="Remenant Threshold", default=50.0)
    remenant_tolerence = fields.Float(
        string="Remenant Tolerance", default=150, digits=(16, 0),
    )
    lx_weight = fields.Float(string="Weight (g/m²)")
    lx_qty_by_width = fields.Boolean(string="Qty by Width")
    lx_qty_by_height = fields.Boolean(string="Qty by Height")

    # ------------------------------------------------------------------
    # AUXILIARY M2O
    # ------------------------------------------------------------------
    openness_factor_id = fields.Many2one(
        'product.openness.factor', string="Openness Factor", ondelete='set null',
    )
    color_fastness_id = fields.Many2one(
        'product.color.fastness', string="Color Fastness", ondelete='set null',
    )
    composition_id = fields.Many2one(
        'product.composition', string="Composition", ondelete='set null',
    )

    # ------------------------------------------------------------------
    # FABRIC / ROLLER WIDTH
    # ------------------------------------------------------------------
    roller_width_ids = fields.Many2many(
        'roller.width',
        'product_template_roller_width_rel',
        'product_tmpl_id',
        'roller_width_id',
        string='Roller Width Tags',
    )

    lx_fabric_ref_id = fields.Many2one(
        'product.template',
        string="Fabric Reference",
        default=lambda self: self._default_lx_fabric_ref_from_ctx(),
    )

    width_cm = fields.Float(
        string="Width (cm)",
        compute='_compute_width_cm_from_tags',
        store=True,
    )

    # ------------------------------------------------------------------
    # ORIENTATION
    # ------------------------------------------------------------------
    orientation = fields.Selection(
        selection=[
            ('widthwise', 'Widthwise'),
            ('width_heightwise', 'Widthwise & Heightwise'),
        ],
        string="Orientation",
        default='widthwise',
    )

    # ------------------------------------------------------------------
    # DIMENSION PRODUCT FLAG + MAX HEIGHT
    # ------------------------------------------------------------------
    is_dimension_product = fields.Boolean(
        string="Dimension Product",
        default=False,
    )

    max_height = fields.Float(
        string="Maximum Height",
        compute="_compute_max_height",
        store=True,
    )

    # ------------------------------------------------------------------
    # HELPERS — fabric / roller name
    # ------------------------------------------------------------------
    def _lx_get_remenant_threshold_m(self):
        self.ensure_one()
        try:
            return float(self.remenant_threshold or 0.0) / 100.0
        except Exception:
            return 0.0

    @api.model
    def _default_lx_fabric_ref_from_ctx(self):
        name = (self.env.context.get('default_name') or '').strip()
        m = re.search(r'\[([^\]]+)\]\s*Roller\s*Blind', name, flags=re.IGNORECASE)
        if not m:
            return False
        code = m.group(1).strip()
        Fabric = self.env['product.template']
        exact = Fabric.search([('name', '=', f"Fabric ({code})")], limit=1)
        if exact:
            return exact.id
        like = Fabric.search([('name', 'ilike', f"Fabric ({code})")], limit=1)
        return like.id if like else False

    def _is_roller_name(self):
        self.ensure_one()
        return bool(re.search(r'\[[^\]]+\]\s*Roller\s*Blind', (self.name or ''), re.IGNORECASE))

    def _extract_code_from_roller_name(self):
        self.ensure_one()
        m = re.search(r'\[([^\]]+)\]\s*Roller\s*Blind', (self.name or ''), re.IGNORECASE)
        return m.group(1).strip() if m else ''

    def _search_fabric_by_code(self, code):
        Fabric = self.env['product.template']
        exact = Fabric.search([('name', '=', f"Fabric ({code})")], limit=1)
        if exact:
            return exact
        return Fabric.search([('name', 'ilike', f"Fabric ({code})")], limit=1)

    def _min_width_cm_from_tag_records(self, tag_records):
        vals = [float(getattr(t, 'value_cm', 0.0) or 0.0) for t in (tag_records or self.env['roller.width'])]
        vals = [v for v in vals if v > 0]
        return min(vals) if vals else 0.0

    def _min_width_cm_from_fabric(self):
        self.ensure_one()
        fabric = self.lx_fabric_ref_id
        if not fabric and self._is_roller_name():
            code = self._extract_code_from_roller_name()
            if code:
                fabric = self._search_fabric_by_code(code)
        if not fabric:
            return 0.0
        return self._min_width_cm_from_tag_records(fabric.roller_width_ids)

    def _lx_get_max_width_from_tags(self, tag_records):
        values = [float(getattr(t, "value_cm", 0.0) or 0.0) for t in (tag_records or self.env["roller.width"])]
        values = [v for v in values if v > 0]
        return max(values) if values else 0.0

    # ------------------------------------------------------------------
    # COMPUTES
    # ------------------------------------------------------------------
    @api.depends(
        "roller_width_ids", "roller_width_ids.value_cm",
        "lx_fabric_ref_id", "lx_fabric_ref_id.roller_width_ids",
        "lx_fabric_ref_id.roller_width_ids.value_cm",
    )
    def _compute_width_cm_from_tags(self):
        for product in self:
            fabric = product.lx_fabric_ref_id
            if fabric:
                product.width_cm = product._lx_get_max_width_from_tags(fabric.roller_width_ids)
            else:
                product.width_cm = product._lx_get_max_width_from_tags(product.roller_width_ids)

    @api.depends('width_cm', 'lx_fabric_ref_id.lx_weight', 'lx_weight', 'lx_is_day_night')
    def _compute_max_height(self):
        mech = self.env['product.template'].search(
            [('lx_is_roller_mechanism', '=', True)], limit=1
        )
        load = float(mech.maximum_load or 0.0)

        for product in self:
            usable_width = max(0.0, float(product.width_cm or 0.0))
            fabric = product.lx_fabric_ref_id
            weight = float(
                getattr(fabric, 'lx_weight', 0.0) or product.lx_weight or 0.0
            )
            if load and usable_width and weight:
                height = (load / (usable_width * weight)) * 100000.0
                if product.lx_is_day_night:
                    height /= 2.0
                product.max_height = height
            else:
                product.max_height = 0.0

    # ------------------------------------------------------------------
    # ONCHANGES
    # ------------------------------------------------------------------
    @api.onchange('name')
    def _onchange_name_autofill_fabric(self):
        for p in self:
            if p.lx_fabric_ref_id:
                continue
            if p._is_roller_name():
                code = p._extract_code_from_roller_name()
                if code:
                    fabric = p._search_fabric_by_code(code)
                    if fabric:
                        p.lx_fabric_ref_id = fabric.id

    @api.onchange('roller_width_ids', 'lx_fabric_ref_id')
    def _onchange_roller_width_ids(self):
        for product in self:
            fabric = product.lx_fabric_ref_id
            if fabric:
                product.width_cm = product._lx_get_max_width_from_tags(fabric.roller_width_ids)
            else:
                product.width_cm = product._lx_get_max_width_from_tags(product.roller_width_ids)

    # ------------------------------------------------------------------
    # MAX WIDTH / HEIGHT helpers (used by controller + wizard)
    # ------------------------------------------------------------------
    def _lx_extract_code_from_roller_name_str(self, name):
        if not name:
            return False
        m = re.search(r'\[([^\]]+)\]\s*Roller\s*Blind', name, flags=re.IGNORECASE)
        return m.group(1).strip() if m else False

    def _lx_max_width_m_from_fabric_or_tmpl(self):
        """Return {tmpl_id: max_w_m}."""
        res = {}
        for tmpl in self:
            max_w_m = 0.0
            fabric = getattr(tmpl, "lx_fabric_ref_id", False)
            if not fabric:
                code = tmpl._lx_extract_code_from_roller_name_str(tmpl.name or "")
                if code:
                    fabric = self.env["product.template"].sudo().search(
                        [("default_code", "=", code)], limit=1
                    )
            if fabric and getattr(fabric, "roller_width_ids", False):
                vals_cm = [
                    float(getattr(rec, "value_cm", 0.0) or 0.0)
                    for rec in fabric.roller_width_ids.sudo()
                ]
                vals_cm = [v for v in vals_cm if v > 0]
                if vals_cm:
                    max_w_m = max(vals_cm) / 100.0
            if not max_w_m and getattr(tmpl, "width_cm", False):
                try:
                    max_w_m = max(0.0, float(tmpl.width_cm or 0.0) / 100.0)
                except Exception:
                    max_w_m = 0.0
            res[tmpl.id] = max_w_m
        return res

    def _lx_max_height_from_width(self, width_m):
        """Return {tmpl_id: max_h_m}."""
        res = {}
        mech = self.env["product.template"].sudo().search(
            [("default_code", "=", "MS")], limit=1
        )
        load = float(getattr(mech, "maximum_load", 0.0) or 0.0)

        for tmpl in self:
            divisor = 1.0
            cat = getattr(tmpl, "categ_id", False)
            if cat and "Day & Night" in (cat.name or ""):
                divisor = 2.0

            fabric = getattr(tmpl, "lx_fabric_ref_id", False)
            weight = float(
                getattr(fabric, "lx_weight", 0.0)
                or getattr(tmpl, "lx_weight", 0.0)
                or 0.0
            )
            width_cm = max(0.0, float(width_m or 0.0) * 100.0)

            if width_cm <= 0.0 or weight <= 0.0 or load <= 0.0 or divisor <= 0.0:
                try:
                    res[tmpl.id] = float(getattr(tmpl, "max_height", 0.0) or 0.0)
                except Exception:
                    res[tmpl.id] = 0.0
                continue

            h_m = (load / (width_cm * weight)) / divisor * 100000.0
            res[tmpl.id] = max(0.0, round(h_m, 4))
        return res

    @api.model
    def lx_dimensions_hints_backend(self, product_id=None, product_tmpl_id=None, width_m=None, unit="m"):
        """Backend-safe mirror of /lx/dimensions/hints — callable via call_kw."""
        Product = self.env["product.product"].sudo()
        Template = self.env["product.template"].sudo()

        tmpl = None
        if product_id:
            p = Product.browse(int(product_id))
            if p.exists():
                tmpl = p.product_tmpl_id
        if not tmpl and product_tmpl_id:
            t = Template.browse(int(product_tmpl_id))
            tmpl = t if t.exists() else None

        if not tmpl:
            return {"ok": False, "error": "product_template_not_found"}

        min_w_m, min_h_m = 0.60, 0.90
        max_w_map = tmpl._lx_max_width_m_from_fabric_or_tmpl()
        max_w_m = max_w_map.get(tmpl.id, 0.0)

        if width_m and float(width_m or 0.0) > 0:
            max_h_map = tmpl._lx_max_height_from_width(float(width_m))
            max_h_m = max_h_map.get(tmpl.id, 0.0)
        else:
            try:
                max_h_m = float(getattr(tmpl, "max_height", 0.0) or 0.0)
            except Exception:
                max_h_m = 0.0

        def _fmt(v):
            return f"{float(v or 0.0):.2f} m"

        width_hint = f"min: {_fmt(min_w_m)}" + (f" / max: {_fmt(max_w_m)}" if max_w_m > 0 else "")
        height_hint = f"min: {_fmt(min_h_m)}" + (f" / max: {_fmt(max_h_m)}" if max_h_m > 0 else "")

        return {
            "ok": True,
            "product": {"tmpl_id": tmpl.id, "name": tmpl.name},
            "width": {"min_m": min_w_m, "max_m": max_w_m, "hint": width_hint},
            "height": {"min_m": min_h_m, "max_m": max_h_m, "hint": height_hint},
        }

