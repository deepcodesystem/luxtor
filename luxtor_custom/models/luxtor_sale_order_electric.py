# -*- coding: utf-8 -*-
"""
LX Electric Roller Blind — Accessory Sync Engine  (v2 — Location-based)
========================================================================
Replace models/lx_electric_blinds.py with this file entirely.

NEW FIELD ON sale_order_line  (add to your module's _columns or run SQL once)
------------------------------------------------------------------------------
    lx_location_id = fields.Many2one("luxtor.installation.space", ...)

SQL to add it without a migration file:

    ALTER TABLE sale_order_line
      ADD COLUMN IF NOT EXISTS lx_location_id INTEGER
        REFERENCES luxtor_installation_space(id) ON DELETE SET NULL;
    CREATE INDEX IF NOT EXISTS sol_lx_location_id_idx
      ON sale_order_line(lx_location_id);

All other fields (lx_parent_line_id, lx_base_price_unit,
lx_section_control_type, lx_is_electric_subtotal,
lx_electric_subtotal_amount) are unchanged from v1 and already exist.

EXCEL-MATCHED STYLING
----------------------
Row type                     bold   italic  color
--------------------------   ----   ------  -------
Section header (Location :)  True   True    #45818E  (teal)
Line numbers (1, 1.1 …)      False  True    #434343  (dark gray)
Subtotal note lines          False  True    #BF9000  (amber/gold)
Normal product rows          False  False   #434343

Implemented via decoration-* in the list view XML + a small CSS asset.
See sale_order_views.xml for details.
"""
import logging
import math

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


# =====================================================================
# PRODUCT TEMPLATE
# =====================================================================

class ProductTemplate(models.Model):
    _inherit = "product.template"

    lx_is_tubular_motor    = fields.Boolean("Is Tubular Motor",     default=False)
    lx_is_remote_control   = fields.Boolean("Is Remote Control",    default=False)
    lx_is_zigbee_gateway   = fields.Boolean("Is ZigBee Gateway",    default=False)
    lx_is_electric_charger = fields.Boolean("Is Electric Charger",  default=False)
    lx_is_solar_charger    = fields.Boolean("Is Solar Charger",     default=False)
    lx_is_idler            = fields.Boolean("Is Idler",             default=False)

    def lx_is_electric_accessory(self):
        self.ensure_one()
        return bool(
            self.lx_is_tubular_motor
            or self.lx_is_remote_control
            or self.lx_is_zigbee_gateway
            or self.lx_is_electric_charger
            or self.lx_is_solar_charger
        )


# =====================================================================
# PRODUCT PRODUCT
# =====================================================================

class ProductProduct(models.Model):
    _inherit = "product.product"

    lx_idler_variant_id = fields.Many2one(
        "product.product",
        string="Idler Variant",
        domain="[('product_tmpl_id.lx_is_idler', '=', True)]",
        help="Idler to include in the MO when this tubular motor variant is selected "
             "on a Motor Only sale order line.",
        index=True,
    )

    def _lx_get_attribute_value_name(self, attribute_name):
        self.ensure_one()
        attr = (attribute_name or "").strip()
        for ptav in self.product_template_attribute_value_ids:
            if ptav.attribute_id and (ptav.attribute_id.name or "").strip() == attr:
                return (ptav.product_attribute_value_id.name or "").strip()
        return ""

    def _lx_get_control_type_value(self):
        return self._lx_get_attribute_value_name("Control Type")

    def _lx_get_code_value(self):
        return self._lx_get_attribute_value_name("Code")

    def lx_is_electric_variant(self):
        self.ensure_one()
        return self._lx_get_control_type_value() in {
            "Motorized, Remote Controlled",
            "Motorized, Smartphone Controlled",
            "Motor Only",
        }

    def lx_is_motor_only_variant(self):
        self.ensure_one()
        return self._lx_get_control_type_value() == "Motor Only"

    def lx_is_smartphone_controlled_variant(self):
        self.ensure_one()
        return self._lx_get_control_type_value() == "Motorized, Smartphone Controlled"

    def lx_is_remote_controlled_variant(self):
        self.ensure_one()
        return self._lx_get_control_type_value() == "Motorized, Remote Controlled"


# =====================================================================
# CONFIGURATOR PENDING PAYLOAD
# =====================================================================

class LxConfiguratorPending(models.Model):
    _name = "lx.configurator.pending"
    _description = "Pending backend configurator payload"
    _order = "id desc"

    order_id = fields.Many2one("sale.order", required=True, index=True, ondelete="cascade")
    user_id = fields.Many2one("res.users", required=True, index=True, default=lambda self: self.env.user)
    product_tmpl_id = fields.Many2one("product.template", required=True, index=True, ondelete="cascade")
    lx_location_id = fields.Many2one("luxtor.installation.space", ondelete="set null")
    lx_motor_only_variant_id = fields.Many2one("product.product", ondelete="set null")
    lx_width_m = fields.Float(digits="Product Price", default=0.0)
    lx_height_m = fields.Float(digits="Product Price", default=0.0)
    price_unit = fields.Float(digits="Product Price", default=0.0)


# =====================================================================
# SALE ORDER LINE
# =====================================================================

