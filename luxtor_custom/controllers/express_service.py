# -*- coding: utf-8 -*-
from odoo import http, fields
from odoo.http import request
from contextlib import contextmanager
from datetime import datetime, time
import pytz

PRIORITY_CODE = "PRIORITY_SERVICE"
REWARD_MODEL = "lx.review.reward"


def _lx_sale_get_order(force_create=False):
    """V19-compatible cart order getter — replaces website.sale_get_order()."""
    try:
        return request.website.sale_get_order(force_create=force_create)
    except AttributeError:
        pass
    Order = request.env['sale.order'].sudo()
    order_id = request.session.get('sale_order_id')
    if order_id:
        order = Order.browse(int(order_id)).exists()
        if order:
            return order
    return Order.browse()


def _cart_remove_line(order, product_id, line_id):
    """V19-compatible: remove a specific order line."""
    try:
        order.with_context(skip_cart_verification=True)._cart_update_line_quantity(
            line_id=line_id, quantity=0
        )
    except AttributeError:
        order._cart_update(product_id=product_id, line_id=line_id, set_qty=0)


def _cart_add_product(order, product_id, qty):
    """V19-compatible: add or update a product in the cart."""
    try:
        order.with_context(skip_cart_verification=True)._cart_add(
            product_id=product_id, quantity=qty
        )
    except AttributeError:
        order._cart_update(product_id=product_id, set_qty=qty)


# -----------------------------
# Helpers
# -----------------------------
@contextmanager
def _savepoint(env):
    env.cr.execute("SAVEPOINT lx_priority_rm")
    try:
        yield
    except Exception:
        env.cr.execute("ROLLBACK TO SAVEPOINT lx_priority_rm")
        raise
    finally:
        env.cr.execute("RELEASE SAVEPOINT lx_priority_rm")


def _get_priority_product():
    return request.env["product.product"].sudo().search([("default_code", "=", PRIORITY_CODE)], limit=1)


def _qty_mrp_total(order):
    qty_total = 0.0
    Bom = request.env["mrp.bom"].sudo()

    tmpl_ids = set()
    lines = []
    for line in order.sudo().order_line:
        p = line.product_id
        if not p or line.display_type:
            continue
        tid = p.product_tmpl_id.id
        tmpl_ids.add(tid)
        lines.append((line, tid))

    if not tmpl_ids:
        return 0.0

    boms = Bom.search([("product_tmpl_id", "in", list(tmpl_ids))])
    has_bom_tmpl = set(boms.mapped("product_tmpl_id").ids)

    for line, tid in lines:
        if tid in has_bom_tmpl:
            qty_total += float(line.product_uom_qty or 0.0)

    return qty_total


def _find_priority_lines(order, product):
    return order.order_line.filtered(
        lambda l: not l.display_type and (
            l.product_id.id == product.id or
            l.product_id.product_tmpl_id.id == product.product_tmpl_id.id
        )
    )


def _currency_meta(order):
    cur = order.currency_id
    return (cur.symbol or "DH"), int(cur.decimal_places or 2)


def _fmt_money_en(amount, decimals=2, currency_symbol="DH"):
    return f"{amount:,.{decimals}f} {currency_symbol}".strip()


def _reward_message():
    return "Express delivery is free because you submitted a product review. Thank you."


def _get_reward_model():
    try:
        return request.env[REWARD_MODEL].sudo()
    except Exception:
        return None


def _current_partner(order=None):
    user = request.env.user
    try:
        is_public = user._is_public()
    except Exception:
        is_public = False

    if user and not is_public and user.partner_id:
        return user.partner_id.sudo()

    if order and order.partner_id:
        return order.partner_id.sudo()

    return None


def _today_utc_range():
    """
    Return (start_utc_naive, end_utc_naive) for the user's 'today' in UTC,
    so we can filter create_date safely.
    """
    user = request.env.user
    tzname = user.tz or "UTC"
    tz = pytz.timezone(tzname)

    today = fields.Date.context_today(user)
    local_start = tz.localize(datetime.combine(today, time(0, 0, 0)))
    local_end = tz.localize(datetime.combine(today, time(23, 59, 59)))

    start_utc = local_start.astimezone(pytz.UTC).replace(tzinfo=None)
    end_utc = local_end.astimezone(pytz.UTC).replace(tzinfo=None)
    return start_utc, end_utc


# -----------------------------
# DB Reviews = SOURCE OF TRUTH
# (UPDATED: only reviews created TODAY count)
# -----------------------------
def _has_any_review(order=None, product_id=None, product_tmpl_id=None):
    partner = _current_partner(order)
    if not partner:
        return False, None, 0

    Rating = request.env["rating.rating"].sudo()
    start_utc, end_utc = _today_utc_range()

    domain = [
        ("partner_id", "=", partner.id),
        ("res_model", "in", ["product.template", "product.product"]),
        ("create_date", ">=", start_utc),
        ("create_date", "<=", end_utc),
    ]

    # Optional filter
    if product_tmpl_id:
        try:
            domain += [("res_model", "=", "product.template"), ("res_id", "=", int(product_tmpl_id))]
        except Exception:
            pass
    elif product_id:
        try:
            domain += [("res_model", "=", "product.product"), ("res_id", "=", int(product_id))]
        except Exception:
            pass

    cnt = Rating.search_count(domain)
    last = Rating.search(domain, order="create_date desc", limit=1)
    return bool(cnt), (last if last else None), int(cnt or 0)


def _review_free_active(order=None):
    """
    Final decision (UPDATED):
    Express is FREE only if DB has a review for this partner created TODAY.
    """
    has_review, _last, _cnt = _has_any_review(order=order)
    return bool(has_review)


# -----------------------------
# Tracking reward model (optional, never blocks free)
# (kept, but prevent reusing old "available" records by scoping to TODAY)
# -----------------------------
def _ensure_tracking_reward_available(order=None):
    Reward = _get_reward_model()
    if not Reward:
        return None

    partner = _current_partner(order)
    if not partner:
        return None

    website = request.website
    start_utc, end_utc = _today_utc_range()

    rec = Reward.search([
        ("partner_id", "=", partner.id),
        ("website_id", "=", website.id),
        ("state", "=", "available"),
        ("create_date", ">=", start_utc),
        ("create_date", "<=", end_utc),
    ], limit=1)
    if rec:
        return rec

    # Create only if "today" review exists
    if not _review_free_active(order):
        return None

    has_review, last_rating, _cnt = _has_any_review(order=order)
    vals = {
        "partner_id": partner.id,
        "website_id": website.id,
        "state": "available",
    }
    if last_rating:
        try:
            vals["rating"] = int(last_rating.rating or 0)
        except Exception:
            vals["rating"] = 0
        vals["message"] = last_rating.feedback or ""

    try:
        return Reward.create(vals)
    except Exception:
        return None


def _consume_tracking_reward(order=None):
    Reward = _get_reward_model()
    if not Reward:
        return

    partner = _current_partner(order)
    if not partner:
        return

    website = request.website
    start_utc, end_utc = _today_utc_range()

    rec = Reward.search([
        ("partner_id", "=", partner.id),
        ("website_id", "=", website.id),
        ("state", "=", "available"),
        ("create_date", ">=", start_utc),
        ("create_date", "<=", end_utc),
    ], limit=1)

    if not rec:
        return

    vals = {"state": "used", "used_date": fields.Datetime.now()}
    if order:
        vals["order_id"] = order.id
    try:
        rec.write(vals)
    except Exception:
        pass


# -----------------------------
# Price computation
# -----------------------------
def _compute_unit_price(product, order):
    if _review_free_active(order):
        return 0.0
    return float(product.sudo().lst_price or 0.0)


def _refresh_totals_dict(order, unit_price, currency_symbol, decimals):
    fields_to_invalidate = ["amount_total", "amount_delivery", "amount_untaxed", "amount_tax"]
    order.invalidate_recordset(fields_to_invalidate)
    recompute = getattr(order, "_amount_all", None)
    if callable(recompute):
        recompute()
        order.invalidate_recordset(fields_to_invalidate)

    total_formatted = _fmt_money_en(order.amount_total, decimals, currency_symbol)
    reward_active = _review_free_active(order)
    is_free = bool(float(unit_price or 0.0) <= 0.0)

    return {
        "ok": True,
        "enabled": False,
        "qty": 0.0,
        "unit_price": unit_price,
        "unit_formatted": f"+({unit_price:.2f} {currency_symbol})",
        "unit_label": "Free" if is_free else f"+({unit_price:.2f} {currency_symbol})",
        "is_free": is_free,
        "bom_qty": _qty_mrp_total(order),
        "total": order.amount_total,
        "total_formatted": total_formatted,
        "amount_delivery": order.amount_delivery,
        "amount_untaxed": order.amount_untaxed,
        "amount_tax": order.amount_tax,
        "currency": currency_symbol,
        "decimals": decimals,

        "reward_express_free": bool(reward_active),
        "reward_message": _reward_message() if reward_active else "",
    }


