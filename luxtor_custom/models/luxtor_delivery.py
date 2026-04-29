# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


# ---------------------------------------------------------
# 1) Carrier config (LX layer)
# ---------------------------------------------------------
class DeliveryCarrierLx(models.Model):
    _name = "delivery.carrier.lx"
    _description = "Luxtor Delivery Carrier Config"
    _rec_name = "carrier_id"
    _order = "carrier_id"

    carrier_id = fields.Many2one(
        "delivery.carrier",
        string="Website Delivery Method",
        required=True,
        ondelete="cascade",
        index=True,
    )

    mode = fields.Selection(
        [
            ("standard", "Standard (City/ZIP price)"),
            ("express", "Express (Weight brackets)"),
        ],
        string="Mode",
        required=True,
        default="standard",
        index=True,
    )

    active = fields.Boolean(default=True, index=True)

    # If 0 -> use global ir.config_parameter luxtor.lx_free_amount_order
    free_threshold = fields.Float(string="Free Shipping Threshold", default=0.0)

    _sql_constraints = [
        ("carrier_unique", "unique(carrier_id)", "This carrier already has an LX configuration."),
    ]

    @api.constrains("free_threshold")
    def _check_free_threshold(self):
        for rec in self:
            if rec.free_threshold < 0:
                raise ValidationError(_("Free Shipping Threshold cannot be negative."))

    # -------------------------
    # Helpers used by controller
    # -------------------------
    def lx_get_threshold(self):
        """
        Threshold resolution:
        - per carrier_lx threshold if set (>0)
        - else global icp (luxtor.lx_free_amount_order)
        """
        self.ensure_one()
        if float(self.free_threshold or 0.0) > 0:
            return float(self.free_threshold or 0.0)

        ICP = self.env["ir.config_parameter"].sudo()
        val = ICP.get_param("luxtor.lx_free_amount_order", default="5000")
        try:
            return float(val or 0.0)
        except Exception:
            return 5000.0

    def lx_session_force_free(self):
        """True if session is forcing free shipping."""
        # NOTE: request is only available in HTTP context.
        try:
            from odoo.http import request
            return bool(request.session.get("lx_free_force", False))
        except Exception:
            return False

    def lx_merch_total_excl_services(self, order):
        """
        Merch total excluding:
        - delivery lines
        - tips
        - downpayments
        - display lines
        - service products: INSTALL_SERVICE / PRIORITY_SERVICE (code or template code)
        """
        total = 0.0
        if not order:
            return total

        for l in order.sudo().order_line:
            if l.display_type:
                continue
            if getattr(l, "is_delivery", False):
                continue
            if getattr(l, "is_tip", False):
                continue
            if getattr(l, "is_downpayment", False):
                continue

            p = l.product_id
            if not p:
                continue
            code = (p.default_code or "").strip().upper()
            tcode = (p.product_tmpl_id.default_code or "").strip().upper()
            if code in ("INSTALL_SERVICE", "PRIORITY_SERVICE") or tcode in ("INSTALL_SERVICE", "PRIORITY_SERVICE"):
                continue

            total += float(l.price_total or 0.0)
        return total

    def lx_apply_free_logic(self, order, raw_price=0.0):
        """
        Apply free shipping:
        1) session force -> free
        2) threshold (merch total excl services) >= threshold -> free
        Return: (final_price, free_applied, free_reason, threshold_used, merch_total, forced)
        """
        self.ensure_one()

        forced = self.lx_session_force_free()
        merch_total = self.lx_merch_total_excl_services(order)
        threshold_used = self.lx_get_threshold()

        if forced:
            return 0.0, True, "session_forced", threshold_used, merch_total, True

        if threshold_used and merch_total >= threshold_used:
            return 0.0, True, "order_amount_over_threshold", threshold_used, merch_total, False

        return float(raw_price or 0.0), False, None, threshold_used, merch_total, False


