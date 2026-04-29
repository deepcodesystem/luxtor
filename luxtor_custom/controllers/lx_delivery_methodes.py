# -*- coding: utf-8 -*-
import logging
import traceback
import math

from odoo import http, _
from odoo.http import request
from odoo.exceptions import UserError

from odoo.addons.website_sale.controllers.main import WebsiteSale

_logger = logging.getLogger(__name__)


def _lx_sale_get_order(force_create=False):
    """V19-compatible cart order getter — replaces website.sale_get_order()."""
    try:
        return request.website.sale_get_order(force_create=force_create)
    except AttributeError:
        pass
    # V19: session-based fallback
    Order = request.env['sale.order'].sudo()
    order_id = request.session.get('sale_order_id')
    if order_id:
        order = Order.browse(int(order_id)).exists()
        if order:
            return order
    return Order.browse()

# ---------------------------------------------------------
# FREE logic helpers (KEEP)
# ● Standard: City: Fix Accessories as one Parcel
# ● Express: Weight: Total of BoM Components Weight (VIRTUAL MOs)
# ---------------------------------------------------------

def _get_free_threshold():
    ICP = request.env["ir.config_parameter"].sudo()
    val = ICP.get_param("luxtor.lx_free_amount_order", default="5000")
    try:
        return float(val or 0.0)
    except Exception:
        return 5000.0


def _is_service_line(line):
    p = line.product_id
    if not p or line.display_type:
        return False
    code = (p.default_code or "").strip().upper()
    tcode = (p.product_tmpl_id.default_code or "").strip().upper()
    return code in ("INSTALL_SERVICE", "PRIORITY_SERVICE") or tcode in ("INSTALL_SERVICE", "PRIORITY_SERVICE")


def _merch_total_excl_services(order):
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
        if _is_service_line(l):
            continue
        total += float(l.price_total or 0.0)
    return total


def _apply_free_logic(order, raw_price):
    forced = bool(request.session.get("lx_free_force", False))
    threshold = _get_free_threshold()
    merch_total = _merch_total_excl_services(order)

    if forced:
        return 0.0, True, "session_forced", threshold, merch_total, True

    if threshold and merch_total >= threshold:
        return 0.0, True, "order_amount_over_threshold", threshold, merch_total, False

    return float(raw_price or 0.0), False, None, threshold, merch_total, False


def _lx_free_applies(order):
    threshold = _get_free_threshold()
    merch_total = _merch_total_excl_services(order)
    return bool(order and threshold and merch_total >= threshold)


def _lx_find_standard_carrier():
    Carrier = request.env["delivery.carrier"].sudo()
    carrier = Carrier.search([("name", "=ilike", "Standard Delivery")], limit=1)
    if carrier:
        return carrier
    return Carrier.search([("name", "ilike", "standard")], limit=1)


def _lx_force_standard_carrier_if_free(order):
    if not order or not order._has_deliverable_products() or not _lx_free_applies(order):
        return False
    carrier = _lx_find_standard_carrier()
    if not carrier:
        return False
    return bool(_apply_delivery_line(order, carrier, 0.0))


def _lx_inject_free_flags(ctx, order):
    if ctx is None:
        return
    threshold = _get_free_threshold()
    merch_total = _merch_total_excl_services(order) if order else 0.0
    ctx["lx_free_threshold"] = threshold
    ctx["lx_merch_total"] = merch_total
    ctx["lx_free_applies"] = bool(order and threshold and merch_total >= threshold)


# ---------------------------------------------------------
# STANDARD city-rate helpers (shipping.rate by zip)
# ---------------------------------------------------------
def _lookup_shipping_rate(zip_code):
    if not zip_code:
        return False
    return request.env["shipping.rate"].sudo().search([("zip_code", "=", zip_code)], limit=1)


# ---------------------------------------------------------
# Apply carrier + delivery line on order (robust)
# ---------------------------------------------------------
def _apply_delivery_line(order, carrier, price):
    order_sudo = order.sudo()

    try:
        order_sudo.write({"carrier_id": carrier.id})
    except Exception:
        pass

    for meth in ("set_delivery_line", "_set_delivery_line", "_create_delivery_line"):
        fn = getattr(order_sudo, meth, None)
        if not fn:
            continue
        try:
            fn(carrier, price)
            return True
        except TypeError:
            try:
                fn(carrier)
                try:
                    dl = order_sudo.order_line.filtered(lambda l: getattr(l, "is_delivery", False))[:1]
                    if dl:
                        dl.write({"price_unit": float(price or 0.0)})
                except Exception:
                    pass
                return True
            except Exception:
                continue
        except Exception:
            continue

    try:
        dl = order_sudo.order_line.filtered(lambda l: getattr(l, "is_delivery", False))[:1]
        if dl:
            dl.write({"price_unit": float(price or 0.0)})
            return True
    except Exception:
        pass

    return False


# ---------------------------------------------------------
# Currency payload (optional for frontend formatting)
# ---------------------------------------------------------
def _currency_payload(order):
    cur = order.currency_id
    return {
        "name": cur.name,
        "symbol": cur.symbol or "",
        "position": cur.position or "after",
        "decimal_places": int(cur.decimal_places or 2),
    }


# ---------------------------------------------------------
# Debug helpers
# ---------------------------------------------------------
def _err_name(e):
    try:
        return e.__class__.__name__
    except Exception:
        return "Exception"


def _short_trace(limit_lines=35):
    try:
        tb = traceback.format_exc()
        lines = (tb or "").splitlines()
        if len(lines) > limit_lines:
            lines = lines[-limit_lines:]
        return "\n".join(lines)
    except Exception:
        return ""


def _save_last_debug(payload):
    try:
        request.session["lx_last_debug"] = payload
    except Exception:
        pass


# ---------------------------------------------------------
# STANDARD "Accessories as ONE parcel" helpers
# ---------------------------------------------------------
def _is_accessory_product(product):
    """Heuristic (safe): match internal category OR website categories containing 'access'."""
    if not product:
        return False
    try:
        c = product.categ_id
        if c and ("access" in (c.complete_name or "").lower() or "access" in (c.name or "").lower()):
            return True
    except Exception:
        pass
    try:
        pubs = product.public_categ_ids
        for pc in pubs:
            if "access" in (pc.name or "").lower():
                return True
    except Exception:
        pass
    return False


def _std_order_lines_for_parcels(order):
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
        if _is_service_line(l):
            continue
        res.append(l)
    return res


# def _compute_standard_city_raw_price(order, shipping_rate):
#     """
#     STANDARD raw price:
#     - base = shipping.rate.price (ZIP)
#     - parcels:
#         * 1 parcel if blinds exist (qty ignored)
#         * +1 parcel if any other tangible exists (qty ignored, grouped)
#       => max 2 parcels, min 1
#     """
#     base = float(getattr(shipping_rate, "price", 0.0) or 0.0)

#     has_blind = False
#     has_other_tangible = False
#     per_line_debug = []

#     def _is_roller_blind_line(line):
#         p = line.product_id
#         if not p or line.display_type:
#             return False
#         if hasattr(p.product_tmpl_id, "lx_is_blind"):
#             return bool(getattr(p.product_tmpl_id, "lx_is_blind", False))
#         return "roller blind" in (p.display_name or "").lower()

#     def _is_tubular_motor(product):
#         try:
#             name = (product.display_name or "").lower()
#             code = (product.default_code or "").lower()
#             return ("tubular motor" in name) or code.startswith("dm")
#         except Exception:
#             return False

#     for line in _std_order_lines_for_parcels(order):
#         p = line.product_id
#         qty = float(line.product_uom_qty or 0.0)
#         if not p or qty <= 0:
#             continue

#         if _is_roller_blind_line(line):
#             has_blind = True
#             per_line_debug.append({
#                 "product": p.display_name,
#                 "qty": qty,
#                 "bucket": "roller_blind",
#                 "parcels_counted": 0,
#                 "note": "blind exists => contributes to +1 blind parcel (qty ignored)",
#             })
#             continue

#         if _is_tubular_motor(p):
#             per_line_debug.append({
#                 "product": p.display_name,
#                 "qty": qty,
#                 "bucket": "included_in_blind",
#                 "parcels_counted": 0,
#                 "note": "ignored (tubular motor included in blind parcel)",
#             })
#             continue

#         if p.type in ("product", "consu"):
#             has_other_tangible = True
#             per_line_debug.append({
#                 "product": p.display_name,
#                 "qty": qty,
#                 "bucket": "other_tangible_group",
#                 "parcels_counted": 0,
#                 "note": "tangible exists => contributes to +1 grouped parcel (qty ignored)",
#             })
#             continue

#         per_line_debug.append({
#             "product": p.display_name,
#             "qty": qty,
#             "bucket": "ignored",
#             "parcels_counted": 0,
#             "note": "ignored (not tangible)",
#         })

#     blind_parcels = 1 if has_blind else 0
#     other_parcel = 1 if has_other_tangible else 0

#     parcels_total = blind_parcels + other_parcel
#     if parcels_total <= 0:
#         parcels_total = 1

#     raw = base * float(parcels_total)

#     return float(raw), {
#         "base_zip_price": base,
#         "blind_parcels": blind_parcels,
#         "other_accessories_parcel": other_parcel,
#         "parcels_total": int(parcels_total),
#         "lines": per_line_debug,
#         "formula": "raw = base_zip_price * ((1 if blinds exist else 0) + (1 if other tangible exists else 0))",
#     }

def _compute_standard_city_raw_price(order, shipping_rate):
    """
    STANDARD (by city) raw price:
    - base = shipping.rate.price (ZIP)

    Parcels:
      - Each BoM/manufactured product line contributes ceil(qty) parcels (qty applied).
      - Accessories (no BoM + accessory category) are grouped into ONE parcel if present.
      - Extra tangible (no BoM + not accessory) are grouped into ONE separate parcel if present.

    raw = base * parcels_total, with a minimum of 1 parcel.
    """
    base = float(getattr(shipping_rate, "price", 0.0) or 0.0)

    manufactured_parcels = 0
    has_accessory_group = False
    has_extra_group = False
    per_line_debug = []

    for line in _std_order_lines_for_parcels(order):
        p = line.product_id
        qty_f = float(line.product_uom_qty or 0.0)
        if not p or qty_f <= 0:
            continue

        if not _lx_is_countable_product(p):
            per_line_debug.append({
                "product": p.display_name if p else None,
                "qty": qty_f,
                "bucket": "ignored",
                "parcels_counted": 0,
                "note": "ignored (not tangible/countable)",
            })
            continue

        bom = _lx_find_bom_sudo(p)
        if bom:
            parcels = int(math.ceil(qty_f))
            manufactured_parcels += parcels
            per_line_debug.append({
                "product": p.display_name,
                "qty": qty_f,
                "bucket": "manufactured_bom",
                "bom_id": bom.id,
                "parcels_counted": parcels,
                "note": "BoM found => parcels += ceil(qty)",
            })
            continue

        # no BoM => accessory vs extra tangible grouping
        if _is_accessory_product(p):
            has_accessory_group = True
            per_line_debug.append({
                "product": p.display_name,
                "qty": qty_f,
                "bucket": "accessory_grouped",
                "parcels_counted": 0,
                "note": "no BoM + accessory => grouped into 1 parcel (if any present)",
            })
        else:
            has_extra_group = True
            per_line_debug.append({
                "product": p.display_name,
                "qty": qty_f,
                "bucket": "extra_tangible_grouped",
                "parcels_counted": 0,
                "note": "no BoM + not accessory => grouped into 1 separate parcel (if any present)",
            })

    parcels_total = int(manufactured_parcels) + (1 if has_accessory_group else 0) + (1 if has_extra_group else 0)
    if parcels_total <= 0:
        parcels_total = 1

    raw = base * float(parcels_total)

    return float(raw), {
        "base_zip_price": base,
        "manufactured_bom_parcels": int(manufactured_parcels),
        "accessories_group_parcel": 1 if has_accessory_group else 0,
        "extra_tangible_group_parcel": 1 if has_extra_group else 0,
        "parcels_total": int(parcels_total),
        "lines": per_line_debug,
        "formula": "raw = base_zip_price * (sum ceil(qty) for BoM lines + (1 if any accessory(no BoM) else 0) + (1 if any extra tangible(no BoM, not accessory) else 0))",
    }



# ---------------------------------------------------------
# Weight helpers (Express) - VIRTUAL MO simulation
# ---------------------------------------------------------