def _ensure_single_priority_line(order, product, qty, unit_price):
    lines = _find_priority_lines(order, product)
    if lines:
        keep = lines[:1]
        keep.write({
            "product_uom_qty": qty,
            "price_unit": unit_price,
            "tax_ids": [(5,)],
        })
        (lines - keep).unlink()
        return keep

    _cart_add_product(order, product.id, qty)
    line = _find_priority_lines(order, product)[:1]
    if line:
        line.write({"price_unit": unit_price, "tax_ids": [(5,)]})
    return line


# -----------------------------
# Controller
# -----------------------------
class PriorityServiceController(http.Controller):
    """
    Priority-only endpoints (NO pricelist/tax mapping).
    PRICE decision = DB reviews (rating.rating) created TODAY only.
    Reward model = optional tracking only (never blocks free).
    """

    @http.route("/lx/review/reward", type="json", auth="public", website=True, csrf=False)
    def lx_review_reward(self, review=None, **kw):
        """
        Kept for compatibility.
        But price/free decision no longer depends on this endpoint.
        """
        order = _lx_sale_get_order(force_create=True)
        partner = _current_partner(order)
        Reward = _get_reward_model()
        if not Reward or not partner:
            return {"ok": False, "error": "Reward model or partner not available"}

        # keep original behavior but scoped to today (avoid reusing old 'available')
        start_utc, end_utc = _today_utc_range()
        exists = Reward.search([
            ("partner_id", "=", partner.id),
            ("website_id", "=", request.website.id),
            ("state", "=", "available"),
            ("create_date", ">=", start_utc),
            ("create_date", "<=", end_utc),
        ], limit=1)
        if exists:
            return {"ok": True, "reward_express_free": True, "message": "Reward already available."}

        vals = {
            "partner_id": partner.id,
            "website_id": request.website.id,
            "state": "available",
        }

        if isinstance(review, dict):
            try:
                vals["rating"] = int(review.get("rating") or 0)
            except Exception:
                vals["rating"] = 0
            vals["message"] = review.get("message") or ""

            pid = review.get("product_id")
            if pid:
                try:
                    prod = request.env["product.product"].sudo().browse(int(pid))
                    if prod.exists():
                        vals["product_id"] = prod.id
                except Exception:
                    pass

        Reward.create(vals)

        return {
            "ok": True,
            "reward_express_free": True,
            "message": "Express delivery is now free. Thank you for your review.",
        }

    @http.route("/lx/review/status", type="json", auth="public", website=True, csrf=False)
    def lx_review_status(self, **kw):
        order = _lx_sale_get_order()
        partner = _current_partner(order)

        active = _review_free_active(order)
        if active:
            _ensure_tracking_reward_available(order)  # optional audit (today-scoped)

        last_review = {}
        has_review, last_rating, cnt = _has_any_review(order=order)
        if last_rating:
            last_review = {
                "rating": int(last_rating.rating or 0),
                "message": last_rating.feedback or "",
                "count": int(cnt or 0),
            }

        return {
            "ok": True,
            "free_flag": bool(active),
            "used_flag": False,
            "active": bool(active),
            "last_review": last_review,
            "sid": request.session.sid if hasattr(request.session, "sid") else "",
            "partner_id": partner.id if partner else False,
        }

    @http.route("/lx/review/reset", type="json", auth="public", website=True, csrf=False)
    def lx_review_reset(self, **kw):
        """
        Debug/admin helper: cancel today's available tracking rewards
        (doesn't affect free if reviews exist today).
        """
        order = _lx_sale_get_order()
        partner = _current_partner(order)
        Reward = _get_reward_model()
        if not Reward or not partner:
            return {"ok": False}

        start_utc, end_utc = _today_utc_range()
        recs = Reward.search([
            ("partner_id", "=", partner.id),
            ("website_id", "=", request.website.id),
            ("state", "=", "available"),
            ("create_date", ">=", start_utc),
            ("create_date", "<=", end_utc),
        ])
        if recs:
            recs.write({"state": "cancelled"})
        return {"ok": True}

    @http.route("/lx/priority/price", type="json", auth="public", website=True, csrf=False)
    def priority_price(self, **kw):
        order = _lx_sale_get_order()
        prod = _get_priority_product()
        if not (order and prod):
            return {"ok": False, "error": "Order or PRIORITY_SERVICE not found"}

        currency_symbol, decimals = _currency_meta(order)

        reward_active = _review_free_active(order)
        if reward_active:
            _ensure_tracking_reward_available(order)  # optional audit (today-scoped)

        unit_price = _compute_unit_price(prod, order)

        return {
            "ok": True,
            "default_code": PRIORITY_CODE,
            "unit_price": unit_price,
            "unit_formatted": f"+({unit_price:.2f} {currency_symbol})",
            "unit_label": "Free" if float(unit_price or 0.0) <= 0.0 else f"+({unit_price:.2f} {currency_symbol})",
            "is_free": bool(float(unit_price or 0.0) <= 0.0),
            "currency": currency_symbol,
            "decimals": decimals,

            "reward_express_free": bool(reward_active),
            "reward_message": _reward_message() if reward_active else "",
        }

    @http.route("/lx/priority/mrp_qty", type="json", auth="public", website=True, csrf=False)
    def priority_mrp_qty(self, **kw):
        order = _lx_sale_get_order()
        if not order:
            return {"ok": True, "qty_total": 0.0}
        return {"ok": True, "qty_total": _qty_mrp_total(order)}

    @http.route("/lx/priority/has", type="json", auth="public", website=True, csrf=False)
    def priority_has(self, **kw):
        order = _lx_sale_get_order()
        prod = _get_priority_product()
        if not (order and prod):
            return {"ok": True, "enabled": False, "is_free": False}
        unit_price = _compute_unit_price(prod, order)
        return {
            "ok": True,
            "enabled": bool(_find_priority_lines(order.sudo(), prod)),
            "is_free": bool(float(unit_price or 0.0) <= 0.0),
        }

    @http.route("/lx/priority/apply", type="json", auth="public", website=True, csrf=False)
    def priority_apply(self, enabled=False, qty=0.0, **kw):
        order = _lx_sale_get_order(force_create=True)
        prod = _get_priority_product()
        if not (order and prod):
            return {"ok": False}

        order = order.sudo()
        currency_symbol, decimals = _currency_meta(order)

        reward_active_before = _review_free_active(order)
        if reward_active_before:
            _ensure_tracking_reward_available(order)  # optional audit (today-scoped)

        unit_price = _compute_unit_price(prod, order)

        try:
            qty = float(qty or 0.0)
        except Exception:
            qty = 0.0

        if enabled and qty <= 0.0:
            qty = _qty_mrp_total(order)

        if (not enabled) or qty <= 0.0:
            lines = _find_priority_lines(order, prod)
            for l in lines:
                _cart_remove_line(order, prod.id, l.id)
            _find_priority_lines(order, prod).unlink()
        else:
            _ensure_single_priority_line(order, prod, qty, unit_price)

            # optional tracking: mark today's available record as used
            if reward_active_before:
                _consume_tracking_reward(order)

        order.invalidate_recordset(["amount_total", "amount_delivery", "amount_untaxed", "amount_tax"])
        total_formatted = _fmt_money_en(order.amount_total, decimals, currency_symbol)

        reward_active_after = _review_free_active(order)

        return {
            "ok": True,
            "enabled": bool(enabled and qty > 0.0),
            "qty": qty,
            "unit_price": unit_price,
            "unit_formatted": f"+({unit_price:.2f} {currency_symbol})",
            "unit_label": "Free" if float(unit_price or 0.0) <= 0.0 else f"+({unit_price:.2f} {currency_symbol})",
            "is_free": bool(float(unit_price or 0.0) <= 0.0),
            "bom_qty": _qty_mrp_total(order),
            "total": order.amount_total,
            "total_formatted": total_formatted,
            "amount_delivery": order.amount_delivery,
            "amount_untaxed": order.amount_untaxed,
            "amount_tax": order.amount_tax,
            "currency": currency_symbol,
            "decimals": decimals,

            "reward_express_free": bool(reward_active_after),
            "reward_message": _reward_message() if reward_active_after else "",
        }

    @http.route("/lx/priority/remove", type="json", auth="public", website=True, csrf=False)
    def priority_remove(self, **kw):
        order = _lx_sale_get_order(force_create=True)
        prod = _get_priority_product()
        if not (order and prod):
            return {"ok": False}

        order = order.sudo()
        currency_symbol, decimals = _currency_meta(order)
        unit_price = _compute_unit_price(prod, order)

        with _savepoint(request.env):
            lines = _find_priority_lines(order, prod)
            for l in lines:
                _cart_remove_line(order, l.product_id.id, l.id)
            _find_priority_lines(order, prod).unlink()

        return _refresh_totals_dict(order, unit_price, currency_symbol, decimals)

    @http.route("/lx/review/existing", type="json", auth="public", website=True, csrf=False)
    def lx_review_existing(self, product_id=None, product_tmpl_id=None, **kw):
        order = _lx_sale_get_order()
        partner = _current_partner(order)
        if not partner:
            return {"ok": True, "has_review": False, "count": 0, "reason": "no_partner"}

        has_review, last, cnt = _has_any_review(order=order, product_id=product_id, product_tmpl_id=product_tmpl_id)

        last_info = {}
        if last:
            last_info = {
                "rating": last.rating,
                "feedback": last.feedback or "",
                "create_date": str(last.create_date) if last.create_date else "",
                "res_model": last.res_model,
                "res_id": last.res_id,
            }

        return {
            "ok": True,
            "has_review": bool(has_review),
            "count": int(cnt or 0),
            "partner_id": partner.id,
            "last": last_info,
        }



