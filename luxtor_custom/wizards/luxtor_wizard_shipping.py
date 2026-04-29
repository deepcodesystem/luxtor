# -*- coding: utf-8 -*-
import math
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.misc import format_amount


def _get_free_threshold(env):
    ICP = env["ir.config_parameter"].sudo()
    try:
        return float(ICP.get_param("luxtor.lx_free_amount_order", default="5000") or 5000.0)
    except Exception:
        return 5000.0


def _merch_total_excl_services(env, order):
    total = 0.0
    if not order:
        return total

    for line in order.sudo().order_line:
        if line.display_type:
            continue
        if getattr(line, "is_delivery", False):
            continue
        if getattr(line, "is_tip", False):
            continue
        if getattr(line, "is_downpayment", False):
            continue
        if getattr(line, "is_shipping_line", False):
            continue
        if getattr(line, "is_free_shipping_line", False):
            continue
        if _is_service_line(line):
            continue
        total += float(line.price_total or 0.0)
    return float(total)


def _free_applies(env, order):
    threshold = _get_free_threshold(env)
    return bool(order and threshold and _merch_total_excl_services(env, order) >= threshold)


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers (mirror controller, but env-based instead of request.env)
# ─────────────────────────────────────────────────────────────────────────────

def _is_service_line(line):
    p = line.product_id
    if not p or line.display_type:
        return False
    code = (p.default_code or "").strip().upper()
    tcode = (p.product_tmpl_id.default_code or "").strip().upper()
    return code in ("INSTALL_SERVICE", "PRIORITY_SERVICE") or tcode in ("INSTALL_SERVICE", "PRIORITY_SERVICE")


def _is_accessory_product(product):
    if not product:
        return False
    try:
        c = product.categ_id
        if c and ("access" in (c.complete_name or "").lower() or "access" in (c.name or "").lower()):
            return True
    except Exception:
        pass
    return False


def _is_countable_product(product):
    return bool(product and product.type in ("product", "consu"))


def _raw_weight(product):
    try:
        return float(product.weight or 0.0)
    except Exception:
        return 0.0


def _find_bom(env, product):
    try:
        p = product.sudo()
        Bom = env["mrp.bom"].sudo()
        try:
            bom = Bom._bom_find(product=p)
            if bom:
                return bom
        except Exception:
            pass
        tmpl = p.product_tmpl_id.sudo()
        if tmpl:
            try:
                bom = Bom._bom_find(product_tmpl=tmpl)
                if bom:
                    return bom
            except Exception:
                pass
            if getattr(tmpl, "bom_ids", False) and tmpl.bom_ids:
                return tmpl.bom_ids[:1]
    except Exception:
        return False
    return False


def _bom_weight_per_unit_excluding(bom, exclude_ids, exclude_name_tokens):
    """Return weight per unit from BoM, excluding accessory components."""
    if not bom:
        return 0.0
    total = 0.0
    denom = float(bom.product_qty or 1.0) or 1.0
    for bl in bom.bom_line_ids.sudo():
        comp = bl.product_id
        if not comp or not _is_countable_product(comp):
            continue
        if comp.id in exclude_ids:
            continue
        name = (comp.display_name or comp.name or "").lower()
        if any(tok and tok in name for tok in exclude_name_tokens):
            continue
        w = _raw_weight(comp)
        if w <= 0.0:
            continue
        qty = float(bl.product_qty or 0.0)
        total += (w * qty) / denom
    return float(total)


def _is_electric_variant(product):
    try:
        return bool(product and hasattr(product, "lx_is_electric_variant") and product.lx_is_electric_variant())
    except Exception:
        return False


def _is_motor_only_variant(product):
    try:
        return bool(product and hasattr(product, "lx_is_motor_only_variant") and product.lx_is_motor_only_variant())
    except Exception:
        return False


def _is_smartphone_variant(product):
    try:
        return bool(product and hasattr(product, "lx_is_smartphone_controlled_variant") and product.lx_is_smartphone_controlled_variant())
    except Exception:
        return False