def _lx_get_accessory_products_for_weight():
    """Same lookup logic as your SaleOrder._lx_get_accessory_products but safe in controller."""
    Product = request.env["product.product"].sudo()
    ICP = request.env["ir.config_parameter"].sudo()
    empty = Product.browse()

    motor_code = ICP.get_param("luxtor.motor_code", "MOTOR_28MM_230V")
    remote_code = ICP.get_param("luxtor.remote_code", "REMOTE_15CH")
    charger_code = ICP.get_param("luxtor.charger_code", "CHARGER_LIION")
    zigbee_name = ICP.get_param("luxtor.zigbee_gateway_name", "ZigBee")

    motor = ((Product.search([("default_code", "=", motor_code)], limit=1)
             or Product.search([("name", "=", "Tubular Motor")], limit=1))
             or empty)
    remote = ((Product.search([("default_code", "=", remote_code)], limit=1)
              or Product.search([("name", "=", "Remote Control")], limit=1))
              or empty)
    charger = ((Product.search([("default_code", "=", charger_code)], limit=1)
               or Product.search([("name", "=", "Charger")], limit=1))
               or empty)
    zigbee = ((Product.search([("name", "=", zigbee_name)], limit=1)
              or Product.search([("name", "ilike", "ZigBee")], limit=1))
              or empty)

    return motor, remote, charger, zigbee


def _lx_get_ratios_for_weight():
    ICP = request.env["ir.config_parameter"].sudo()
    r_ratio = max(1, int(ICP.get_param("luxtor.remote_ratio", 5) or 5))
    c_ratio = max(1, int(ICP.get_param("luxtor.charger_ratio", 15) or 15))
    z_ratio = max(1, int(ICP.get_param("luxtor.zigbee_ratio", 30) or 30))
    return r_ratio, c_ratio, z_ratio


def _lx_is_electric_variant_product(product):
    try:
        return bool(product and hasattr(product, "lx_is_electric_variant") and product.lx_is_electric_variant())
    except Exception:
        return False


def _lx_is_motor_only_variant_product(product):
    try:
        return bool(product and hasattr(product, "lx_is_motor_only_variant") and product.lx_is_motor_only_variant())
    except Exception:
        return False


def _lx_is_smartphone_variant_product(product):
    try:
        return bool(product and hasattr(product, "lx_is_smartphone_controlled_variant") and product.lx_is_smartphone_controlled_variant())
    except Exception:
        return False


def _lx_raw_weight(product):
    try:
        return float(product.weight or 0.0)
    except Exception:
        return 0.0


def _lx_is_countable_product(product):
    return bool(product and product.type in ("product", "consu"))


def _lx_pick_brackets_by_kind(is_intracity):
    kind = "intra" if is_intracity else "inter"
    return request.env["delivery.bracket.lx"].sudo().search(
        [("kind", "=", kind)],
        order="max_kg asc",
    )


def _lx_find_bracket_for_weight(weight, brackets):
    chosen = None
    for b in brackets:
        if (b.min_kg or 0.0) <= weight <= (b.max_kg or 0.0):
            chosen = b
            break
    if not chosen and brackets:
        chosen = brackets[-1]
    return chosen


def _lx_order_lines_for_weight(order):
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
        # keep services OUT of express weight (virtual MO)
        if _is_service_line(l):
            continue
        res.append(l)
    return res


def _lx_find_bom_sudo(product):
    """
    Robust BoM finder for website context (sudo, no crash):
    - Try variant BoM via _bom_find(product=variant)
    - Then template BoM via _bom_find(product_tmpl=template) if supported
    - Fallback to template.bom_ids
    """
    try:
        p = product.sudo()
        Bom = request.env["mrp.bom"].sudo()

        # Variant match
        try:
            bom = Bom._bom_find(product=p)
            if bom:
                return bom
        except Exception:
            pass

        tmpl = p.product_tmpl_id.sudo()
        if tmpl:
            # Template match (some versions accept product_tmpl kw)
            try:
                bom = Bom._bom_find(product_tmpl=tmpl)
                if bom:
                    return bom
            except TypeError:
                pass
            except Exception:
                pass

            if getattr(tmpl, "bom_ids", False) and tmpl.bom_ids:
                return tmpl.bom_ids[:1]

    except Exception:
        return False

    return False



def _lx_bom_weight_per_unit_excluding(bom, exclude_products=None, exclude_codes=None, exclude_name_tokens=None):
    """
    Per-unit weight from BoM components excluding anything considered an "accessory"
    (so we can re-add accessories virtually + add any 'extra tangible' from cart lines separately).

    Exclusion works by:
    - product.id in exclude_products
    - OR product.default_code in exclude_codes
    - OR product name contains any token from exclude_name_tokens (case-insensitive)
    """
    if not bom:
        return 0.0, []

    exclude_products = set(exclude_products or [])
    exclude_codes = set((c or "").strip().upper() for c in (exclude_codes or []))
    exclude_name_tokens = [t.strip().lower() for t in (exclude_name_tokens or []) if t and t.strip()]

    def _is_excluded_product(prod):
        if not prod:
            return False
        if prod.id in exclude_products:
            return True
        code = (prod.default_code or "").strip().upper()
        if code and code in exclude_codes:
            return True
        name = (prod.display_name or prod.name or "").lower()
        for tok in exclude_name_tokens:
            if tok and tok in name:
                return True
        return False

    total = 0.0
    details = []
    denom = float(bom.product_qty or 1.0) or 1.0

    for bl in bom.bom_line_ids.sudo():
        comp = bl.product_id
        if not comp:
            continue
        if not _lx_is_countable_product(comp):
            continue
        if _is_excluded_product(comp):
            continue

        w = _lx_raw_weight(comp)
        if w <= 0.0:
            continue

        qty = float(bl.product_qty or 0.0)

        # UoM conversion best-effort
        try:
            if bl.product_uom_id and comp.uom_id and bl.product_uom_id.id != comp.uom_id.id:
                qty = bl.product_uom_id._compute_quantity(qty, comp.uom_id)
        except Exception:
            pass

        part = (w * qty) / denom
        total += part
        details.append({
            "component": comp.display_name,
            "component_weight": w,
            "component_qty_in_bom_uom": qty,
            "contrib_weight_per_unit": part,
        })

    return float(total), details



# def _compute_express_raw_price(order, is_intracity):
#     """
#     EXPRESS raw price:
#     TOTAL WEIGHT =
#       (sum manufactured lines: BoM components weight per unit EXCLUDING accessories) * qty
#       + virtual accessories allocation (motor/remote/charger/zigbee using ratios)
#       + extra tangible products from cart lines (lines with NO BoM) using product.weight * qty

#     raw_price = bracket.unit_price (charged once)
#     """
#     brackets = _lx_pick_brackets_by_kind(is_intracity)
#     if not brackets:
#         raise UserError(_("No %s brackets found.") % ("Intracity" if is_intracity else "Intercity"))

#     motor, remote, charger, zigbee = _lx_get_accessory_products_for_weight()
#     r_ratio, c_ratio, z_ratio = _lx_get_ratios_for_weight()

#     # Exclusion identity for BoM
#     exclude_products = {motor.id, remote.id, charger.id, zigbee.id}
#     exclude_codes = [
#         motor.default_code, remote.default_code, charger.default_code, zigbee.default_code
#     ]
#     # This prevents "Charger (CH-5V)" or similar from being counted inside BoM weight
#     exclude_name_tokens = ["charger", "zigbee", "remote", "tubular motor", "motor"]

#     # ---- classify order lines ----
#     manufactured = []   # (line, product, qty_i, bom)
#     extras = []         # (line, product, qty_f, weight_added, note)

#     for l in _lx_order_lines_for_weight(order):
#         p = l.product_id
#         qty = float(l.product_uom_qty or 0.0)
#         if not p or qty <= 0:
#             continue

#         # ignore delivery/tip/downpayment already filtered, but also ignore your service products
#         if _is_service_line(l):
#             continue

#         if not _lx_is_countable_product(p):
#             continue

#         bom = _lx_find_bom_sudo(p)
#         if bom:
#             manufactured.append((l, p, int(qty), bom))
#         else:
#             # Extra tangible line: counted separately by product weight
#             w = _lx_raw_weight(p)
#             if w > 0:
#                 wa = w * qty
#                 extras.append((l, p, qty, wa, "added: extra tangible line (no BoM) => product.weight * qty"))
#             else:
#                 extras.append((l, p, qty, 0.0, "ignored: extra tangible line has no weight"))

#     # ---- compute electric totals like your action_confirm() ----
#     motors_total_units = 0
#     non_motor_only_units = 0
#     smartphone_units = 0
#     non_smartphone_units = 0

#     for (_l, p, qty_i, _bom) in manufactured:
#         if _lx_is_electric_variant_product(p):
#             motors_total_units += qty_i
#             if not _lx_is_motor_only_variant_product(p):
#                 non_motor_only_units += qty_i
#                 if _lx_is_smartphone_variant_product(p):
#                     smartphone_units += qty_i
#                 else:
#                     non_smartphone_units += qty_i

#     remote_needed = int(math.ceil(non_motor_only_units / r_ratio)) if non_motor_only_units > 0 else 0
#     charger_needed = int(math.ceil(non_motor_only_units / c_ratio)) if non_motor_only_units > 0 else 0
#     zigbee_needed = int(math.ceil(smartphone_units / z_ratio)) if smartphone_units > 0 else 0

#     # ---- base bom weights excluding accessory products ----
#     total_weight = 0.0
#     per_line_debug = []
#     bom_debug = []

#     for (l, p, qty_i, bom) in manufactured:
#         per_unit_w, comp_details = _lx_bom_weight_per_unit_excluding(
#             bom,
#             exclude_products=exclude_products,
#             exclude_codes=exclude_codes,
#             exclude_name_tokens=exclude_name_tokens,
#         )
#         line_w = per_unit_w * qty_i
#         total_weight += line_w

#         per_line_debug.append({
#             "product": p.display_name,
#             "qty": qty_i,
#             "mode": "bom_components_excluding_accessories",
#             "bom_id": bom.id,
#             "weight_per_unit": per_unit_w,
#             "weight_added": line_w,
#             "note": "added: bom components per unit (excluding accessory SKUs) * qty",
#         })

#         bom_debug.append({
#             "product": p.display_name,
#             "bom_id": bom.id,
#             "qty": qty_i,
#             "weight_per_unit_excluding_accessories": per_unit_w,
#             "weight_total_for_line": line_w,
#             "components": comp_details[:50],
#             "components_truncated": bool(len(comp_details) > 50),
#         })

#     # ---- add extras separately (your requirement) ----
#     extras_total = 0.0
#     extras_debug = []
#     for (l, p, qty, wa, note) in extras:
#         extras_total += float(wa or 0.0)
#         extras_debug.append({
#             "product": p.display_name,
#             "qty": qty,
#             "mode": "extra_tangible_line",
#             "product_weight": _lx_raw_weight(p),
#             "weight_added": float(wa or 0.0),
#             "note": note,
#         })

#     total_weight += extras_total

#     # ---- add virtual accessory weights using ratios ----
#     motor_w = _lx_raw_weight(motor) * float(motors_total_units or 0)
#     remote_w = _lx_raw_weight(remote) * float(remote_needed or 0)
#     charger_w = _lx_raw_weight(charger) * float(charger_needed or 0)
#     zigbee_w = _lx_raw_weight(zigbee) * float(zigbee_needed or 0)

#     total_weight += (motor_w + remote_w + charger_w + zigbee_w)

#     virtual_alloc_debug = {
#         "motors_total_units": motors_total_units,
#         "non_motor_only_units": non_motor_only_units,
#         "smartphone_units": smartphone_units,
#         "non_smartphone_units": non_smartphone_units,
#         "remote_needed": remote_needed,
#         "charger_needed": charger_needed,
#         "zigbee_needed": zigbee_needed,
#         "motor_weight_total": motor_w,
#         "remote_weight_total": remote_w,
#         "charger_weight_total": charger_w,
#         "zigbee_weight_total": zigbee_w,
#         "note": "virtual allocation, no DB writes",
#     }

#     if total_weight <= 0.0:
#         return 0.0, {
#             "total_weight": 0.0,
#             "bracket": None,
#             "unit_price_charged_once": 0.0,
#             "lines": per_line_debug,
#             "bom_details": bom_debug,
#             "extra_lines": extras_debug,
#             "virtual_accessory_allocation": virtual_alloc_debug,
#             "formula": "TOTAL WEIGHT = (BoM excl accessories) + (extras by product.weight) + (virtual accessories); raw = bracket.unit_price (once)",
#         }

#     br = _lx_find_bracket_for_weight(total_weight, brackets)
#     if not br:
#         raise UserError(_("No matching bracket for total weight %.2f kg.") % total_weight)

#     raw_price = float(br.unit_price or 0.0)