# # -----------------------------
# # Helpers
# # -----------------------------
# @contextmanager
# def _savepoint(env):
#     env.cr.execute("SAVEPOINT lx_priority_rm")
#     try:
#         yield
#     except Exception:
#         env.cr.execute("ROLLBACK TO SAVEPOINT lx_priority_rm")
#         raise
#     finally:
#         env.cr.execute("RELEASE SAVEPOINT lx_priority_rm")


# def _get_priority_product():
#     return request.env["product.product"].sudo().search([("default_code", "=", PRIORITY_CODE)], limit=1)


# def _qty_mrp_total(order):
#     qty_total = 0.0
#     Bom = request.env["mrp.bom"].sudo()

#     tmpl_ids = set()
#     lines = []
#     for line in order.sudo().order_line:
#         p = line.product_id
#         if not p or line.display_type:
#             continue
#         tid = p.product_tmpl_id.id
#         tmpl_ids.add(tid)
#         lines.append((line, tid))

#     if not tmpl_ids:
#         return 0.0

#     boms = Bom.search([("product_tmpl_id", "in", list(tmpl_ids))])
#     has_bom_tmpl = set(boms.mapped("product_tmpl_id").ids)

#     for line, tid in lines:
#         if tid in has_bom_tmpl:
#             qty_total += float(line.product_uom_qty or 0.0)

#     return qty_total


# def _find_priority_lines(order, product):
#     return order.order_line.filtered(
#         lambda l: not l.display_type and (
#             l.product_id.id == product.id or
#             l.product_id.product_tmpl_id.id == product.product_tmpl_id.id
#         )
#     )


# def _currency_meta(order):
#     cur = order.currency_id
#     return (cur.symbol or "DH"), int(cur.decimal_places or 2)


# def _fmt_money_en(amount, decimals=2, currency_symbol="DH"):
#     return f"{amount:,.{decimals}f} {currency_symbol}".strip()


# def _reward_message():
#     return "Express delivery is free because you submitted a product review. Thank you."


# def _get_reward_model():
#     try:
#         return request.env[REWARD_MODEL].sudo()
#     except Exception:
#         return None


# def _current_partner(order=None):
#     user = request.env.user
#     try:
#         is_public = user._is_public()
#     except Exception:
#         is_public = False

#     if user and not is_public and user.partner_id:
#         return user.partner_id.sudo()

#     if order and order.partner_id:
#         return order.partner_id.sudo()

#     return None


# # -----------------------------
# # DB Reviews = SOURCE OF TRUTH
# # -----------------------------
# def _has_any_review(order=None, product_id=None, product_tmpl_id=None):
#     partner = _current_partner(order)
#     if not partner:
#         return False, None, 0

#     Rating = request.env["rating.rating"].sudo()
#     domain = [
#         ("partner_id", "=", partner.id),
#         ("res_model", "in", ["product.template", "product.product"]),
#     ]

#     # Optional filter
#     if product_tmpl_id:
#         try:
#             domain += [("res_model", "=", "product.template"), ("res_id", "=", int(product_tmpl_id))]
#         except Exception:
#             pass
#     elif product_id:
#         try:
#             domain += [("res_model", "=", "product.product"), ("res_id", "=", int(product_id))]
#         except Exception:
#             pass

#     cnt = Rating.search_count(domain)
#     last = Rating.search(domain, order="create_date desc", limit=1)
#     return bool(cnt), (last if last else None), int(cnt or 0)


# def _review_free_active(order=None):
#     """
#     Final decision:
#     If DB has any review for this partner => Express is FREE.
#     """
#     has_review, _last, _cnt = _has_any_review(order=order)
#     return bool(has_review)


# # -----------------------------
# # Tracking reward model (optional, never blocks free)
# # -----------------------------
# def _ensure_tracking_reward_available(order=None):
#     """
#     Optional: create 'available' reward record when review exists (for audit).
#     Never blocks price if missing.
#     """
#     Reward = _get_reward_model()
#     if not Reward:
#         return None

#     partner = _current_partner(order)
#     if not partner:
#         return None

#     website = request.website
#     rec = Reward.search([
#         ("partner_id", "=", partner.id),
#         ("website_id", "=", website.id),
#         ("state", "=", "available"),
#     ], limit=1)
#     if rec:
#         return rec

#     # Create only if review exists
#     if not _review_free_active(order):
#         return None

#     has_review, last_rating, _cnt = _has_any_review(order=order)
#     vals = {
#         "partner_id": partner.id,
#         "website_id": website.id,
#         "state": "available",
#     }
#     if last_rating:
#         try:
#             vals["rating"] = int(last_rating.rating or 0)
#         except Exception:
#             vals["rating"] = 0
#         vals["message"] = last_rating.feedback or ""

#     try:
#         return Reward.create(vals)
#     except Exception:
#         return None


# def _consume_tracking_reward(order=None):
#     """
#     Optional: mark one available record as used (audit only).
#     Express stays free anyway if reviews exist.
#     """
#     Reward = _get_reward_model()
#     if not Reward:
#         return

#     partner = _current_partner(order)
#     if not partner:
#         return

#     website = request.website
#     rec = Reward.search([
#         ("partner_id", "=", partner.id),
#         ("website_id", "=", website.id),
#         ("state", "=", "available"),
#     ], limit=1)

#     if not rec:
#         return

#     vals = {"state": "used", "used_date": fields.Datetime.now()}
#     if order:
#         vals["order_id"] = order.id
#     try:
#         rec.write(vals)
#     except Exception:
#         pass


# # -----------------------------
# # Price computation
# # -----------------------------
# def _compute_unit_price(product, order):
#     if _review_free_active(order):
#         return 0.0
#     return float(product.sudo().lst_price or 0.0)


# def _refresh_totals_dict(order, unit_price, currency_symbol, decimals):
#     fields_to_invalidate = ["amount_total", "amount_delivery", "amount_untaxed", "amount_tax"]
#     order.invalidate_recordset(fields_to_invalidate)
#     recompute = getattr(order, "_amount_all", None)
#     if callable(recompute):
#         recompute()
#         order.invalidate_recordset(fields_to_invalidate)

#     total_formatted = _fmt_money_en(order.amount_total, decimals, currency_symbol)
#     reward_active = _review_free_active(order)

#     return {
#         "ok": True,
#         "enabled": False,
#         "qty": 0.0,
#         "unit_price": unit_price,
#         "unit_formatted": f"+({unit_price:.2f} {currency_symbol})",
#         "bom_qty": _qty_mrp_total(order),
#         "total": order.amount_total,
#         "total_formatted": total_formatted,
#         "amount_delivery": order.amount_delivery,
#         "amount_untaxed": order.amount_untaxed,
#         "amount_tax": order.amount_tax,
#         "currency": currency_symbol,
#         "decimals": decimals,

#         "reward_express_free": bool(reward_active),
#         "reward_message": _reward_message() if reward_active else "",
#     }


# def _ensure_single_priority_line(order, product, qty, unit_price):
#     lines = _find_priority_lines(order, product)
#     if lines:
#         keep = lines[:1]
#         keep.write({
#             "product_uom_qty": qty,
#             "price_unit": unit_price,
#             "tax_ids": [(5,)],
#         })
#         (lines - keep).unlink()
#         return keep

#     order._cart_update(product_id=product.id, set_qty=qty)
#     line = _find_priority_lines(order, product)[:1]
#     if line:
#         line.write({"price_unit": unit_price, "tax_ids": [(5,)]})
#     return line


# # -----------------------------
# # Controller
# # -----------------------------
# class PriorityServiceController(http.Controller):
#     """
#     Priority-only endpoints (NO pricelist/tax mapping).
#     PRICE decision = DB reviews (rating.rating).
#     Reward model = optional tracking only (never blocks free).
#     """

#     @http.route("/lx/review/reward", type="json", auth="public", website=True, csrf=False)
#     def lx_review_reward(self, review=None, **kw):
#         """
#         Kept for compatibility.
#         But price/free decision no longer depends on this endpoint.
#         """
#         order = _lx_sale_get_order(force_create=True)
#         partner = _current_partner(order)
#         Reward = _get_reward_model()
#         if not Reward or not partner:
#             return {"ok": False, "error": "Reward model or partner not available"}

#         exists = Reward.search([
#             ("partner_id", "=", partner.id),
#             ("website_id", "=", request.website.id),
#             ("state", "=", "available"),
#         ], limit=1)
#         if exists:
#             return {"ok": True, "reward_express_free": True, "message": "Reward already available."}

#         vals = {
#             "partner_id": partner.id,
#             "website_id": request.website.id,
#             "state": "available",
#         }

#         if isinstance(review, dict):
#             try:
#                 vals["rating"] = int(review.get("rating") or 0)
#             except Exception:
#                 vals["rating"] = 0
#             vals["message"] = review.get("message") or ""

