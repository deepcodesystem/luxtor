import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class RemnantStock(models.Model):
    _name = "remnant.stock"
    _description = "Fabric Remnant"
    _order = "name asc"
    _sql_constraints = [
        (
            "name_company_unique",
            "unique(name, company_id)",
            "Remnant ID must be unique per company.",
        ),
        (
            "product_remnant_code_company_unique",
            "unique(product_id, remnant_code, company_id)",
            "Remnant code must be unique per product and company.",
        ),
    ]

    name = fields.Char(
        string="Remnant ID",
        required=True,
        default="New",
        copy=False,
    )
    remnant_code = fields.Char(
        string="Remnant Code",
        required=True,
        default="New",
        copy=False,
        index=True,
        help="Product-specific remnant counter, for example 001, 002, 003.",
    )
    product_id = fields.Many2one(
        "product.product",
        string="Fabric Product",
        required=True,
        index=True,
        ondelete="restrict",
        help="Exact fabric/product this remnant belongs to.",
    )
    lot_id = fields.Many2one(
        "stock.lot",
        string="Source LOT Number",
        index=True,
        ondelete="restrict",
        domain="[('product_id', '=', product_id)]",
        help="Optional source roll lot for traceability. Remnants are selected by remnant code.",
    )
    fabric_color = fields.Char(
        string="Color",
        related="product_id.fabric_color",
        store=True,
        readonly=True,
    )
    category_rule_id = fields.Many2one(
        "remnant.category.rule",
        string="Category",
        required=True,
        index=True,
        ondelete="restrict",
    )
    usable_layer_count = fields.Integer(required=True, default=1)
    width_m = fields.Float(
        string="Fabric Width (m)",
        required=True,
        help="Available fabric width of the remnant.",
    )
    height_m = fields.Float(
        string="Fabric Height (m)",
        required=True,
        help="Available fabric height of the remnant.",
    )
    size_m = fields.Float(
        string="Selection Size (m)",
        compute="_compute_size_m",
        store=True,
        help="Area used for final best-fit sorting: fabric width multiplied by fabric height.",
    )
    dimension_label = fields.Char(
        string="Dimensions",
        compute="_compute_dimension_label",
        store=True,
    )
    state = fields.Selection(
        [
            ("available", "Available"),
            ("reserved", "Reserved"),
            ("consumed", "Consumed"),
            ("scrapped", "Scrapped"),
        ],
        default="available",
        required=True,
        index=True,
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    location_id = fields.Many2one(
        "stock.location",
        string="Location",
        required=True,
        domain=[("usage", "=", "internal")],
        default=lambda self: self.env.ref(
            "remnant_fetching.location_wh_remnants", raise_if_not_found=False
        ),
    )
    reserved_sale_line_id = fields.Many2one(
        "sale.order.line",
        string="Reserved For",
        readonly=True,
        copy=False,
    )

    @api.model_create_multi
    def create(self, vals_list):
        next_sequences = {}
        for vals in vals_list:
            if vals.get("product_id"):
                product = self.env["product.product"].browse(vals["product_id"])
                company_id = vals.get("company_id") or self.env.company.id
                prefix = self._get_remnant_name_prefix(product)
                sequence_key = (product.id, company_id)
                if vals.get("remnant_code", "New") == "New":
                    if sequence_key not in next_sequences:
                        next_sequences[sequence_key] = self._get_next_remnant_sequence(
                            product, company_id
                        )
                    vals["remnant_code"] = f"{next_sequences[sequence_key]:03d}"
                    next_sequences[sequence_key] += 1
                else:
                    vals["remnant_code"] = self._normalize_remnant_code(vals["remnant_code"])
                if vals.get("name", "New") == "New":
                    vals["name"] = self._format_remnant_name(
                        prefix, vals["remnant_code"]
                    )
        return super().create(vals_list)

    def _next_remnant_name(self, product):
        prefix = self._get_remnant_name_prefix(product)
        code = f"{self._get_next_remnant_sequence(product, self.env.company.id):03d}"
        return self._format_remnant_name(prefix, code)

    def _format_remnant_name(self, prefix, remnant_code):
        return f"{prefix}{remnant_code}"

    def _normalize_remnant_code(self, code):
        code = (code or "").strip()
        if code.isdigit():
            return code.zfill(3)
        return code

    def _get_remnant_name_prefix(self, product):
        code_source = product.default_code or product.display_name or "REM"
        code = code_source.split("-")[0]
        code = re.sub(r"[^A-Za-z0-9]+", "", code).upper() or "REM"
        color = re.sub(r"[^A-Za-z0-9]+", "", product.fabric_color or "").upper()
        if color:
            return f"R-{code}-{color}-"
        return f"R-{code}-"

    def _get_next_remnant_sequence(self, product, company_id):
        prefix = self._get_remnant_name_prefix(product)
        existing_remnants = self.search(
            [
                ("product_id", "=", product.id),
                ("company_id", "=", company_id),
            ]
        )
        sequence_numbers = []
        for remnant in existing_remnants:
            if remnant.remnant_code and remnant.remnant_code.isdigit():
                sequence_numbers.append(int(remnant.remnant_code))
                continue
            name = remnant.name
            match = re.match(rf"^{re.escape(prefix)}(\d+)$", name or "")
            if match:
                sequence_numbers.append(int(match.group(1)))
        return max(sequence_numbers, default=0) + 1

    @api.depends("width_m", "height_m")
    def _compute_size_m(self):
        for remnant in self:
            remnant.size_m = remnant.width_m * remnant.height_m

    @api.depends("width_m", "height_m")
    def _compute_dimension_label(self):
        for remnant in self:
            remnant.dimension_label = f"W.{remnant.width_m:.2f} * H.{remnant.height_m:.2f}"

    @api.constrains("width_m", "height_m", "usable_layer_count", "remnant_code")
    def _check_positive_values(self):
        for remnant in self:
            if remnant.width_m <= 0 or remnant.height_m <= 0:
                raise ValidationError("Remnant width and height must be greater than zero.")
            if remnant.usable_layer_count <= 0:
                raise ValidationError("Usable layer count must be greater than zero.")
            if not remnant.remnant_code or not remnant.remnant_code.isdigit():
                raise ValidationError("Remnant code must be a numeric counter, for example 001.")

    @api.constrains("product_id", "lot_id")
    def _check_lot_product(self):
        for remnant in self:
            if remnant.lot_id and remnant.lot_id.product_id != remnant.product_id:
                raise ValidationError("LOT number must belong to the same product as the remnant.")

    def action_mark_available(self):
        self.write({"state": "available", "reserved_sale_line_id": False})

    def action_mark_consumed(self):
        self.write({"state": "consumed"})