#     return float(raw_price), {
#         "total_weight": float(total_weight),
#         "bracket": {
#             "id": br.id,
#             "min_kg": float(br.min_kg or 0.0),
#             "max_kg": float(br.max_kg or 0.0),
#             "unit_price": float(br.unit_price or 0.0),
#             "kind": "intra" if is_intracity else "inter",
#         },
#         "unit_price_charged_once": raw_price,
#         "lines": per_line_debug,
#         "bom_details": bom_debug,
#         "extra_lines": extras_debug,
#         "virtual_accessory_allocation": virtual_alloc_debug,
#         "formula": "TOTAL WEIGHT = (BoM excl accessories) + (extras by product.weight) + (virtual accessories); raw = bracket.unit_price (charged once)",
#     }

def _compute_express_raw_price(order, is_intracity):
    """
    EXPRESS (by weight) raw price:

    - Weight uses qty_float (no truncation).
    - Each BoM/manufactured product line is treated as ONE parcel rated by weight:
        raw_price = sum(bracket.unit_price for each parcel).
    - Accessory allocation decisions use ceil(qty) units:
        motors_total_units / remote_needed / charger_needed / zigbee_needed.
      Allocation is distributed across manufactured parcels (greedy by unit-coverage).
    - Accessories (no BoM + accessory category) => ONE grouped parcel by weight if present.
    - Extra tangible (no BoM + not accessory) => ONE separate grouped parcel by weight if present.

    BoM parcel weight = (BoM component weights per unit excluding accessory SKUs) * qty_float
                        + allocated virtual accessory weights for that parcel.
    """
    brackets = _lx_pick_brackets_by_kind(is_intracity)
    if not brackets:
        raise UserError(_("No %s brackets found.") % ("Intracity" if is_intracity else "Intercity"))

    motor, remote, charger, zigbee = _lx_get_accessory_products_for_weight()
    r_ratio, c_ratio, z_ratio = _lx_get_ratios_for_weight()

    exclude_products = {p.id for p in (motor, remote, charger, zigbee) if p}
    exclude_codes = [p.default_code for p in (motor, remote, charger, zigbee) if p and p.default_code]
    exclude_name_tokens = ["charger", "zigbee", "remote", "tubular motor", "motor"]

    # ---- classify lines ----
    manufactured = []     # one parcel per BoM line
    accessory_cart = []   # grouped parcel if any
    extra_cart = []       # grouped parcel if any

    for l in _lx_order_lines_for_weight(order):
        p = l.product_id
        qty_f = float(l.product_uom_qty or 0.0)
        if not p or qty_f <= 0:
            continue
        if not _lx_is_countable_product(p):
            continue

        bom = _lx_find_bom_sudo(p)
        if bom:
            manufactured.append({
                "line": l,
                "product": p,
                "bom": bom,
                "qty_float": qty_f,               # for weight
                "units_ceil": int(math.ceil(qty_f)),  # for accessory decisions
                "base_weight": 0.0,
                "alloc": {"motor": 0, "remote": 0, "charger": 0, "zigbee": 0},
            })
        else:
            w = _lx_raw_weight(p)
            wa = (w * qty_f) if w > 0 else 0.0
            if _is_accessory_product(p):
                accessory_cart.append((l, p, qty_f, wa))
            else:
                extra_cart.append((l, p, qty_f, wa))

    # ---- base manufactured parcel weights (qty_float) ----
    per_line_debug = []
    bom_debug = []

    for m in manufactured:
        p = m["product"]
        bom = m["bom"]
        qty_f = m["qty_float"]

        per_unit_w, comp_details = _lx_bom_weight_per_unit_excluding(
            bom,
            exclude_products=exclude_products,
            exclude_codes=exclude_codes,
            exclude_name_tokens=exclude_name_tokens,
        )
        line_w = per_unit_w * float(qty_f)
        m["base_weight"] = float(line_w)

        per_line_debug.append({
            "product": p.display_name,
            "qty_float": qty_f,
            "units_ceil": m["units_ceil"],
            "mode": "manufactured_parcel_bom_excluding_accessories",
            "bom_id": bom.id,
            "weight_per_unit": per_unit_w,
            "weight_added": float(line_w),
            "note": "parcel weight = (BoM components per unit excluding accessories) * qty_float",
        })

        bom_debug.append({
            "product": p.display_name,
            "bom_id": bom.id,
            "qty_float": qty_f,
            "units_ceil": m["units_ceil"],
            "weight_per_unit_excluding_accessories": per_unit_w,
            "weight_total_for_line": float(line_w),
            "components": comp_details[:50],
            "components_truncated": bool(len(comp_details) > 50),
        })

    # ---- accessory decisions use ceil(units) ----
    motors_total_units = 0
    non_motor_only_units = 0
    smartphone_units = 0
    non_smartphone_units = 0

    for m in manufactured:
        p = m["product"]
        u = int(m["units_ceil"] or 0)
        if u <= 0:
            continue
        if _lx_is_electric_variant_product(p):
            motors_total_units += u
            if not _lx_is_motor_only_variant_product(p):
                non_motor_only_units += u
                if _lx_is_smartphone_variant_product(p):
                    smartphone_units += u
                else:
                    non_smartphone_units += u

    remote_needed = int(math.ceil(non_motor_only_units / r_ratio)) if (remote and non_motor_only_units > 0) else 0
    charger_needed = int(math.ceil(non_motor_only_units / c_ratio)) if (charger and non_motor_only_units > 0) else 0
    zigbee_needed = int(math.ceil(smartphone_units / z_ratio)) if (zigbee and smartphone_units > 0) else 0

    # Motors: allocate per eligible parcel by its units_ceil
    for m in manufactured:
        if motor and _lx_is_electric_variant_product(m["product"]):
            m["alloc"]["motor"] = int(m["units_ceil"] or 0)

    # Greedy pack accessories by unit-coverage
    def _pack_by_coverage(kind, needed, coverage_units, eligible_fn):
        remaining = int(needed or 0)
        if remaining <= 0:
            return 0
        cov = int(coverage_units or 1)
        for m in manufactured:
            if remaining <= 0:
                break
            if not eligible_fn(m):
                continue
            units_left = int(m["units_ceil"] or 0)
            while remaining > 0 and units_left > 0:
                m["alloc"][kind] += 1
                remaining -= 1
                units_left -= cov
        return remaining

    def _eligible_non_motor_only(m):
        p = m["product"]
        return bool(_lx_is_electric_variant_product(p) and (not _lx_is_motor_only_variant_product(p)))

    def _eligible_smartphone(m):
        p = m["product"]
        return bool(_lx_is_electric_variant_product(p)
                    and (not _lx_is_motor_only_variant_product(p))
                    and _lx_is_smartphone_variant_product(p))

    rem_left = _pack_by_coverage("remote", remote_needed, r_ratio, _eligible_non_motor_only)
    chg_left = _pack_by_coverage("charger", charger_needed, c_ratio, _eligible_non_motor_only)
    zig_left = _pack_by_coverage("zigbee", zigbee_needed, z_ratio, _eligible_smartphone)

    # Edge-case fallback: if no eligible parcels, attach remainder to first manufactured parcel
    if manufactured:
        if rem_left > 0:
            manufactured[0]["alloc"]["remote"] += rem_left
            rem_left = 0
        if chg_left > 0:
            manufactured[0]["alloc"]["charger"] += chg_left
            chg_left = 0
        if zig_left > 0:
            manufactured[0]["alloc"]["zigbee"] += zig_left
            zig_left = 0

    # ---- price per parcel (sum of brackets) ----
    def _price_for_weight(w):
        if w <= 0.0:
            return 0.0, None
        br = _lx_find_bracket_for_weight(w, brackets)
        if not br:
            raise UserError(_("No matching bracket for parcel weight %.2f kg.") % w)
        return float(br.unit_price or 0.0), br

    parcels = []
    total_weight = 0.0
    total_price = 0.0

    # Manufactured parcels
    for m in manufactured:
        bw = float(m["base_weight"] or 0.0)

        mw = (_lx_raw_weight(motor) * float(m["alloc"]["motor"] or 0)) if motor else 0.0
        rw = (_lx_raw_weight(remote) * float(m["alloc"]["remote"] or 0)) if remote else 0.0
        cw = (_lx_raw_weight(charger) * float(m["alloc"]["charger"] or 0)) if charger else 0.0
        zw = (_lx_raw_weight(zigbee) * float(m["alloc"]["zigbee"] or 0)) if zigbee else 0.0

        w_total = bw + mw + rw + cw + zw
        price, br = _price_for_weight(w_total)

        parcels.append({
            "kind": "manufactured",
            "product": m["product"].display_name,
            "qty_float": float(m["qty_float"] or 0.0),
            "units_ceil": int(m["units_ceil"] or 0),
            "bom_id": m["bom"].id,
            "weight_base": float(bw),
            "virtual_accessories_alloc": dict(m["alloc"]),
            "weight_virtual_accessories": {
                "motor": float(mw),
                "remote": float(rw),
                "charger": float(cw),
                "zigbee": float(zw),
            },
            "weight_total": float(w_total),
            "bracket": {
                "id": br.id,
                "min_kg": float(br.min_kg or 0.0),
                "max_kg": float(br.max_kg or 0.0),
                "unit_price": float(br.unit_price or 0.0),
                "kind": "intra" if is_intracity else "inter",
            } if br else None,
            "price": float(price),
        })

        total_weight += float(w_total)
        total_price += float(price)

    # Grouped accessories parcel (cart lines with no BoM + accessory)
    accessory_weight = 0.0
    accessory_debug = []
    for (_l, p, qty_f, wa) in accessory_cart:
        accessory_weight += float(wa or 0.0)
        accessory_debug.append({
            "product": p.display_name,
            "qty_float": float(qty_f),
            "product_weight": _lx_raw_weight(p),
            "weight_added": float(wa or 0.0),
            "note": "grouped accessories parcel (no BoM + accessory category) by weight",
        })

    if accessory_weight > 0.0:
        price, br = _price_for_weight(accessory_weight)
        parcels.append({
            "kind": "accessories_group",
            "weight_total": float(accessory_weight),
            "lines": accessory_debug,
            "bracket": {
                "id": br.id,
                "min_kg": float(br.min_kg or 0.0),
                "max_kg": float(br.max_kg or 0.0),
                "unit_price": float(br.unit_price or 0.0),
                "kind": "intra" if is_intracity else "inter",
            } if br else None,
            "price": float(price),
        })
        total_weight += float(accessory_weight)
        total_price += float(price)

    # Grouped extra tangible parcel (cart lines with no BoM + not accessory)
    extra_weight = 0.0
    extras_debug = []
    for (_l, p, qty_f, wa) in extra_cart:
        extra_weight += float(wa or 0.0)
        extras_debug.append({
            "product": p.display_name,
            "qty_float": float(qty_f),
            "product_weight": _lx_raw_weight(p),
            "weight_added": float(wa or 0.0),
            "note": "grouped extra tangible parcel (no BoM + not accessory) by weight",
        })

    if extra_weight > 0.0:
        price, br = _price_for_weight(extra_weight)
        parcels.append({
            "kind": "extra_tangible_group",
            "weight_total": float(extra_weight),
            "lines": extras_debug,
            "bracket": {
                "id": br.id,
                "min_kg": float(br.min_kg or 0.0),
                "max_kg": float(br.max_kg or 0.0),
                "unit_price": float(br.unit_price or 0.0),
                "kind": "intra" if is_intracity else "inter",
            } if br else None,
            "price": float(price),
        })
        total_weight += float(extra_weight)
        total_price += float(price)

    if total_weight <= 0.0:
        return 0.0, {
            "total_weight": 0.0,
            "parcels": [],
            "total_price": 0.0,
            "lines": per_line_debug,
            "bom_details": bom_debug,
            "extra_lines": extras_debug,
            "accessory_lines": accessory_debug,
            "virtual_accessory_allocation": {
                "motors_total_units": motors_total_units,
                "non_motor_only_units": non_motor_only_units,
                "smartphone_units": smartphone_units,
                "non_smartphone_units": non_smartphone_units,
                "remote_needed": remote_needed,
                "charger_needed": charger_needed,
                "zigbee_needed": zigbee_needed,
                "note": "decisions use ceil(qty) units; allocation distributed across manufactured parcels",
            },
            "formula": "raw_price = sum(parcel_bracket_unit_price); parcel weights use qty_float; accessory decisions use ceil(qty)",
        }

    return float(total_price), {
        "total_weight": float(total_weight),
        "parcels": parcels,
        "total_price": float(total_price),
        "lines": per_line_debug,
        "bom_details": bom_debug,
        "extra_lines": extras_debug,
        "accessory_lines": accessory_debug,
        "virtual_accessory_allocation": {
            "motors_total_units": motors_total_units,
            "non_motor_only_units": non_motor_only_units,
            "smartphone_units": smartphone_units,
            "non_smartphone_units": non_smartphone_units,
            "remote_needed": remote_needed,
            "charger_needed": charger_needed,
            "zigbee_needed": zigbee_needed,
            "note": "decisions use ceil(qty) units; allocation distributed across manufactured parcels",
        },
        "formula": "raw_price = sum(parcel_bracket_unit_price); parcel weights use qty_float; accessory decisions use ceil(qty)",
    }