#             pid = review.get("product_id")
#             if pid:
#                 try:
#                     prod = request.env["product.product"].sudo().browse(int(pid))
#                     if prod.exists():
#                         vals["product_id"] = prod.id
#                 except Exception:
#                     pass

#         Reward.create(vals)

#         return {
#             "ok": True,
#             "reward_express_free": True,
#             "message": "Express delivery is now free. Thank you for your review.",
#         }

#     @http.route("/lx/review/status", type="json", auth="public", website=True, csrf=False)
#     def lx_review_status(self, **kw):
#         order = _lx_sale_get_order()
#         partner = _current_partner(order)

#         active = _review_free_active(order)
#         _ensure_tracking_reward_available(order)  # optional audit

#         last_review = {}
#         has_review, last_rating, cnt = _has_any_review(order=order)
#         if last_rating:
#             last_review = {
#                 "rating": int(last_rating.rating or 0),
#                 "message": last_rating.feedback or "",
#                 "count": int(cnt or 0),
#             }

#         return {
#             "ok": True,
#             "free_flag": bool(active),
#             "used_flag": False,
#             "active": bool(active),
#             "last_review": last_review,
#             "sid": request.session.sid if hasattr(request.session, "sid") else "",
#             "partner_id": partner.id if partner else False,
#         }

#     @http.route("/lx/review/reset", type="json", auth="public", website=True, csrf=False)
#     def lx_review_reset(self, **kw):
#         """
#         Debug/admin helper: cancel available tracking rewards (doesn't affect free if reviews exist).
#         """
#         order = _lx_sale_get_order()
#         partner = _current_partner(order)
#         Reward = _get_reward_model()
#         if not Reward or not partner:
#             return {"ok": False}

#         recs = Reward.search([
#             ("partner_id", "=", partner.id),
#             ("website_id", "=", request.website.id),
#             ("state", "=", "available"),
#         ])
#         if recs:
#             recs.write({"state": "cancelled"})
#         return {"ok": True}

#     @http.route("/lx/priority/price", type="json", auth="public", website=True, csrf=False)
#     def priority_price(self, **kw):
#         order = _lx_sale_get_order()
#         prod = _get_priority_product()
#         if not (order and prod):
#             return {"ok": False, "error": "Order or PRIORITY_SERVICE not found"}

#         currency_symbol, decimals = _currency_meta(order)

#         reward_active = _review_free_active(order)
#         if reward_active:
#             _ensure_tracking_reward_available(order)  # optional audit

#         unit_price = _compute_unit_price(prod, order)

#         return {
#             "ok": True,
#             "default_code": PRIORITY_CODE,
#             "unit_price": unit_price,
#             "unit_formatted": f"+({unit_price:.2f} {currency_symbol})",
#             "currency": currency_symbol,
#             "decimals": decimals,

#             "reward_express_free": bool(reward_active),
#             "reward_message": _reward_message() if reward_active else "",
#         }

#     @http.route("/lx/priority/mrp_qty", type="json", auth="public", website=True, csrf=False)
#     def priority_mrp_qty(self, **kw):
#         order = _lx_sale_get_order()
#         if not order:
#             return {"ok": True, "qty_total": 0.0}
#         return {"ok": True, "qty_total": _qty_mrp_total(order)}

#     @http.route("/lx/priority/has", type="json", auth="public", website=True, csrf=False)
#     def priority_has(self, **kw):
#         order = _lx_sale_get_order()
#         prod = _get_priority_product()
#         if not (order and prod):
#             return {"ok": True, "enabled": False}
#         return {"ok": True, "enabled": bool(_find_priority_lines(order.sudo(), prod))}

#     @http.route("/lx/priority/apply", type="json", auth="public", website=True, csrf=False)
#     def priority_apply(self, enabled=False, qty=0.0, **kw):
#         order = _lx_sale_get_order(force_create=True)
#         prod = _get_priority_product()
#         if not (order and prod):
#             return {"ok": False}

#         order = order.sudo()
#         currency_symbol, decimals = _currency_meta(order)

#         reward_active_before = _review_free_active(order)
#         if reward_active_before:
#             _ensure_tracking_reward_available(order)  # optional audit

#         unit_price = _compute_unit_price(prod, order)

#         try:
#             qty = float(qty or 0.0)
#         except Exception:
#             qty = 0.0

#         if enabled and qty <= 0.0:
#             qty = _qty_mrp_total(order)

#         if (not enabled) or qty <= 0.0:
#             lines = _find_priority_lines(order, prod)
#             for l in lines:
#                 order._cart_update(product_id=prod.id, line_id=l.id, set_qty=0)
#             _find_priority_lines(order, prod).unlink()
#         else:
#             _ensure_single_priority_line(order, prod, qty, unit_price)

#             # optional tracking: mark available as used
#             if reward_active_before:
#                 _consume_tracking_reward(order)

#         order.invalidate_recordset(["amount_total", "amount_delivery", "amount_untaxed", "amount_tax"])
#         total_formatted = _fmt_money_en(order.amount_total, decimals, currency_symbol)

#         reward_active_after = _review_free_active(order)

#         return {
#             "ok": True,
#             "enabled": bool(enabled and qty > 0.0),
#             "qty": qty,
#             "unit_price": unit_price,
#             "unit_formatted": f"+({unit_price:.2f} {currency_symbol})",
#             "bom_qty": _qty_mrp_total(order),
#             "total": order.amount_total,
#             "total_formatted": total_formatted,
#             "amount_delivery": order.amount_delivery,
#             "amount_untaxed": order.amount_untaxed,
#             "amount_tax": order.amount_tax,
#             "currency": currency_symbol,
#             "decimals": decimals,

#             "reward_express_free": bool(reward_active_after),
#             "reward_message": _reward_message() if reward_active_after else "",
#         }

#     @http.route("/lx/priority/remove", type="json", auth="public", website=True, csrf=False)
#     def priority_remove(self, **kw):
#         order = _lx_sale_get_order(force_create=True)
#         prod = _get_priority_product()
#         if not (order and prod):
#             return {"ok": False}

#         order = order.sudo()
#         currency_symbol, decimals = _currency_meta(order)
#         unit_price = _compute_unit_price(prod, order)

#         with _savepoint(request.env):
#             lines = _find_priority_lines(order, prod)
#             for l in lines:
#                 order._cart_update(product_id=l.product_id.id, line_id=l.id, set_qty=0)
#             _find_priority_lines(order, prod).unlink()

#         return _refresh_totals_dict(order, unit_price, currency_symbol, decimals)

#     @http.route("/lx/review/existing", type="json", auth="public", website=True, csrf=False)
#     def lx_review_existing(self, product_id=None, product_tmpl_id=None, **kw):
#         order = _lx_sale_get_order()
#         partner = _current_partner(order)
#         if not partner:
#             return {"ok": True, "has_review": False, "count": 0, "reason": "no_partner"}

#         has_review, last, cnt = _has_any_review(order=order, product_id=product_id, product_tmpl_id=product_tmpl_id)

#         last_info = {}
#         if last:
#             last_info = {
#                 "rating": last.rating,
#                 "feedback": last.feedback or "",
#                 "create_date": str(last.create_date) if last.create_date else "",
#                 "res_model": last.res_model,
#                 "res_id": last.res_id,
#             }

#         return {
#             "ok": True,
#             "has_review": bool(has_review),
#             "count": int(cnt or 0),
#             "partner_id": partner.id,
#             "last": last_info,
#         }



# # # -----------------------------
# # # Helpers
# # # -----------------------------
# # @contextmanager
# # def _savepoint(env):
# #     env.cr.execute("SAVEPOINT lx_priority_rm")
# #     try:
# #         yield
# #     except Exception:
# #         env.cr.execute("ROLLBACK TO SAVEPOINT lx_priority_rm")
# #         raise
# #     finally:
# #         env.cr.execute("RELEASE SAVEPOINT lx_priority_rm")


# # def _get_priority_product():
# #     return request.env["product.product"].sudo().search([("default_code", "=", PRIORITY_CODE)], limit=1)


# # def _qty_mrp_total(order):
# #     qty_total = 0.0
# #     Bom = request.env["mrp.bom"].sudo()

# #     tmpl_ids = set()
# #     lines = []
# #     for line in order.sudo().order_line:
# #         p = line.product_id
# #         if not p or line.display_type:
# #             continue
# #         tid = p.product_tmpl_id.id
# #         tmpl_ids.add(tid)
# #         lines.append((line, tid))

# #     if not tmpl_ids:
# #         return 0.0

# #     boms = Bom.search([("product_tmpl_id", "in", list(tmpl_ids))])
# #     has_bom_tmpl = set(boms.mapped("product_tmpl_id").ids)

# #     for line, tid in lines:
# #         if tid in has_bom_tmpl:
# #             qty_total += float(line.product_uom_qty or 0.0)

# #     return qty_total


# # def _find_priority_lines(order, product):
# #     return order.order_line.filtered(
# #         lambda l: not l.display_type and (
# #             l.product_id.id == product.id or
# #             l.product_id.product_tmpl_id.id == product.product_tmpl_id.id
# #         )
# #     )


