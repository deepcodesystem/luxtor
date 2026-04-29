# -*- coding: utf-8 -*-
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

ALLOWED_UOM_NAMES = ["m²", "m", "Unit", "Set", "Pair"]


# -------------------------------------------------------------------------
# STOCK LOT: add width_cm to identify fabric rolls
# -------------------------------------------------------------------------
class StockLot(models.Model):
    _inherit = "stock.lot"

    width_cm = fields.Integer(
        string="Width (cm)",
        help="Nominal fabric width for this roll, stored in centimeters.",
    )


# -------------------------------------------------------------------------
# PURCHASE ORDER LINE: width + roll/lot management
# -------------------------------------------------------------------------
class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    width = fields.Float(
        string="Width (m)",
        digits=(10, 2),
        default=0.0,
        help="Nominal fabric width in meters used to select/create the roll lot.",
    )

    lot_id = fields.Many2one(
        "stock.lot",
        string="Roll / Lot",
        copy=False,
        domain="[('product_id', '=', product_id)]",
        help="Lot / roll that will be used for reception and stock moves.",
    )

    lot_number = fields.Char(
        string="LoT Number",
        related="lot_id.name",
        store=True,
        readonly=False,
        help="Compatibility field that exposes the lot name.",
    )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _is_tracked_by_lot(self):
        """Return True only when product is tracked by LOT (not serial/none)."""
        self.ensure_one()
        return bool(self.product_id) and self.product_id.tracking == "lot"

    # ------------------------------------------------------------------
    # UTIL — Find or create lot based on width
    # ------------------------------------------------------------------
    def _find_or_create_lot_by_width(self):
        self.ensure_one()

        if not self._is_tracked_by_lot():
            return False

        width_m = self.width or 0.0
        if width_m <= 0.0:
            _logger.info(
                "POL[%s] - Skip lot creation: width <= 0 (width=%s).",
                self.id or "new", width_m,
            )
            return False

        width_cm = int(round(width_m * 100))  # 3.00 m -> 300 cm
        lot_obj = self.env["stock.lot"]

        # 1) Try to reuse an existing lot with same product + width
        lot = lot_obj.search([
            ("product_id", "=", self.product_id.id),
            ("company_id", "=", self.order_id.company_id.id),
            ("width_cm", "=", width_cm),
        ], limit=1)

        if lot:
            _logger.info(
                "POL[%s] - Reusing Lot: %s for width %s cm.",
                self.id or "new", lot.name, width_cm
            )
            return lot

        # 2) Otherwise create a new lot
        # Format: Lot-300-Lot-001
        seq = self.env["ir.sequence"].next_by_code("purchase.lot.number") or "001"
        name = f"Lot-{width_cm}-Lot-{seq}"

        lot_vals = {
            "name": name,
            "product_id": self.product_id.id,
            "company_id": self.order_id.company_id.id,
            "width_cm": width_cm,
        }

        lot = lot_obj.create(lot_vals)

        _logger.info(
            "POL[%s] - New lot created %s (width: %s cm).",
            self.id or "new", lot.name, width_cm
        )

        return lot

    # ------------------------------------------------------------------
    # CREATE → auto assign lot (multi-create safe)
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for line in records:
            if (
                line._is_tracked_by_lot()
                and not line.lot_id
                and line.width
            ):
                lot = line._find_or_create_lot_by_width()
                if lot:
                    line.lot_id = lot
        return records

    # ------------------------------------------------------------------
    # WRITE → if width or product changes, update lot
    # ------------------------------------------------------------------
    def write(self, vals):
        res = super().write(vals)
        if "width" in vals or "product_id" in vals:
            for line in self:
                if line._is_tracked_by_lot() and line.width:
                    lot = line._find_or_create_lot_by_width()
                    if lot:
                        line.lot_id = lot
        return res

    # ------------------------------------------------------------------
    # ONCHANGE → instant lot selection/creation in the UI
    # ------------------------------------------------------------------
    @api.onchange("width", "product_id")
    def _onchange_width_or_product(self):
        for line in self:
            if line._is_tracked_by_lot() and line.width:
                lot = line._find_or_create_lot_by_width()
                if lot:
                    line.lot_id = lot

    # ------------------------------------------------------------------
    # ORIGINAL SUBTOTAL LOGIC (KEPT AS-IS) + Odoo 19 field names
    # ------------------------------------------------------------------
    @api.depends("product_qty", "price_unit", "product_uom_id", "width", "tax_ids")
    def _compute_amount(self):
        """
        Custom subtotal rule with backend debug logging & small popup notification.
        - If UoM == 'm²': (qty * width * unit_price) / 100
        - Else: qty * unit_price
        - If width = 0 or empty: treat width = 1
        """
        for line in self:
            if not line.product_id:
                line.price_tax = line.price_total = line.price_subtotal = 0.0
                continue

            uom_name = (line.product_uom_id.name or "").strip()
            qty = line.product_qty or 0.0
            price = line.price_unit or 0.0
            width = line.width if (line.width and line.width > 0) else 1.0

            # Apply formula exactly as required
            if uom_name == "m²":
                subtotal = (qty * width * price) / 100.0
            else:
                subtotal = qty * price

            # Compute taxes (aligned with the custom subtotal logic)
            # We compute taxes on a per-unit base that matches `subtotal`:
            #   base_unit = subtotal / qty  (or 0 if qty == 0)
            base_unit = (subtotal / qty) if qty else 0.0

            taxes_res = line.tax_ids.compute_all(
                base_unit,
                currency=line.order_id.currency_id,
                quantity=qty,
                product=line.product_id,
                partner=line.order_id.partner_id,
            )

            # Keep fields consistent with tax computation output
            line.price_subtotal = taxes_res["total_excluded"]
            line.price_tax = taxes_res["total_included"] - taxes_res["total_excluded"]
            line.price_total = taxes_res["total_included"]

            # -------- Debug outputs --------
            _logger.info(
                "DEBUG ➜ POLine[%s] | Product: %s | UoM: %s | Qty: %.2f | Width: %.2f | "
                "Unit: %.2f | Subtotal: %.2f | Tax: %.2f | Total: %.2f",
                line.id or "new",
                line.product_id.display_name,
                uom_name,
                qty,
                width,
                price,
                line.price_subtotal,
                line.price_tax,
                line.price_total,
            )