def _lx_sync_selected_carrier_price(order):
    """
    Compute price for the currently selected carrier (standard/express) from ZIP
    then write it to the delivery line (DB) so totals show correctly.
    """
    order = order.sudo()
    if not order or not order.partner_shipping_id:
        return

    zip_code = (order.partner_shipping_id.zip or "").strip()
    shipping_rate = _lookup_shipping_rate(zip_code)
    if not shipping_rate:
        return

    carrier = order.carrier_id.sudo() if order.carrier_id else None
    if not carrier:
        return

    name_norm = (carrier.name or "").strip().lower()

    if name_norm == "standard delivery":
        raw_price, _dbg = _compute_standard_city_raw_price(order, shipping_rate)
        final_price, *_ = _apply_free_logic(order, raw_price)
        _apply_delivery_line(order, carrier, float(final_price or 0.0))
        return

    if name_norm == "express delivery":
        raw_price, _dbg = _compute_express_raw_price(order, bool(shipping_rate.is_intracity))
        final_price, *_ = _apply_free_logic(order, raw_price)
        _apply_delivery_line(order, carrier, float(final_price or 0.0))
        return



# ---------------------------------------------------------
# Controller (FINAL)
# ---------------------------------------------------------
class WebsiteSaleLx(WebsiteSale):

    @http.route(["/lx/shipping/last_debug"], type="json", auth="public", website=True, csrf=False)
    def lx_last_debug(self, **kw):
        try:
            return {"status": "success", "lx_debug": request.session.get("lx_last_debug") or {}}
        except Exception:
            return {"status": "success", "lx_debug": {}}

    @http.route(["/lx/shipping/preview_prices"], type="json", auth="public", website=True, csrf=False)
    def lx_preview_prices(self, **kw):
        order = _lx_sale_get_order(force_create=True)
        if not order:
            payload = {"status": "no_order", "prices": {}}
            _save_last_debug({"route": "preview_prices", "payload": payload})
            return payload

        zip_code = (order.partner_shipping_id.zip or "").strip()
        shipping_rate = _lookup_shipping_rate(zip_code)
        is_intracity = bool(getattr(shipping_rate, "is_intracity", False)) if shipping_rate else None
        threshold = _get_free_threshold()
        merch_total = _merch_total_excl_services(order)
        free_applies = bool(threshold and merch_total >= threshold)

        carriers = request.env["delivery.carrier"].sudo().search([("website_published", "=", True)])
        prices = {}
        debug_by_carrier = {}

        for c in carriers:
            name_norm = (c.name or "").strip().lower()
            try:
                # STANDARD
                if name_norm == "standard delivery":
                    if not shipping_rate:
                        prices[c.id] = 0.0
                        debug_by_carrier[c.id] = {"ok": False, "reason": "no_shipping_rate_for_zip"}
                        continue

                    raw_price, std_debug = _compute_standard_city_raw_price(order, shipping_rate)
                    final_price, free_applied, free_reason, thr_used, merch_total, forced = _apply_free_logic(order, raw_price)

                    prices[c.id] = float(final_price or 0.0)
                    debug_by_carrier[c.id] = {
                        "ok": True,
                        "route": "standard_city_strict_preview",
                        "zip": zip_code,
                        "shipping_rate_id": shipping_rate.id,
                        "is_intracity": is_intracity,
                        "calc": {
                            "raw_price": float(raw_price or 0.0),
                            "final_price": float(final_price or 0.0),
                            "details": std_debug,
                        },
                        "free_logic": {
                            "applied": bool(free_applied),
                            "reason": free_reason,
                            "threshold": float(thr_used or 0.0),
                            "merch_total_excl_services": float(merch_total or 0.0),
                            "forced_session": bool(forced),
                        },
                    }
                    continue

                # EXPRESS
                if name_norm == "express delivery":
                    if not shipping_rate:
                        prices[c.id] = 0.0
                        debug_by_carrier[c.id] = {"ok": False, "reason": "no_shipping_rate_for_zip"}
                        continue

                    raw_price, exp_debug = _compute_express_raw_price(order, bool(shipping_rate.is_intracity))
                    final_price, free_applied, free_reason, thr_used, merch_total, forced = _apply_free_logic(order, raw_price)

                    prices[c.id] = float(final_price or 0.0)
                    debug_by_carrier[c.id] = {
                        "ok": True,
                        "route": "express_weight_strict_preview",
                        "zip": zip_code,
                        "shipping_rate_id": shipping_rate.id,
                        "is_intracity": bool(shipping_rate.is_intracity),
                        "calc": {
                            "raw_price": float(raw_price or 0.0),
                            "final_price": float(final_price or 0.0),
                            "details": exp_debug,
                        },
                        "free_logic": {
                            "applied": bool(free_applied),
                            "reason": free_reason,
                            "threshold": float(thr_used or 0.0),
                            "merch_total_excl_services": float(merch_total or 0.0),
                            "forced_session": bool(forced),
                        },
                    }
                    continue

                # Other carriers: keep 0 (avoid fixed_price flash usage on frontend)
                prices[c.id] = 0.0
                debug_by_carrier[c.id] = {"ok": False, "route": "unsupported_carrier_preview"}

            except Exception as e:
                fallback_price = None
                try:
                    if hasattr(c, "_lx_dynamic_price_for_order") and (c.name or "").strip().lower() in ("standard delivery", "express delivery"):
                        fallback_price = c._lx_dynamic_price_for_order(order)
                except Exception:
                    fallback_price = None
                prices[c.id] = float(fallback_price or 0.0)
                debug_by_carrier[c.id] = {
                    "ok": False,
                    "route": "preview_exception",
                    "error": str(e),
                    "error_name": _err_name(e),
                    "error_trace": _short_trace(),
                    "fallback_price": float(fallback_price or 0.0),
                }

        payload = {
            "status": "success",
            "zip": zip_code,
            "is_intracity": is_intracity,
            "currency": _currency_payload(order),
            "free_flags": {
                "lx_free_applies": free_applies,
                "lx_merch_total": float(merch_total or 0.0),
                "lx_free_threshold": float(threshold or 0.0),
            },
            "prices": prices,
            "lx_debug": {"by_carrier": debug_by_carrier},
        }
        _save_last_debug({"route": "preview_prices", "payload": payload})
        return payload

    @http.route(["/shop/carrier_rate_shipment"], type="json", auth="public", website=True, csrf=False)
    def carrier_rate_shipment(self, carrier_id=None, **kw):
        order = _lx_sale_get_order(force_create=True)
        if not order:
            debug = {"route": "early_exit", "reason": "no_order"}
            _save_last_debug(debug)
            return {"status": "error", "error": "no_order", "lx_debug": debug}

        if carrier_id is None:
            carrier_id = kw.get("carrier_id")

        try:
            carrier_id = int(carrier_id)
        except Exception as e:
            debug = {"route": "early_exit", "reason": "bad_carrier_id", "error": str(e)}
            _save_last_debug(debug)
            return {"status": "error", "error": "bad_carrier_id", "message": str(e), "lx_debug": debug}

        carrier = request.env["delivery.carrier"].sudo().browse(carrier_id)
        if not carrier.exists():
            debug = {"route": "early_exit", "reason": "carrier_not_found", "carrier_id": carrier_id}
            _save_last_debug(debug)
            return {"status": "error", "error": "carrier_not_found", "lx_debug": debug}

        zip_code = (order.partner_shipping_id.zip or "").strip()
        shipping_rate = _lookup_shipping_rate(zip_code)
        is_intracity = bool(getattr(shipping_rate, "is_intracity", False)) if shipping_rate else None

        base_debug = {
            "zip": zip_code,
            "carrier_id": carrier.id,
            "carrier_name": carrier.name,
            "currency": _currency_payload(order),
            "order": {
                "id": order.id,
                "amount_total": float(order.amount_total or 0.0),
                "amount_delivery_before": float(getattr(order, "amount_delivery", 0.0) or 0.0),
            },
            "is_intracity": is_intracity,
        }

        carrier_name_norm = (carrier.name or "").strip().lower()

        # STANDARD
        if carrier_name_norm == "standard delivery":
            if not shipping_rate:
                debug = dict(base_debug, **{
                    "route": "standard_city_strict",
                    "reason": "missing_zip_or_no_shipping_rate",
                    "shipping_rate_id": None,
                    "calc": {"raw_price": None, "final_price": None},
                })
                _save_last_debug(debug)
                return {
                    "status": "error",
                    "error": "no_shipping_rate_for_zip",
                    "carrier_id": carrier.id,
                    "new_amount_delivery": 0.0,
                    "lx_debug": debug,
                }

            raw_price, std_debug = _compute_standard_city_raw_price(order, shipping_rate)
            final_price, free_applied, free_reason, thr_used, merch_total, forced = _apply_free_logic(order, raw_price)
            applied = _apply_delivery_line(order, carrier, float(final_price or 0.0))

            debug = dict(base_debug, **{
                "route": "standard_city_strict",
                "reason": "carrier_is_standard_delivery",
                "shipping_rate_id": shipping_rate.id,
                "apply_delivery_line": bool(applied),
                "calc": {
                    "raw_price": float(raw_price or 0.0),
                    "final_price": float(final_price or 0.0),
                    "details": std_debug
                },
                "free_logic": {
                    "applied": bool(free_applied),
                    "reason": free_reason,
                    "threshold": float(thr_used or 0.0),
                    "merch_total_excl_services": float(merch_total or 0.0),
                    "forced_session": bool(forced),
                },
            })
            _save_last_debug(debug)

            return {
                "status": "success",
                "carrier_id": carrier.id,
                "new_amount_delivery": float(final_price or 0.0),
                "is_free_delivery": bool(free_applied),
                "lx_debug": debug,
            }

        # EXPRESS
        if carrier_name_norm == "express delivery":
            if not shipping_rate:
                debug = dict(base_debug, **{
                    "route": "express_weight_strict",
                    "reason": "missing_zip_or_no_shipping_rate",
                    "shipping_rate_id": None,
                    "calc": {"raw_price": None, "final_price": None},
                })
                _save_last_debug(debug)
                return {
                    "status": "error",
                    "error": "no_shipping_rate_for_zip",
                    "carrier_id": carrier.id,
                    "new_amount_delivery": 0.0,
                    "lx_debug": debug,
                }

            try:
                raw_price, exp_debug = _compute_express_raw_price(order, bool(shipping_rate.is_intracity))
                final_price, free_applied, free_reason, thr_used, merch_total, forced = _apply_free_logic(order, raw_price)
                applied = _apply_delivery_line(order, carrier, float(final_price or 0.0))

                debug = dict(base_debug, **{
                    "route": "express_weight_strict",
                    "reason": "carrier_is_express_delivery",
                    "shipping_rate_id": shipping_rate.id,
                    "bracket_kind": "intra" if bool(shipping_rate.is_intracity) else "inter",
                    "apply_delivery_line": bool(applied),
                    "calc": {
                        "raw_price": float(raw_price or 0.0),
                        "final_price": float(final_price or 0.0),
                        "details": exp_debug
                    },
                    "free_logic": {
                        "applied": bool(free_applied),
                        "reason": free_reason,
                        "threshold": float(thr_used or 0.0),
                        "merch_total_excl_services": float(merch_total or 0.0),
                        "forced_session": bool(forced),
                    },
                })
                _save_last_debug(debug)

                return {
                    "status": "success",
                    "carrier_id": carrier.id,
                    "new_amount_delivery": float(final_price or 0.0),
                    "is_free_delivery": bool(free_applied),
                    "lx_debug": debug,
                }

            except Exception as e:
                _logger.exception("Express compute error")
                debug = dict(base_debug, **{
                    "route": "express_weight_strict",
                    "reason": "compute_exception",
                    "shipping_rate_id": getattr(shipping_rate, "id", None),
                    "error": str(e),
                    "error_name": _err_name(e),
                    "error_trace": _short_trace(),
                    "calc": {"raw_price": None, "final_price": None},
                })
                _save_last_debug(debug)
                return {
                    "status": "error",
                    "error": "compute_exception",
                    "carrier_id": carrier.id,
                    "new_amount_delivery": 0.0,
                    "lx_debug": debug,
                }

        # Any other carrier: no fallback to fixed_price
        debug = dict(base_debug, **{
            "route": "unsupported_carrier",
            "reason": "carrier_name_not_supported",
            "calc": {"raw_price": None, "final_price": None},
        })
        _save_last_debug(debug)
        return {
            "status": "error",
            "error": "unsupported_carrier",
            "carrier_id": carrier.id,
            "new_amount_delivery": 0.0,
            "lx_debug": debug,
        }


    def _lx_sync_order_shipping_before_render(self):
        order = _lx_sale_get_order()
        if order:
            order = order.sudo()
            if hasattr(order, "_lx_ensure_payment_term_records"):
                order._lx_ensure_payment_term_records()
            if hasattr(order, "_lx_apply_website_payment_terms") and not order.lx_payment_terms:
                order._lx_apply_website_payment_terms("upfront")
            if hasattr(order, "_lx_sync_dimension_website_prices"):
                order._lx_sync_dimension_website_prices()
            if hasattr(order, "_lx_sync_electric_accessories"):
                try:
                    with request.env.cr.savepoint():
                        order.with_context(lx_keep_zero_accessories=True)._lx_sync_electric_accessories()
                except Exception:
                    _logger.exception("Luxtor checkout render accessory self-heal failed.")
            if _lx_free_applies(order):
                _lx_force_standard_carrier_if_free(order)
            elif order.carrier_id:
                order._lx_sync_selected_carrier_delivery_line()

    def _lx_redirect_if_verification_pending(self, order):
        if not (order and order.exists()):
            return None

        order = order.sudo()
        if order.lx_verification_required and not order.lx_verification_ok:
            if hasattr(order, "lx_ensure_verification_token"):
                order.lx_ensure_verification_token()
            request.session["lx_msg_err"] = _(
                "You must validate your order with an authorization code before continuing to checkout."
            )
            return request.redirect('/shop/cart')
        return None

    @http.route(['/shop/checkout'], type='http', auth='public', website=True, sitemap=False)
    def checkout(self, **post):
        redirect = self._lx_redirect_if_verification_pending(_lx_sale_get_order(force_create=False))
        if redirect:
            return redirect
        self._lx_sync_order_shipping_before_render()
        sup = super(WebsiteSaleLx, self)
        if hasattr(sup, "checkout"):
            response = sup.checkout(**post)
        else:
            response = sup.shop_checkout(**post)

        if hasattr(response, "qcontext"):
            order = response.qcontext.get("website_sale_order") or _lx_sale_get_order()
            _lx_inject_free_flags(response.qcontext, order.sudo() if order else order)
        return response

    @http.route(['/shop/payment'], type='http', auth='public', website=True, sitemap=False)
    def payment(self, **post):
        redirect = self._lx_redirect_if_verification_pending(_lx_sale_get_order(force_create=False))
        if redirect:
            return redirect
        self._lx_sync_order_shipping_before_render()
        sup = super(WebsiteSaleLx, self)
        response = sup.payment(**post) if hasattr(sup, "payment") else sup.shop_payment(**post)

        payment_error = request.session.pop("lx_payment_error", False)
        if hasattr(response, "qcontext"):
            if payment_error:
                errors = list(response.qcontext.get("errors") or [])
                errors.append((_("Payment Method"), payment_error))
                response.qcontext["errors"] = errors
            response.qcontext["lx_payment_choice"] = (
                response.qcontext.get("website_sale_order").lx_payment_terms
                if response.qcontext.get("website_sale_order")
                else "upfront"
            ) or "upfront"
            if response.qcontext.get("website_sale_order") and hasattr(response.qcontext["website_sale_order"], "_lx_payment_summary_values"):
                response.qcontext["lx_payment_summary"] = response.qcontext["website_sale_order"]._lx_payment_summary_values()
            _lx_inject_free_flags(
                response.qcontext,
                response.qcontext.get("website_sale_order") or _lx_sale_get_order(),
            )
        return response

    @http.route(['/shop/payment/update_terms'], type='json', auth='public', website=True, csrf=False)
    def lx_payment_update_terms(self, lx_payment_terms=None, **post):
        order = _lx_sale_get_order(force_create=False)
        if not order:
            return {"ok": False, "error": "no_order"}

        order = order.sudo()
        if hasattr(order, "_lx_sync_dimension_website_prices"):
            order._lx_sync_dimension_website_prices()
        if hasattr(order, "_lx_apply_website_payment_terms"):
            order._lx_apply_website_payment_terms(lx_payment_terms)

        summary = order._lx_payment_summary_values() if hasattr(order, "_lx_payment_summary_values") else {}
        return {
            "ok": True,
            "summary": summary,
            "currency": _currency_payload(order),
        }

    @http.route(['/shop/payment/select'], type='http', auth='public', website=True, sitemap=False, methods=['POST'])
    def lx_payment_select(self, lx_payment_terms=None, **post):
        order = _lx_sale_get_order(force_create=False)
        if not order:
            return request.redirect('/shop/cart')

        redirect = self._lx_redirect_if_verification_pending(order)
        if redirect:
            return redirect

        order = order.sudo()
        try:
            if hasattr(order, "_lx_sync_dimension_website_prices"):
                order._lx_sync_dimension_website_prices()
            if hasattr(order, "_lx_apply_website_payment_terms"):
                order._lx_apply_website_payment_terms(lx_payment_terms)

            if order.state in ("draft", "sent"):
                order.action_confirm()

            payment_result = {}
            if hasattr(order, "_lx_create_website_backend_payment"):
                payment_result = order._lx_create_website_backend_payment() or {}

            request.session["sale_last_order_id"] = order.id
            request.session["sale_order_id"] = None
            request.session.pop("website_sale_cart_quantity", None)
            return request.redirect('/shop/confirmation')
        except Exception as err:
            _logger.exception("Luxtor payment selection failed")
            request.session["lx_payment_error"] = str(err) or _("Unable to confirm your order.")
            return request.redirect('/shop/payment')
        