# # def _currency_meta(order):
# #     cur = order.currency_id
# #     return (cur.symbol or "DH"), int(cur.decimal_places or 2)


# # def _fmt_money_en(amount, decimals=2, currency_symbol="DH"):
# #     return f"{amount:,.{decimals}f} {currency_symbol}".strip()


# # def _reward_message():
# #     return "Express delivery is free because you submitted a product review. Thank you."


# # def _get_reward_model():
# #     """
# #     Safety: if model not installed, behave as "no reward" (won't crash pages).
# #     """
# #     try:
# #         return request.env[REWARD_MODEL].sudo()
# #     except Exception:
# #         return None


# # def _current_partner(order=None):
# #     """
# #     DB reward is tied to partner.
# #     - Logged user => user.partner_id
# #     - Public user => cart partner_id (from sale order)
# #     """
# #     user = request.env.user
# #     try:
# #         is_public = user._is_public()
# #     except Exception:
# #         is_public = False

# #     if user and not is_public and user.partner_id:
# #         return user.partner_id.sudo()

# #     if order and order.partner_id:
# #         return order.partner_id.sudo()

# #     return None


# # def _reward_available(order=None):
# #     """
# #     Return (active_bool, reward_record_or_None)
# #     Active means there is an AVAILABLE reward record for current partner + website.
# #     """
# #     Reward = _get_reward_model()
# #     if not Reward:
# #         return False, None

# #     partner = _current_partner(order)
# #     if not partner:
# #         return False, None

# #     website = request.website
# #     rec = Reward.search([
# #         ("partner_id", "=", partner.id),
# #         ("website_id", "=", website.id),
# #         ("state", "=", "available"),
# #     ], limit=1)

# #     return bool(rec), rec if rec else None


# # def _consume_reward(rec, order=None):
# #     if not rec:
# #         return
# #     vals = {
# #         "state": "used",
# #         "used_date": fields.Datetime.now(),
# #     }
# #     if order:
# #         vals["order_id"] = order.id
# #     rec.sudo().write(vals)


# # def _compute_unit_price(product, order):
# #     active, _rec = _reward_available(order)
# #     if active:
# #         return 0.0
# #     return float(product.sudo().lst_price or 0.0)


# # def _refresh_totals_dict(order, unit_price, currency_symbol, decimals):
# #     fields_to_invalidate = ["amount_total", "amount_delivery", "amount_untaxed", "amount_tax"]
# #     order.invalidate_recordset(fields_to_invalidate)
# #     recompute = getattr(order, "_amount_all", None)
# #     if callable(recompute):
# #         recompute()
# #         order.invalidate_recordset(fields_to_invalidate)

# #     total_formatted = _fmt_money_en(order.amount_total, decimals, currency_symbol)

# #     reward_active, _rec = _reward_available(order)

# #     return {
# #         "ok": True,
# #         "enabled": False,
# #         "qty": 0.0,
# #         "unit_price": unit_price,
# #         "unit_formatted": f"+({unit_price:.2f} {currency_symbol})",
# #         "bom_qty": _qty_mrp_total(order),
# #         "total": order.amount_total,
# #         "total_formatted": total_formatted,
# #         "amount_delivery": order.amount_delivery,
# #         "amount_untaxed": order.amount_untaxed,
# #         "amount_tax": order.amount_tax,
# #         "currency": currency_symbol,
# #         "decimals": decimals,

# #         # keep same keys used by JS
# #         "reward_express_free": reward_active,
# #         "reward_message": _reward_message() if reward_active else "",
# #     }


# # def _ensure_single_priority_line(order, product, qty, unit_price):
# #     lines = _find_priority_lines(order, product)
# #     if lines:
# #         keep = lines[:1]
# #         keep.write({
# #             "product_uom_qty": qty,
# #             "price_unit": unit_price,
# #             "tax_ids": [(5,)],
# #         })
# #         (lines - keep).unlink()
# #         return keep

# #     order._cart_update(product_id=product.id, set_qty=qty)
# #     line = _find_priority_lines(order, product)[:1]
# #     if line:
# #         line.write({"price_unit": unit_price, "tax_ids": [(5,)]})
# #     return line


# # # -----------------------------
# # # Controller
# # # -----------------------------
# # class PriorityServiceController(http.Controller):
# #     """
# #     Priority-only endpoints (NO pricelist/tax mapping).
# #     Review reward is DB-backed (NOT session).
# #     """

# #     @http.route("/lx/review/reward", type="json", auth="public", website=True, csrf=False)
# #     def lx_review_reward(self, review=None, **kw):
# #         order = _lx_sale_get_order(force_create=True)
# #         partner = _current_partner(order)
# #         Reward = _get_reward_model()
# #         if not Reward or not partner:
# #             return {"ok": False, "error": "Reward model or partner not available"}

# #         # do not duplicate available reward
# #         exists = Reward.search([
# #             ("partner_id", "=", partner.id),
# #             ("website_id", "=", request.website.id),
# #             ("state", "=", "available"),
# #         ], limit=1)
# #         if exists:
# #             return {"ok": True, "reward_express_free": True, "message": "Reward already available."}

# #         vals = {
# #             "partner_id": partner.id,
# #             "website_id": request.website.id,
# #             "state": "available",
# #         }

# #         if isinstance(review, dict):
# #             try:
# #                 vals["rating"] = int(review.get("rating") or 0)
# #             except Exception:
# #                 vals["rating"] = 0
# #             vals["message"] = review.get("message") or ""

# #             pid = review.get("product_id")
# #             if pid:
# #                 try:
# #                     prod = request.env["product.product"].sudo().browse(int(pid))
# #                     if prod.exists():
# #                         vals["product_id"] = prod.id
# #                 except Exception:
# #                     pass

# #         Reward.create(vals)

# #         return {
# #             "ok": True,
# #             "reward_express_free": True,
# #             "message": "Express delivery is now free. Thank you for your review.",
# #         }

# #     @http.route("/lx/review/status", type="json", auth="public", website=True, csrf=False)
# #     def lx_review_status(self, **kw):
# #         order = _lx_sale_get_order()
# #         partner = _current_partner(order)

# #         active, rec = _reward_available(order)
# #         last_review = {}
# #         if rec:
# #             last_review = {
# #                 "product_name": rec.product_id.display_name if getattr(rec, "product_id", False) else "",
# #                 "rating": int(getattr(rec, "rating", 0) or 0),
# #                 "message": getattr(rec, "message", "") or "",
# #             }

# #         return {
# #             "ok": True,
# #             "free_flag": bool(active),
# #             "used_flag": bool(not active),
# #             "active": bool(active),
# #             "last_review": last_review,
# #             "sid": request.session.sid if hasattr(request.session, "sid") else "",
# #             "partner_id": partner.id if partner else False,
# #         }

# #     @http.route("/lx/review/reset", type="json", auth="public", website=True, csrf=False)
# #     def lx_review_reset(self, **kw):
# #         order = _lx_sale_get_order()
# #         partner = _current_partner(order)
# #         Reward = _get_reward_model()
# #         if not Reward or not partner:
# #             return {"ok": False}

# #         # cancel any available reward (admin/debug action)
# #         recs = Reward.search([
# #             ("partner_id", "=", partner.id),
# #             ("website_id", "=", request.website.id),
# #             ("state", "=", "available"),
# #         ])
# #         if recs:
# #             recs.write({"state": "cancelled"})
# #         return {"ok": True}

# #     @http.route("/lx/priority/price", type="json", auth="public", website=True, csrf=False)
# #     def priority_price(self, **kw):
# #         order = _lx_sale_get_order()
# #         prod = _get_priority_product()
# #         if not (order and prod):
# #             return {"ok": False, "error": "Order or PRIORITY_SERVICE not found"}

# #         currency_symbol, decimals = _currency_meta(order)
# #         unit_price = _compute_unit_price(prod, order)

# #         reward_active, _rec = _reward_available(order)

# #         return {
# #             "ok": True,
# #             "default_code": PRIORITY_CODE,
# #             "unit_price": unit_price,
# #             "unit_formatted": f"+({unit_price:.2f} {currency_symbol})",
# #             "currency": currency_symbol,
# #             "decimals": decimals,

# #             # keys used by your JS
# #             "reward_express_free": bool(reward_active),
# #             "reward_message": _reward_message() if reward_active else "",
# #         }

# #     @http.route("/lx/priority/mrp_qty", type="json", auth="public", website=True, csrf=False)
# #     def priority_mrp_qty(self, **kw):
# #         order = _lx_sale_get_order()
# #         if not order:
# #             return {"ok": True, "qty_total": 0.0}
# #         return {"ok": True, "qty_total": _qty_mrp_total(order)}

# #     @http.route("/lx/priority/has", type="json", auth="public", website=True, csrf=False)
# #     def priority_has(self, **kw):
# #         order = _lx_sale_get_order()
# #         prod = _get_priority_product()
# #         if not (order and prod):
# #             return {"ok": True, "enabled": False}
# #         return {"ok": True, "enabled": bool(_find_priority_lines(order.sudo(), prod))}