def _order_lines_for_shipping(order):
    res = []
    for l in order.order_line:
        if l.display_type:
            continue
        if getattr(l, "is_delivery", False):
            continue
        if getattr(l, "is_tip", False):
            continue
        if getattr(l, "is_downpayment", False):
            continue
        if getattr(l, "is_shipping_line", False):
            continue
        if getattr(l, "is_free_shipping_line", False):
            continue
        if _is_service_line(l):
            continue
        res.append(l)
    return res


# ─────────────────────────────────────────────────────────────────────────────
# Standard: by city (shipping.rate price × parcels)
# ─────────────────────────────────────────────────────────────────────────────

def _compute_standard_price(env, order, shipping_rate):
    """
    Standard price = shipping_rate.price × parcels_total
    Parcels:
      - Each BoM product line: ceil(qty) parcels
      - Accessories (no BoM + accessory category): 1 grouped parcel
      - Extra tangible (no BoM + not accessory): 1 grouped parcel
    Minimum 1 parcel.
    """
    base = float(getattr(shipping_rate, "price", 0.0) or 0.0)
    manufactured_parcels = 0
    has_accessory_group = False
    has_extra_group = False

    for line in _order_lines_for_shipping(order):
        p = line.product_id
        qty_f = float(line.product_uom_qty or 0.0)
        if not p or qty_f <= 0:
            continue
        if not _is_countable_product(p):
            continue
        bom = _find_bom(env, p)
        if bom:
            manufactured_parcels += int(math.ceil(qty_f))
        elif _is_accessory_product(p):
            has_accessory_group = True
        else:
            has_extra_group = True

    parcels_total = (
        manufactured_parcels
        + (1 if has_accessory_group else 0)
        + (1 if has_extra_group else 0)
    )
    if parcels_total <= 0:
        parcels_total = 1

    return float(base * parcels_total)


# ─────────────────────────────────────────────────────────────────────────────
# Express: by weight (virtual BoM weight → bracket price, sum per parcel)
# ─────────────────────────────────────────────────────────────────────────────

def _get_accessory_products(env):
    """
    Return (motor, remote, charger, zigbee) — any that are not found in the
    database are returned as an empty recordset (falsy). Callers skip weight
    contribution for missing products instead of raising.

    For Motor Only orders the tubular motor lives as a SOL child line, not a
    virtual accessory, so it may legitimately not exist under these codes.
    """
    ICP = env["ir.config_parameter"].sudo()
    Product = env["product.product"].sudo()
    empty = Product.browse()

    motor_code   = ICP.get_param("luxtor.motor_code",          "MOTOR_28MM_230V")
    remote_code  = ICP.get_param("luxtor.remote_code",         "REMOTE_15CH")
    charger_code = ICP.get_param("luxtor.charger_code",        "CHARGER_LIION")
    zigbee_name  = ICP.get_param("luxtor.zigbee_gateway_name", "ZigBee")

    motor   = (Product.search([("default_code", "=", motor_code)],  limit=1)
               or Product.search([("name", "=", "Tubular Motor")], limit=1)
               or empty)
    remote  = (Product.search([("default_code", "=", remote_code)], limit=1)
               or Product.search([("name", "=", "Remote Control")], limit=1)
               or empty)
    charger = (Product.search([("default_code", "=", charger_code)], limit=1)
               or Product.search([("name", "=", "Charger")],         limit=1)
               or empty)
    zigbee  = (Product.search([("name", "=", zigbee_name)], limit=1)
               or Product.search([("name", "ilike", "ZigBee")],      limit=1)
               or empty)

    return motor, remote, charger, zigbee


def _get_ratios(env):
    ICP = env["ir.config_parameter"].sudo()
    return (
        max(1, int(ICP.get_param("luxtor.remote_ratio",  5)  or 5)),
        max(1, int(ICP.get_param("luxtor.charger_ratio", 15) or 15)),
        max(1, int(ICP.get_param("luxtor.zigbee_ratio",  30) or 30)),
    )


def _pick_brackets(env, is_intracity):
    kind = "intra" if is_intracity else "inter"
    return env["delivery.bracket.lx"].sudo().search(
        [("kind", "=", kind)], order="max_kg asc"
    )