class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    lx_location_id = fields.Many2one(
        "luxtor.installation.space",
        string="Location",
        index=True,
        ondelete="set null",
        help="Room / installation space. Electric blind lines are grouped "
             "and subtotalled per location.",
    )

    lx_motor_only_variant_id = fields.Many2one(
        "product.product",
        string="Motor Only Variant",
        index=True,
        ondelete="set null",
        help="Tubular motor variant selected in the configurator when "
             "Control Type = Motor Only. Used by the sync engine to create "
             "the correct motor child line.",
    )

    lx_parent_line_id = fields.Many2one(
        "sale.order.line",
        string="Parent Blind Line",
        index=True,
        ondelete="cascade",
    )

    lx_base_price_unit = fields.Float(
        string="Base Unit Price (pre-markdown)",
        digits="Product Price",
        default=0.0,
    )

    lx_section_control_type = fields.Char(
        "Electric Section Control Type",
        copy=False,
        index=True,
        help="Value '__location__' marks auto-generated location section headers.",
    )

    lx_is_electric_subtotal = fields.Boolean(
        "Is Electric Subtotal Line",
        default=False,
        copy=False,
    )

    lx_electric_subtotal_amount = fields.Float(
        "Section Subtotal",
        digits="Product Price",
        default=0.0,
        copy=False,
        store=True,
    )

    # ------------------------------------------------------------------
    # ORM hooks
    # ------------------------------------------------------------------

    @api.model
    def _lx_default_location(self):
        """Return (or create) the 'Other' installation space used as default."""
        Space = self.env["luxtor.installation.space"]
        space = Space.search([("name", "=", "Other")], limit=1)
        if not space:
            space = Space.create({"name": "Other"})
        return space

    @api.model
    def _lx_apply_pending_configurator_payload(self, vals):
        order_id = vals.get("order_id")
        pid = vals.get("product_id")
        if not order_id or not pid:
            return False

        product = self.env["product.product"].browse(pid)
        tmpl = product.product_tmpl_id
        if not tmpl:
            return False

        Pending = self.env["lx.configurator.pending"].sudo()
        pending = Pending.search([
            ("order_id", "=", order_id),
            ("user_id", "=", self.env.user.id),
            ("product_tmpl_id", "=", tmpl.id),
        ], order="id desc", limit=1)
        if not pending:
            return False

        _logger.warning(
            "[LX-PC] create matched pending payload | order_id=%s product_tmpl_id=%s pending_id=%s "
            "location_id=%s motor_id=%s width=%s height=%s price_unit=%s",
            order_id,
            tmpl.id,
            pending.id,
            pending.lx_location_id.id or False,
            pending.lx_motor_only_variant_id.id or False,
            pending.lx_width_m,
            pending.lx_height_m,
            pending.price_unit,
        )
        if not vals.get("lx_location_id") and pending.lx_location_id:
            vals["lx_location_id"] = pending.lx_location_id.id
        if not vals.get("lx_motor_only_variant_id") and pending.lx_motor_only_variant_id:
            vals["lx_motor_only_variant_id"] = pending.lx_motor_only_variant_id.id
        if not vals.get("lx_width_m") and pending.lx_width_m:
            vals["lx_width_m"] = pending.lx_width_m
        if not vals.get("lx_height_m") and pending.lx_height_m:
            vals["lx_height_m"] = pending.lx_height_m
        if not vals.get("price_unit") and pending.price_unit:
            vals["price_unit"] = pending.price_unit
        pending.unlink()
        return True

    @api.model_create_multi
    def create(self, vals_list):
        # Auto-set location to 'Other' for dimension products when none given.
        # Cache the default location id to avoid repeated DB hits per batch.
        if not self.env.context.get("lx_syncing_accessories"):
            default_loc_id = None
            for vals in vals_list:
                self._lx_apply_pending_configurator_payload(vals)
                if vals.get("lx_location_id"):
                    _logger.warning(
                        "[LX-PC] SOL create incoming location preserved | "
                        "product_id=%s location_id=%s motor_id=%s width=%s height=%s",
                        vals.get("product_id"),
                        vals.get("lx_location_id"),
                        vals.get("lx_motor_only_variant_id"),
                        vals.get("lx_width_m"),
                        vals.get("lx_height_m"),
                    )
                    continue
                pid = vals.get("product_id")
                if not pid:
                    continue
                tmpl = self.env["product.product"].browse(pid).product_tmpl_id
                is_dim = bool(
                    getattr(tmpl, "lx_fabric_ref_id", False)
                    or getattr(tmpl, "is_dimension_product", False)
                )
                if is_dim:
                    if default_loc_id is None:
                        default_loc_id = self._lx_default_location().id
                    _logger.warning(
                        "[LX-PC] SOL create defaulting location to Other | "
                        "product_id=%s width=%s height=%s motor_id=%s other_id=%s vals=%s",
                        pid,
                        vals.get("lx_width_m"),
                        vals.get("lx_height_m"),
                        vals.get("lx_motor_only_variant_id"),
                        default_loc_id,
                        vals,
                    )
                    vals["lx_location_id"] = default_loc_id

        lines = super().create(vals_list)
        real_lines = lines.filtered(lambda l: isinstance(l.id, int))
        for line in real_lines.filtered(
            lambda l: (
                l.product_template_id
                and (
                    getattr(l.product_template_id, "lx_fabric_ref_id", False)
                    or getattr(l.product_template_id, "is_dimension_product", False)
                )
            )
        ):
            _logger.warning(
                "[LX-PC] SOL created | line_id=%s order_id=%s product_id=%s "
                "location_id=%s location_name=%s motor_id=%s width=%s height=%s price_unit=%s",
                line.id,
                line.order_id.id,
                line.product_id.id,
                line.lx_location_id.id or False,
                line.lx_location_id.name or False,
                line.lx_motor_only_variant_id.id or False,
                line.lx_width_m,
                line.lx_height_m,
                line.price_unit,
            )
        for line in real_lines:
            line._lx_apply_vendor_markdown_if_needed()
        motor_only_lines = real_lines.filtered(
            lambda l: (
                l.lx_motor_only_variant_id
                and l.product_id
                and hasattr(l.product_id, "lx_is_motor_only_variant")
                and l.product_id.lx_is_motor_only_variant()
            )
        )
        if motor_only_lines:
            motor_only_lines._lx_recalc_motor_only_price()
        if real_lines and not self.env.context.get("lx_syncing_accessories"):
            for order in real_lines.mapped("order_id"):
                order._lx_sync_electric_accessories()
        return lines

    @api.model
    def lx_apply_configurator_values(
        self,
        order_id,
        product_id=False,
        lx_width_m=False,
        lx_height_m=False,
        lx_location_id=False,
        lx_motor_only_variant_id=False,
        price_unit=False,
    ):
        """Apply configurator values to the newest matching parent line.

        The backend configurator can create the sale order line first and only
        then flush custom Luxtor fields. This helper lets the client update the
        actual persisted line without relying on the transient x2many record id.
        """
        try:
            order_id = int(order_id or 0)
        except (TypeError, ValueError):
            return False
        if not order_id:
            return False

        def _f(value):
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0

        width = _f(lx_width_m)
        height = _f(lx_height_m)
        wanted_product_id = int(product_id or 0) if product_id else 0
        _logger.warning(
            "[LX-PC] helper request | order_id=%s product_id=%s location_id=%s "
            "motor_id=%s width=%s height=%s price_unit=%s",
            order_id,
            wanted_product_id,
            lx_location_id,
            lx_motor_only_variant_id,
            width,
            height,
            price_unit,
        )

        domain = [
            ("order_id", "=", order_id),
            ("display_type", "=", False),
            ("lx_parent_line_id", "=", False),
        ]
        candidates = self.search(domain, order="id desc", limit=25)
        if not candidates:
            _logger.warning("[LX-PC] helper request found no candidates for order_id=%s", order_id)
            return False

        def _score(line):
            score = 0
            if wanted_product_id and line.product_id.id == wanted_product_id:
                score += 100
            if width > 0 and abs(float(line.lx_width_m or 0.0) - width) < 1e-6:
                score += 20
            if height > 0 and abs(float(line.lx_height_m or 0.0) - height) < 1e-6:
                score += 20
            if (
                line.product_template_id
                and (
                    getattr(line.product_template_id, "lx_fabric_ref_id", False)
                    or getattr(line.product_template_id, "is_dimension_product", False)
                )
            ):
                score += 10
            return score

        line = max(candidates, key=_score)
        if not line:
            return False
        _logger.warning(
            "[LX-PC] helper picked line | line_id=%s product_id=%s location_id=%s "
            "location_name=%s motor_id=%s width=%s height=%s",
            line.id,
            line.product_id.id,
            line.lx_location_id.id or False,
            line.lx_location_id.name or False,
            line.lx_motor_only_variant_id.id or False,
            line.lx_width_m,
            line.lx_height_m,
        )

        vals = {}
        if width > 0:
            vals["lx_width_m"] = width
        if height > 0:
            vals["lx_height_m"] = height
        if lx_location_id:
            vals["lx_location_id"] = int(lx_location_id)
        if lx_motor_only_variant_id:
            vals["lx_motor_only_variant_id"] = int(lx_motor_only_variant_id)
        if price_unit:
            vals["price_unit"] = _f(price_unit)

        if vals:
            _logger.warning("[LX-PC] helper write vals | line_id=%s vals=%s", line.id, vals)
            line.write(vals)
            line.invalidate_recordset([
                "lx_location_id",
                "lx_motor_only_variant_id",
                "lx_width_m",
                "lx_height_m",
                "price_unit",
            ])
            _logger.warning(
                "[LX-PC] helper write result | line_id=%s location_id=%s location_name=%s "
                "motor_id=%s width=%s height=%s price_unit=%s",
                line.id,
                line.lx_location_id.id or False,
                line.lx_location_id.name or False,
                line.lx_motor_only_variant_id.id or False,
                line.lx_width_m,
                line.lx_height_m,
                line.price_unit,
            )
        return line.id

    def _lx_compute_motor_only_price(self):
        """
        Return the computed price_unit for this Motor Only SOL (single record).
        Always uses W=1 so that _compute_amount (which multiplies by size=W×H)
        produces the correct subtotal — same convention as
        _lx_compute_price_unit_like_wizard.
        Returns 0.0 when the price cannot be determined.
        """
        self.ensure_one()
        motor_var = self.lx_motor_only_variant_id
        if not motor_var or not motor_var.exists():
            return 0.0
        variant = self.product_id
        if not variant:
            return 0.0
        bom = self._lx_find_bom_local(variant)
        if not bom:
            return 0.0
        try:
            idler_id = (
                motor_var.lx_idler_variant_id.id
                if motor_var.lx_idler_variant_id
                else None
            )
            mo = self.env['mrp.production'].new({
                'company_id': (
                    self.order_id.company_id.id
                    if self.order_id
                    else self.env.company.id
                ),
                'product_id': variant.id,
                'bom_id':     bom.id,
                'lx_width_m': 1.0,
            })
            _cost, amount = mo._lx_virtual_calculate(
                width_m=1.0,
                idler_variant_id=idler_id,
                skip_tubular_motor=True,
            )
            if amount <= 0:
                return 0.0
            partner = self.order_id.partner_id
            factor = 1.0
            if partner and getattr(partner, 'lx_account_type_id', False):
                try:
                    factor = float(partner.lx_account_type_id.rank or 100.0) / 100.0
                except Exception:
                    factor = 1.0
            return round(amount * factor, 2)
        except Exception:
            _logger.exception(
                "[Luxtor] _lx_compute_motor_only_price failed for line %s", self.id
            )
            return 0.0

    def _lx_recalc_motor_only_price(self):
        """Write the computed Motor Only price_unit to all lines in self.

        Guard : si la ligne a déjà un prix configuré par le site web
        (lx_final_unit_price > 0, posé par le configurateur/cart), on ne
        touche PAS au price_unit — le prix 569.00 DH doit être préservé.
        Seules les lignes sans prix configuré (backend SO) sont recalculées.
        """
        for line in self:
            # Preserve website-configured price (e.g. 569.00 DH from the
            # dimension configurator).  Only reprice backend-created lines.
            if line.lx_final_unit_price and line.lx_final_unit_price > 0:
                continue
            new_price = line._lx_compute_motor_only_price()
            if new_price > 0:
                line.with_context(lx_syncing_accessories=True).write(
                    {'price_unit': new_price}
                )

    @api.onchange('lx_motor_only_variant_id')
    def _onchange_lx_motor_only_variant_id(self):
        """Immediately update price_unit in the UI when the motor variant changes."""
        for line in self:
            if not line.lx_motor_only_variant_id:
                continue
            new_price = line._lx_compute_motor_only_price()
            if new_price > 0:
                line.price_unit = new_price

    def write(self, vals):
        if any(k in vals for k in {"lx_location_id", "lx_motor_only_variant_id", "lx_width_m", "lx_height_m", "price_unit"}):
            _logger.warning(
                "[LX-PC] SOL write request | line_ids=%s vals=%s context_sync=%s",
                self.ids,
                vals,
                bool(self.env.context.get("lx_syncing_accessories")),
            )
        # Fix: lx_motor_only_variant_id is written by the OWL configurator AFTER
        # the initial create(). The ORM cache may still hold False from the create
        # read, so we must invalidate it and run the sync with a clean context
        # (stripping lx_syncing_accessories in case the caller set it) so the sync
        # engine reads the real database value and creates the motor child line.
        if "lx_motor_only_variant_id" in vals:
            res = super().write(vals)
            real_lines = self.filtered(lambda l: isinstance(l.id, int))
            if real_lines:
                real_lines.invalidate_recordset(["lx_motor_only_variant_id"])
                real_lines._lx_recalc_motor_only_price()
                clean_ctx = {
                    k: v for k, v in self.env.context.items()
                    if k != "lx_syncing_accessories"
                }
                for order in real_lines.mapped("order_id"):
                    order.with_context(clean_ctx)._lx_sync_electric_accessories()
            return res

        if "product_id" in vals and not self.env.context.get("lx_syncing_accessories"):
            super(SaleOrderLine, self).write({"lx_base_price_unit": 0.0})
        res = super().write(vals)
        if not self.env.context.get("lx_syncing_accessories"):
            # Guard: skip virtual records (id is a string like "virtual_102")
            real_lines = self.filtered(lambda l: isinstance(l.id, int))
            for line in real_lines:
                line._lx_apply_vendor_markdown_if_needed()
            # Re-sync when any relevant field changes, including motor variant
            sync_keys = {
                'product_id', 'product_uom_qty',
                'lx_location_id', 'lx_width_m', 'lx_height_m',
                'lx_motor_only_variant_id',
            }
            if any(k in vals for k in sync_keys):
                for order in real_lines.mapped("order_id"):
                    order._lx_sync_electric_accessories()
            else:
                for order in real_lines.mapped("order_id"):
                    order._lx_sync_electric_accessories()
        if any(k in vals for k in {"lx_location_id", "lx_motor_only_variant_id", "lx_width_m", "lx_height_m", "price_unit"}):
            for line in self.filtered(lambda l: isinstance(l.id, int)):
                _logger.warning(
                    "[LX-PC] SOL write result | line_id=%s location_id=%s location_name=%s "
                    "motor_id=%s width=%s height=%s price_unit=%s",
                    line.id,
                    line.lx_location_id.id or False,
                    line.lx_location_id.name or False,
                    line.lx_motor_only_variant_id.id or False,
                    line.lx_width_m,
                    line.lx_height_m,
                    line.price_unit,
                )
        return res

    def unlink(self):
        # Guard: skip virtual records (id is a string like "virtual_102")
        if not all(isinstance(l.id, int) for l in self):
            real = self.filtered(lambda l: isinstance(l.id, int))
            if real:
                return real.unlink()
            return True

        orders = self.mapped("order_id")
        blind_lines = self.filtered(
            lambda l: not l.display_type
            and l.product_id
            and l.product_id.lx_is_electric_variant()
        )
        if blind_lines:
            children = self.env["sale.order.line"].search([
                ("lx_parent_line_id", "in", blind_lines.ids),
                ("display_type", "=", False),
            ])
            if children:
                children.with_context(lx_syncing_accessories=True).unlink()
        res = super().unlink()
        if not self.env.context.get("lx_syncing_accessories"):
            for order in orders:
                if order.exists():
                    order._lx_sync_electric_accessories()
        return res

    # ------------------------------------------------------------------
    # Vendor markdown
    # ------------------------------------------------------------------

    def _lx_apply_vendor_markdown_if_needed(self):
        self.ensure_one()
        if self.display_type:
            return
        if not self.product_id:
            return
        tmpl = self.product_id.product_tmpl_id
        if not tmpl.lx_is_electric_accessory():
            return
        partner = self.order_id.partner_id
        if not partner:
            return
        markdown = partner.lx_vendor_markdown or 0.0
        if markdown <= 0.0:
            return
        if self.lx_base_price_unit:
            return
        base_price = self.price_unit
        if not base_price:
            return
        final_price = base_price * (1.0 - markdown / 100.0)
        self.with_context(lx_syncing_accessories=True).write({
            "lx_base_price_unit": base_price,
            "price_unit":         final_price,
        })