# #     @http.route("/lx/priority/apply", type="json", auth="public", website=True, csrf=False)
# #     def priority_apply(self, enabled=False, qty=0.0, **kw):
# #         order = _lx_sale_get_order(force_create=True)
# #         prod = _get_priority_product()
# #         if not (order and prod):
# #             return {"ok": False}

# #         order = order.sudo()
# #         currency_symbol, decimals = _currency_meta(order)

# #         reward_active_before, reward_rec = _reward_available(order)
# #         unit_price = _compute_unit_price(prod, order)

# #         try:
# #             qty = float(qty or 0.0)
# #         except Exception:
# #             qty = 0.0

# #         if enabled and qty <= 0.0:
# #             qty = _qty_mrp_total(order)

# #         if (not enabled) or qty <= 0.0:
# #             lines = _find_priority_lines(order, prod)
# #             for l in lines:
# #                 order._cart_update(product_id=prod.id, line_id=l.id, set_qty=0)
# #             _find_priority_lines(order, prod).unlink()
# #         else:
# #             _ensure_single_priority_line(order, prod, qty, unit_price)

# #             # consume DB reward one-time when express is actually applied
# #             if reward_active_before and reward_rec:
# #                 _consume_reward(reward_rec, order=order)

# #         order.invalidate_recordset(["amount_total", "amount_delivery", "amount_untaxed", "amount_tax"])
# #         total_formatted = _fmt_money_en(order.amount_total, decimals, currency_symbol)

# #         reward_active_after, _rec2 = _reward_available(order)

# #         return {
# #             "ok": True,
# #             "enabled": bool(enabled and qty > 0.0),
# #             "qty": qty,
# #             "unit_price": unit_price,
# #             "unit_formatted": f"+({unit_price:.2f} {currency_symbol})",
# #             "bom_qty": _qty_mrp_total(order),
# #             "total": order.amount_total,
# #             "total_formatted": total_formatted,
# #             "amount_delivery": order.amount_delivery,
# #             "amount_untaxed": order.amount_untaxed,
# #             "amount_tax": order.amount_tax,
# #             "currency": currency_symbol,
# #             "decimals": decimals,

# #             # keys used by your JS
# #             "reward_express_free": bool(reward_active_after),
# #             "reward_message": _reward_message() if (reward_active_before or reward_active_after) else "",
# #         }

# #     @http.route("/lx/priority/remove", type="json", auth="public", website=True, csrf=False)
# #     def priority_remove(self, **kw):
# #         order = _lx_sale_get_order(force_create=True)
# #         prod = _get_priority_product()
# #         if not (order and prod):
# #             return {"ok": False}

# #         order = order.sudo()
# #         currency_symbol, decimals = _currency_meta(order)
# #         unit_price = _compute_unit_price(prod, order)

# #         with _savepoint(request.env):
# #             lines = _find_priority_lines(order, prod)
# #             for l in lines:
# #                 order._cart_update(product_id=l.product_id.id, line_id=l.id, set_qty=0)
# #             _find_priority_lines(order, prod).unlink()

# #         return _refresh_totals_dict(order, unit_price, currency_symbol, decimals)

# #     @http.route("/lx/review/existing", type="json", auth="public", website=True, csrf=False)
# #     def lx_review_existing(self, product_id=None, product_tmpl_id=None, **kw):
# #         order = _lx_sale_get_order()
# #         partner = _current_partner(order)
# #         if not partner:
# #             return {"ok": True, "has_review": False, "count": 0, "reason": "no_partner"}

# #         Rating = request.env["rating.rating"].sudo()

# #         domain = [
# #             ("partner_id", "=", partner.id),
# #             ("res_model", "in", ["product.template", "product.product"]),
# #         ]

# #         # Filter by product if provided
# #         if product_tmpl_id:
# #             try:
# #                 domain += [("res_model", "=", "product.template"), ("res_id", "=", int(product_tmpl_id))]
# #             except Exception:
# #                 pass
# #         elif product_id:
# #             try:
# #                 domain += [("res_model", "=", "product.product"), ("res_id", "=", int(product_id))]
# #             except Exception:
# #                 pass

# #         # Most installations store real ratings as "consumed" (not just pending)
# #         # We keep it permissive to not miss anything:
# #         # If you want stricter, add: ("consumed", "=", True)
# #         cnt = Rating.search_count(domain)

# #         last = Rating.search(domain, order="create_date desc", limit=1)
# #         last_info = {}
# #         if last:
# #             last_info = {
# #                 "rating": last.rating,
# #                 "feedback": last.feedback or "",
# #                 "create_date": str(last.create_date) if last.create_date else "",
# #                 "res_model": last.res_model,
# #                 "res_id": last.res_id,
# #             }

# #         return {
# #             "ok": True,
# #             "has_review": bool(cnt),
# #             "count": cnt,
# #             "partner_id": partner.id,
# #             "last": last_info,
# #         }



# # # New: session keys for "review => free express"
# # LX_REVIEW_REWARD_FREE_KEY = "lx_review_reward_express_free"
# # LX_REVIEW_REWARD_USED_KEY = "lx_review_reward_express_used"


# # # -----------------------------
# # # Helpers
# # # -----------------------------
# # @contextmanager
# # def _savepoint(env):
# #     """Avoid partially-removed states on unexpected errors."""
# #     env.cr.execute("SAVEPOINT lx_priority_rm")
# #     try:
# #         yield
# #     except Exception:
# #         env.cr.execute("ROLLBACK TO SAVEPOINT lx_priority_rm")
# #         raise
# #     finally:
# #         env.cr.execute("RELEASE SAVEPOINT lx_priority_rm")


# # def _get_priority_product():
# #     return request.env["product.product"].sudo().search([("default_code", "=", PRIORITY_CODE)], limit=1)


# # def _qty_mrp_total(order):
# #     qty_total = 0.0
# #     Bom = request.env["mrp.bom"].sudo()

# #     tmpl_ids = set()
# #     lines = []
# #     for line in order.sudo().order_line:
# #         p = line.product_id
# #         if not p or line.display_type:
# #             continue
# #         tid = p.product_tmpl_id.id
# #         tmpl_ids.add(tid)
# #         lines.append((line, tid))

# #     if not tmpl_ids:
# #         return 0.0

# #     # get templates that have at least one BoM
# #     boms = Bom.search([("product_tmpl_id", "in", list(tmpl_ids))])
# #     has_bom_tmpl = set(boms.mapped("product_tmpl_id").ids)

# #     for line, tid in lines:
# #         if tid in has_bom_tmpl:
# #             qty_total += float(line.product_uom_qty or 0.0)

# #     return qty_total


# # def _find_priority_lines(order, product):
# #     return order.order_line.filtered(
# #         lambda l: not l.display_type and (
# #             l.product_id.id == product.id or
# #             l.product_id.product_tmpl_id.id == product.product_tmpl_id.id
# #         )
# #     )


# # def _currency_meta(order):
# #     cur = order.currency_id
# #     return (cur.symbol or " DH"), int(cur.decimal_places or 2)


# # # -----------------------------
# # # New: Review reward helpers
# # # -----------------------------
# # def _reward_express_free_active():
# #     """
# #     Express becomes free when session has reward flag and it is not consumed yet.
# #     This does NOT change any existing logic unless the flag exists.
# #     """
# #     try:
# #         free_flag = bool(request.session.get(LX_REVIEW_REWARD_FREE_KEY))
# #         used_flag = bool(request.session.get(LX_REVIEW_REWARD_USED_KEY))
# #         return free_flag and (not used_flag)
# #     except Exception:
# #         return False


# # def _reward_message():
# #     return "Express delivery is free because you submitted a product review. Thank you."


# # def _compute_unit_price(product, order):
# #     """Use raw list price only. No pricelist, no tax mapping, no discounts."""
# #     if _reward_express_free_active():
# #         return 0.0
# #     product = product.sudo()
# #     return float(product.lst_price or 0.0)


# # def _fmt_money_en(amount, decimals=2, currency_symbol=" DH"):
# #     """
# #     Format like 3,250.50 DH regardless of user locale.
# #     """
# #     return f"{amount:,.{decimals}f}{currency_symbol}"


# # def _refresh_totals_dict(order, unit_price, currency_symbol, decimals):
# #     # Ensure fresh totals
# #     fields_to_invalidate = ["amount_total", "amount_delivery", "amount_untaxed", "amount_tax"]
# #     order.invalidate_recordset(fields_to_invalidate)
# #     recompute = getattr(order, "_amount_all", None)
# #     if callable(recompute):
# #         recompute()
# #         order.invalidate_recordset(fields_to_invalidate)

# #     total_formatted = _fmt_money_en(order.amount_total, decimals, f" {currency_symbol}" if currency_symbol else "")

# #     return {
# #         "ok": True,
# #         "enabled": False,
# #         "qty": 0.0,
# #         "unit_price": unit_price,
# #         "unit_formatted": f"+({unit_price:.2f} {currency_symbol})",
# #         "bom_qty": _qty_mrp_total(order),
# #         "total": order.amount_total,
# #         "total_formatted": total_formatted,
# #         "amount_delivery": order.amount_delivery,
# #         "amount_untaxed": order.amount_untaxed,
# #         "amount_tax": order.amount_tax,
# #         "currency": currency_symbol,
# #         "decimals": decimals,
# #         # New (non-breaking): expose reward status/message for UI
# #         "reward_express_free": _reward_express_free_active(),
# #         "reward_message": _reward_message() if _reward_express_free_active() else "",
# #     }