def _find_bracket(weight, brackets):
    chosen = None
    for b in brackets:
        if (b.min_kg or 0.0) <= weight <= (b.max_kg or 0.0):
            chosen = b
            break
    if not chosen and brackets:
        chosen = brackets[-1]
    return chosen


def _compute_express_price(env, order, is_intracity):
    """
    Express price = sum of bracket.unit_price per parcel.
    Each BoM line = one parcel. Accessories and extras = one grouped parcel each.
    Virtual accessory weight allocated per parcel using electric/motor ratios.
    """
    brackets = _pick_brackets(env, is_intracity)
    if not brackets:
        raise UserError(_("No %s brackets defined.") % ("Intracity" if is_intracity else "Intercity"))

    motor, remote, charger, zigbee = _get_accessory_products(env)
    r_ratio, c_ratio, z_ratio = _get_ratios(env)

    # Build exclusion set only from products that actually exist
    exclude_ids = {p.id for p in (motor, remote, charger, zigbee) if p}
    exclude_name_tokens = ["charger", "zigbee", "remote", "tubular motor", "motor"]

    manufactured = []
    accessory_weight = 0.0
    extra_weight = 0.0

    for line in _order_lines_for_shipping(order):
        p = line.product_id
        qty_f = float(line.product_uom_qty or 0.0)
        if not p or qty_f <= 0:
            continue
        if not _is_countable_product(p):
            continue
        bom = _find_bom(env, p)
        if bom:
            manufactured.append({
                "product": p,
                "bom": bom,
                "qty_float": qty_f,
                "units_ceil": int(math.ceil(qty_f)),
                "alloc": {"motor": 0, "remote": 0, "charger": 0, "zigbee": 0},
            })
        else:
            w = _raw_weight(p) * qty_f
            if _is_accessory_product(p):
                accessory_weight += w
            else:
                extra_weight += w

    # Electric counters for accessory allocation
    motors_total = 0
    non_motor_only = 0
    smartphone = 0
    for m in manufactured:
        u = m["units_ceil"]
        if _is_electric_variant(m["product"]):
            motors_total += u
            if not _is_motor_only_variant(m["product"]):
                non_motor_only += u
                if _is_smartphone_variant(m["product"]):
                    smartphone += u

    # Skip virtual allocation entirely if the accessory products are not in DB.
    # For Motor Only orders the motor/remote/charger are SOL child lines — they
    # are NOT virtual accessories to add here.
    remote_needed  = (int(math.ceil(non_motor_only / r_ratio)) if non_motor_only > 0 else 0) if remote  else 0
    charger_needed = (int(math.ceil(non_motor_only / c_ratio)) if non_motor_only > 0 else 0) if charger else 0
    zigbee_needed  = (int(math.ceil(smartphone / z_ratio))     if smartphone > 0 else 0)      if zigbee  else 0

    # Allocate motor weight per electric parcel (only if motor product exists)
    if motor:
        for m in manufactured:
            if _is_electric_variant(m["product"]):
                m["alloc"]["motor"] = m["units_ceil"]

    # Greedy allocation for remote/charger/zigbee
    def _pack(kind, needed, coverage, eligible_fn):
        remaining = int(needed or 0)
        if remaining <= 0:
            return
        for m in manufactured:
            if remaining <= 0:
                break
            if not eligible_fn(m):
                continue
            left = m["units_ceil"]
            while remaining > 0 and left > 0:
                m["alloc"][kind] += 1
                remaining -= 1
                left -= coverage
        # fallback: dump remainder on first parcel
        if remaining > 0 and manufactured:
            manufactured[0]["alloc"][kind] += remaining

    _pack("remote",  remote_needed,  r_ratio, lambda m: _is_electric_variant(m["product"]) and not _is_motor_only_variant(m["product"]))
    _pack("charger", charger_needed, c_ratio, lambda m: _is_electric_variant(m["product"]) and not _is_motor_only_variant(m["product"]))
    _pack("zigbee",  zigbee_needed,  z_ratio, lambda m: _is_electric_variant(m["product"]) and not _is_motor_only_variant(m["product"]) and _is_smartphone_variant(m["product"]))

    def _price_for_weight(w):
        if w <= 0.0:
            return 0.0
        br = _find_bracket(w, brackets)
        if not br:
            raise UserError(_("No matching bracket for weight %.2f kg.") % w)
        return float(br.unit_price or 0.0)

    total_price = 0.0

    for m in manufactured:
        bw = _bom_weight_per_unit_excluding(m["bom"], exclude_ids, exclude_name_tokens) * m["qty_float"]
        # Only add virtual accessory weight if the product was found in DB
        mw = (_raw_weight(motor)   * float(m["alloc"]["motor"]   or 0)) if motor   else 0.0
        rw = (_raw_weight(remote)  * float(m["alloc"]["remote"]  or 0)) if remote  else 0.0
        cw = (_raw_weight(charger) * float(m["alloc"]["charger"] or 0)) if charger else 0.0
        zw = (_raw_weight(zigbee)  * float(m["alloc"]["zigbee"]  or 0)) if zigbee  else 0.0
        total_price += _price_for_weight(bw + mw + rw + cw + zw)

    if accessory_weight > 0.0:
        total_price += _price_for_weight(accessory_weight)
    if extra_weight > 0.0:
        total_price += _price_for_weight(extra_weight)

    return float(total_price)


