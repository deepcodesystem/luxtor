from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..picking_logic import (
    PickingInput,
    RemnantInput,
    best_fit_for_remnant,
)


class RemnantFetchRequest(models.Model):
    _name = "remnant.fetch.request"
    _description = "Remnant Picking Request"
    _order = "create_date desc, id desc"

    name = fields.Char(default="New", readonly=True, copy=False)
    category_rule_id = fields.Many2one(
        "remnant.category.rule",
        string="Category",
        required=True,
        ondelete="restrict",
    )
    product_id = fields.Many2one(
        "product.product",
        string="Ordered Fabric Product",
        required=True,
        index=True,
        ondelete="restrict",
        help="Only remnants for this exact product are eligible.",
    )
    required_length_m = fields.Float(
        string="Fallback Length (m)",
        help="Legacy fallback used only when width or height is not provided.",
    )
    required_width_m = fields.Float(
        string="Order Width (m)",
        required=True,
        help="Roller blind width in meters.",
    )
    required_height_m = fields.Float(
        string="Order Height (m)",
        required=True,
        help="Roller blind height in meters.",
    )
    tolerance = fields.Float(
        default=1.5,
        required=True,
        help="Maximum acceptable oversize multiplier. Example: 1.5 means 150%.",
    )
    required_layer_count = fields.Integer(required=True, default=1)
    orientation = fields.Selection(
        [
            ("widthwise", "Widthwise"),
            ("heightwise", "Heightwise"),
        ],
        required=True,
        default="widthwise",
    )
    max_remnant_size_m = fields.Float(
        string="Fallback Max Length (m)",
        compute="_compute_max_remnant_size",
        store=True,
    )
    best_remnant_id = fields.Many2one(
        "remnant.stock",
        string="Picked Remnant",
        compute="_compute_best_remnant",
        store=True,
    )
    best_remnant_size_m = fields.Float(
        related="best_remnant_id.size_m",
        string="Picked Remnant Area",
        store=True,
    )
    selected_orientation = fields.Selection(
        [
            ("widthwise", "Widthwise"),
            ("heightwise", "Heightwise"),
        ],
        string="Valid By",
        compute="_compute_confirmations",
        store=True,
    )
    selected_required_length_m = fields.Float(
        string="Selected Fallback Length (m)",
        compute="_compute_confirmations",
        store=True,
    )
    selected_required_width_m = fields.Float(
        string="Fabric Width Minimum",
        compute="_compute_confirmations",
        store=True,
    )
    selected_max_width_m = fields.Float(
        string="Fabric Width Maximum",
        compute="_compute_confirmations",
        store=True,
    )
    selected_required_height_m = fields.Float(
        string="Fabric Height Minimum",
        compute="_compute_confirmations",
        store=True,
    )
    selected_max_height_m = fields.Float(
        string="Fabric Height Maximum",
        compute="_compute_confirmations",
        store=True,
    )
    selected_fabric_width_m = fields.Float(
        string="Picked Fabric Width",
        compute="_compute_confirmations",
        store=True,
    )
    selected_fabric_height_m = fields.Float(
        string="Picked Fabric Height",
        compute="_compute_confirmations",
        store=True,
    )
    selected_fit_area_m = fields.Float(
        string="Picked Area",
        compute="_compute_confirmations",
        store=True,
    )
    meets_orientation = fields.Boolean(
        string="Meets Orientation",
        compute="_compute_confirmations",
        store=True,
    )
    meets_layer_requirement = fields.Boolean(
        string="Meets Layer Requirement",
        compute="_compute_confirmations",
        store=True,
    )
    meets_tolerance = fields.Boolean(
        string="Meets Dimension Rules",
        compute="_compute_confirmations",
        store=True,
    )
    result_note = fields.Char(compute="_compute_confirmations", store=True)
    sale_line_id = fields.Many2one("sale.order.line", readonly=True, copy=False)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env["ir.sequence"].sudo()
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = sequence.next_by_code("remnant.fetch.request") or "New"
        return super().create(vals_list)

    @api.constrains(
        "required_length_m",
        "required_width_m",
        "required_height_m",
        "tolerance",
        "required_layer_count",
    )
    def _check_positive_values(self):
        for request in self:
            if request.required_width_m <= 0 or request.required_height_m <= 0:
                raise ValidationError("Order width and height must be greater than zero.")
            if request.required_length_m < 0:
                raise ValidationError("Fallback length cannot be negative.")
            if request.tolerance < 1:
                raise ValidationError("Tolerance must be at least 1.0.")
            if request.required_layer_count <= 0:
                raise ValidationError("Required layer count must be greater than zero.")

    @api.depends("required_length_m", "tolerance")
    def _compute_max_remnant_size(self):
        for request in self:
            request.max_remnant_size_m = request.required_length_m * request.tolerance

    @api.depends(
        "category_rule_id",
        "product_id",
        "required_length_m",
        "required_width_m",
        "required_height_m",
        "tolerance",
        "required_layer_count",
        "orientation",
        "company_id",
    )
    def _compute_best_remnant(self):
        for request in self:
            request.best_remnant_id = request._find_best_remnant()

    @api.depends(
        "best_remnant_id",
        "best_remnant_id.usable_layer_count",
        "best_remnant_id.width_m",
        "best_remnant_id.height_m",
        "best_remnant_id.size_m",
        "required_length_m",
        "required_width_m",
        "required_height_m",
        "tolerance",
        "max_remnant_size_m",
        "required_layer_count",
        "orientation",
        "category_rule_id.orientation",
    )
    def _compute_confirmations(self):
        for request in self:
            remnant = request.best_remnant_id
            selected_fit = request._get_best_fit_for_remnant(remnant) if remnant else False
            selected_orientation = selected_fit["orientation"] if selected_fit else False
            selected_required_length = request._get_required_length_for_orientation(
                selected_orientation
            ) if selected_orientation else 0.0
            selected_width = selected_fit["min_width"] if selected_fit else 0.0
            selected_max_width = selected_fit["max_width"] if selected_fit else 0.0
            selected_height = selected_fit["min_height"] if selected_fit else 0.0
            selected_max_height = selected_fit["max_height"] if selected_fit else 0.0

            request.selected_orientation = selected_orientation
            request.selected_required_length_m = selected_required_length
            request.selected_required_width_m = selected_width
            request.selected_max_width_m = selected_max_width
            request.selected_required_height_m = selected_height
            request.selected_max_height_m = selected_max_height
            request.selected_fabric_width_m = selected_fit["fabric_width"] if selected_fit else 0.0
            request.selected_fabric_height_m = selected_fit["fabric_height"] if selected_fit else 0.0
            request.selected_fit_area_m = selected_fit["area"] if selected_fit else 0.0
            request.meets_orientation = bool(selected_orientation)
            request.meets_layer_requirement = bool(
                remnant and remnant.usable_layer_count >= request.required_layer_count
            )
            request.meets_tolerance = bool(selected_fit)
            request.result_note = request._get_result_note(selected_fit)

    def _find_best_remnant(self):
        self.ensure_one()
        if not self.category_rule_id or not self.product_id:
            return self.env["remnant.stock"]
        if not self._get_order_width() or not self._get_order_height():
            return self.env["remnant.stock"]

        domain = [
            ("state", "=", "available"),
            ("company_id", "=", self.company_id.id),
            ("product_id", "=", self.product_id.id),
            ("category_rule_id", "=", self.category_rule_id.id),
            ("usable_layer_count", ">=", self.required_layer_count),
        ]
        best_remnant = self.env["remnant.stock"]
        best_key = False
        for remnant in self.env["remnant.stock"].search(domain):
            fit = self._get_best_fit_for_remnant(remnant)
            if not fit:
                continue
            key = (fit["area"], remnant.id)
            if best_key is False or key < best_key:
                best_key = key
                best_remnant = remnant
        return best_remnant

    def _get_required_length_for_orientation(self, orientation):
        self.ensure_one()
        if orientation == "widthwise":
            return self._get_order_width()
        if orientation == "heightwise":
            return self._get_order_height()
        return self._get_order_width()

    def _get_best_fit_for_remnant(self, remnant):
        self.ensure_one()
        result = best_fit_for_remnant(
            self._to_picking_input(), self._remnant_to_picking_input(remnant)
        )
        return self._fit_result_to_dict(result) if result else False

    def _get_result_note(self, selected_fit):
        if not selected_fit:
            return "No eligible remnant; use full roll or review stock"
        return (
            "Remnant picked by %(orientation)s: "
            "W.%(fabric_width).2f * H.%(fabric_height).2f"
        ) % selected_fit

    def _get_order_width(self):
        self.ensure_one()
        return self.required_width_m or self.required_length_m

    def _get_order_height(self):
        self.ensure_one()
        return self.required_height_m or self.required_length_m

    def _to_picking_input(self):
        self.ensure_one()
        return PickingInput(
            order_width=self._get_order_width(),
            order_height=self._get_order_height(),
            tolerance=self.tolerance,
            layer_count=self.required_layer_count,
            rule_orientation=self.category_rule_id.orientation,
            requested_orientation=self.orientation,
        )

    def _remnant_to_picking_input(self, remnant):
        return RemnantInput(
            remnant_id=remnant.name,
            fabric_width=remnant.width_m,
            fabric_height=remnant.height_m,
            sequence=remnant.id,
        )

    def _fit_result_to_dict(self, result):
        return {
            "orientation": result.calculation,
            "fabric_width": result.effective_width,
            "fabric_height": result.effective_height,
            "min_width": result.min_width,
            "max_width": result.max_width,
            "min_height": result.min_height,
            "max_height": result.max_height,
            "width_ok": result.width_ok,
            "height_ok": result.height_ok,
            "valid": result.valid,
            "area": result.area,
        }

    def action_reserve_best_remnant(self):
        for request in self:
            if not request.best_remnant_id:
                raise UserError("No eligible remnant is available for this request.")
            if request.best_remnant_id.state != "available":
                raise UserError("The picked remnant is no longer available.")
            request.best_remnant_id.write(
                {
                    "state": "reserved",
                    "reserved_sale_line_id": request.sale_line_id.id or False,
                }
            )