# ---------------------------------------------------------
# 2) Weight brackets (intracity / intercity)
# ---------------------------------------------------------
class DeliveryBracket(models.Model):
    _name = "delivery.bracket.lx"
    _description = "Weight pricing bracket (intracity/intercity)"
    _order = "carrier_id, kind, min_kg, max_kg"

    KIND_SELECTION = [
        ("intra", "Intracity"),
        ("inter", "Intercity"),
    ]

    # Keep for backward compatibility / existing records
    carrier_id = fields.Many2one(
        "delivery.carrier",
        string="Carrier",
        required=False,
        ondelete="cascade",
        index=True,
    )

    # NEW link used by controller
    carrier_lx_id = fields.Many2one(
        "delivery.carrier.lx",
        string="LX Carrier Config",
        required=False,
        ondelete="cascade",
        index=True,
        help="If empty, it can be auto-filled from Carrier when possible.",
    )

    kind = fields.Selection(KIND_SELECTION, required=True, index=True)
    min_kg = fields.Float(string="Min (Kg)", required=True, index=True)
    max_kg = fields.Float(string="Max (Kg)", required=True, index=True)
    unit_price = fields.Float(string="Unit Price", required=True)

    @api.constrains("min_kg", "max_kg")
    def _check_range(self):
        for rec in self:
            if rec.min_kg < 0 or rec.max_kg <= 0 or rec.max_kg <= rec.min_kg:
                raise ValidationError(_("Invalid bracket range."))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._lx_sync_carrier_lx()
        return records

    def write(self, vals):
        res = super().write(vals)
        self._lx_sync_carrier_lx()
        return res

    def _lx_sync_carrier_lx(self):
        """Auto-link carrier_lx_id from carrier_id (backward compatible)."""
        for rec in self:
            if rec.carrier_lx_id or not rec.carrier_id:
                continue
            lx = self.env["delivery.carrier.lx"].sudo().search(
                [("carrier_id", "=", rec.carrier_id.id)],
                limit=1,
            )
            if lx:
                rec.sudo().carrier_lx_id = lx.id


# ---------------------------------------------------------
# 3) City / ZIP rate table
# ---------------------------------------------------------
class ShippingRate(models.Model):
    _name = "shipping.rate"
    _description = "City Shipping Rate"
    _order = "name"

    name = fields.Char(string="City/Suburb", required=True)
    province = fields.Char(string="Province")
    zip_code = fields.Char(string="Zip Code", index=True)
    delivery_eta = fields.Char(string="Range Date", help="Example: '24h - 48h'")
    price = fields.Float(string="Price", default=0.0)

    is_intracity = fields.Boolean(
        string="Intracity",
        help="Bill this destination with the Intracity weight brackets.",
        default=False,
    )

    _sql_constraints = [
        ("name_unique", "unique(name)", "Each city/suburb must be unique."),
    ]


# ---------------------------------------------------------
# 4) Pure-python helpers (shared logic for controller)
#    (kept here as "delivery helpers" as you requested)
# ---------------------------------------------------------

def lx_raw_weight(product):
    """Return product.weight as float, or 0.0 if missing/invalid."""
    try:
        return float(product.weight or 0.0)
    except Exception:
        return 0.0


def lx_is_countable_product(product):
    """Only count storable/consumable items. Services are excluded."""
    return bool(product and product.type in ("product", "consu"))


def lx_has_bom(product):
    """True if product has an MRP BoM (template or variant)."""
    if not product:
        return False
    if hasattr(product, "bom_count") and product.bom_count:
        return True
    tmpl = product.product_tmpl_id
    return bool((getattr(product, "bom_ids", False) and product.bom_ids) or (tmpl and tmpl.bom_ids))


def lx_pick_brackets(env, carrier_lx, is_intracity):
    """Fetch brackets for LX carrier config + city kind."""
    kind = "intra" if is_intracity else "inter"
    return env["delivery.bracket.lx"].sudo().search(
        [("carrier_lx_id", "=", carrier_lx.id), ("kind", "=", kind)],
        order="max_kg asc",
    )


def lx_find_bracket_for_weight(weight, brackets):
    """Find bracket where min_kg <= weight <= max_kg; fallback to highest."""
    chosen = None
    for b in brackets:
        if (b.min_kg or 0.0) <= weight <= (b.max_kg or 0.0):
            chosen = b
            break
    if not chosen and brackets:
        chosen = brackets[-1]
    return chosen