# # ---------------------------------------------------------
# # FREE logic helpers (KEEP)
# # ● Standard: City: Fix Accessories as one Parcel
# # ● Express: Weight: Total of BoM Weight
# # ---------------------------------------------------------

# def _get_free_threshold():
#     ICP = request.env["ir.config_parameter"].sudo()
#     val = ICP.get_param("luxtor.lx_free_amount_order", default="0")
#     try:
#         return float(val or 0.0)
#     except Exception:
#         return 0.0


# def _is_service_line(line):
#     p = line.product_id
#     if not p or line.display_type:
#         return False
#     code = (p.default_code or "").strip().upper()
#     tcode = (p.product_tmpl_id.default_code or "").strip().upper()
#     return code in ("INSTALL_SERVICE", "PRIORITY_SERVICE") or tcode in ("INSTALL_SERVICE", "PRIORITY_SERVICE")


# def _merch_total_excl_services(order):
#     total = 0.0
#     if not order:
#         return total
#     for l in order.sudo().order_line:
#         if l.display_type:
#             continue
#         if getattr(l, "is_delivery", False):
#             continue
#         if getattr(l, "is_tip", False):
#             continue
#         if getattr(l, "is_downpayment", False):
#             continue
#         if _is_service_line(l):
#             continue
#         total += float(l.price_total or 0.0)
#     return total


# def _apply_free_logic(order, raw_price):
#     forced = bool(request.session.get("lx_free_force", False))
#     threshold = _get_free_threshold()
#     merch_total = _merch_total_excl_services(order)

#     if forced:
#         return 0.0, True, "session_forced", threshold, merch_total, True

#     if threshold and merch_total >= threshold:
#         return 0.0, True, "order_amount_over_threshold", threshold, merch_total, False

#     return float(raw_price or 0.0), False, None, threshold, merch_total, False


# # ---------------------------------------------------------
# # STANDARD city-rate helpers (shipping.rate by zip)
# # ---------------------------------------------------------
# def _lookup_shipping_rate(zip_code):
#     if not zip_code:
#         return False
#     return request.env["shipping.rate"].sudo().search([("zip_code", "=", zip_code)], limit=1)


# # ---------------------------------------------------------
# # Apply carrier + delivery line on order (robust)
# # ---------------------------------------------------------
# def _apply_delivery_line(order, carrier, price):
#     order_sudo = order.sudo()

#     try:
#         order_sudo.write({"carrier_id": carrier.id})
#     except Exception:
#         pass

#     for meth in ("set_delivery_line", "_set_delivery_line", "_create_delivery_line"):
#         fn = getattr(order_sudo, meth, None)
#         if not fn:
#             continue
#         try:
#             fn(carrier, price)
#             return True
#         except TypeError:
#             try:
#                 fn(carrier)
#                 try:
#                     dl = order_sudo.order_line.filtered(lambda l: getattr(l, "is_delivery", False))[:1]
#                     if dl:
#                         dl.write({"price_unit": float(price or 0.0)})
#                 except Exception:
#                     pass
#                 return True
#             except Exception:
#                 continue
#         except Exception:
#             continue

#     try:
#         dl = order_sudo.order_line.filtered(lambda l: getattr(l, "is_delivery", False))[:1]
#         if dl:
#             dl.write({"price_unit": float(price or 0.0)})
#             return True
#     except Exception:
#         pass

#     return False


# # ---------------------------------------------------------
# # Currency payload (optional for frontend formatting)
# # ---------------------------------------------------------
# def _currency_payload(order):
#     cur = order.currency_id
#     return {
#         "name": cur.name,
#         "symbol": cur.symbol or "",
#         "position": cur.position or "after",
#         "decimal_places": int(cur.decimal_places or 2),
#     }


# # ---------------------------------------------------------
# # Debug helpers
# # ---------------------------------------------------------
# def _err_name(e):
#     try:
#         return e.__class__.__name__
#     except Exception:
#         return "Exception"


# def _short_trace(limit_lines=35):
#     try:
#         tb = traceback.format_exc()
#         lines = (tb or "").splitlines()
#         if len(lines) > limit_lines:
#             lines = lines[-limit_lines:]
#         return "\n".join(lines)
#     except Exception:
#         return ""


# def _save_last_debug(payload):
#     """Store last debug in session for the debug panel."""
#     try:
#         request.session["lx_last_debug"] = payload
#     except Exception:
#         pass


# # ---------------------------------------------------------
# # Weight helpers (Express)
# # ---------------------------------------------------------
# def _lx_raw_weight(product):
#     try:
#         return float(product.weight or 0.0)
#     except Exception:
#         return 0.0


# def _lx_is_countable_product(product):
#     # storable/consu only; services excluded
#     return bool(product and product.type in ("product", "consu"))


# def _lx_has_bom_sudo(product):
#     """
#     Safe BoM detection on website context:
#     - always sudo
#     - never crash if MRP is restricted
#     """
#     try:
#         p = product.sudo()
#         if hasattr(p, "bom_count") and p.bom_count:
#             return True
#         tmpl = p.product_tmpl_id.sudo()
#         if getattr(p, "bom_ids", False) and p.bom_ids:
#             return True
#         if tmpl and getattr(tmpl, "bom_ids", False) and tmpl.bom_ids:
#             return True
#     except Exception:
#         return False
#     return False


# def _lx_pick_brackets_by_kind(is_intracity):
#     """
#     IMPORTANT: Express:
#     - do NOT filter by carrier_id
#     - only by kind (intra/inter)
#     """
#     kind = "intra" if is_intracity else "inter"
#     return request.env["delivery.bracket.lx"].sudo().search(
#         [("kind", "=", kind)],
#         order="max_kg asc",
#     )


# def _lx_find_bracket_for_weight(weight, brackets):
#     chosen = None
#     for b in brackets:
#         if (b.min_kg or 0.0) <= weight <= (b.max_kg or 0.0):
#             chosen = b
#             break
#     if not chosen and brackets:
#         chosen = brackets[-1]
#     return chosen


# def _lx_order_lines_for_weight(order):
#     res = []
#     for l in order.sudo().order_line:
#         if l.display_type:
#             continue
#         if getattr(l, "is_delivery", False):
#             continue
#         if getattr(l, "is_tip", False):
#             continue
#         if getattr(l, "is_downpayment", False):
#             continue
#         res.append(l)
#     return res


# def _compute_express_raw_price(order, is_intracity):
#     """
#     EXPRESS raw price:
#     - services excluded
#     - zero-weight ignored
#     - BoM products priced per-unit by bracket chosen with unit weight
#     - Non-BoM products aggregated by total weight and charged once
#     """
#     brackets = _lx_pick_brackets_by_kind(is_intracity)
#     if not brackets:
#         raise UserError(_("No %s brackets found.") % ("Intracity" if is_intracity else "Intercity"))