# =====================================================================
# SALE ORDER  — sync engine (v2 — location-based)
# =====================================================================

class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_lx_apply_pending_configurator_payloads(self):
        self.ensure_one()
        Pending = self.env["lx.configurator.pending"].sudo()
        pendings = Pending.search([
            ("order_id", "=", self.id),
            ("user_id", "=", self.env.user.id),
        ], order="id asc")

        applied = 0
        details = []

        def _score_candidate(line, pending):
            score = 0
            if line.product_template_id.id == pending.product_tmpl_id.id:
                score += 100
            if pending.lx_width_m and abs(float(line.lx_width_m or 0.0) - float(pending.lx_width_m or 0.0)) < 1e-6:
                score += 20
            if pending.lx_height_m and abs(float(line.lx_height_m or 0.0) - float(pending.lx_height_m or 0.0)) < 1e-6:
                score += 20
            if not line.lx_location_id:
                score += 10
            elif (line.lx_location_id.name or "").strip().lower() == "other":
                score += 8
            return score

        for pending in pendings:
            candidates = self.order_line.filtered(lambda line: (
                not line.display_type
                and not line.lx_parent_line_id
                and line.product_template_id.id == pending.product_tmpl_id.id
            ))
            if not candidates:
                details.append(
                    _("No parent line found for template %s.") % (pending.product_tmpl_id.display_name,)
                )
                continue

            line = max(candidates, key=lambda candidate: _score_candidate(candidate, pending))
            vals = {}
            if pending.lx_location_id:
                vals["lx_location_id"] = pending.lx_location_id.id
            if pending.lx_motor_only_variant_id:
                vals["lx_motor_only_variant_id"] = pending.lx_motor_only_variant_id.id
            if pending.lx_width_m:
                vals["lx_width_m"] = pending.lx_width_m
            if pending.lx_height_m:
                vals["lx_height_m"] = pending.lx_height_m
            if pending.price_unit:
                vals["price_unit"] = pending.price_unit

            if not vals:
                details.append(
                    _("Pending payload %s had no values to apply.") % (pending.id,)
                )
                continue

            _logger.warning(
                "[LX-PC] manual apply pending payload | order_id=%s pending_id=%s line_id=%s vals=%s",
                self.id,
                pending.id,
                line.id,
                vals,
            )
            line.write(vals)
            applied += 1
            details.append(
                _("Applied payload %s to line %s.") % (pending.id, line.display_name or line.id)
            )
            pending.unlink()

        if applied:
            self._lx_sync_electric_accessories()

        message = "\n".join(details) if details else _("No pending configurator payload found for this quotation.")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Configurator Payload"),
                "message": message,
                "type": "success" if applied else "warning",
                "sticky": True,
            },
        }

    def _lx_get_motor_only_debug_messages(self):
        """
        Temporary diagnostic helper for website pages.
        Shows why a Motor Only parent line does not yet have its tubular motor
        child line.
        """
        self.ensure_one()
        messages = []
        Product = self.env["product.product"]

        def _label(prod):
            if not prod or not prod.exists():
                return "none"
            return (
                prod._lx_get_code_value()
                or prod.default_code
                or prod.display_name
            )

        motor_only_lines = self.order_line.filtered(
            lambda l: (
                not l.display_type
                and l.product_id
                and hasattr(l.product_id, "lx_is_motor_only_variant")
                and l.product_id.lx_is_motor_only_variant()
            )
        )

        for line in motor_only_lines:
            child_lines = self.order_line.filtered(
                lambda l: not l.display_type and l.lx_parent_line_id.id == line.id
            )
            motor_children = child_lines.filtered(
                lambda l: l.product_id and l.product_id.product_tmpl_id.lx_is_tubular_motor
            )
            if motor_children:
                continue

            self.env.cr.execute(
                "SELECT lx_motor_only_variant_id FROM sale_order_line WHERE id = %s",
                (line.id,),
            )
            row = self.env.cr.fetchone()
            db_motor_id = row[0] if row else False
            db_motor = Product.browse(db_motor_id) if db_motor_id else Product.browse()

            child_desc = ", ".join(
                (
                    ch.product_id._lx_get_code_value()
                    or ch.product_id.default_code
                    or ch.product_id.display_name
                )
                for ch in child_lines if ch.product_id
            ) or "none"

            messages.append(
                "Motor Only debug | "
                f"parent SOL={line.id} | "
                f"blind={line.name_short or line.product_id.display_name} | "
                f"selected motor(cache)={_label(line.lx_motor_only_variant_id)} | "
                f"selected motor(db)={_label(db_motor)} | "
                f"motor child count={len(motor_children)} | "
                f"all child lines={child_desc}"
            )
        return messages

    def _lx_fetch_accessory_catalog(self):
        PT    = self.env["product.template"]
        PP    = self.env["product.product"]
        empty = PP.browse()

        motor_tmpl    = PT.search([("lx_is_tubular_motor", "=", True)], limit=1)
        charger_tmpls = PT.search([
            "|",
            ("lx_is_electric_charger", "=", True),
            ("lx_is_solar_charger",    "=", True),
        ])
        remote = PP.search(
            [("product_tmpl_id.lx_is_remote_control", "=", True)], limit=1
        )
        zigbee = PP.search(
            [("product_tmpl_id.lx_is_zigbee_gateway", "=", True)], limit=1
        )

        motor_remote = motor_smart = empty
        if motor_tmpl:
            for v in motor_tmpl.product_variant_ids:
                code = v._lx_get_code_value()
                if code == "DM28LEU/SH-2/28":
                    motor_remote = v
                elif code == "AM28-1.8/30-ES-EZ":
                    motor_smart = v

        charger_remote = charger_smart = empty
        for tmpl in charger_tmpls:
            for v in tmpl.product_variant_ids:
                code = v._lx_get_code_value()
                if code == "DC2300-14A" and not charger_remote:
                    charger_remote = v
                elif code == "DC2300-28K" and not charger_smart:
                    charger_smart = v

        return {
            "motor_tmpl":     motor_tmpl,
            "charger_tmpls":  charger_tmpls,
            "motor_remote":   motor_remote,
            "motor_smart":    motor_smart,
            "remote":         remote,
            "zigbee":         zigbee,
            "charger_remote": charger_remote,
            "charger_smart":  charger_smart,
        }

    def _lx_resolve_motor_variant(self, control_type, catalog):
        if control_type == "Motorized, Remote Controlled":
            return catalog["motor_remote"]
        if control_type == "Motorized, Smartphone Controlled":
            return catalog["motor_smart"]
        return self.env["product.product"].browse()

    def _lx_resolve_charger_variant(self, control_type, catalog):
        if control_type == "Motorized, Remote Controlled":
            return catalog["charger_remote"]
        if control_type == "Motorized, Smartphone Controlled":
            return catalog["charger_smart"]
        return self.env["product.product"].browse()

    def _lx_get_accessory_products(self):
        """
        Return (motor_remote, motor_smart, remote, charger, zigbee) as a tuple.

        Called by action_confirm to populate MO raw-material moves.
        The 'charger' slot maps to charger_remote (the standard remote-controlled
        charger); smartphone-controlled charger is handled separately when needed.
        """
        cat = self._lx_fetch_accessory_catalog()
        return (
            cat["motor_remote"],
            cat["motor_smart"],
            cat["remote"],
            cat["charger_remote"],
            cat["zigbee"],
        )

    def _lx_compute_location_pool(self, location_blinds):
        total_remote = total_smart = 0
        for line in location_blinds:
            if line.product_id.lx_is_motor_only_variant():
                continue
            qty = int(line.product_uom_qty or 0)
            if line.product_id.lx_is_smartphone_controlled_variant():
                total_smart  += qty
            elif line.product_id.lx_is_remote_controlled_variant():
                total_remote += qty
        return {
            "total_remote":          total_remote,
            "total_smart":           total_smart,
            "remote_needed":         math.ceil(total_remote / 5)  if total_remote else 0,
            "zigbee_needed":         math.ceil(total_smart  / 30) if total_smart  else 0,
            "charger_remote_needed": math.ceil(total_remote / 15) if total_remote else 0,
            "charger_smart_needed":  math.ceil(total_smart  / 15) if total_smart  else 0,
        }

    def _lx_is_electric_store_line(self, line):
        return bool(
            line
            and not line.display_type
            and line.product_id
            and line.product_id.lx_is_electric_variant()
        )

    def _lx_desc(self, prod):
        return prod.get_product_multiline_description_sale() or prod.display_name

    def _lx_apply_delta(self, line, desired_qty, ctx):
        if not line or not line.exists():
            return
        current = int(line.product_uom_qty or 0)
        desired = int(desired_qty or 0)
        if desired <= 0:
            line.with_context(ctx).unlink()
            return
        if current != desired:
            line.with_context(ctx).write({"product_uom_qty": desired})

    def _lx_upsert_child_accessory(
        self, product, desired_qty, parent_line, ctx, child_map_by_parent,
        line_name=None, sequence=None,
    ):
        if not product or not product.exists():
            return None
        desired = int(desired_qty or 0)
        parent_children = child_map_by_parent.get(parent_line.id, {})
        existing = parent_children.get(product.id)

        if existing and existing.exists():
            write_vals = {}
            if line_name and existing.name != line_name:
                write_vals["name"] = line_name
            if sequence is not None and (existing.sequence or 0) != sequence:
                write_vals["sequence"] = sequence
            if write_vals:
                existing.with_context(ctx).write(write_vals)
            self._lx_apply_delta(existing, desired, ctx)
            return existing if desired > 0 else None
        elif desired > 0:
            child_vals = {
                "product_id":        product.id,
                "product_uom_qty":   desired,
                "name":              line_name or self._lx_desc(product),
                "lx_parent_line_id": parent_line.id,
                "lx_location_id":    parent_line.lx_location_id.id or False,
            }
            if sequence is not None:
                child_vals["sequence"] = sequence
            self.with_context(ctx).write({
                "order_line": [(0, 0, child_vals)]
            })
            self.invalidate_recordset(["order_line", "website_order_line"])
            new_line = self.env["sale.order.line"].search([
                ("order_id", "=", self.id),
                ("product_id", "=", product.id),
                ("lx_parent_line_id", "=", parent_line.id),
                ("display_type", "=", False),
            ], order="id desc", limit=1)
            if new_line:
                new_line._lx_apply_vendor_markdown_if_needed()
                child_map_by_parent.setdefault(parent_line.id, {})[product.id] = new_line
            return new_line
        return None

    def _lx_sync_sections_and_subtotals(self, ctx):
        self.ensure_one()
        all_lines = self.order_line

        elect_lines = (
            all_lines
            .filtered(lambda l: self._lx_is_electric_store_line(l))
            .sorted(lambda l: (l.sequence or 0, l.id))
        )

        auto_sections  = {}
        auto_subtotals = {}

        for l in all_lines:
            loc_key = l.lx_location_id.id or 0
            if (l.display_type == "line_section"
                    and l.lx_section_control_type == "__location__"):
                auto_sections[loc_key] = l
            elif l.lx_is_electric_subtotal:
                auto_subtotals[loc_key] = l

        if not elect_lines:
            stale = all_lines.filtered(
                lambda l: (
                    l.display_type == "line_section"
                    and l.lx_section_control_type == "__location__"
                ) or l.lx_is_electric_subtotal
            )
            if stale:
                stale.with_context(ctx).unlink()
            return

        groups    = {}
        loc_order = []
        loc_label = {}

        for bl in elect_lines:
            loc_key = bl.lx_location_id.id or 0
            if loc_key not in groups:
                groups[loc_key] = []
                loc_order.append(loc_key)
                loc_label[loc_key] = (
                    "Location : " + (bl.lx_location_id.name or "—")
                    if bl.lx_location_id else "Location : —"
                )
            groups[loc_key].append(bl)

        for k in list(auto_sections):
            if k not in groups:
                auto_sections.pop(k).with_context(ctx).unlink()
        for k in list(auto_subtotals):
            if k not in groups:
                auto_subtotals.pop(k).with_context(ctx).unlink()

        for loc_key in loc_order:
            if loc_key not in auto_sections:
                self.with_context(ctx).write({
                    "order_line": [(0, 0, {
                        "display_type":            "line_section",
                        "name":                    loc_label[loc_key],
                        "sequence":                0,
                        "lx_section_control_type": "__location__",
                        "lx_location_id":          loc_key or False,
                    })]
                })

        for loc_key in loc_order:
            if loc_key not in auto_subtotals:
                self.with_context(ctx).write({
                    "order_line": [(0, 0, {
                        "display_type":               "line_note",
                        "name":                       "Subtotal",
                        "sequence":                   0,
                        "lx_is_electric_subtotal":    True,
                        "lx_electric_subtotal_amount": 0.0,
                        "lx_location_id":             loc_key or False,
                    })]
                })

        all_lines = self.order_line
        auto_sections  = {}
        auto_subtotals = {}
        for l in all_lines:
            loc_key = l.lx_location_id.id or 0
            if (l.display_type == "line_section"
                    and l.lx_section_control_type == "__location__"):
                auto_sections[loc_key] = l
            elif l.lx_is_electric_subtotal:
                auto_subtotals[loc_key] = l

        elect_ids = set(elect_lines.ids)
        children_by_blind = {}
        for l in all_lines:
            if l.display_type or l.lx_is_electric_subtotal:
                continue
            if l.lx_parent_line_id and l.lx_parent_line_id.id in elect_ids:
                children_by_blind \
                    .setdefault(l.lx_parent_line_id.id, []) \
                    .append(l)
        for bid in children_by_blind:
            children_by_blind[bid].sort(key=lambda l: (l.sequence or 0, l.id))

        seq              = 10
        section_counter  = 0
        new_sequences    = {}
        electric_ids_all = set()

        for loc_key in loc_order:
            section_counter += 1

            sec = auto_sections.get(loc_key)
            if sec:
                new_sequences[sec.id] = seq
                electric_ids_all.add(sec.id)
                seq += 10

            group_subtotal = 0.0
            ct_present     = set()

            for bl in groups[loc_key]:
                new_sequences[bl.id] = seq
                electric_ids_all.add(bl.id)
                group_subtotal += bl.price_subtotal or 0.0
                ct = bl.product_id._lx_get_control_type_value() if bl.product_id else ""
                if ct:
                    ct_present.add(ct)
                seq += 10

                for ch in children_by_blind.get(bl.id, []):
                    new_sequences[ch.id] = seq
                    electric_ids_all.add(ch.id)
                    group_subtotal += ch.price_subtotal or 0.0
                    seq += 10

            sub = auto_subtotals.get(loc_key)
            if sub:
                new_sequences[sub.id] = seq
                electric_ids_all.add(sub.id)
                seq += 10

                pnames = []
                for bl in groups[loc_key]:
                    n = (bl.product_id.display_name or "") if bl.product_id else ""
                    if n and n not in pnames:
                        pnames.append(n)
                parts = [p for p in pnames if p]

                currency  = self.currency_id
                symbol    = currency.symbol if currency else ""
                formatted = "{:,.2f} {}".format(group_subtotal, symbol).strip()
                full_name = _("Subtotal (%s)") % section_counter
                if parts:
                    full_name += " - " + ", ".join(parts)
                full_name += ":  " + formatted

                if (
                    sub.lx_electric_subtotal_amount != group_subtotal
                    or sub.name != full_name
                ):
                    sub.with_context(ctx).write({
                        "lx_electric_subtotal_amount": group_subtotal,
                        "name":                        full_name,
                    })

        for l in all_lines.sorted(lambda x: (x.sequence or 0, x.id)):
            if l.id not in electric_ids_all:
                new_sequences[l.id] = seq
                seq += 10

        for l in all_lines:
            desired = new_sequences.get(l.id)
            if desired is not None and (l.sequence or 0) != desired:
                l.with_context(ctx).write({"sequence": desired})

    def _lx_sync_electric_accessories(self):
        self.ensure_one()
        if self.env.context.get("lx_syncing_accessories"):
            return True

        ctx = dict(self.env.context, lx_syncing_accessories=True)

        with self.env.cr.savepoint():

            catalog = self._lx_fetch_accessory_catalog()

            elect_lines = (
                self.order_line
                .filtered(lambda l: self._lx_is_electric_store_line(l))
                .sorted(lambda l: (l.sequence or 0, l.id))
            )

            motor_child_map = {}
            for l in self.order_line:
                if (
                    not l.display_type
                    and l.lx_parent_line_id
                    and l.product_id.product_tmpl_id.lx_is_tubular_motor
                ):
                    motor_child_map \
                        .setdefault(l.lx_parent_line_id.id, {}) \
                        [l.product_id.id] = l

            pool_product_ids = {
                p.id
                for key in ("remote", "zigbee", "charger_remote", "charger_smart")
                for p in [catalog[key]]
                if p and p.exists()
            }
            pool_child_map = {}
            for l in self.order_line:
                if (
                    not l.display_type
                    and l.lx_parent_line_id
                    and l.product_id.id in pool_product_ids
                ):
                    pool_child_map \
                        .setdefault(l.lx_parent_line_id.id, {}) \
                        [l.product_id.id] = l

            # ============================================================
            # PART 1 — Motor per blind
            # ============================================================
            for blind in elect_lines:
                control = blind.product_id._lx_get_control_type_value()

                if control == "Motor Only":
                    self.env.cr.execute(
                        "SELECT lx_motor_only_variant_id"
                        " FROM sale_order_line WHERE id = %s",
                        (blind.id,),
                    )
                    row = self.env.cr.fetchone()
                    motor_id = row[0] if row else None
                    motor = (
                        self.env["product.product"].browse(motor_id)
                        if motor_id else self.env["product.product"].browse()
                    )
                    if not motor or not motor.exists():
                        # No variant selected yet — remove any stale motor children
                        for stale_child in motor_child_map.get(blind.id, {}).values():
                            if stale_child.exists():
                                stale_child.with_context(ctx).unlink()
                        continue
                    motor_line_name = (
                        motor._lx_get_code_value()
                        or motor.default_code
                        or self._lx_desc(motor)
                    )
                    # Remove stale motor children with a DIFFERENT variant
                    # (user changed variant in the configurator)
                    for stale_pid, stale_child in list(
                        motor_child_map.get(blind.id, {}).items()
                    ):
                        if stale_pid != motor.id and stale_child.exists():
                            stale_child.with_context(ctx).unlink()
                else:
                    motor = self._lx_resolve_motor_variant(control, catalog)
                    if not motor or not motor.exists():
                        raise UserError(
                            _("Motor variant not found for control type: %s") % control
                        )

                qty   = int(blind.product_uom_qty or 0)
                self._lx_upsert_child_accessory(
                    motor,
                    qty,
                    blind,
                    ctx,
                    motor_child_map,
                    line_name=motor_line_name if control == "Motor Only" else None,
                    sequence=(blind.sequence or 0) + 1,
                )
                final_motor_child = self.order_line.filtered(
                    lambda l: (
                        not l.display_type
                        and l.lx_parent_line_id.id == blind.id
                        and l.product_id.id == motor.id
                    )
                )[:1]
                if control == "Motor Only" and qty > 0 and not final_motor_child:
                    _logger.warning(
                        "[Luxtor][MotorOnly] Missing motor child after sync | "
                        "order=%s blind_sol=%s blind=%s selected_motor_cache=%s selected_motor_db=%s qty=%s",
                        self.name,
                        blind.id,
                        blind.product_id.display_name if blind.product_id else "",
                        (
                            blind.lx_motor_only_variant_id._lx_get_code_value()
                            or blind.lx_motor_only_variant_id.default_code
                            or blind.lx_motor_only_variant_id.display_name
                        ) if blind.lx_motor_only_variant_id else "none",
                        motor._lx_get_code_value() or motor.default_code or motor.display_name,
                        qty,
                    )

            # ============================================================
            # PART 2 — Per-location pooled accessories
            # ============================================================

            loc_groups = {}
            loc_order  = []
            for bl in elect_lines:
                k = bl.lx_location_id.id or 0
                if k not in loc_groups:
                    loc_groups[k] = []
                    loc_order.append(k)
                loc_groups[k].append(bl)

            for loc_key in loc_order:
                loc_blinds = loc_groups[loc_key]
                non_motor  = [
                    bl for bl in loc_blinds
                    if not bl.product_id.lx_is_motor_only_variant()
                ]

                if not non_motor:
                    for bl in loc_blinds:
                        for _pid, line in list(
                            pool_child_map.get(bl.id, {}).items()
                        ):
                            if line.exists():
                                line.with_context(ctx).unlink()
                    continue

                remote_blinds = [
                    bl for bl in non_motor
                    if bl.product_id and bl.product_id.lx_is_remote_controlled_variant()
                ]
                smart_blinds = [
                    bl for bl in non_motor
                    if bl.product_id and bl.product_id.lx_is_smartphone_controlled_variant()
                ]
                remote_owner = remote_blinds[-1] if remote_blinds else None
                smart_owner  = smart_blinds[-1] if smart_blinds else None

                pool = self._lx_compute_location_pool(loc_blinds)

                desired_by_product = {}

                def add_assignment(product, owner_line, qty, sequence=None):
                    if not product or not product.exists() or not owner_line:
                        return
                    desired_qty = int(qty or 0)
                    if desired_qty <= 0:
                        return
                    bucket = desired_by_product.setdefault(product.id, {
                        "product": product,
                        "assignments": {},
                    })
                    assignment = bucket["assignments"].setdefault(owner_line.id, {
                        "qty": 0,
                        "sequence": sequence,
                    })
                    assignment["qty"] += desired_qty
                    if sequence is not None:
                        assignment["sequence"] = sequence

                add_assignment(
                    catalog["remote"],
                    remote_owner,
                    pool["remote_needed"],
                    sequence=((remote_owner.sequence or 0) + 2) if remote_owner else None,
                )
                add_assignment(
                    catalog["zigbee"],
                    smart_owner,
                    pool["zigbee_needed"],
                    sequence=((smart_owner.sequence or 0) + 2) if smart_owner else None,
                )
                add_assignment(
                    catalog["charger_remote"],
                    remote_owner,
                    pool["charger_remote_needed"],
                    sequence=((remote_owner.sequence or 0) + 3) if remote_owner else None,
                )
                add_assignment(
                    catalog["charger_smart"],
                    smart_owner,
                    pool["charger_smart_needed"],
                    sequence=((smart_owner.sequence or 0) + 3) if smart_owner else None,
                )

                managed_products = [
                    product for product in (
                        catalog["remote"],
                        catalog["zigbee"],
                        catalog["charger_remote"],
                        catalog["charger_smart"],
                    )
                    if product and product.exists()
                ]
                managed_product_ids = {product.id for product in managed_products}

                for bucket in desired_by_product.values():
                    product = bucket["product"]
                    for parent_id, assignment in bucket["assignments"].items():
                        owner_line = self.env["sale.order.line"].browse(parent_id)
                        self._lx_upsert_child_accessory(
                            product,
                            assignment["qty"],
                            owner_line,
                            ctx,
                            pool_child_map,
                            sequence=assignment.get("sequence"),
                        )

                for product in managed_products:
                    keep_parent_ids = set(
                        desired_by_product.get(product.id, {}).get("assignments", {}).keys()
                    )
                    for bl in loc_blinds:
                        stale = pool_child_map.get(bl.id, {}).get(product.id)
                        if (
                            stale
                            and stale.exists()
                            and bl.id not in keep_parent_ids
                        ):
                            stale.with_context(ctx).unlink()
                            pool_child_map.get(bl.id, {}).pop(product.id, None)

                for bl in loc_blinds:
                    for product_id, line in list(pool_child_map.get(bl.id, {}).items()):
                        if product_id not in managed_product_ids:
                            continue
                        if not line.exists():
                            pool_child_map.get(bl.id, {}).pop(product_id, None)

            # ============================================================
            # PART 3 — Sections, subtotals, resequencing
            # ============================================================
            self._lx_sync_sections_and_subtotals(ctx)

        self.invalidate_recordset(["order_line", "website_order_line"])
        return True

    # ------------------------------------------------------------------
    # Line numbering (v2) — two-pass to guarantee parent_nos is populated
    # ------------------------------------------------------------------

    def _generate_sequence_numbers_for_lines(self):
        """
        Two-pass line numbering:
          Pass 1 — assign 1,2,3… to storable/blind lines → builds parent_nos
          Pass 2 — assign 1.1,1.2… to child lines using parent_nos

        Two passes prevent empty sub-numbers when sequence ordering is
        temporarily inconsistent during sync.
        """
        for order in self:
            main_seq    = 0
            parent_nos  = {}   # {line_id: str}
            child_lines = []   # collected for pass 2

            # ── PASS 1: main sequence numbers ──────────────────────────
            for line in order.order_line.sorted("sequence"):

                if (
                    line.display_type == "line_section"
                    and line.lx_section_control_type == "__location__"
                ):
                    line.sequence_number = ""
                    continue

                if line.lx_is_electric_subtotal:
                    line.sequence_number = ""
                    continue

                if line.display_type:
                    line.sequence_number = ""
                    continue

                if line.lx_parent_line_id:
                    child_lines.append(line)
                    continue

                if line.product_template_id:
                    if line.product_template_id.type in ("consu", "combo", "product"):
                        main_seq += 1
                        sn = str(main_seq)
                        line.sequence_number = sn
                        parent_nos[line.id]  = sn
                    else:
                        line.sequence_number = "#"
                elif (
                    getattr(line, "is_priority_line", False)
                    or getattr(line, "is_installation_line", False)
                    or getattr(line, "is_shipping_line", False)
                ):
                    line.sequence_number = "#"

            # ── PASS 2: sub-numbers for child lines ─────────────────────
            sub_seq = {}  # {parent_id: int}
            for line in sorted(child_lines, key=lambda l: (l.sequence or 0, l.id)):
                pid       = line.lx_parent_line_id.id
                parent_no = parent_nos.get(pid, "")
                if parent_no:
                    sub_seq[pid] = sub_seq.get(pid, 0) + 1
                    line.sequence_number = "%s.%s" % (parent_no, sub_seq[pid])
                else:
                    line.sequence_number = ""

