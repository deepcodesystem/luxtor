# -*- coding: utf-8 -*-
import logging
from odoo import http
from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale

_logger = logging.getLogger(__name__)

SKEY_SLUG = "lx_artisan_slug"
SKEY_PARTNER = "lx_artisan_partner_id"


def _session_key():
    # stable key per visitor session
    return getattr(request.session, "sid", None) or request.httprequest.cookies.get("session_id") or "no_sid"


def _normalize_slug_token(value):
    value = (value or "").strip().lower()
    value = "-".join(part for part in value.replace("_", "-").split("-") if part)
    return value


def _find_artisan_partner(token):
    token = _normalize_slug_token(token)
    if not token:
        return request.env["res.partner"]

    Partner = request.env["res.partner"].sudo()
    partner = Partner.search([
        ("lx_is_artisan", "=", True),
        ("lx_affiliate_slug", "=ilike", token),
    ], limit=1)
    if partner:
        return partner

    partner = Partner.search([
        ("lx_is_artisan", "=", True),
        ("name", "=ilike", token.replace("-", " ")),
    ], limit=1)
    if partner:
        return partner

    # Fallback for older records whose stored slug may be stale or missing.
    artisans = Partner.search([("lx_is_artisan", "=", True)])
    return next((p for p in artisans if getattr(p, "lx_affiliate_slug", False) and p.lx_affiliate_slug.lower() == token), Partner.browse()) or next(
        (p for p in artisans if p.name and p.name.strip() and p.name.strip().replace(" ", "-").lower() == token),
        Partner.browse(),
    )


class LuxtorAffiliateRef(http.Controller):

    @http.route(["/shop/ref"], type="http", auth="public", website=True, sitemap=False)
    def luxtor_ref(self, artisan=None, next=None, **kw):
        artisan = _normalize_slug_token(artisan)
        next_url = (next or "/shop").strip() or "/shop"
        skey = _session_key()

        _logger.warning("[AFFILIATE][REF] sid=%s scheme=%s artisan=%r next=%s url=%s",
                        skey, request.httprequest.scheme, artisan, next_url, request.httprequest.url)

        if not artisan:
            _logger.warning("[AFFILIATE][REF] sid=%s empty artisan -> redirect %s", skey, next_url)
            return request.redirect(next_url)

        partner = _find_artisan_partner(artisan)

        _logger.warning("[AFFILIATE][REF] sid=%s search slug=%s found=%s partner_id=%s",
                        skey, artisan, bool(partner), partner.id if partner else None)

        # Save in session (for quick retrieval)
        request.session[SKEY_SLUG] = artisan
        if partner:
            request.session[SKEY_PARTNER] = partner.id
        else:
            request.session.pop(SKEY_PARTNER, None)

        # Create JSON trace record in DB (your “json record” requirement)
        payload = {
            "artisan_slug": artisan,
            "partner_id": partner.id if partner else None,
            "url": request.httprequest.url,
            "path": request.httprequest.path,
            "query": dict(request.httprequest.args),
            "ip": request.httprequest.remote_addr,
            "user_agent": request.httprequest.headers.get("User-Agent"),
        }

        click = request.env["lx.affiliate.click"].sudo().create({
            "session_key": skey,
            "artisan_slug": artisan,
            "artisan_id": partner.id if partner else False,
            "url": request.httprequest.url,
            "ip": request.httprequest.remote_addr,
            "user_agent": request.httprequest.headers.get("User-Agent"),
            "payload_json": payload,
        })

        _logger.warning("[AFFILIATE][REF] sid=%s created click trace id=%s payload_partner=%s",
                        skey, click.id, payload.get("partner_id"))

        order_id = request.session.get("sale_order_id")
        if partner and order_id:
            order = request.env["sale.order"].sudo().browse(int(order_id)).exists()
            if order:
                vals = {}
                if not order.lx_artisan_id:
                    vals["lx_artisan_id"] = partner.id
                if vals:
                    order.write(vals)
                if not click.sale_order_id:
                    click.write({"sale_order_id": order.id})
                _logger.warning(
                    "[AFFILIATE][REF] sid=%s immediately attached artisan=%s to order=%s",
                    skey, partner.id, order.id,
                )

        return request.redirect(next_url)


class WebsiteSaleLuxtorAffiliate(WebsiteSale):
    """
    Attach artisan to order when order is created or accessed.
    Reads latest lx.affiliate.click record (JSON trace) for this session.
    """

    def _get_affiliate_partner_from_trace(self):
        skey = _session_key()

        # Prefer direct session partner id if available
        artisan_id = request.session.get(SKEY_PARTNER)
        if artisan_id:
            try:
                artisan_id = int(artisan_id)
                p = request.env["res.partner"].sudo().browse(artisan_id)
                if p.exists() and p.lx_is_artisan:
                    _logger.warning("[AFFILIATE][TRACE] sid=%s partner from session=%s", skey, artisan_id)
                    return p
            except Exception:
                pass

        # Otherwise, read from latest click trace
        click = request.env["lx.affiliate.click"].sudo().search(
            [("session_key", "=", skey)],
            order="create_date desc, id desc",
            limit=1,
        )

        if not click:
            _logger.warning("[AFFILIATE][TRACE] sid=%s no click trace found", skey)
            return None

        partner = click.artisan_id
        _logger.warning("[AFFILIATE][TRACE] sid=%s latest click=%s slug=%s partner=%s",
                        skey, click.id, click.artisan_slug, partner.id if partner else None)
        return partner if (partner and partner.lx_is_artisan) else None

    def _prepare_sale_order_values(self, partner, pricelist):
        vals = super()._prepare_sale_order_values(partner, pricelist)
        artisan = self._get_affiliate_partner_from_trace()
        if artisan:
            vals.setdefault("lx_artisan_id", artisan.id)
            _logger.warning("[AFFILIATE][CREATE_ORDER] set lx_artisan_id=%s in create vals", artisan.id)
        return vals

    def sale_get_order(self, force_create=False, update_pricelist=False):
        # V19: sale_get_order was removed from the parent; guard the super() call
        try:
            order = super().sale_get_order(force_create=force_create, update_pricelist=update_pricelist)
        except AttributeError:
            Order = request.env['sale.order'].sudo()
            order_id = request.session.get('sale_order_id')
            order = Order.browse(int(order_id)).exists() if order_id else Order.browse()

        artisan = self._get_affiliate_partner_from_trace()
        _logger.warning("[AFFILIATE][GET_ORDER] order=%s artisan=%s",
                        order.id if order else None, artisan.id if artisan else None)

        if order and artisan and not order.lx_artisan_id:
            order.sudo().write({"lx_artisan_id": artisan.id})
            _logger.warning("[AFFILIATE][ATTACH] attached artisan=%s to order=%s", artisan.id, order.id)

            # Optional: link trace to this order for auditing
            skey = _session_key()
            click = request.env["lx.affiliate.click"].sudo().search(
                [("session_key", "=", skey)],
                order="create_date desc, id desc",
                limit=1,
            )
            if click and not click.sale_order_id:
                click.write({"sale_order_id": order.id})
                _logger.warning("[AFFILIATE][ATTACH] linked click=%s to order=%s", click.id, order.id)

        return order