#     raw_total = 0.0
#     per_line_debug = []
#     non_bom_total_weight = 0.0

#     for line in _lx_order_lines_for_weight(order):
#         p = line.product_id
#         qty = float(line.product_uom_qty or 0.0)
#         if not p:
#             continue

#         # Exclude services
#         if not _lx_is_countable_product(p):
#             per_line_debug.append({
#                 "product": p.display_name,
#                 "has_bom": False,
#                 "qty": qty,
#                 "unit_weight_for_bracket": 0.0,
#                 "bracket": None,
#                 "per_unit_shipping_price": 0.0,
#                 "line_shipping": 0.0,
#                 "note": "ignored (service type)",
#             })
#             continue

#         w = _lx_raw_weight(p)
#         if w <= 0.0:
#             per_line_debug.append({
#                 "product": p.display_name,
#                 "has_bom": _lx_has_bom_sudo(p),
#                 "qty": qty,
#                 "unit_weight_for_bracket": 0.0,
#                 "bracket": None,
#                 "per_unit_shipping_price": 0.0,
#                 "line_shipping": 0.0,
#                 "note": "ignored (no weight)",
#             })
#             continue

#         has_bom = _lx_has_bom_sudo(p)

#         # Non-BoM => aggregate later
#         if not has_bom:
#             non_bom_total_weight += w * qty
#             per_line_debug.append({
#                 "product": p.display_name,
#                 "has_bom": False,
#                 "qty": qty,
#                 "unit_weight_for_bracket": 0.0,
#                 "bracket": None,
#                 "per_unit_shipping_price": 0.0,
#                 "line_shipping": 0.0,
#                 "note": "aggregated later (no BoM, weight>0)",
#             })
#             continue

#         # BoM => per unit bracket
#         unit_w = w
#         br = _lx_find_bracket_for_weight(unit_w, brackets)
#         if not br:
#             raise UserError(_("No matching bracket for unit weight %.2f kg.") % unit_w)

#         per_unit_price = float(br.unit_price or 0.0)
#         line_total = per_unit_price * qty
#         raw_total += line_total

#         per_line_debug.append({
#             "product": p.display_name,
#             "has_bom": True,
#             "qty": qty,
#             "unit_weight_for_bracket": unit_w,
#             "bracket": {
#                 "min_kg": float(br.min_kg or 0.0),
#                 "max_kg": float(br.max_kg or 0.0),
#                 "unit_price": per_unit_price,
#             },
#             "per_unit_shipping_price": per_unit_price,
#             "line_shipping": line_total,
#             "note": "counted (BoM, weight>0)",
#         })

#     # Aggregate non-BoM
#     if non_bom_total_weight > 0.0:
#         br = _lx_find_bracket_for_weight(non_bom_total_weight, brackets)
#         if not br:
#             raise UserError(_("No matching bracket for total non-BoM weight %.2f kg.") % non_bom_total_weight)

#         agg_price = float(br.unit_price or 0.0)
#         raw_total += agg_price

#         per_line_debug.append({
#             "product": "Non-BoM aggregated",
#             "has_bom": False,
#             "qty": 1.0,
#             "unit_weight_for_bracket": float(non_bom_total_weight or 0.0),
#             "bracket": {
#                 "min_kg": float(br.min_kg or 0.0),
#                 "max_kg": float(br.max_kg or 0.0),
#                 "unit_price": float(br.unit_price or 0.0),
#             },
#             "per_unit_shipping_price": float(br.unit_price or 0.0),
#             "line_shipping": agg_price,
#             "note": "counted as 1 unit (sum of non-BoM weights)",
#         })

#     return float(raw_total or 0.0), per_line_debug


# # ---------------------------------------------------------
# # Controller (FINAL)
# # ---------------------------------------------------------
# class WebsiteSaleLx(WebsiteSale):

#     # -----------------------------
#     # Debug fetch: read last debug from session (panel uses this)
#     # -----------------------------
#     @http.route(["/lx/shipping/last_debug"], type="json", auth="public", website=True, csrf=False)
#     def lx_last_debug(self, **kw):
#         try:
#             return {
#                 "status": "success",
#                 "lx_debug": request.session.get("lx_last_debug") or {},
#             }
#         except Exception:
#             return {"status": "success", "lx_debug": {}}

#     # -----------------------------
#     # PREVIEW: compute prices for all carriers WITHOUT writing anything
#     # (used by your JS to overwrite the fixed_price flicker)
#     # -----------------------------
#     @http.route(["/lx/shipping/preview_prices"], type="json", auth="public", website=True, csrf=False)
#     def lx_preview_prices(self, **kw):
#         order = _lx_sale_get_order(force_create=True)
#         if not order:
#             payload = {"status": "no_order", "prices": {}}
#             _save_last_debug({"route": "preview", "status": "no_order"})
#             return payload

#         zip_code = (order.partner_shipping_id.zip or "").strip()
#         shipping_rate = _lookup_shipping_rate(zip_code)
#         is_intracity = bool(getattr(shipping_rate, "is_intracity", False)) if shipping_rate else None

#         carriers = request.env["delivery.carrier"].sudo().search([("website_published", "=", True)])
#         prices = {}
#         debug_by_carrier = {}

#         for c in carriers:
#             name_norm = (c.name or "").strip().lower()
#             try:
#                 # STANDARD (strict ZIP)
#                 if name_norm == "standard delivery":
#                     if not shipping_rate:
#                         prices[c.id] = 0.0
#                         debug_by_carrier[c.id] = {"ok": False, "reason": "no_shipping_rate_for_zip"}
#                         continue

#                     raw_price = float(getattr(shipping_rate, "price", 0.0) or 0.0)
#                     final_price, free_applied, free_reason, thr_used, merch_total, forced = _apply_free_logic(order, raw_price)
#                     prices[c.id] = float(final_price or 0.0)
#                     debug_by_carrier[c.id] = {
#                         "ok": True,
#                         "route": "standard_city_strict_preview",
#                         "zip": zip_code,
#                         "shipping_rate_id": shipping_rate.id,
#                         "is_intracity": is_intracity,
#                         "raw_price": raw_price,
#                         "final_price": float(final_price or 0.0),
#                         "free_applied": bool(free_applied),
#                         "free_reason": free_reason,
#                         "threshold": float(thr_used or 0.0),
#                         "merch_total_excl_services": float(merch_total or 0.0),
#                         "forced_session": bool(forced),
#                     }
#                     continue

#                 # EXPRESS (strict brackets)
#                 if name_norm == "express delivery":
#                     if not shipping_rate:
#                         prices[c.id] = 0.0
#                         debug_by_carrier[c.id] = {"ok": False, "reason": "no_shipping_rate_for_zip"}
#                         continue

#                     raw_price, _per_line_debug = _compute_express_raw_price(order, bool(shipping_rate.is_intracity))
#                     final_price, free_applied, free_reason, thr_used, merch_total, forced = _apply_free_logic(order, raw_price)
#                     prices[c.id] = float(final_price or 0.0)
#                     debug_by_carrier[c.id] = {
#                         "ok": True,
#                         "route": "express_weight_strict_preview",
#                         "zip": zip_code,
#                         "shipping_rate_id": shipping_rate.id,
#                         "is_intracity": bool(shipping_rate.is_intracity),
#                         "bracket_kind": "intra" if bool(shipping_rate.is_intracity) else "inter",
#                         "raw_price": float(raw_price or 0.0),
#                         "final_price": float(final_price or 0.0),
#                         "free_applied": bool(free_applied),
#                         "free_reason": free_reason,
#                         "threshold": float(thr_used or 0.0),
#                         "merch_total_excl_services": float(merch_total or 0.0),
#                         "forced_session": bool(forced),
#                     }
#                     continue

#                 # Other carriers: keep 0.0 (so you NEVER show fixed_price)
#                 prices[c.id] = 0.0
#                 debug_by_carrier[c.id] = {"ok": False, "route": "unsupported_carrier_preview"}

#             except Exception as e:
#                 prices[c.id] = 0.0
#                 debug_by_carrier[c.id] = {
#                     "ok": False,
#                     "route": "preview_exception",
#                     "error": str(e),
#                     "error_name": _err_name(e),
#                 }

#         payload = {
#             "status": "success",
#             "zip": zip_code,
#             "is_intracity": is_intracity,
#             "currency": _currency_payload(order),
#             "prices": prices,
#             "lx_debug": {"by_carrier": debug_by_carrier},
#         }
#         _save_last_debug({"route": "preview_prices", "payload": payload})
#         return payload

#     # -----------------------------
#     # APPLY: compute + write delivery line (this is the ONLY place that writes)
#     # -----------------------------
#     @http.route(["/shop/carrier_rate_shipment"], type="json", auth="public", website=True, csrf=False)
#     def carrier_rate_shipment(self, carrier_id=None, **kw):
#         order = _lx_sale_get_order(force_create=True)
#         if not order:
#             debug = {"route": "early_exit", "reason": "no_order"}
#             _save_last_debug(debug)
#             return {"status": "error", "error": "no_order", "lx_debug": debug}

#         # accept carrier_id from args or kw
#         if carrier_id is None:
#             carrier_id = kw.get("carrier_id")

#         try:
#             carrier_id = int(carrier_id)
#         except Exception as e:
#             debug = {"route": "early_exit", "reason": "bad_carrier_id", "error": str(e)}
#             _save_last_debug(debug)
#             return {
#                 "status": "error",
#                 "error": "bad_carrier_id",
#                 "message": str(e),
#                 "lx_debug": debug,
#             }

#         carrier = request.env["delivery.carrier"].sudo().browse(carrier_id)
#         if not carrier.exists():
#             debug = {"route": "early_exit", "reason": "carrier_not_found", "carrier_id": carrier_id}
#             _save_last_debug(debug)
#             return {"status": "error", "error": "carrier_not_found", "lx_debug": debug}

#         zip_code = (order.partner_shipping_id.zip or "").strip()
#         shipping_rate = _lookup_shipping_rate(zip_code)
#         is_intracity = bool(getattr(shipping_rate, "is_intracity", False)) if shipping_rate else None

#         base_debug = {
#             "zip": zip_code,
#             "carrier_id": carrier.id,
#             "carrier_name": carrier.name,
#             "currency": _currency_payload(order),
#             "order": {
#                 "id": order.id,
#                 "amount_total": float(order.amount_total or 0.0),
#                 "amount_delivery_before": float(getattr(order, "amount_delivery", 0.0) or 0.0),
#             },
#             "is_intracity": is_intracity,
#         }

#         carrier_name_norm = (carrier.name or "").strip().lower()

#         # -----------------------------
#         # STANDARD: strict shipping.rate by ZIP
#         # -----------------------------
#         if carrier_name_norm == "standard delivery":
#             if not shipping_rate:
#                 debug = dict(base_debug, **{
#                     "route": "standard_city_strict",
#                     "reason": "missing_zip_or_no_shipping_rate",
#                     "shipping_rate_id": None,
#                     "calc": {"raw_price": None, "final_price": None},
#                 })
#                 _save_last_debug(debug)
#                 return {
#                     "status": "error",
#                     "error": "no_shipping_rate_for_zip",
#                     "carrier_id": carrier.id,
#                     "new_amount_delivery": 0.0,
#                     "lx_debug": debug,
#                 }

#             raw_price = float(getattr(shipping_rate, "price", 0.0) or 0.0)
#             final_price, free_applied, free_reason, thr_used, merch_total, forced = _apply_free_logic(order, raw_price)

#             applied = _apply_delivery_line(order, carrier, float(final_price or 0.0))

#             debug = dict(base_debug, **{
#                 "route": "standard_city_strict",
#                 "reason": "carrier_is_standard_delivery",
#                 "shipping_rate_id": shipping_rate.id,
#                 "apply_delivery_line": bool(applied),
#                 "calc": {"raw_price": raw_price, "final_price": float(final_price or 0.0)},
#                 "free_logic": {
#                     "applied": bool(free_applied),
#                     "reason": free_reason,
#                     "threshold": float(thr_used or 0.0),
#                     "merch_total_excl_services": float(merch_total or 0.0),
#                     "forced_session": bool(forced),
#                 },
#                 "formula": "STRICT STANDARD: shipping.rate.price (ZIP) -> apply_free_logic -> final_price",
#             })
#             _save_last_debug(debug)

#             return {
#                 "status": "success",
#                 "carrier_id": carrier.id,
#                 "new_amount_delivery": float(final_price or 0.0),
#                 "is_free_delivery": bool(free_applied),
#                 "lx_debug": debug,
#             }