# # def _ensure_single_priority_line(order, product, qty, unit_price):
# #     """
# #     Create/update exactly one line for PRIORITY_SERVICE with:
# #     - qty = bom_qty
# #     - price_unit = unit_price (raw)
# #     - tax_id = [] (no taxes → doesn't affect amount_tax)
# #     """
# #     lines = _find_priority_lines(order, product)
# #     if lines:
# #         keep = lines[:1]
# #         keep.write({
# #             "product_uom_qty": qty,
# #             "price_unit": unit_price,
# #             "tax_ids": [(5,)],
# #         })
# #         # purge extras
# #         (lines - keep).unlink()
# #         return keep
# #     # create via _cart_update, then force price/taxes
# #     order._cart_update(product_id=product.id, set_qty=qty)
# #     line = _find_priority_lines(order, product)[:1]
# #     if line:
# #         line.write({"price_unit": unit_price, "tax_ids": [(5,)]})
# #     return line


# # # -----------------------------
# # # Controller
# # # -----------------------------
# # class PriorityServiceController(http.Controller):
# #     """
# #     Priority-only endpoints (NO free/threshold logic; NO pricelist/tax math).
# #     Added feature: if visitor submitted a product review (session reward flag),
# #     express (PRIORITY_SERVICE) becomes free and message is returned.
# #     """

# #     @http.route("/lx/review/reward", type="json", auth="public", website=True, csrf=False)
# #     def lx_review_reward(self, review=None, **kw):
# #         request.session["lx_review_reward_express_free"] = True
# #         request.session.setdefault("lx_review_reward_express_used", False)

# #         # store last review content for debugging (optional)
# #         if isinstance(review, dict):
# #             request.session["lx_last_review"] = {
# #                 "product_id": review.get("product_id"),
# #                 "product_name": review.get("product_name"),
# #                 "rating": review.get("rating"),
# #                 "title": review.get("title"),
# #                 "message": review.get("message"),
# #                 "author": review.get("author"),
# #             }

# #         return {
# #             "ok": True,
# #             "reward_express_free": True,
# #             "message": "Express delivery is now free. Thank you for your review.",
# #         }

# #     @http.route("/lx/priority/price", type="json", auth="public", website=True, csrf=False)
# #     def priority_price(self, **kw):
# #         order = _lx_sale_get_order()
# #         prod = _get_priority_product()
# #         if not (order and prod):
# #             return {"ok": False, "error": "Order or PRIORITY_SERVICE not found"}

# #         currency_symbol, decimals = _currency_meta(order)
# #         unit_price = _compute_unit_price(prod, order)

# #         reward_active = _reward_express_free_active()

# #         return {
# #             "ok": True,
# #             "default_code": PRIORITY_CODE,
# #             "unit_price": unit_price,
# #             "unit_formatted": f"+({unit_price:.2f} {currency_symbol})",
# #             "currency": currency_symbol,
# #             "decimals": decimals,
# #             # New (non-breaking): UI can show the message
# #             "reward_express_free": reward_active,
# #             "reward_message": _reward_message() if reward_active else "",
# #         }

# #     @http.route("/lx/priority/mrp_qty", type="json", auth="public", website=True, csrf=False)
# #     def priority_mrp_qty(self, **kw):
# #         order = _lx_sale_get_order()
# #         if not order:
# #             return {"ok": True, "qty_total": 0.0}
# #         return {"ok": True, "qty_total": _qty_mrp_total(order)}

# #     @http.route("/lx/priority/has", type="json", auth="public", website=True, csrf=False)
# #     def priority_has(self, **kw):
# #         order = _lx_sale_get_order()
# #         prod = _get_priority_product()
# #         if not (order and prod):
# #             return {"ok": True, "enabled": False}
# #         return {"ok": True, "enabled": bool(_find_priority_lines(order.sudo(), prod))}

# #     @http.route("/lx/priority/apply", type="json", auth="public", website=True, csrf=False)
# #     def priority_apply(self, enabled=False, qty=0.0, **kw):
# #         order = _lx_sale_get_order(force_create=True)
# #         prod = _get_priority_product()
# #         if not (order and prod):
# #             return {"ok": False}

# #         order = order.sudo()
# #         currency_symbol, decimals = _currency_meta(order)

# #         reward_active_before = _reward_express_free_active()
# #         unit_price = _compute_unit_price(prod, order)

# #         try:
# #             qty = float(qty or 0.0)
# #         except Exception:
# #             qty = 0.0

# #         if enabled and qty <= 0.0:
# #             qty = _qty_mrp_total(order)

# #         if (not enabled) or qty <= 0.0:
# #             # remove completely
# #             lines = _find_priority_lines(order, prod)
# #             for l in lines:
# #                 order._cart_update(product_id=prod.id, line_id=l.id, set_qty=0)
# #             _find_priority_lines(order, prod).unlink()
# #         else:
# #             # upsert one line, force price_unit & clear taxes
# #             _ensure_single_priority_line(order, prod, qty, unit_price)

# #             # New: consume reward one-time when express is actually applied
# #             if reward_active_before:
# #                 request.session[LX_REVIEW_REWARD_USED_KEY] = True

# #         # fresh totals
# #         order.invalidate_recordset(["amount_total", "amount_delivery", "amount_untaxed", "amount_tax"])
# #         total_formatted = _fmt_money_en(order.amount_total, decimals, f" {currency_symbol}" if currency_symbol else "")

# #         reward_active_after = _reward_express_free_active()

# #         return {
# #             "ok": True,
# #             "enabled": bool(enabled and qty > 0.0),
# #             "qty": qty,
# #             "unit_price": unit_price,
# #             "unit_formatted": f"+({unit_price:.2f} {currency_symbol})",
# #             "bom_qty": _qty_mrp_total(order),
# #             "total": order.amount_total,
# #             "total_formatted": total_formatted,
# #             "amount_delivery": order.amount_delivery,
# #             "amount_untaxed": order.amount_untaxed,
# #             "amount_tax": order.amount_tax,
# #             "currency": currency_symbol,
# #             "decimals": decimals,
# #             # New (non-breaking): UI can show the message
# #             "reward_express_free": reward_active_after,
# #             "reward_message": _reward_message() if (reward_active_before or reward_active_after) else "",
# #         }

# #     @http.route("/lx/priority/remove", type="json", auth="public", website=True, csrf=False)
# #     def priority_remove(self, **kw):
# #         order = _lx_sale_get_order(force_create=True)
# #         prod = _get_priority_product()
# #         if not (order and prod):
# #             return {"ok": False}

# #         order = order.sudo()
# #         currency_symbol, decimals = _currency_meta(order)
# #         unit_price = _compute_unit_price(prod, order)

# #         with _savepoint(request.env):
# #             lines = _find_priority_lines(order, prod)
# #             for l in lines:
# #                 order._cart_update(product_id=l.product_id.id, line_id=l.id, set_qty=0)
# #             # hard cleanup
# #             _find_priority_lines(order, prod).unlink()

# #         return _refresh_totals_dict(order, unit_price, currency_symbol, decimals)

# #     @http.route("/lx/review/status", type="json", auth="public", website=True, csrf=False)
# #     def lx_review_status(self, **kw):
# #         free_flag = bool(request.session.get("lx_review_reward_express_free"))
# #         used_flag = bool(request.session.get("lx_review_reward_express_used"))
# #         active = free_flag and (not used_flag)
# #         last_review = request.session.get("lx_last_review") or {}

# #         return {
# #             "ok": True,
# #             "free_flag": free_flag,
# #             "used_flag": used_flag,
# #             "active": active,
# #             "last_review": last_review,
# #             "sid": request.session.sid if hasattr(request.session, "sid") else "",
# #         }


# #     @http.route("/lx/review/reset", type="json", auth="public", website=True, csrf=False)
# #     def lx_review_reset(self, **kw):
# #         request.session.pop("lx_review_reward_express_free", None)
# #         request.session.pop("lx_review_reward_express_used", None)
# #         return {"ok": True}



# # # # -----------------------------
# # # # Helpers
# # # # -----------------------------
# # # @contextmanager
# # # def _savepoint(env):
# # #     """Avoid partially-removed states on unexpected errors."""
# # #     env.cr.execute("SAVEPOINT lx_priority_rm")
# # #     try:
# # #         yield
# # #     except Exception:
# # #         env.cr.execute("ROLLBACK TO SAVEPOINT lx_priority_rm")
# # #         raise
# # #     finally:
# # #         env.cr.execute("RELEASE SAVEPOINT lx_priority_rm")


# # # def _get_priority_product():
# # #     return request.env["product.product"].sudo().search([("default_code", "=", PRIORITY_CODE)], limit=1)