# import math

# from odoo import api, fields, models, _
# from odoo.exceptions import UserError


# # =====================================================================
# # PRODUCT TEMPLATE
# # =====================================================================

# class ProductTemplate(models.Model):
#     _inherit = "product.template"

#     lx_is_tubular_motor    = fields.Boolean("Is Tubular Motor",     default=False)
#     lx_is_remote_control   = fields.Boolean("Is Remote Control",    default=False)
#     lx_is_zigbee_gateway   = fields.Boolean("Is ZigBee Gateway",    default=False)
#     lx_is_electric_charger = fields.Boolean("Is Electric Charger",  default=False)
#     lx_is_solar_charger    = fields.Boolean("Is Solar Charger",     default=False)

#     def lx_is_electric_accessory(self):
#         self.ensure_one()
#         return bool(
#             self.lx_is_tubular_motor
#             or self.lx_is_remote_control
#             or self.lx_is_zigbee_gateway
#             or self.lx_is_electric_charger
#             or self.lx_is_solar_charger
#         )


# # =====================================================================
# # PRODUCT PRODUCT
# # =====================================================================

# class ProductProduct(models.Model):
#     _inherit = "product.product"

#     def _lx_get_attribute_value_name(self, attribute_name):
#         self.ensure_one()
#         attr = (attribute_name or "").strip()
#         for ptav in self.product_template_attribute_value_ids:
#             if ptav.attribute_id and (ptav.attribute_id.name or "").strip() == attr:
#                 return (ptav.product_attribute_value_id.name or "").strip()
#         return ""