#         # -----------------------------
#         # EXPRESS: strict brackets by kind (intra/inter)
#         # -----------------------------
#         if carrier_name_norm == "express delivery":
#             if not shipping_rate:
#                 debug = dict(base_debug, **{
#                     "route": "express_weight_strict",
#                     "reason": "missing_zip_or_no_shipping_rate",
#                     "shipping_rate_id": None,
#                     "calc": {"raw_price": None, "final_price": None},
#                 })
#                 _save_last_debug(debug)
#                 return {
#                     "status": "error",
#                     "error": "no_shipping_rate_for_zip",
#                     "carrier_id": carrier.id,
#                     "new_amount_delivery": 0.0,
#                     "lx_debug": debug,
#                 }

#             try:
#                 raw_price, per_line_debug = _compute_express_raw_price(order, bool(shipping_rate.is_intracity))
#                 final_price, free_applied, free_reason, thr_used, merch_total, forced = _apply_free_logic(order, raw_price)

#                 applied = _apply_delivery_line(order, carrier, float(final_price or 0.0))

#                 debug = dict(base_debug, **{
#                     "route": "express_weight_strict",
#                     "reason": "carrier_is_express_delivery",
#                     "shipping_rate_id": shipping_rate.id,
#                     "bracket_kind": "intra" if bool(shipping_rate.is_intracity) else "inter",
#                     "apply_delivery_line": bool(applied),
#                     "calc": {"raw_price": float(raw_price or 0.0), "final_price": float(final_price or 0.0)},
#                     "free_logic": {
#                         "applied": bool(free_applied),
#                         "reason": free_reason,
#                         "threshold": float(thr_used or 0.0),
#                         "merch_total_excl_services": float(merch_total or 0.0),
#                         "forced_session": bool(forced),
#                     },
#                     "order_lines": per_line_debug,
#                     "formula": "STRICT EXPRESS: shipping.rate.is_intracity -> delivery.bracket.lx(kind) -> BoM per-unit + non-BoM aggregated -> apply_free_logic -> final_price",
#                 })
#                 _save_last_debug(debug)

#                 return {
#                     "status": "success",
#                     "carrier_id": carrier.id,
#                     "new_amount_delivery": float(final_price or 0.0),
#                     "is_free_delivery": bool(free_applied),
#                     "lx_debug": debug,
#                 }

#             except Exception as e:
#                 _logger.exception("Express compute error")
#                 debug = dict(base_debug, **{
#                     "route": "express_weight_strict",
#                     "reason": "compute_exception",
#                     "shipping_rate_id": getattr(shipping_rate, "id", None),
#                     "error": str(e),
#                     "error_name": _err_name(e),
#                     "error_trace": _short_trace(),
#                     "calc": {"raw_price": None, "final_price": None},
#                 })
#                 _save_last_debug(debug)
#                 return {
#                     "status": "error",
#                     "error": "compute_exception",
#                     "carrier_id": carrier.id,
#                     "new_amount_delivery": 0.0,
#                     "lx_debug": debug,
#                 }

#         # -----------------------------
#         # Any other carrier: no fallback to fixed_price
#         # -----------------------------
#         debug = dict(base_debug, **{
#             "route": "unsupported_carrier",
#             "reason": "carrier_name_not_supported",
#             "calc": {"raw_price": None, "final_price": None},
#         })
#         _save_last_debug(debug)
#         return {
#             "status": "error",
#             "error": "unsupported_carrier",
#             "carrier_id": carrier.id,
#             "new_amount_delivery": 0.0,
#             "lx_debug": debug,
#         }


# # ---------------------------------------------------------
# # FREE logic helpers (KEEP)
# # ●	Standard: City: Fix Accessories as one Parcel
# # ●	Express: Weight: Total of BoM Weight

# # ---------------------------------------------------------
# def _get_free_threshold():
#     ICP = request.env["ir.config_parameter"].sudo()
#     val = ICP.get_param("luxtor.lx_free_amount_order", default="0")
#     try:
#         return float(val or 0.0)
#     except Exception:
#         return 0.0


# def _is_service_line(line):
#     p = line.product_id
#     if not p or line.display_type:
#         return False
#     code = (p.default_code or "").strip().upper()
#     tcode = (p.product_tmpl_id.default_code or "").strip().upper()
#     return code in ("INSTALL_SERVICE", "PRIORITY_SERVICE") or tcode in ("INSTALL_SERVICE", "PRIORITY_SERVICE")


# def _merch_total_excl_services(order):
#     total = 0.0
#     if not order:
#         return total
#     for l in order.sudo().order_line:
#         if l.display_type:
#             continue
#         if getattr(l, "is_delivery", False):
#             continue
#         if getattr(l, "is_tip", False):
#             continue
#         if getattr(l, "is_downpayment", False):
#             continue
#         if _is_service_line(l):
#             continue
#         total += float(l.price_total or 0.0)
#     return total


# def _apply_free_logic(order, raw_price):
#     forced = bool(request.session.get("lx_free_force", False))
#     threshold = _get_free_threshold()
#     merch_total = _merch_total_excl_services(order)

#     if forced:
#         return 0.0, True, "session_forced", threshold, merch_total, True

#     if threshold and merch_total >= threshold:
#         return 0.0, True, "order_amount_over_threshold", threshold, merch_total, False

#     return float(raw_price or 0.0), False, None, threshold, merch_total, False


# # ---------------------------------------------------------
# # STANDARD city-rate helpers (shipping.rate by zip)
# # ---------------------------------------------------------
# def _lookup_shipping_rate(zip_code):
#     if not zip_code:
#         return False
#     return request.env["shipping.rate"].sudo().search([("zip_code", "=", zip_code)], limit=1)


# # ---------------------------------------------------------
# # Apply carrier + delivery line on order (robust)
# # ---------------------------------------------------------
# def _apply_delivery_line(order, carrier, price):
#     order_sudo = order.sudo()

#     try:
#         order_sudo.write({"carrier_id": carrier.id})
#     except Exception:
#         pass

#     for meth in ("set_delivery_line", "_set_delivery_line", "_create_delivery_line"):
#         fn = getattr(order_sudo, meth, None)
#         if not fn:
#             continue
#         try:
#             fn(carrier, price)
#             return True
#         except TypeError:
#             try:
#                 fn(carrier)
#                 try:
#                     dl = order_sudo.order_line.filtered(lambda l: getattr(l, "is_delivery", False))[:1]
#                     if dl:
#                         dl.write({"price_unit": float(price or 0.0)})
#                 except Exception:
#                     pass
#                 return True
#             except Exception:
#                 continue
#         except Exception:
#             continue

#     try:
#         dl = order_sudo.order_line.filtered(lambda l: getattr(l, "is_delivery", False))[:1]
#         if dl:
#             dl.write({"price_unit": float(price or 0.0)})
#             return True
#     except Exception:
#         pass

#     return False


# # ---------------------------------------------------------
# # Currency payload (optional for frontend formatting)
# # ---------------------------------------------------------
# def _currency_payload(order):
#     cur = order.currency_id
#     return {
#         "name": cur.name,
#         "symbol": cur.symbol or "",
#         "position": cur.position or "after",
#         "decimal_places": int(cur.decimal_places or 2),
#     }


# # ---------------------------------------------------------
# # Debug helpers
# # ---------------------------------------------------------
# def _err_name(e):
#     try:
#         return e.__class__.__name__
#     except Exception:
#         return "Exception"


# def _short_trace(limit_lines=35):
#     try:
#         tb = traceback.format_exc()
#         lines = (tb or "").splitlines()
#         if len(lines) > limit_lines:
#             lines = lines[-limit_lines:]
#         return "\n".join(lines)
#     except Exception:
#         return ""


# # ---------------------------------------------------------
# # Weight helpers (Express)
# # ---------------------------------------------------------
# def _lx_raw_weight(product):
#     try:
#         return float(product.weight or 0.0)
#     except Exception:
#         return 0.0


# def _lx_is_countable_product(product):
#     # storable/consu only; services excluded
#     return bool(product and product.type in ("product", "consu"))


# def _lx_has_bom_sudo(product):
#     """
#     Safe BoM detection on website context:
#     - always sudo
#     - never crash if MRP is restricted
#     """
#     try:
#         p = product.sudo()
#         if hasattr(p, "bom_count") and p.bom_count:
#             return True
#         tmpl = p.product_tmpl_id.sudo()
#         if getattr(p, "bom_ids", False) and p.bom_ids:
#             return True
#         if tmpl and getattr(tmpl, "bom_ids", False) and tmpl.bom_ids:
#             return True
#     except Exception:
#         return False
#     return False


# def _lx_pick_brackets_by_kind(is_intracity):
#     """
#     IMPORTANT: Express:
#     - do NOT filter by carrier_id
#     - only by kind (intra/inter)
#     """
#     kind = "intra" if is_intracity else "inter"
#     return request.env["delivery.bracket.lx"].sudo().search(
#         [("kind", "=", kind)],
#         order="max_kg asc",
#     )


# def _lx_find_bracket_for_weight(weight, brackets):
#     chosen = None
#     for b in brackets:
#         if (b.min_kg or 0.0) <= weight <= (b.max_kg or 0.0):
#             chosen = b
#             break
#     if not chosen and brackets:
#         chosen = brackets[-1]
#     return chosen


# def _lx_order_lines_for_weight(order):
#     res = []
#     for l in order.sudo().order_line:
#         if l.display_type:
#             continue
#         if getattr(l, "is_delivery", False):
#             continue
#         if getattr(l, "is_tip", False):
#             continue
#         if getattr(l, "is_downpayment", False):
#             continue
#         res.append(l)
#     return res


# def _compute_express_raw_price(order, is_intracity):
#     """
#     EXPRESS raw price:
#     - services excluded
#     - zero-weight ignored
#     - BoM products priced per-unit by bracket chosen with unit weight
#     - Non-BoM products aggregated by total weight and charged once
#     """
#     brackets = _lx_pick_brackets_by_kind(is_intracity)
#     if not brackets:
#         raise UserError(_("No %s brackets found.") % ("Intracity" if is_intracity else "Intercity"))

#     raw_total = 0.0
#     per_line_debug = []
#     non_bom_total_weight = 0.0

#     for line in _lx_order_lines_for_weight(order):
#         p = line.product_id
#         qty = float(line.product_uom_qty or 0.0)
#         if not p:
#             continue

#         # Exclude services
#         if not _lx_is_countable_product(p):
#             per_line_debug.append({
#                 "product": p.display_name,
#                 "has_bom": False,
#                 "qty": qty,
#                 "unit_weight_for_bracket": 0.0,
#                 "bracket": None,
#                 "per_unit_shipping_price": 0.0,
#                 "line_shipping": 0.0,
#                 "note": "ignored (service type)",
#             })
#             continue

#         w = _lx_raw_weight(p)
#         if w <= 0.0:
#             per_line_debug.append({
#                 "product": p.display_name,
#                 "has_bom": _lx_has_bom_sudo(p),
#                 "qty": qty,
#                 "unit_weight_for_bracket": 0.0,
#                 "bracket": None,
#                 "per_unit_shipping_price": 0.0,
#                 "line_shipping": 0.0,
#                 "note": "ignored (no weight)",
#             })
#             continue

#         has_bom = _lx_has_bom_sudo(p)

#         # Non-BoM => aggregate later
#         if not has_bom:
#             non_bom_total_weight += w * qty
#             per_line_debug.append({
#                 "product": p.display_name,
#                 "has_bom": False,
#                 "qty": qty,
#                 "unit_weight_for_bracket": 0.0,
#                 "bracket": None,
#                 "per_unit_shipping_price": 0.0,
#                 "line_shipping": 0.0,
#                 "note": "aggregated later (no BoM, weight>0)",
#             })
#             continue

#         # BoM => per unit bracket
#         unit_w = w
#         br = _lx_find_bracket_for_weight(unit_w, brackets)
#         if not br:
#             raise UserError(_("No matching bracket for unit weight %.2f kg.") % unit_w)

#         per_unit_price = float(br.unit_price or 0.0)
#         line_total = per_unit_price * qty
#         raw_total += line_total

#         per_line_debug.append({
#             "product": p.display_name,
#             "has_bom": True,
#             "qty": qty,
#             "unit_weight_for_bracket": unit_w,
#             "bracket": {
#                 "min_kg": float(br.min_kg or 0.0),
#                 "max_kg": float(br.max_kg or 0.0),
#                 "unit_price": per_unit_price,
#             },
#             "per_unit_shipping_price": per_unit_price,
#             "line_shipping": line_total,
#             "note": "counted (BoM, weight>0)",
#         })