# # # # def _qty_mrp_total(order):
# # # #     """Sum quantities of lines that have a BoM (used as service qty)."""
# # # #     qty_total = 0.0
# # # #     for line in order.sudo().order_line:
# # # #         p = line.product_id
# # # #         if not p or line.display_type:
# # # #             continue
# # # #         if not (p.product_tmpl_id.bom_ids or getattr(p, "bom_count", 0)):
# # # #             continue
# # # #         qty_total += float(line.product_uom_qty or 0.0)
# # # #     return qty_total

# # # def _qty_mrp_total(order):
# # #     qty_total = 0.0
# # #     Bom = request.env["mrp.bom"].sudo()

# # #     tmpl_ids = set()
# # #     lines = []
# # #     for line in order.sudo().order_line:
# # #         p = line.product_id
# # #         if not p or line.display_type:
# # #             continue
# # #         tid = p.product_tmpl_id.id
# # #         tmpl_ids.add(tid)
# # #         lines.append((line, tid))

# # #     if not tmpl_ids:
# # #         return 0.0

# # #     # get templates that have at least one BoM
# # #     boms = Bom.search([("product_tmpl_id", "in", list(tmpl_ids))])
# # #     has_bom_tmpl = set(boms.mapped("product_tmpl_id").ids)

# # #     for line, tid in lines:
# # #         if tid in has_bom_tmpl:
# # #             qty_total += float(line.product_uom_qty or 0.0)

# # #     return qty_total



# # # def _find_priority_lines(order, product):
# # #     return order.order_line.filtered(
# # #         lambda l: not l.display_type and (
# # #             l.product_id.id == product.id or
# # #             l.product_id.product_tmpl_id.id == product.product_tmpl_id.id
# # #         )
# # #     )


# # # def _currency_meta(order):
# # #     cur = order.currency_id
# # #     return (cur.symbol or " DH"), int(cur.decimal_places or 2)


# # # def _compute_unit_price(product, order):
# # #     """Use raw list price only. No pricelist, no tax mapping, no discounts."""
# # #     product = product.sudo()
# # #     return float(product.lst_price or 0.0)


# # # def _fmt_money_en(amount, decimals=2, currency_symbol=" DH"):
# # #     """
# # #     Format like 3,250.50 DH regardless of user locale.
# # #     """
# # #     return f"{amount:,.{decimals}f}{currency_symbol}"


# # # def _refresh_totals_dict(order, unit_price, currency_symbol, decimals):
# # #     # Ensure fresh totals
# # #     fields_to_invalidate = ["amount_total", "amount_delivery", "amount_untaxed", "amount_tax"]
# # #     order.invalidate_recordset(fields_to_invalidate)
# # #     recompute = getattr(order, "_amount_all", None)
# # #     if callable(recompute):
# # #         recompute()
# # #         order.invalidate_recordset(fields_to_invalidate)

# # #     total_formatted = _fmt_money_en(order.amount_total, decimals, f" {currency_symbol}" if currency_symbol else "")

# # #     return {
# # #         "ok": True,
# # #         "enabled": False,
# # #         "qty": 0.0,
# # #         "unit_price": unit_price,
# # #         "unit_formatted": f"+({unit_price:.2f} {currency_symbol})",
# # #         "bom_qty": _qty_mrp_total(order),
# # #         "total": order.amount_total,
# # #         "total_formatted": total_formatted,
# # #         "amount_delivery": order.amount_delivery,
# # #         "amount_untaxed": order.amount_untaxed,
# # #         "amount_tax": order.amount_tax,
# # #         "currency": currency_symbol,
# # #         "decimals": decimals,
# # #     }


# # # def _ensure_single_priority_line(order, product, qty, unit_price):
# # #     """
# # #     Create/update exactly one line for PRIORITY_SERVICE with:
# # #     - qty = bom_qty
# # #     - price_unit = unit_price (raw)
# # #     - tax_id = [] (no taxes → doesn't affect amount_tax)
# # #     """
# # #     lines = _find_priority_lines(order, product)
# # #     if lines:
# # #         keep = lines[:1]
# # #         keep.write({
# # #             "product_uom_qty": qty,
# # #             "price_unit": unit_price,
# # #             "tax_ids": [(5,)],
# # #         })
# # #         # purge extras
# # #         (lines - keep).unlink()
# # #         return keep
# # #     # create via _cart_update, then force price/taxes
# # #     order._cart_update(product_id=product.id, set_qty=qty)
# # #     line = _find_priority_lines(order, product)[:1]
# # #     if line:
# # #         line.write({"price_unit": unit_price, "tax_ids": [(5,)]})
# # #     return line


# # # # -----------------------------
# # # # Controller
# # # # -----------------------------
# # # class PriorityServiceController(http.Controller):
# # #     """
# # #     Priority-only endpoints (NO free/threshold logic; NO pricelist/tax math).
# # #     """

# # #     @http.route("/lx/priority/price", type="json", auth="public", website=True, csrf=False)
# # #     def priority_price(self, **kw):
# # #         order = _lx_sale_get_order()
# # #         prod = _get_priority_product()
# # #         if not (order and prod):
# # #             return {"ok": False, "error": "Order or PRIORITY_SERVICE not found"}

# # #         currency_symbol, decimals = _currency_meta(order)
# # #         unit_price = _compute_unit_price(prod, order)

# # #         return {
# # #             "ok": True,
# # #             "default_code": PRIORITY_CODE,
# # #             "unit_price": unit_price,
# # #             "unit_formatted": f"+({unit_price:.2f} {currency_symbol})",
# # #             "currency": currency_symbol,
# # #             "decimals": decimals,
# # #         }

# # #     @http.route("/lx/priority/mrp_qty", type="json", auth="public", website=True, csrf=False)
# # #     def priority_mrp_qty(self, **kw):
# # #         order = _lx_sale_get_order()
# # #         if not order:
# # #             return {"ok": True, "qty_total": 0.0}
# # #         return {"ok": True, "qty_total": _qty_mrp_total(order)}

# # #     @http.route("/lx/priority/has", type="json", auth="public", website=True, csrf=False)
# # #     def priority_has(self, **kw):
# # #         order = _lx_sale_get_order()
# # #         prod = _get_priority_product()
# # #         if not (order and prod):
# # #             return {"ok": True, "enabled": False}
# # #         return {"ok": True, "enabled": bool(_find_priority_lines(order.sudo(), prod))}

# # #     @http.route("/lx/priority/apply", type="json", auth="public", website=True, csrf=False)
# # #     def priority_apply(self, enabled=False, qty=0.0, **kw):
# # #         order = _lx_sale_get_order(force_create=True)
# # #         prod = _get_priority_product()
# # #         if not (order and prod):
# # #             return {"ok": False}

# # #         order = order.sudo()
# # #         currency_symbol, decimals = _currency_meta(order)
# # #         unit_price = _compute_unit_price(prod, order)

# # #         try:
# # #             qty = float(qty or 0.0)
# # #         except Exception:
# # #             qty = 0.0

# # #         if enabled and qty <= 0.0:
# # #             qty = _qty_mrp_total(order)

# # #         if (not enabled) or qty <= 0.0:
# # #             # remove completely
# # #             lines = _find_priority_lines(order, prod)
# # #             for l in lines:
# # #                 order._cart_update(product_id=prod.id, line_id=l.id, set_qty=0)
# # #             _find_priority_lines(order, prod).unlink()
# # #         else:
# # #             # upsert one line, force price_unit & clear taxes
# # #             _ensure_single_priority_line(order, prod, qty, unit_price)

# # #         # fresh totals
# # #         order.invalidate_recordset(["amount_total", "amount_delivery", "amount_untaxed", "amount_tax"])
# # #         total_formatted = _fmt_money_en(order.amount_total, decimals, f" {currency_symbol}" if currency_symbol else "")

# # #         return {
# # #             "ok": True,
# # #             "enabled": bool(enabled and qty > 0.0),
# # #             "qty": qty,
# # #             "unit_price": unit_price,
# # #             "unit_formatted": f"+({unit_price:.2f} {currency_symbol})",
# # #             "bom_qty": _qty_mrp_total(order),
# # #             "total": order.amount_total,
# # #             "total_formatted": total_formatted,
# # #             "amount_delivery": order.amount_delivery,
# # #             "amount_untaxed": order.amount_untaxed,
# # #             "amount_tax": order.amount_tax,
# # #             "currency": currency_symbol,
# # #             "decimals": decimals,
# # #         }

# # #     @http.route("/lx/priority/remove", type="json", auth="public", website=True, csrf=False)
# # #     def priority_remove(self, **kw):
# # #         order = _lx_sale_get_order(force_create=True)
# # #         prod = _get_priority_product()
# # #         if not (order and prod):
# # #             return {"ok": False}

# # #         order = order.sudo()
# # #         currency_symbol, decimals = _currency_meta(order)
# # #         unit_price = _compute_unit_price(prod, order)

# # #         with _savepoint(request.env):
# # #             lines = _find_priority_lines(order, prod)
# # #             for l in lines:
# # #                 order._cart_update(product_id=l.product_id.id, line_id=l.id, set_qty=0)
# # #             # hard cleanup
# # #             _find_priority_lines(order, prod).unlink()

# # #         return _refresh_totals_dict(order, unit_price, currency_symbol, decimals)