#     def _lx_get_control_type_value(self):
#         return self._lx_get_attribute_value_name("Control Type")

#     def _lx_get_code_value(self):
#         return self._lx_get_attribute_value_name("Code")

#     def lx_is_electric_variant(self):
#         self.ensure_one()
#         return self._lx_get_control_type_value() in {
#             "Motorized, Remote Controlled",
#             "Motorized, Smartphone Controlled",
#             "Motor Only",
#         }

#     def lx_is_motor_only_variant(self):
#         self.ensure_one()
#         return self._lx_get_control_type_value() == "Motor Only"

#     def lx_is_smartphone_controlled_variant(self):
#         self.ensure_one()
#         return self._lx_get_control_type_value() == "Motorized, Smartphone Controlled"

#     def lx_is_remote_controlled_variant(self):
#         self.ensure_one()
#         return self._lx_get_control_type_value() == "Motorized, Remote Controlled"


# # =====================================================================
# # SALE ORDER LINE
# # =====================================================================

# class SaleOrderLine(models.Model):
#     _inherit = "sale.order.line"

#     # ------------------------------------------------------------------
#     # NEW field — add column to DB (see SQL in module docstring)
#     # ------------------------------------------------------------------
#     lx_location_id = fields.Many2one(
#         "luxtor.installation.space",
#         string="Location",
#         index=True,
#         ondelete="set null",
#         help="Room / installation space.  Electric blind lines are grouped "
#              "and subtotalled per location.",
#     )