#     # Aggregate non-BoM
#     if non_bom_total_weight > 0.0:
#         br = _lx_find_bracket_for_weight(non_bom_total_weight, brackets)
#         if not br:
#             raise UserError(_("No matching bracket for total non-BoM weight %.2f kg.") % non_bom_total_weight)

#         agg_price = float(br.unit_price or 0.0)
#         raw_total += agg_price

#         per_line_debug.append({
#             "product": "Non-BoM aggregated",
#             "has_bom": False,
#             "qty": 1.0,
#             "unit_weight_for_bracket": float(non_bom_total_weight or 0.0),
#             "bracket": {
#                 "min_kg": float(br.min_kg or 0.0),
#                 "max_kg": float(br.max_kg or 0.0),
#                 "unit_price": float(br.unit_price or 0.0),
#             },
#             "per_unit_shipping_price": float(br.unit_price or 0.0),
#             "line_shipping": agg_price,
#             "note": "counted as 1 unit (sum of non-BoM weights)",
#         })

#     return float(raw_total or 0.0), per_line_debug


# # ---------------------------------------------------------
# # Controller (FINAL)
# # ---------------------------------------------------------
# class WebsiteSaleLx(WebsiteSale):

#     # -----------------------------
#     # PREVIEW: compute prices for all carriers WITHOUT writing anything
#     # (used by your JS to overwrite the fixed_price flicker)
#     # -----------------------------
#     @http.route(["/lx/shipping/preview_prices"], type="json", auth="public", website=True, csrf=False)
#     def lx_preview_prices(self, **kw):
#         order = _lx_sale_get_order(force_create=True)
#         if not order:
#             return {"status": "no_order", "prices": {}}

#         zip_code = (order.partner_shipping_id.zip or "").strip()
#         shipping_rate = _lookup_shipping_rate(zip_code)
#         is_intracity = bool(getattr(shipping_rate, "is_intracity", False)) if shipping_rate else None

#         carriers = request.env["delivery.carrier"].sudo().search([("website_published", "=", True)])
#         prices = {}
#         debug_by_carrier = {}

#         for c in carriers:
#             name_norm = (c.name or "").strip().lower()
#             try:
#                 # STANDARD (strict ZIP)
#                 if name_norm == "standard delivery":
#                     if not shipping_rate:
#                         prices[c.id] = 0.0
#                         debug_by_carrier[c.id] = {"ok": False, "reason": "no_shipping_rate_for_zip"}
#                         continue

#                     raw_price = float(getattr(shipping_rate, "price", 0.0) or 0.0)
#                     final_price, free_applied, free_reason, thr_used, merch_total, forced = _apply_free_logic(order, raw_price)
#                     prices[c.id] = float(final_price or 0.0)
#                     debug_by_carrier[c.id] = {
#                         "ok": True,
#                         "route": "standard_city_strict_preview",
#                         "zip": zip_code,
#                         "shipping_rate_id": shipping_rate.id,
#                         "is_intracity": is_intracity,
#                         "raw_price": raw_price,
#                         "final_price": float(final_price or 0.0),
#                         "free_applied": bool(free_applied),
#                         "free_reason": free_reason,
#                         "threshold": float(thr_used or 0.0),
#                         "merch_total_excl_services": float(merch_total or 0.0),
#                         "forced_session": bool(forced),
#                     }
#                     continue

#                 # EXPRESS (strict brackets)
#                 if name_norm == "express delivery":
#                     if not shipping_rate:
#                         prices[c.id] = 0.0
#                         debug_by_carrier[c.id] = {"ok": False, "reason": "no_shipping_rate_for_zip"}
#                         continue

#                     raw_price, _per_line_debug = _compute_express_raw_price(order, bool(shipping_rate.is_intracity))
#                     final_price, free_applied, free_reason, thr_used, merch_total, forced = _apply_free_logic(order, raw_price)
#                     prices[c.id] = float(final_price or 0.0)
#                     debug_by_carrier[c.id] = {
#                         "ok": True,
#                         "route": "express_weight_strict_preview",
#                         "zip": zip_code,
#                         "shipping_rate_id": shipping_rate.id,
#                         "is_intracity": bool(shipping_rate.is_intracity),
#                         "bracket_kind": "intra" if bool(shipping_rate.is_intracity) else "inter",
#                         "raw_price": float(raw_price or 0.0),
#                         "final_price": float(final_price or 0.0),
#                         "free_applied": bool(free_applied),
#                         "free_reason": free_reason,
#                         "threshold": float(thr_used or 0.0),
#                         "merch_total_excl_services": float(merch_total or 0.0),
#                         "forced_session": bool(forced),
#                     }
#                     continue

#                 # Other carriers: keep 0.0 (so you NEVER show fixed_price)
#                 prices[c.id] = 0.0
#                 debug_by_carrier[c.id] = {"ok": False, "route": "unsupported_carrier_preview"}

#             except Exception as e:
#                 prices[c.id] = 0.0
#                 debug_by_carrier[c.id] = {
#                     "ok": False,
#                     "route": "preview_exception",
#                     "error": str(e),
#                     "error_name": _err_name(e),
#                 }

#         return {
#             "status": "success",
#             "zip": zip_code,
#             "is_intracity": is_intracity,
#             "currency": _currency_payload(order),
#             "prices": prices,
#             "lx_debug": {"by_carrier": debug_by_carrier},
#         }

#     # -----------------------------
#     # APPLY: compute + write delivery line (this is the ONLY place that writes)
#     # -----------------------------
#     @http.route(["/shop/carrier_rate_shipment"], type="json", auth="public", website=True, csrf=False)
#     def carrier_rate_shipment(self, carrier_id=None, **kw):
#         order = _lx_sale_get_order(force_create=True)
#         if not order:
#             return {"status": "error", "error": "no_order", "lx_debug": {"route": "early_exit", "reason": "no_order"}}

#         # accept carrier_id from args or kw
#         if carrier_id is None:
#             carrier_id = kw.get("carrier_id")

#         try:
#             carrier_id = int(carrier_id)
#         except Exception as e:
#             return {
#                 "status": "error",
#                 "error": "bad_carrier_id",
#                 "message": str(e),
#                 "lx_debug": {"route": "early_exit", "reason": "bad_carrier_id", "error": str(e)},
#             }

#         carrier = request.env["delivery.carrier"].sudo().browse(carrier_id)
#         if not carrier.exists():
#             return {
#                 "status": "error",
#                 "error": "carrier_not_found",
#                 "lx_debug": {"route": "early_exit", "reason": "carrier_not_found", "carrier_id": carrier_id},
#             }

#         zip_code = (order.partner_shipping_id.zip or "").strip()
#         shipping_rate = _lookup_shipping_rate(zip_code)
#         is_intracity = bool(getattr(shipping_rate, "is_intracity", False)) if shipping_rate else None

#         base_debug = {
#             "zip": zip_code,
#             "carrier_id": carrier.id,
#             "carrier_name": carrier.name,
#             "currency": _currency_payload(order),
#             "order": {
#                 "id": order.id,
#                 "amount_total": float(order.amount_total or 0.0),
#                 "amount_delivery_before": float(getattr(order, "amount_delivery", 0.0) or 0.0),
#             },
#             "is_intracity": is_intracity,
#         }

#         carrier_name_norm = (carrier.name or "").strip().lower()

#         # -----------------------------
#         # STANDARD: strict shipping.rate by ZIP
#         # -----------------------------
#         if carrier_name_norm == "standard delivery":
#             if not shipping_rate:
#                 debug = dict(base_debug, **{
#                     "route": "standard_city_strict",
#                     "reason": "missing_zip_or_no_shipping_rate",
#                     "shipping_rate_id": None,
#                     "calc": {"raw_price": None, "final_price": None},
#                 })
#                 return {
#                     "status": "error",
#                     "error": "no_shipping_rate_for_zip",
#                     "carrier_id": carrier.id,
#                     "new_amount_delivery": 0.0,
#                     "lx_debug": debug,
#                 }

#             raw_price = float(getattr(shipping_rate, "price", 0.0) or 0.0)
#             final_price, free_applied, free_reason, thr_used, merch_total, forced = _apply_free_logic(order, raw_price)

#             applied = _apply_delivery_line(order, carrier, float(final_price or 0.0))

#             debug = dict(base_debug, **{
#                 "route": "standard_city_strict",
#                 "reason": "carrier_is_standard_delivery",
#                 "shipping_rate_id": shipping_rate.id,
#                 "apply_delivery_line": bool(applied),
#                 "calc": {"raw_price": raw_price, "final_price": float(final_price or 0.0)},
#                 "free_logic": {
#                     "applied": bool(free_applied),
#                     "reason": free_reason,
#                     "threshold": float(thr_used or 0.0),
#                     "merch_total_excl_services": float(merch_total or 0.0),
#                     "forced_session": bool(forced),
#                 },
#                 "formula": "STRICT STANDARD: shipping.rate.price (ZIP) -> apply_free_logic -> final_price",
#             })

#             return {
#                 "status": "success",
#                 "carrier_id": carrier.id,
#                 "new_amount_delivery": float(final_price or 0.0),
#                 "is_free_delivery": bool(free_applied),
#                 "lx_debug": debug,
#             }

#         # -----------------------------
#         # EXPRESS: strict brackets by kind (intra/inter)
#         # -----------------------------
#         if carrier_name_norm == "express delivery":
#             if not shipping_rate:
#                 debug = dict(base_debug, **{
#                     "route": "express_weight_strict",
#                     "reason": "missing_zip_or_no_shipping_rate",
#                     "shipping_rate_id": None,
#                     "calc": {"raw_price": None, "final_price": None},
#                 })
#                 return {
#                     "status": "error",
#                     "error": "no_shipping_rate_for_zip",
#                     "carrier_id": carrier.id,
#                     "new_amount_delivery": 0.0,
#                     "lx_debug": debug,
#                 }

#             try:
#                 raw_price, per_line_debug = _compute_express_raw_price(order, bool(shipping_rate.is_intracity))
#                 final_price, free_applied, free_reason, thr_used, merch_total, forced = _apply_free_logic(order, raw_price)

#                 applied = _apply_delivery_line(order, carrier, float(final_price or 0.0))

#                 debug = dict(base_debug, **{
#                     "route": "express_weight_strict",
#                     "reason": "carrier_is_express_delivery",
#                     "shipping_rate_id": shipping_rate.id,
#                     "bracket_kind": "intra" if bool(shipping_rate.is_intracity) else "inter",
#                     "apply_delivery_line": bool(applied),
#                     "calc": {"raw_price": float(raw_price or 0.0), "final_price": float(final_price or 0.0)},
#                     "free_logic": {
#                         "applied": bool(free_applied),
#                         "reason": free_reason,
#                         "threshold": float(thr_used or 0.0),
#                         "merch_total_excl_services": float(merch_total or 0.0),
#                         "forced_session": bool(forced),
#                     },
#                     "order_lines": per_line_debug,
#                     "formula": "STRICT EXPRESS: shipping.rate.is_intracity -> delivery.bracket.lx(kind) -> BoM per-unit + non-BoM aggregated -> apply_free_logic -> final_price",
#                 })

#                 return {
#                     "status": "success",
#                     "carrier_id": carrier.id,
#                     "new_amount_delivery": float(final_price or 0.0),
#                     "is_free_delivery": bool(free_applied),
#                     "lx_debug": debug,
#                 }

#             except Exception as e:
#                 _logger.exception("Express compute error")
#                 debug = dict(base_debug, **{
#                     "route": "express_weight_strict",
#                     "reason": "compute_exception",
#                     "shipping_rate_id": getattr(shipping_rate, "id", None),
#                     "error": str(e),
#                     "error_name": _err_name(e),
#                     "error_trace": _short_trace(),
#                     "calc": {"raw_price": None, "final_price": None},
#                 })
#                 return {
#                     "status": "error",
#                     "error": "compute_exception",
#                     "carrier_id": carrier.id,
#                     "new_amount_delivery": 0.0,
#                     "lx_debug": debug,
#                 }

#         # -----------------------------
#         # Any other carrier: no fallback to fixed_price
#         # (to avoid the overwrite you hate)
#         # -----------------------------
#         debug = dict(base_debug, **{
#             "route": "unsupported_carrier",
#             "reason": "carrier_name_not_supported",
#             "calc": {"raw_price": None, "final_price": None},
#         })
#         return {
#             "status": "error",
#             "error": "unsupported_carrier",
#             "carrier_id": carrier.id,
#             "new_amount_delivery": 0.0,
#             "lx_debug": debug,
#         }


