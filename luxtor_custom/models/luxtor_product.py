# -*- coding: utf-8 -*-
import re
from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # ---------------------------------------------------------------------
    # BASIC TECHNICAL FIELDS (unchanged, preserved exactly as in original)
    # ---------------------------------------------------------------------
    is_mounting_bracket = fields.Boolean(
        string="Is Mounting Bracket",
        default=False,
        help="Indicates if a mounting bracket is required for this product."
    )
    lx_is_fabric = fields.Boolean(
        string="Is Fabric",
        default=False,
        help="Marks this template as the fabric component used in Luxtor costing.",
    )
    lx_is_cassette = fields.Boolean(
        string="Is Cassette",
        default=False,
        help="Marks this template as a cassette/headrail component.",
    )
    lx_is_roller_tube = fields.Boolean(
        string="Is Roller Tube",
        default=False,
        help="Marks this template as a roller tube component.",
    )
    lx_is_bottom_rail = fields.Boolean(
        string="Is Bottom Rail",
        default=False,
        help="Marks this template as a bottom rail component.",
    )
    lx_is_inner_tube = fields.Boolean(
        string="Is Inner Tube",
        default=False,
        help="Marks this template as an inner tube component.",
    )
    lx_is_adhesive_tape = fields.Boolean(
        string="Is Adhesive Tape",
        default=False,
        help="Marks this template as an adhesive tape component.",
    )

    lx_is_day_night = fields.Boolean(
        string="Is Day & Night",
        help="Marks product as Day & Night category for max height divisor."
    )
    lx_is_plastic_chain = fields.Boolean(
        string="Is Plastic Chain",
        default=False,
        help="Marks this template as a plastic control chain component.",
    )
    lx_is_roller_mechanism = fields.Boolean(
        string="Is Roller Mechanism",
        help="Marks this template as Roller Mechanism used for max load calculation."
    )
    lx_carrier = fields.Many2one("delivery.carrier")

    is_ceiling_clip = fields.Boolean(
        string="Is Ceiling Clip",
        default=False,
        help="Deprecated legacy field kept only for compatibility with existing records."
    )
    waste_rate = fields.Float(
        string="Waste Ratio",
        default=0.0,
        help="Percentage of extra material wasted during manufacturing."
    )
    added_margin = fields.Float(
        string="Profit Ratio",
        default=0.0,
        help="Additional margin used to calculate the final sale price."
    )

    maximum_load = fields.Float(
        string="Maximum Load",
        help="Maximum load (kg) that the product can support."
    )
    composition = fields.Text(
        string="Composition",
        help="Free-text description of the material composition."
    )

    waste_ids = fields.One2many(
        'luxtor.waste',
        'product_tmpl_id',
        string="Waste / Remnants",
        readonly=True,
    )

    lx_installation_space_id = fields.Many2one(
        "luxtor.installation.space",
        string="Location",
        help="Where the client typically installs this product (Salon, Bedroom, etc.)",
    )
    lx_is_new_in = fields.Boolean(string="New In", default=False)
    lx_is_weekly_deal = fields.Boolean(string="Weekly Deal", default=False)
    lx_is_bestseller = fields.Boolean(string="Bestsellers", default=False)
    lx_is_trending = fields.Boolean(string="Trending now", default=False)
    lx_is_sale = fields.Boolean(string="Sale", default=False)

    lx_color_ids = fields.Many2many(
        "lx.product.color",
        "lx_product_tmpl_color_rel",
        "product_tmpl_id",
        "color_id",
        string="Colors",
    )

 


    # ---------------------------------------------------------------------
    # FABRIC PARAMETERS (USED HEAVILY IN THE NEW ORIENTATION REMNANT LOGIC)
    # ---------------------------------------------------------------------
    # Stored in CENTIMETERS, ALWAYS convert to meters when used.
    fabric_allowance = fields.Float(
        string="Fabric Allowance",
        default=20.0,
    )

    # Minimum allowed remnant width (centimetres)
    # If remnant_width < threshold => auto SCRAP.
    remenant_threshold = fields.Float(
        string="Remenant Threshold",
        default=50.0,
    )

    remenant_tolerence = fields.Float(
        string="Remenant Tolerance",
        default=150,
        digits=(16, 0),
    )

    max_height = fields.Float(
        string="Maximum Height",
        compute="_compute_max_height",
        store=True,
        help="Maximum height supported by this product based on its width, weight and load."
    )

    is_dimension_product = fields.Boolean(
        string="Dimension Product",
        default=False,
        help=(
            "When set to True the product will use the custom dimension wizard "
            "instead of the standard product configurator."
        ),
    )

    lx_weight = fields.Float(
        string="Weight (g/m²)",
        help="Material areal density used in max-height calculation."
    )

    # ---------------------------------------------------------------------
    # ROLLER WIDTH TAGS / FABRIC REFERENCES
    # ---------------------------------------------------------------------
    roller_width_ids = fields.Many2many(
        'roller.width',
        'product_template_roller_width_rel',
        'product_tmpl_id',
        'roller_width_id',
        string='Roller Width Tags',
        help="Width tags for this product. For Rollers, the min width comes from the linked Fabric."
    )

    lx_fabric_ref_id = fields.Many2one(
        'product.template',
        string="Fabric Reference",
        default=lambda self: self._default_lx_fabric_ref_from_ctx(),
        help="Roller → Fabric link. Auto-filled when naming pattern matches."
    )

    width_cm = fields.Float(
        string="Width (cm)",
        compute='_compute_width_cm_from_tags',
        store=True,
        help="For Fabric: min width from own tags. For Rollers: min width strictly from linked Fabric."
    )

    lx_qty_by_width = fields.Boolean(
        string="Qty by Width",
        help="If true, MO cost/amount is multiplied by MO width."
    )
    lx_qty_by_height = fields.Boolean(
        string="Qty by Height",
        help="If true, MO cost/amount is multiplied by MO height."
    )

    model= fields.Char(string="Model", index=True)

    # ---------------------------------------------------------------------
    # M2O LOOKUPS / STATUS / ORIENTATION
    # ---------------------------------------------------------------------
    openness_factor_id = fields.Many2one(
        'product.openness.factor', string="Openness Factor", ondelete='set null'
    )
    color_fastness_id = fields.Many2one(
        'product.color.fastness', string="Color Fastness", ondelete='set null'
    )
    composition_id = fields.Many2one(
        'product.composition', string="Composition", ondelete='set null'
    )

    lx_status = fields.Selection(
        selection=[('active', 'Active'), ('discontinued', 'Discontinued')],
        string="Status", default='active'
    )

    # IMPORTANT FOR NEW REMNANT LOGIC
    # widthwise        => normal cutting
    # width_heightwise => rotated cutting (swap width <-> height)
    orientation = fields.Selection(
        selection=[
            ('widthwise', 'Widthwise'),
            ('width_heightwise', 'Widthwise & Heightwise')
        ],
        string="Orientation",
        default='widthwise'
    )

    # ---------------------------------------------------------------------
    # TABULATION VALUES (unchanged)
    # ---------------------------------------------------------------------
    tab_new_customer_pct = fields.Float(string="New Customer", default=0.0)
    tab_buy_earn_pct = fields.Float(string="Buy & Earn", default=0.0)
    tab_refer_earn_points = fields.Integer(string="Refer & Earn", default=0)
    tab_review_points = fields.Integer(string="Review", default=0)

    # ---------------------------------------------------------------------
    # HELPER: Convert remnant threshold from CM → METERS
    # ---------------------------------------------------------------------
    def _lx_get_remenant_threshold_m(self):
        """Convert remenant_threshold from CM to METERS."""
        self.ensure_one()
        try:
            return float(self.remenant_threshold or 0.0) / 100.0
        except Exception:
            return 0.0

    # ---------------------------------------------------------------------
    # EXISTING HELPERS (kept as-is)
    # ---------------------------------------------------------------------

    # def action_update_quantity_on_hand(self):
    #     res = super().action_update_quantity_on_hand()
    #     treasure_locations = self.env['stock.location'].search([
    #         ('is_lx_treasure', '=', True)
    #     ])
    #     if treasure_locations:
    #         domain = list(res.get('domain') or [])
    #         domain.append(('location_id', 'not in', treasure_locations.ids))
    #         res['domain'] = domain
    #     return res

    @api.model
    def _lx_remaining_threshold_from_cap(self):
        Param = self.env["ir.config_parameter"].sudo()
        cap_pct = float(Param.get_param("luxtor.lx_quantity_cap_pct", "95"))
        cap_pct = max(0.0, min(100.0, cap_pct))
        remaining_threshold = max(0.0, min(1.0, 1.0 - (cap_pct / 100.0)))
        return remaining_threshold

    def _lx_template_is_fabric_like(self):
        self.ensure_one()
        name_has_fabric = "fabric" in (self.name or "").lower()
        is_fabric = bool(self.lx_is_fabric)
        has_fabric_ref = bool(self.lx_fabric_ref_id)
        return is_fabric or name_has_fabric or has_fabric_ref

    def _lx_collect_fabric_variants(self):
        self.ensure_one()
        Product = self.env["product.product"]
        result = Product

        if self.lx_is_fabric or "fabric" in (self.name or "").lower():
            result |= self.product_variant_ids

        if self.lx_fabric_ref_id:
            result |= self.lx_fabric_ref_id.product_variant_ids

        boms = self.env["mrp.bom"].search([("product_tmpl_id", "=", self.id)])
        for bom in boms:
            for line in bom.bom_line_ids:
                comp_tmpl = line.product_id.product_tmpl_id
                if comp_tmpl.lx_is_fabric or "fabric" in (comp_tmpl.name or "").lower():
                    result |= comp_tmpl.product_variant_ids
                if comp_tmpl.lx_fabric_ref_id:
                    result |= comp_tmpl.lx_fabric_ref_id.product_variant_ids

        return result

    def _lx_fabric_remaining_ratio(self, website=None):
        self.ensure_one()
        fabrics = self._lx_collect_fabric_variants()
        if not fabrics:
            return 1.0, {"count": 0, "sum_virtual": 0.0, "sum_base": 0.0}

        ctx = dict(self.env.context or {})
        site = website or self.env["website"].get_current_website()
        wh = site.warehouse_id if site and site.exists() else False
        if wh:
            ctx["warehouse"] = wh.id

        sum_virtual = 0.0
        sum_base = 0.0
        for p in fabrics.with_context(ctx):
            sum_virtual += p.virtual_available
            sum_base += (p.qty_available + p.incoming_qty)

        base = max(1e-6, sum_base)
        ratio = max(0.0, min(1.0, sum_virtual / base))
        return ratio, {
            "count": len(fabrics),
            "sum_virtual": sum_virtual,
            "sum_base": base
        }

    def _lx_should_freeze_fabric_cap(self, website=None):
        self.ensure_one()
        involved = bool(self._lx_collect_fabric_variants())
        if not involved:
            return False, 1.0

        remaining_threshold = self._lx_remaining_threshold_from_cap()
        ratio, _ = self._lx_fabric_remaining_ratio(website=website)
        return (ratio <= remaining_threshold), ratio

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
        return bool(re.search(r'\[[^\]]+\]\s*Roller\s*Blind', (self.name or ''), flags=re.IGNORECASE))

    def _extract_code_from_roller_name(self):
        self.ensure_one()
        m = re.search(r'\[([^\]]+)\]\s*Roller\s*Blind', (self.name or ''), flags=re.IGNORECASE)
        return (m.group(1).strip() if m else '')

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

    
    def _lx_get_max_width_from_tags(self, tag_records):
        values = [
            float(getattr(t, "value_cm", 0.0) or 0.0)
            for t in (tag_records or self.env["roller.width"])
        ]
        values = [v for v in values if v > 0]
        return max(values) if values else 0.0


    @api.depends(
        "roller_width_ids",
        "roller_width_ids.value_cm",
        "lx_fabric_ref_id",
        "lx_fabric_ref_id.roller_width_ids",
        "lx_fabric_ref_id.roller_width_ids.value_cm",
    )
    def _compute_width_cm_from_tags(self):

        for product in self:

            fabric = product.lx_fabric_ref_id

            if fabric:
                roll_width = product._lx_get_max_width_from_tags(
                    fabric.roller_width_ids
                )
            else:
                roll_width = product._lx_get_max_width_from_tags(
                    product.roller_width_ids
                )

            product.width_cm = roll_width


    @api.onchange('roller_width_ids', 'lx_fabric_ref_id')
    def _onchange_roller_width_ids(self):

        for product in self:

            fabric = product.lx_fabric_ref_id

            if fabric:
                roll_width = product._lx_get_max_width_from_tags(
                    fabric.roller_width_ids
                )
            else:
                roll_width = product._lx_get_max_width_from_tags(
                    product.roller_width_ids
                )

            product.width_cm = roll_width

    

    # @api.depends('width_cm', 'lx_fabric_ref_id.lx_weight', 'lx_weight', 'categ_id')
    # def _compute_max_height(self):
    #     for product in self:
    #         divisor = 1.0
    #         cat = product.categ_id
    #         if cat and "Day & Night" in (cat.name or ""):
    #             divisor = 2.0

    #         fabric = product.lx_fabric_ref_id
    #         weight = float((getattr(fabric, 'lx_weight', 0.0) or product.lx_weight or 0.0) or 0.0)
    #         width_cm = float(product.width_cm or 0.0)

    #         mech = self.env['product.template'].search([('default_code', '=', 'MS')], limit=1)
    #         load = float(getattr(mech, 'maximum_load', 0.0) or 0.0)

    #         if load > 0 and width_cm > 0 and weight > 0 and divisor > 0:
    #             product.max_height = (load / (width_cm * weight) / divisor) * 100000.0
    #         else:
    #             product.max_height = 0.0

    @api.depends(
        'width_cm',
        'lx_fabric_ref_id.lx_weight',
        'lx_weight',
        'lx_is_day_night',
    )
    def _compute_max_height(self):

        Mechanism = self.env['product.template']

        mech = Mechanism.search(
            [('lx_is_roller_mechanism', '=', True)],
            limit=1
        )

        load = float(mech.maximum_load or 0.0)

        for product in self:
            usable_width = float(product.width_cm or 0.0)
            usable_width = max(usable_width, 0.0)

            fabric = product.lx_fabric_ref_id
            weight = float(
                getattr(fabric, 'lx_weight', 0.0)
                or product.lx_weight
                or 0.0
            )

            if load and usable_width and weight:

                height = (load / (usable_width * weight)) * 100000.0

                if product.lx_is_day_night:
                    height = height / 2.0

                product.max_height = height

            else:
                product.max_height = 0.0

    def _lx_virtual_price_for_width_partner(self, width_m, partner):

        self.ensure_one()

        Product = self.product_variant_id
        Bom = self.env['mrp.bom']
        Mrp = self.env['mrp.production']

        bom = Bom.search([
            ('product_tmpl_id', '=', self.id)
        ], limit=1)

        if not bom:
            return 0.0

        mo = Mrp.new({
            'product_id': Product.id,
            'bom_id': bom.id,
            'lx_width_m': width_m,
        })

        _cost, amount = mo._lx_virtual_calculate(width_m=width_m)

        factor = 1.0
        if partner and partner.lx_account_type_id:
            try:
                factor = float(partner.lx_account_type_id.rank or 100.0) / 100.0
            except:
                factor = 1.0

        return amount * factor

    # ---------------------------------------------------------------------
    # TAG SYNC 
    # ---------------------------------------------------------------------
    def _lx_tag_names_map(self):
        return {
            "lx_is_new_in": "New IN",
            "lx_is_weekly_deal": "weekly",
            "lx_is_bestseller": "Bestseller",
            "lx_is_trending": "Trending",
            "lx_is_sale": "Sale",  # NEW: add Sale tag mapping
        }

    def _lx_get_or_create_tag(self, name):
        Tag = self.env["product.tag"].sudo()
        tag = Tag.search([("name", "=", name)], limit=1)
        return tag or Tag.create({"name": name})

    def _lx_sync_tag_on_record(self, record, field_name, enabled):
        """
        Kept for backward compatibility with existing imports/usages.
        This helper is not used by the current implementation.
        """
        return

    def _lx_sync_one_toggle(self, toggle_field, enabled):
        """
        Sync the corresponding product.tag on:
        - template.product_tag_ids (always)
        - variants.product_tag_ids (if exists) (optional propagation)
        """
        self.ensure_one()
        tag_name = self._lx_tag_names_map().get(toggle_field)
        if not tag_name:
            return

        Tag = self.env["product.tag"].sudo()
        tag = Tag.search([("name", "=", tag_name)], limit=1)

        # 1) Template tags
        if enabled:
            if not tag:
                tag = self._lx_get_or_create_tag(tag_name)
            if tag.id not in self.product_tag_ids.ids:
                self.sudo().write({"product_tag_ids": [(4, tag.id)]})
        else:
            if tag and tag.id in self.product_tag_ids.ids:
                self.sudo().write({"product_tag_ids": [(3, tag.id)]})

        if self.product_variant_ids and "product_tag_ids" in self.env["product.product"]._fields:
            variants = self.product_variant_ids.sudo()
            if enabled:
                if not tag:
                    tag = self._lx_get_or_create_tag(tag_name)
                to_add = variants.filtered(lambda v: tag.id not in v.product_tag_ids.ids)
                if to_add:
                    to_add.write({"product_tag_ids": [(4, tag.id)]})
            else:
                if tag:
                    to_remove = variants.filtered(lambda v: tag.id in v.product_tag_ids.ids)
                    if to_remove:
                        to_remove.write({"product_tag_ids": [(3, tag.id)]})

    def _lx_sync_all_toggles(self):
        mapping = self._lx_tag_names_map()
        for tmpl in self:
            for toggle_field in mapping.keys():
                tmpl._lx_sync_one_toggle(toggle_field, bool(tmpl[toggle_field]))

    @api.onchange("lx_is_new_in", "lx_is_weekly_deal", "lx_is_bestseller", "lx_is_trending", "lx_is_sale")
    def _onchange_lx_sync_tags(self):
        for tmpl in self:
            tmpl._lx_sync_all_toggles()

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        recs._lx_sync_all_toggles()
        return recs

    def write(self, vals):
        res = super().write(vals)
        watched = set(self._lx_tag_names_map().keys())
        if watched.intersection(vals.keys()):
            self._lx_sync_all_toggles()
        return res

# ---------------------------------------------------------------------
# AUXILIARY MODELS (unchanged)
# ---------------------------------------------------------------------
class ProductOpennessFactor(models.Model):
    _name = 'product.openness.factor'
    _description = 'Openness Factor'
    _order = 'name'

    name = fields.Char(required=True, index=True, help="Label (e.g. '5').")
    active = fields.Boolean(default=True)


class ProductColorFastness(models.Model):
    _name = 'product.color.fastness'
    _description = 'Color Fastness'
    _order = 'name'

    name = fields.Char(required=True, index=True, help="Grade label (e.g. '8').")
    active = fields.Boolean(default=True)


class ProductComposition(models.Model):
    _name = 'product.composition'
    _description = 'Product Composition'
    _order = 'name'

    name = fields.Char(required=True, index=True, help="Composition label.")
    note = fields.Text(string="Notes")
    active = fields.Boolean(default=True)