def lx_order_lines_for_weight(order):
    """
    Lines to consider for shipping weight pricing:
    exclude display/delivery/tip/downpayment lines.
    """
    res = []
    for l in order.sudo().order_line:
        if l.display_type:
            continue
        if getattr(l, "is_delivery", False):
            continue
        if getattr(l, "is_tip", False):
            continue
        if getattr(l, "is_downpayment", False):
            continue
        res.append(l)
    return res


def lx_compute_express_raw_price(env, order, carrier_lx, is_intracity):
    """
    EXPRESS raw price (before free logic):
    - services excluded (type=service)
    - zero-weight ignored
    - BoM products priced per-unit by bracket selected using unit weight
    - Non-BoM products aggregated by total weight and charged once
    Returns: (raw_total, per_line_debug)
    """
    brackets = lx_pick_brackets(env, carrier_lx, is_intracity)
    if not brackets:
        raise UserError(_("No %s brackets found for this Express carrier.") % (
            "Intracity" if is_intracity else "Intercity"
        ))

    raw_total = 0.0
    per_line_debug = []
    non_bom_total_weight = 0.0

    for line in lx_order_lines_for_weight(order):
        p = line.product_id
        qty = float(line.product_uom_qty or 0.0)
        if not p:
            continue

        # Exclude services
        if not lx_is_countable_product(p):
            per_line_debug.append({
                "product": p.display_name,
                "has_bom": False,
                "qty": qty,
                "unit_weight_for_bracket": 0.0,
                "bracket": None,
                "per_unit_shipping_price": 0.0,
                "line_shipping": 0.0,
                "note": "ignored (service type)",
            })
            continue

        w = lx_raw_weight(p)
        if w <= 0.0:
            per_line_debug.append({
                "product": p.display_name,
                "has_bom": lx_has_bom(p),
                "qty": qty,
                "unit_weight_for_bracket": 0.0,
                "bracket": None,
                "per_unit_shipping_price": 0.0,
                "line_shipping": 0.0,
                "note": "ignored (no weight)",
            })
            continue

        if not lx_has_bom(p):
            non_bom_total_weight += w * qty
            per_line_debug.append({
                "product": p.display_name,
                "has_bom": False,
                "qty": qty,
                "unit_weight_for_bracket": 0.0,
                "bracket": None,
                "per_unit_shipping_price": 0.0,
                "line_shipping": 0.0,
                "note": "aggregated later (no BoM, weight>0)",
            })
            continue

        # BoM product: per unit bracket
        unit_w = w
        br = lx_find_bracket_for_weight(unit_w, brackets)
        if not br:
            raise UserError(_("No matching bracket for unit weight %.2f kg.") % unit_w)

        per_unit_price = float(br.unit_price or 0.0)
        line_total = per_unit_price * qty
        raw_total += line_total

        per_line_debug.append({
            "product": p.display_name,
            "has_bom": True,
            "qty": qty,
            "unit_weight_for_bracket": unit_w,
            "bracket": {
                "min_kg": float(br.min_kg or 0.0),
                "max_kg": float(br.max_kg or 0.0),
                "unit_price": per_unit_price,
            },
            "per_unit_shipping_price": per_unit_price,
            "line_shipping": line_total,
            "note": "counted (BoM, weight>0)",
        })

    # Aggregate non-BoM
    if non_bom_total_weight > 0.0:
        br = lx_find_bracket_for_weight(non_bom_total_weight, brackets)
        if not br:
            raise UserError(_("No matching bracket for total non-BoM weight %.2f kg.") % non_bom_total_weight)

        agg_price = float(br.unit_price or 0.0)
        raw_total += agg_price

        per_line_debug.append({
            "product": "Non-BoM aggregated",
            "has_bom": False,
            "qty": 1.0,
            "unit_weight_for_bracket": non_bom_total_weight,
            "bracket": {
                "min_kg": float(br.min_kg or 0.0),
                "max_kg": float(br.max_kg or 0.0),
                "unit_price": float(br.unit_price or 0.0),
            },
            "per_unit_shipping_price": float(br.unit_price or 0.0),
            "line_shipping": agg_price,
            "note": "counted as 1 unit (sum of non-BoM weights)",
        })

    return float(raw_total or 0.0), per_line_debug