# -------------------------------------------------------------------------
# STOCK MOVE: propagate PO lot to incoming receipts
# -------------------------------------------------------------------------
class StockMove(models.Model):
    _inherit = "stock.move"

    def _prepare_move_line_vals(self, quantity=None, reserved_quant=None):
        vals = super()._prepare_move_line_vals(
            quantity=quantity, reserved_quant=reserved_quant
        )

        self.ensure_one()
        pol = self.purchase_line_id

        if (
            pol
            and pol.lot_id
            and self.picking_type_id.code == "incoming"
            and self.product_id.tracking != "none"
        ):
            if self.picking_type_id.use_existing_lots:
                vals["lot_id"] = pol.lot_id.id
            elif self.picking_type_id.use_create_lots:
                vals["lot_name"] = pol.lot_id.name

        return vals


# # -------------------------------------------------------------------------
# # STOCK LOT: add width_cm to identify fabric rolls
# # -------------------------------------------------------------------------
# class StockLot(models.Model):
#     _inherit = "stock.lot"

#     width_cm = fields.Integer(
#         string="Width (cm)",
#         help="Nominal fabric width for this roll, stored in centimeters.",
#     )


# # -------------------------------------------------------------------------
# # PURCHASE ORDER LINE: width + roll/lot management
# # -------------------------------------------------------------------------
# class PurchaseOrderLine(models.Model):
#     _inherit = "purchase.order.line"

#     width = fields.Float(
#         string="Width (m)",
#         digits=(10, 2),
#         default=0.0,
#         help="Nominal fabric width in meters used to select/create the roll lot.",
#     )

#     lot_id = fields.Many2one(
#         "stock.lot",
#         string="Roll / Lot",
#         copy=False,
#         domain="[('product_id', '=', product_id)]",
#         help="Lot / roll that will be used for reception and stock moves.",
#     )

#     lot_number = fields.Char(
#         string="LoT Number",
#         related="lot_id.name",
#         store=True,
#         readonly=False,
#         help="Compatibility field that exposes the lot name.",
#     )

#     # ------------------------------------------------------------------
#     # Helpers
#     # ------------------------------------------------------------------
#     def _is_tracked_by_lot(self):
#         """Return True only when product is tracked by LOT (not serial/none)."""
#         self.ensure_one()
#         return bool(self.product_id) and self.product_id.tracking == "lot"

#     # ------------------------------------------------------------------
#     # UTIL — Find or create lot based on width
#     # ------------------------------------------------------------------
#     def _find_or_create_lot_by_width(self):
#         self.ensure_one()

#         if not self._is_tracked_by_lot():
#             return False

#         width_m = self.width or 0.0
#         if width_m <= 0.0:
#             _logger.info(
#                 "POL[%s] - Skip lot creation: width <= 0 (width=%s).",
#                 self.id or "new", width_m,
#             )
#             return False

#         width_cm = int(round(width_m * 100))  # 3.00 m -> 300 cm
#         lot_obj = self.env["stock.lot"]

#         # 1) Try to reuse an existing lot with same product + width
#         lot = lot_obj.search([
#             ("product_id", "=", self.product_id.id),
#             ("company_id", "=", self.order_id.company_id.id),
#             ("width_cm", "=", width_cm),
#         ], limit=1)

#         if lot:
#             _logger.info(
#                 "POL[%s] - Reusing Lot: %s for width %s cm.",
#                 self.id or "new", lot.name, width_cm
#             )
#             return lot