#     lx_motor_only_variant_id = fields.Many2one(
#         "product.product",
#         string="Motor Only Variant",
#         index=True,
#         ondelete="set null",
#         help="Selected tubular motor variant when Control Type is Motor Only.",
#     )

#     # ------------------------------------------------------------------
#     # Existing electric accessory fields (unchanged)
#     # ------------------------------------------------------------------
#     lx_parent_line_id = fields.Many2one(
#         "sale.order.line",
#         string="Parent Blind Line",
#         index=True,
#         ondelete="cascade",
#     )

#     lx_base_price_unit = fields.Float(
#         string="Base Unit Price (pre-markdown)",
#         digits="Product Price",
#         default=0.0,
#     )

#     lx_section_control_type = fields.Char(
#         "Electric Section Control Type",
#         copy=False,
#         index=True,
#         help="Value '__location__' marks auto-generated location section headers.",
#     )

#     lx_is_electric_subtotal = fields.Boolean(
#         "Is Electric Subtotal Line",
#         default=False,
#         copy=False,
#     )

#     lx_electric_subtotal_amount = fields.Float(
#         "Section Subtotal",
#         digits="Product Price",
#         default=0.0,
#         copy=False,
#         store=True,
#     )

#     # ------------------------------------------------------------------
#     # ORM hooks
#     # ------------------------------------------------------------------

#     # @api.model
#     # def create(self, vals):
#     #     line = super().create(vals)
#     #     line._lx_apply_vendor_markdown_if_needed()
#     #     if line.order_id and not self.env.context.get("lx_syncing_accessories"):
#     #         line.order_id._lx_sync_electric_accessories()
#     #     return line

#     @api.model
#     def create(self, vals):
#         line = super().create(vals)
#         # Guard: skip virtual/unsaved records (id is a string like "virtual_102")
#         if not isinstance(line.id, int):
#             return line
#         line._lx_apply_vendor_markdown_if_needed()
#         if line.order_id and not self.env.context.get("lx_syncing_accessories"):
#             line.order_id._lx_sync_electric_accessories()
#         return line

#     # def write(self, vals):
#     #     if "product_id" in vals and not self.env.context.get("lx_syncing_accessories"):
#     #         super(SaleOrderLine, self).write({"lx_base_price_unit": 0.0})
#     #     res = super().write(vals)
#     #     if not self.env.context.get("lx_syncing_accessories"):
#     #         for line in self:
#     #             line._lx_apply_vendor_markdown_if_needed()
#     #         for order in self.mapped("order_id"):
#     #             order._lx_sync_electric_accessories()
#     #     return res

#     # def unlink(self):
#     #     orders = self.mapped("order_id")
#     #     blind_lines = self.filtered(
#     #         lambda l: not l.display_type
#     #         and l.product_id
#     #         and l.product_id.lx_is_electric_variant()
#     #     )
#     #     if blind_lines:
#     #         children = self.env["sale.order.line"].search([
#     #             ("lx_parent_line_id", "in", blind_lines.ids),
#     #             ("display_type", "=", False),
#     #         ])
#     #         if children:
#     #             children.with_context(lx_syncing_accessories=True).unlink()
#     #     res = super().unlink()
#     #     if not self.env.context.get("lx_syncing_accessories"):
#     #         for order in orders:
#     #             if order.exists():
#     #                 order._lx_sync_electric_accessories()
#     #     return res

#     def write(self, vals):
#         if "product_id" in vals and not self.env.context.get("lx_syncing_accessories"):
#             super(SaleOrderLine, self).write({"lx_base_price_unit": 0.0})
#         res = super().write(vals)
#         if not self.env.context.get("lx_syncing_accessories"):
#             # Guard: skip virtual records (id is a string like "virtual_102")
#             real_lines = self.filtered(lambda l: isinstance(l.id, int))
#             for line in real_lines:
#                 line._lx_apply_vendor_markdown_if_needed()
#             for order in real_lines.mapped("order_id"):
#                 order._lx_sync_electric_accessories()
#         return res
    
#     def unlink(self):
#         # Guard: skip virtual records (id is a string like "virtual_102")
#         if not all(isinstance(l.id, int) for l in self):
#             real = self.filtered(lambda l: isinstance(l.id, int))
#             if real:
#                 return real.unlink()
#             return True
 
#         orders = self.mapped("order_id")
#         blind_lines = self.filtered(
#             lambda l: not l.display_type
#             and l.product_id
#             and l.product_id.lx_is_electric_variant()
#         )
#         if blind_lines:
#             children = self.env["sale.order.line"].search([
#                 ("lx_parent_line_id", "in", blind_lines.ids),
#                 ("display_type", "=", False),
#             ])
#             if children:
#                 children.with_context(lx_syncing_accessories=True).unlink()
#         res = super().unlink()
#         if not self.env.context.get("lx_syncing_accessories"):
#             for order in orders:
#                 if order.exists():
#                     order._lx_sync_electric_accessories()
#         return res

#     # ------------------------------------------------------------------
#     # Vendor markdown (unchanged — idempotent via lx_base_price_unit)
#     # ------------------------------------------------------------------

#     def _lx_apply_vendor_markdown_if_needed(self):
#         self.ensure_one()
#         if self.display_type:
#             return
#         if not self.product_id:
#             return
#         tmpl = self.product_id.product_tmpl_id
#         if not tmpl.lx_is_electric_accessory():
#             return
#         partner = self.order_id.partner_id
#         if not partner:
#             return
#         markdown = partner.lx_vendor_markdown or 0.0
#         if markdown <= 0.0:
#             return
#         if self.lx_base_price_unit:
#             return
#         base_price = self.price_unit
#         if not base_price:
#             return
#         final_price = base_price * (1.0 - markdown / 100.0)
#         self.with_context(lx_syncing_accessories=True).write({
#             "lx_base_price_unit": base_price,
#             "price_unit":         final_price,
#         })


# # =====================================================================
# # SALE ORDER  — sync engine (v2 — location-based)
# # =====================================================================

# class SaleOrder(models.Model):
#     _inherit = "sale.order"

#     # ------------------------------------------------------------------
#     # Catalog fetch (4 ORM searches — unchanged)
#     # ------------------------------------------------------------------

#     def _lx_fetch_accessory_catalog(self):
#         PT    = self.env["product.template"]
#         PP    = self.env["product.product"]
#         empty = PP.browse()

#         motor_tmpl    = PT.search([("lx_is_tubular_motor", "=", True)], limit=1)
#         charger_tmpls = PT.search([
#             "|",
#             ("lx_is_electric_charger", "=", True),
#             ("lx_is_solar_charger",    "=", True),
#         ])
#         remote = PP.search(
#             [("product_tmpl_id.lx_is_remote_control", "=", True)], limit=1
#         )
#         zigbee = PP.search(
#             [("product_tmpl_id.lx_is_zigbee_gateway", "=", True)], limit=1
#         )

#         motor_remote = motor_smart = empty
#         if motor_tmpl:
#             for v in motor_tmpl.product_variant_ids:
#                 code = v._lx_get_code_value()
#                 if code == "DM28LEU/SH-2/28":
#                     motor_remote = v
#                 elif code == "AM28-1.8/30-ES-EZ":
#                     motor_smart = v

#         charger_remote = charger_smart = empty
#         for tmpl in charger_tmpls:
#             for v in tmpl.product_variant_ids:
#                 code = v._lx_get_code_value()
#                 if code == "DC2300-14A" and not charger_remote:
#                     charger_remote = v
#                 elif code == "DC2300-28K" and not charger_smart:
#                     charger_smart = v

#         return {
#             "motor_tmpl":     motor_tmpl,
#             "charger_tmpls":  charger_tmpls,
#             "motor_remote":   motor_remote,
#             "motor_smart":    motor_smart,
#             "remote":         remote,
#             "zigbee":         zigbee,
#             "charger_remote": charger_remote,
#             "charger_smart":  charger_smart,
#         }

#     def _lx_resolve_motor_variant(self, control_type, catalog):
#         if control_type == "Motorized, Remote Controlled":
#             return catalog["motor_remote"]
#         if control_type == "Motorized, Smartphone Controlled":
#             return catalog["motor_smart"]
#         return self.env["product.product"].browse()

#     def _lx_resolve_charger_variant(self, control_type, catalog):
#         if control_type == "Motorized, Remote Controlled":
#             return catalog["charger_remote"]
#         if control_type == "Motorized, Smartphone Controlled":
#             return catalog["charger_smart"]
#         return self.env["product.product"].browse()