# ─────────────────────────────────────────────────────────────────────────────
# Wizard
# ─────────────────────────────────────────────────────────────────────────────

class SaleOrderShippingWizard(models.TransientModel):
    _name = "sale.order.shipping.wizard"
    _description = "Shipping Method Wizard"

    def _default_order(self):
        aid = self.env.context.get("active_id")
        return self.env["sale.order"].browse(aid).id if aid else False

    def _default_method(self):
        order = self.env["sale.order"].browse(self.env.context.get("active_id"))
        return (getattr(order, "shipping_method_type", False) or "standard") if order else "standard"

    # ── Fields ────────────────────────────────────────────────────────────────
    order_id = fields.Many2one(
        "sale.order", string="Order", required=True, readonly=True,
        default=_default_order,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="order_id.currency_id",
        readonly=True,
        store=False,
    )
    shipping_method = fields.Selection(
        [("standard", "Standard (by City)"), ("express", "Express (by Weight)")],
        string="Shipping Method",
        required=True,
        default=_default_method,
    )
    city_id = fields.Many2one(
        "shipping.rate", string="City / Zone",
        help="Required for Standard shipping. Determines the base price per parcel.",
    )
    # Computed display fields (readonly, auto-filled on open / onchange)
    price = fields.Float(
        string="Computed Price",
        readonly=True,
        help="Computed automatically from city/weight rules.",
    )
    is_free = fields.Boolean(
        compute="_compute_is_free", store=False,
        string="Free Shipping",
    )
    free_note = fields.Char(
        compute="_compute_free_note", store=False, readonly=True,
    )

    # ── Computes ──────────────────────────────────────────────────────────────
    @api.depends("order_id.amount_total", "shipping_method")
    def _compute_is_free(self):
        for w in self:
            w.is_free = _free_applies(w.env, w.order_id)

    @api.depends("order_id.amount_total", "order_id.currency_id")
    def _compute_free_note(self):
        for w in self:
            if not w.order_id:
                w.free_note = ""
                continue
            threshold = _get_free_threshold(w.env)
            if not threshold:
                w.free_note = ""
                continue
            currency = w.order_id.currency_id or w.env.company.currency_id
            w.free_note = _(
                "* Free delivery applies to all delivery methods once the eligible order total reaches %s"
            ) % format_amount(w.env, threshold, currency)

    # ── Internal price computation ────────────────────────────────────────────
    def _compute_price(self):
        """Return computed price for current state. Returns 0.0 if free."""
        self.ensure_one()
        order = self.order_id
        if not order:
            return 0.0

        # Free threshold check
        if _free_applies(self.env, order):
            return 0.0

        if self.shipping_method == "standard":
            if not self.city_id:
                return 0.0
            return _compute_standard_price(self.env, order, self.city_id)

        # Express: detect intracity from shipping address zip → shipping.rate
        zip_code = (order.partner_shipping_id.zip or "").strip()
        shipping_rate = self.env["shipping.rate"].sudo().search(
            [("zip_code", "=", zip_code)], limit=1
        ) if zip_code else False
        is_intracity = bool(shipping_rate and shipping_rate.is_intracity)
        return _compute_express_price(self.env, order, is_intracity)

    # ── default_get: prefill price on open ───────────────────────────────────
    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        order = self.env["sale.order"].browse(self.env.context.get("active_id"))
        if not order:
            return res
        res.setdefault("order_id", order.id)
        res.setdefault("shipping_method", getattr(order, "shipping_method_type", False) or "standard")

        # Pre-fill saved city
        if getattr(order, "shipping_city_id", False):
            res.setdefault("city_id", order.shipping_city_id.id)

        return res

    # ── Onchange: recompute price whenever method or city changes ─────────────
    @api.onchange("shipping_method", "city_id")
    def _onchange_reprice(self):
        for w in self:
            try:
                w.price = w._compute_price()
            except UserError as e:
                w.price = 0.0
                return {"warning": {"title": _("Shipping"), "message": str(e)}}

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _next_shipping_sequence(self, order):
        goods_lines = order.order_line.filtered(
            lambda l: l.product_template_id and l.product_template_id.type != "service"
        )
        if goods_lines:
            return max(goods_lines.mapped("sequence")) + 1
        return max(order.order_line.mapped("sequence") or [10]) + 1

    def _variant_from_xmlid(self, xmlid):
        tmpl = self.env.ref(xmlid, raise_if_not_found=False)
        if not tmpl:
            raise UserError(_("Missing product template: %s") % xmlid)
        product = tmpl.product_variant_id
        if not product:
            product = self.env["product.product"].create({"product_tmpl_id": tmpl.id})
        return product

    # ── Confirm ───────────────────────────────────────────────────────────────
    def action_confirm(self):
        for w in self:
            order = w.order_id
            if not order:
                continue

            # Remove existing shipping lines
            order.order_line.filtered(
                lambda l: getattr(l, "is_shipping_line", False) or getattr(l, "is_free_shipping_line", False)
            ).unlink()

            seq = self._next_shipping_sequence(order)

            # Recompute final price at confirm time
            try:
                final_price = w._compute_price()
            except UserError as e:
                raise UserError(str(e))

            is_free = _free_applies(w.env, order)

            if is_free or final_price == 0.0:
                free_prod = self._variant_from_xmlid("luxtor_custom.prod_free_delivery_tmpl")
                order.write({
                    "shipping_method_type": w.shipping_method,
                    "shipping_city_id": w.city_id.id if w.city_id else False,
                    "shipping_quantity": 0,
                    "shipping_price": 0.0,
                })
                self.env["sale.order.line"].create({
                    "order_id":         order.id,
                    "name":             free_prod.display_name or _("Free Delivery"),
                    "product_id":       free_prod.id,
                    "product_uom_id":   free_prod.uom_id.id,
                    "product_uom_qty":  1,
                    "price_unit":       0.0,
                    "sequence":         seq,
                    "is_free_shipping_line": True,
                    "lx_width_m": False, "lx_height_m": False, "size": False,
                })
            else:
                ship_prod = self._variant_from_xmlid("luxtor_custom.prod_shipping_service_tmpl")
                city_label = f" ({w.city_id.name})" if w.city_id else ""
                order.write({
                    "shipping_method_type": w.shipping_method,
                    "shipping_city_id":     w.city_id.id if w.city_id else False,
                    "shipping_quantity":    0,
                    "shipping_price":       final_price,
                })
                self.env["sale.order.line"].create({
                    "order_id":        order.id,
                    "name":            (ship_prod.display_name or _("Shipping")) + city_label,
                    "product_id":      ship_prod.id,
                    "product_uom_id":  ship_prod.uom_id.id,
                    "product_uom_qty": 1,
                    "price_unit":      final_price,
                    "sequence":        seq,
                    "is_shipping_line": True,
                    "lx_width_m": False, "lx_height_m": False, "size": False,
                })

            if hasattr(order, "_generate_sequence_numbers_for_lines"):
                order._generate_sequence_numbers_for_lines()

        return {"type": "ir.actions.act_window_close"}