#         # 2) Otherwise create a new lot
#         #    Format: Lot-300-0001 (width in cm + sequence)
#         seq = self.env["ir.sequence"].next_by_code("purchase.lot.number") or "0001"
#         name = f"Lot-{width_cm}-{seq}"

#         lot_vals = {
#             "name": name,
#             "product_id": self.product_id.id,
#             "company_id": self.order_id.company_id.id,
#             "width_cm": width_cm,
#         }
#         lot = lot_obj.create(lot_vals)
#         _logger.info(
#             "POL[%s] - New lot created %s (width: %s cm).",
#             self.id or "new", lot.name, width_cm
#         )
#         return lot

#     # ------------------------------------------------------------------
#     # CREATE → auto assign lot (multi-create safe)
#     # ------------------------------------------------------------------
#     @api.model_create_multi
#     def create(self, vals_list):
#         records = super().create(vals_list)
#         for line in records:
#             if (
#                 line._is_tracked_by_lot()
#                 and not line.lot_id
#                 and line.width
#             ):
#                 lot = line._find_or_create_lot_by_width()
#                 if lot:
#                     line.lot_id = lot
#         return records

#     # ------------------------------------------------------------------
#     # WRITE → if width or product changes, update lot
#     # ------------------------------------------------------------------
#     def write(self, vals):
#         res = super().write(vals)
#         if "width" in vals or "product_id" in vals:
#             for line in self:
#                 if line._is_tracked_by_lot() and line.width:
#                     lot = line._find_or_create_lot_by_width()
#                     if lot:
#                         line.lot_id = lot
#         return res

#     # ------------------------------------------------------------------
#     # ONCHANGE → instant lot selection/creation in the UI
#     # ------------------------------------------------------------------
#     @api.onchange("width", "product_id")
#     def _onchange_width_or_product(self):
#         for line in self:
#             if line._is_tracked_by_lot() and line.width:
#                 lot = line._find_or_create_lot_by_width()
#                 if lot:
#                     line.lot_id = lot

#     # ------------------------------------------------------------------
#     # ORIGINAL SUBTOTAL LOGIC (KEPT AS-IS)
#     # ------------------------------------------------------------------
#     @api.depends("product_qty", "price_unit", "product_uom_id", "width", "taxes_id")
#     def _compute_amount(self):
#         """
#         Custom subtotal rule with backend debug logging & small popup notification.
#         - If UoM == 'm²': (qty * width * unit_price) / 100
#         - Else: qty * unit_price
#         - If width = 0 or empty: treat width = 1
#         """
#         for line in self:
#             if not line.product_id:
#                 line.price_tax = line.price_total = line.price_subtotal = 0.0
#                 continue

#             uom_name = (line.product_uom_id.name or "").strip()
#             qty = line.product_qty or 0.0
#             price = line.price_unit or 0.0
#             width = line.width if (line.width and line.width > 0) else 1.0

#             # Apply formula exactly as required
#             if uom_name == "m²":
#                 subtotal = (qty * width * price) / 100.0
#             else:
#                 subtotal = qty * price

#             # Compute taxes
#             taxes_res = line.taxes_id.compute_all(
#                 price,
#                 currency=line.order_id.currency_id,
#                 quantity=qty,
#                 product=line.product_id,
#                 partner=line.order_id.partner_id,
#             )

#             line.price_subtotal = subtotal
#             tax_amount = taxes_res["total_included"] - taxes_res["total_excluded"]
#             line.price_tax = (
#                 (tax_amount / taxes_res["total_excluded"] * subtotal)
#                 if taxes_res["total_excluded"]
#                 else 0.0
#             )
#             line.price_total = line.price_subtotal + line.price_tax

#             # -------- Debug outputs --------
#             _logger.info(
#                 "DEBUG ➜ POLine[%s] | Product: %s | UoM: %s | Qty: %.2f | Width: %.2f | "
#                 "Unit: %.2f | Subtotal: %.2f | Tax: %.2f | Total: %.2f",
#                 line.id or "new",
#                 line.product_id.display_name,
#                 uom_name,
#                 qty,
#                 width,
#                 price,
#                 line.price_subtotal,
#                 line.price_tax,
#                 line.price_total,
#             )


# # -------------------------------------------------------------------------
# # STOCK MOVE: propagate PO lot to incoming receipts
# # -------------------------------------------------------------------------
# class StockMove(models.Model):
#     _inherit = "stock.move"

#     def _prepare_move_line_vals(self, quantity=None, reserved_quant=None):
#         vals = super()._prepare_move_line_vals(
#             quantity=quantity, reserved_quant=reserved_quant
#         )

#         self.ensure_one()
#         pol = self.purchase_line_id

#         if (
#             pol
#             and pol.lot_id
#             and self.picking_type_id.code == "incoming"
#             and self.product_id.tracking != "none"
#         ):
#             if self.picking_type_id.use_existing_lots:
#                 vals["lot_id"] = pol.lot_id.id
#             elif self.picking_type_id.use_create_lots:
#                 vals["lot_name"] = pol.lot_id.name

#         return vals