#     # ------------------------------------------------------------------
#     # Per-location pool computation
#     # ------------------------------------------------------------------

#     def _lx_compute_location_pool(self, location_blinds):
#         """
#         Pool accessories for ONE location's blind lines.
#         Ratios:  Remote 1/5  |  ZigBee 1/30  |  Charger 1/15
#         Motor Only lines are excluded.
#         """
#         total_remote = total_smart = 0
#         for line in location_blinds:
#             if line.product_id.lx_is_motor_only_variant():
#                 continue
#             qty = int(line.product_uom_qty or 0)
#             if line.product_id.lx_is_smartphone_controlled_variant():
#                 total_smart  += qty
#             elif line.product_id.lx_is_remote_controlled_variant():
#                 total_remote += qty
#         return {
#             "total_remote":          total_remote,
#             "total_smart":           total_smart,
#             "remote_needed":         math.ceil(total_remote / 5)  if total_remote else 0,
#             "zigbee_needed":         math.ceil(total_smart  / 30) if total_smart  else 0,
#             "charger_remote_needed": math.ceil(total_remote / 15) if total_remote else 0,
#             "charger_smart_needed":  math.ceil(total_smart  / 15) if total_smart  else 0,
#         }

#     # ------------------------------------------------------------------
#     # Helpers
#     # ------------------------------------------------------------------

#     def _lx_is_electric_store_line(self, line):
#         return bool(
#             line
#             and not line.display_type
#             and line.product_id
#             and line.product_id.lx_is_electric_variant()
#         )

#     def _lx_desc(self, prod):
#         return "⤶" + (prod.get_product_multiline_description_sale() or prod.display_name)

#     def _lx_apply_delta(self, line, desired_qty, ctx):
#         if not line or not line.exists():
#             return
#         current = int(line.product_uom_qty or 0)
#         desired = int(desired_qty or 0)
#         if desired <= 0:
#             line.with_context(ctx).unlink()
#             return
#         if current != desired:
#             line.with_context(ctx).write({"product_uom_qty": desired})

#     def _lx_upsert_child_accessory(
#         self, product, desired_qty, parent_line, ctx, child_map_by_parent
#     ):
#         """
#         Create or update a pooled-accessory line as a child of parent_line.
#         child_map_by_parent: {parent_id: {product_id: line}}   (mutated in-place)
#         """
#         if not product or not product.exists():
#             return None
#         desired = int(desired_qty or 0)
#         parent_children = child_map_by_parent.get(parent_line.id, {})
#         existing = parent_children.get(product.id)

#         if existing and existing.exists():
#             self._lx_apply_delta(existing, desired, ctx)
#             return existing if desired > 0 else None
#         elif desired > 0:
#             self.with_context(ctx).write({
#                 "order_line": [(0, 0, {
#                     "product_id":        product.id,
#                     "product_uom_qty":   desired,
#                     "name":              self._lx_desc(product),
#                     "lx_parent_line_id": parent_line.id,
#                     "lx_location_id":    parent_line.lx_location_id.id or False,
#                 })]
#             })
#             new_line = self.order_line.filtered(
#                 lambda l: l.product_id.id == product.id
#                 and l.lx_parent_line_id.id == parent_line.id
#                 and not l.display_type
#             )[:1]
#             if new_line:
#                 new_line._lx_apply_vendor_markdown_if_needed()
#                 child_map_by_parent.setdefault(parent_line.id, {})[product.id] = new_line
#             return new_line
#         return None

#     # ------------------------------------------------------------------
#     # Section & subtotal sync  (v2 — location-driven)
#     # ------------------------------------------------------------------

#     def _lx_sync_sections_and_subtotals(self, ctx):
#         """
#         Layout produced for every unique lx_location_id group:

#             [line_section]  "Location : Living Room"       bold+italic #45818E
#               1   Blind A                                  italic #434343
#                   1.1  Motor
#                   1.2  Remote Control
#                   1.3  Charger
#             [line_note]  "Subtotal (1) – …:  X.XX DH"     italic #BF9000

#         Non-electric lines are placed after all electric sections.
#         """
#         self.ensure_one()
#         all_lines = self.order_line

#         elect_lines = (
#             all_lines
#             .filtered(lambda l: self._lx_is_electric_store_line(l))
#             .sorted(lambda l: (l.sequence or 0, l.id))
#         )

#         # ── Collect existing auto lines ─────────────────────────────────
#         auto_sections  = {}   # loc_key -> line
#         auto_subtotals = {}   # loc_key -> line

#         for l in all_lines:
#             loc_key = l.lx_location_id.id or 0
#             if (l.display_type == "line_section"
#                     and l.lx_section_control_type == "__location__"):
#                 auto_sections[loc_key] = l
#             elif l.lx_is_electric_subtotal:
#                 auto_subtotals[loc_key] = l

#         if not elect_lines:
#             stale = all_lines.filtered(
#                 lambda l: (
#                     l.display_type == "line_section"
#                     and l.lx_section_control_type == "__location__"
#                 ) or l.lx_is_electric_subtotal
#             )
#             if stale:
#                 stale.with_context(ctx).unlink()
#             return

#         # ── Build ordered location groups ───────────────────────────────
#         groups    = {}   # loc_key -> [blind_line, ...]
#         loc_order = []
#         loc_label = {}   # loc_key -> header string

#         for bl in elect_lines:
#             loc_key = bl.lx_location_id.id or 0
#             if loc_key not in groups:
#                 groups[loc_key] = []
#                 loc_order.append(loc_key)
#                 loc_label[loc_key] = (
#                     "Location : " + (bl.lx_location_id.name or "—")
#                     if bl.lx_location_id else "Location : —"
#                 )
#             groups[loc_key].append(bl)

#         # ── Prune obsolete auto lines ───────────────────────────────────
#         for k in list(auto_sections):
#             if k not in groups:
#                 auto_sections.pop(k).with_context(ctx).unlink()
#         for k in list(auto_subtotals):
#             if k not in groups:
#                 auto_subtotals.pop(k).with_context(ctx).unlink()

#         # ── Create missing section headers ──────────────────────────────
#         for loc_key in loc_order:
#             if loc_key not in auto_sections:
#                 self.with_context(ctx).write({
#                     "order_line": [(0, 0, {
#                         "display_type":            "line_section",
#                         "name":                    loc_label[loc_key],
#                         "sequence":                0,
#                         "lx_section_control_type": "__location__",
#                         "lx_location_id":          loc_key or False,
#                     })]
#                 })

#         # ── Create missing subtotal note lines ──────────────────────────
#         for loc_key in loc_order:
#             if loc_key not in auto_subtotals:
#                 self.with_context(ctx).write({
#                     "order_line": [(0, 0, {
#                         "display_type":               "line_note",
#                         "name":                       "Subtotal",
#                         "sequence":                   0,
#                         "lx_is_electric_subtotal":    True,
#                         "lx_electric_subtotal_amount": 0.0,
#                         "lx_location_id":             loc_key or False,
#                     })]
#                 })

#         # ── Re-read after creations ─────────────────────────────────────
#         all_lines = self.order_line
#         auto_sections  = {}
#         auto_subtotals = {}
#         for l in all_lines:
#             loc_key = l.lx_location_id.id or 0
#             if (l.display_type == "line_section"
#                     and l.lx_section_control_type == "__location__"):
#                 auto_sections[loc_key] = l
#             elif l.lx_is_electric_subtotal:
#                 auto_subtotals[loc_key] = l

#         # ── Build children map ──────────────────────────────────────────
#         elect_ids = set(elect_lines.ids)
#         children_by_blind = {}  # blind_id -> [child_line, ...]
#         for l in all_lines:
#             if l.display_type or l.lx_is_electric_subtotal:
#                 continue
#             if l.lx_parent_line_id and l.lx_parent_line_id.id in elect_ids:
#                 children_by_blind \
#                     .setdefault(l.lx_parent_line_id.id, []) \
#                     .append(l)
#         for bid in children_by_blind:
#             children_by_blind[bid].sort(key=lambda l: (l.sequence or 0, l.id))

#         # ── Assign sequences + compute subtotals ────────────────────────
#         seq              = 10
#         section_counter  = 0
#         new_sequences    = {}
#         electric_ids_all = set()

#         for loc_key in loc_order:
#             section_counter += 1

#             sec = auto_sections.get(loc_key)
#             if sec:
#                 new_sequences[sec.id] = seq
#                 electric_ids_all.add(sec.id)
#                 seq += 10

#             group_subtotal = 0.0
#             ct_present     = set()

#             for bl in groups[loc_key]:
#                 new_sequences[bl.id] = seq
#                 electric_ids_all.add(bl.id)
#                 group_subtotal += bl.price_subtotal or 0.0
#                 ct = bl.product_id._lx_get_control_type_value() if bl.product_id else ""
#                 if ct:
#                     ct_present.add(ct)
#                 seq += 10

#                 for ch in children_by_blind.get(bl.id, []):
#                     new_sequences[ch.id] = seq
#                     electric_ids_all.add(ch.id)
#                     group_subtotal += ch.price_subtotal or 0.0
#                     seq += 10

#             sub = auto_subtotals.get(loc_key)
#             if sub:
#                 new_sequences[sub.id] = seq
#                 electric_ids_all.add(sub.id)
#                 seq += 10

#                 # ── Subtotal label ──────────────────────────────────────
#                 # "Subtotal (N) - [product names], [control type]:  X.XX DH"

#                 # Full product display_name already contains all variant info
#                 pnames = []
#                 for bl in groups[loc_key]:
#                     n = (bl.product_id.display_name or "") if bl.product_id else ""
#                     if n and n not in pnames:
#                         pnames.append(n)
#                 parts = [p for p in pnames if p]
 

#                 currency  = self.currency_id
#                 symbol    = currency.symbol if currency else ""
#                 formatted = "{:,.2f} {}".format(group_subtotal, symbol).strip()
#                 full_name = _("Subtotal (%s)") % section_counter
#                 if parts:
#                     full_name += " - " + ", ".join(parts)
#                 full_name += ":  " + formatted

#                 if (
#                     sub.lx_electric_subtotal_amount != group_subtotal
#                     or sub.name != full_name
#                 ):
#                     sub.with_context(ctx).write({
#                         "lx_electric_subtotal_amount": group_subtotal,
#                         "name":                        full_name,
#                     })

#         # ── Non-electric lines at the bottom ────────────────────────────
#         for l in all_lines.sorted(lambda x: (x.sequence or 0, x.id)):
#             if l.id not in electric_ids_all:
#                 new_sequences[l.id] = seq
#                 seq += 10

#         # ── Apply sequence changes (delta only) ─────────────────────────
#         for l in all_lines:
#             desired = new_sequences.get(l.id)
#             if desired is not None and (l.sequence or 0) != desired:
#                 l.with_context(ctx).write({"sequence": desired})

#     # ------------------------------------------------------------------
#     # MAIN SYNC ENGINE  (v2)
#     # ------------------------------------------------------------------

#     def _lx_sync_electric_accessories(self):
#         """
#         Idempotent delta sync called after every SOL create/write/unlink.

#         PART 1 — Motor per blind   (child of the blind line)
#         PART 2 — Per-location pooled accessories
#                  Remote / ZigBee / Charger pooled only from blinds
#                  in the same location; stored as children of the LAST
#                  non-Motor-Only blind in that location.
#         PART 3 — Sections, subtotals, full resequencing
#         """
#         self.ensure_one()
#         if self.env.context.get("lx_syncing_accessories"):
#             return True

#         ctx = dict(self.env.context, lx_syncing_accessories=True)

#         with self.env.cr.savepoint():

#             catalog = self._lx_fetch_accessory_catalog()

#             elect_lines = (
#                 self.order_line
#                 .filtered(lambda l: self._lx_is_electric_store_line(l))
#                 .sorted(lambda l: (l.sequence or 0, l.id))
#             )

#             # ── Motor child map  {parent_id: {motor_product_id: line}} ──
#             motor_child_map = {}
#             for l in self.order_line:
#                 if (
#                     not l.display_type
#                     and l.lx_parent_line_id
#                     and l.product_id.product_tmpl_id.lx_is_tubular_motor
#                 ):
#                     motor_child_map \
#                         .setdefault(l.lx_parent_line_id.id, {}) \
#                         [l.product_id.id] = l

#             # ── Pooled-accessory child map  {parent_id: {product_id: line}} ──
#             pool_product_ids = {
#                 p.id
#                 for key in ("remote", "zigbee", "charger_remote", "charger_smart")
#                 for p in [catalog[key]]
#                 if p and p.exists()
#             }
#             pool_child_map = {}
#             for l in self.order_line:
#                 if (
#                     not l.display_type
#                     and l.lx_parent_line_id
#                     and l.product_id.id in pool_product_ids
#                 ):
#                     pool_child_map \
#                         .setdefault(l.lx_parent_line_id.id, {}) \
#                         [l.product_id.id] = l

#             # ============================================================
#             # PART 1 — Motor per blind
#             # ============================================================
#             for blind in elect_lines:
#                 control = blind.product_id._lx_get_control_type_value()
#                 if control == "Motor Only":
#                     motor = blind.lx_motor_only_variant_id
#                     if not motor or not motor.exists():
#                         continue
#                 else:
#                     motor = self._lx_resolve_motor_variant(control, catalog)
#                 if not motor or not motor.exists():
#                     raise UserError(
#                         _("Motor variant not found for control type: %s") % control
#                     )

#                 qty   = int(blind.product_uom_qty or 0)
#                 child = motor_child_map.get(blind.id, {}).get(motor.id)

#                 if child and child.exists():
#                     self._lx_apply_delta(child, qty, ctx)
#                 elif qty > 0:
#                     self.with_context(ctx).write({
#                         "order_line": [(0, 0, {
#                             "product_id":        motor.id,
#                             "product_uom_qty":   qty,
#                             "name":              self._lx_desc(motor),
#                             "sequence":          (blind.sequence or 0) + 1,
#                             "lx_parent_line_id": blind.id,
#                             "lx_location_id":    blind.lx_location_id.id or False,
#                         })]
#                     })
#                     new_child = self.order_line.filtered(
#                         lambda l: l.product_id.id == motor.id
#                         and l.lx_parent_line_id.id == blind.id
#                         and not l.display_type
#                     )[:1]
#                     if new_child:
#                         new_child._lx_apply_vendor_markdown_if_needed()
#                         motor_child_map.setdefault(blind.id, {})[motor.id] = new_child

#             # ============================================================
#             # PART 2 — Per-location pooled accessories
#             # ============================================================

#             loc_groups = {}
#             loc_order  = []
#             for bl in elect_lines:
#                 k = bl.lx_location_id.id or 0
#                 if k not in loc_groups:
#                     loc_groups[k] = []
#                     loc_order.append(k)
#                 loc_groups[k].append(bl)

#             for loc_key in loc_order:
#                 loc_blinds = loc_groups[loc_key]
#                 non_motor  = [
#                     bl for bl in loc_blinds
#                     if not bl.product_id.lx_is_motor_only_variant()
#                 ]

#                 if not non_motor:
#                     # Motor Only location — remove stale pool children
#                     for bl in loc_blinds:
#                         for _pid, line in list(
#                             pool_child_map.get(bl.id, {}).items()
#                         ):
#                             if line.exists():
#                                 line.with_context(ctx).unlink()
#                     continue

#                 last_blind = non_motor[-1]
#                 pool       = self._lx_compute_location_pool(loc_blinds)
#                 has_remote = pool["total_remote"] > 0
#                 has_smart  = pool["total_smart"]  > 0

#                 # Remote
#                 if has_remote:
#                     self._lx_upsert_child_accessory(
#                         catalog["remote"], pool["remote_needed"],
#                         last_blind, ctx, pool_child_map,
#                     )
#                 else:
#                     r_id = catalog["remote"].id if catalog["remote"] else -1
#                     stale = pool_child_map.get(last_blind.id, {}).get(r_id)
#                     if stale and stale.exists():
#                         stale.with_context(ctx).unlink()

#                 # ZigBee
#                 if has_smart:
#                     self._lx_upsert_child_accessory(
#                         catalog["zigbee"], pool["zigbee_needed"],
#                         last_blind, ctx, pool_child_map,
#                     )
#                 else:
#                     z_id = catalog["zigbee"].id if catalog["zigbee"] else -1
#                     stale = pool_child_map.get(last_blind.id, {}).get(z_id)
#                     if stale and stale.exists():
#                         stale.with_context(ctx).unlink()

#                 # Chargers
#                 c_remote    = catalog["charger_remote"]
#                 c_smart     = catalog["charger_smart"]
#                 c_remote_ok = bool(c_remote and c_remote.exists())
#                 c_smart_ok  = bool(c_smart  and c_smart.exists())

#                 if c_remote_ok and c_smart_ok and c_remote.id == c_smart.id:
#                     combined = (
#                         pool["charger_remote_needed"] + pool["charger_smart_needed"]
#                     )
#                     self._lx_upsert_child_accessory(
#                         c_remote, combined, last_blind, ctx, pool_child_map,
#                     )
#                 else:
#                     if c_remote_ok:
#                         if has_remote:
#                             self._lx_upsert_child_accessory(
#                                 c_remote, pool["charger_remote_needed"],
#                                 last_blind, ctx, pool_child_map,
#                             )
#                         else:
#                             stale = pool_child_map.get(last_blind.id, {}).get(c_remote.id)
#                             if stale and stale.exists():
#                                 stale.with_context(ctx).unlink()
#                     if c_smart_ok:
#                         if has_smart:
#                             self._lx_upsert_child_accessory(
#                                 c_smart, pool["charger_smart_needed"],
#                                 last_blind, ctx, pool_child_map,
#                             )
#                         else:
#                             stale = pool_child_map.get(last_blind.id, {}).get(c_smart.id)
#                             if stale and stale.exists():
#                                 stale.with_context(ctx).unlink()

#             # ============================================================
#             # PART 3 — Sections, subtotals, resequencing
#             # ============================================================
#             self._lx_sync_sections_and_subtotals(ctx)

#         return True

#     # ------------------------------------------------------------------
#     # Line numbering (v2)
#     # ------------------------------------------------------------------

#     def _generate_sequence_numbers_for_lines(self):
#         """
#         Numbering:
#           section headers / subtotal notes  → ""
#           child lines (motor + pooled)      → "1.1", "1.2", "2.1" …
#           storable / blind lines            → "1", "2", "3" …
#           service / shipping / priority     → "#"
#         """
#         for order in self:
#             main_seq   = 0
#             sub_seq    = {}   # {parent_id: int}
#             parent_nos = {}   # {line_id: str}

#             for line in order.order_line.sorted("sequence"):

#                 if (
#                     line.display_type == "line_section"
#                     and line.lx_section_control_type == "__location__"
#                 ):
#                     line.sequence_number = ""
#                     continue

#                 if line.lx_is_electric_subtotal:
#                     line.sequence_number = ""
#                     continue

#                 if line.display_type:
#                     line.sequence_number = ""
#                     continue

#                 if line.lx_parent_line_id:
#                     pid = line.lx_parent_line_id.id
#                     sub_seq[pid] = sub_seq.get(pid, 0) + 1
#                     parent_no    = parent_nos.get(pid, "")
#                     line.sequence_number = (
#                         "%s.%s" % (parent_no, sub_seq[pid]) if parent_no else ""
#                     )
#                     continue

#                 if line.product_template_id:
#                     if line.product_template_id.type in ("consu", "combo", "product"):
#                         main_seq += 1
#                         sn = str(main_seq)
#                         line.sequence_number = sn
#                         parent_nos[line.id]  = sn
#                     else:
#                         line.sequence_number = "#"
#                 elif (
#                     getattr(line, "is_priority_line", False)
#                     or getattr(line, "is_installation_line", False)
#                     or getattr(line, "is_shipping_line", False)
#                 ):
#                     line.sequence_number = "#"
