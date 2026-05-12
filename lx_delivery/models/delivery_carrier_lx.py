# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class DeliveryCarrierLx(models.Model):
    """Configuration LX par transporteur natif Odoo."""

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
    free_threshold = fields.Float(string="Free Shipping Threshold", default=0.0)
    bracket_ids = fields.One2many(
        "delivery.bracket.lx", "carrier_lx_id", string="Weight Brackets"
    )

    _sql_constraints = [
        ("carrier_unique", "unique(carrier_id)", "This carrier already has an LX configuration."),
    ]

    @api.constrains("free_threshold")
    def _check_free_threshold(self):
        for rec in self:
            if rec.free_threshold < 0:
                raise ValidationError(_("Free Shipping Threshold cannot be negative."))

    def lx_get_threshold(self):
        """
        Résolution du seuil free shipping :
        - threshold per-carrier si > 0
        - sinon icp luxtor.lx_free_amount_order (défaut 5000)
        """
        self.ensure_one()
        if float(self.free_threshold or 0.0) > 0:
            return float(self.free_threshold)
        ICP = self.env["ir.config_parameter"].sudo()
        val = ICP.get_param("luxtor.lx_free_amount_order", default="5000")
        try:
            return float(val or 0.0)
        except Exception:
            return 5000.0

    def lx_session_force_free(self):
        """True si la session force la livraison gratuite."""
        try:
            from odoo.http import request
            return bool(request.session.get("lx_free_force", False))
        except Exception:
            return False

    def lx_merch_total_excl_services(self, order):
        """
        Total marchandise hors lignes delivery / tip / downpayment /
        INSTALL_SERVICE / PRIORITY_SERVICE / is_shipping_line / is_free_shipping_line.
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
            if getattr(l, "is_shipping_line", False):
                continue
            if getattr(l, "is_free_shipping_line", False):
                continue
            p = l.product_id
            if not p:
                continue
            code = (p.default_code or "").strip().upper()
            tcode = (p.product_tmpl_id.default_code or "").strip().upper()
            if code in ("INSTALL_SERVICE", "PRIORITY_SERVICE") or tcode in ("INSTALL_SERVICE", "PRIORITY_SERVICE"):
                continue
            total += float(l.price_total or 0.0)
        return float(total)

    def lx_apply_free_logic(self, order, raw_price=0.0):
        """
        Applique la logique free shipping.

        Priorité 1 : session lx_free_force → free forcé.
        Priorité 2 : merch_total ≥ threshold.

        Retourne (final_price, free_applied, free_reason, threshold_used, merch_total, forced).
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


class DeliveryCarrierInherit(models.Model):
    """Extension du delivery.carrier natif Odoo pour les besoins Luxtor."""

    _inherit = "delivery.carrier"

    lx_carrier = fields.Selection(
        selection=[
            ("cathedis", "CATHEDIS"),
            ("amana", "AMANA"),
        ],
        string="Carrier Provider",
    )
    lx_carrier_lx_ids = fields.One2many(
        "delivery.carrier.lx", "carrier_id", string="LX Config"
    )

    def _lx_is_luxtor_dynamic(self):
        """True si ce transporteur est géré dynamiquement par Luxtor."""
        self.ensure_one()
        n = (self.name or "").strip().lower()
        return n in ("standard delivery", "express delivery")

    def lx_get_checkout_provider_value(self):
        """Libellé du provider pour le checkout frontend."""
        self.ensure_one()
        if self.lx_carrier == "cathedis":
            return "Cathedis"
        selection = dict(self._fields["lx_carrier"].selection or [])
        return (selection.get(self.lx_carrier) or "").strip()

    def lx_get_checkout_description(self):
        """Sous-titre transporteur pour le checkout frontend."""
        self.ensure_one()
        intro = (
            _("Livraison prioritaire, assurée par")
            if (self.name or "").strip().lower().startswith("express")
            else _("Livraison rapide, assurée par")
        )
        val = self.lx_get_checkout_provider_value()
        if val:
            provider_label = self._fields["lx_carrier"].string or _("Carrier")
            return '%s "%s" %s' % (intro, provider_label, val)
        return intro

    def _lx_dynamic_price_for_order(self, order):
        """Calcule le prix dynamique Luxtor pour la commande donnée."""
        self.ensure_one()
        if not order or not self._lx_is_luxtor_dynamic():
            return None

        order = order.sudo()
        zip_code = (order.partner_shipping_id.zip or "").strip()
        rate = order.env["shipping.rate"].sudo().search([("zip_code", "=", zip_code)], limit=1)
        if not rate:
            return 0.0

        name_norm = (self.name or "").strip().lower()
        if name_norm == "standard delivery":
            raw = order._lx_compute_standard_price(zip_code=zip_code)
        else:
            raw = order._lx_compute_express_price(zip_code=zip_code)

        final_price, *_ = order._lx_apply_free_logic(raw)
        return float(final_price or 0.0)

    def _get_price_available(self, order):
        price = self._lx_dynamic_price_for_order(order)
        if price is not None:
            return price
        return super()._get_price_available(order)

    def rate_shipment(self, order):
        price = self._lx_dynamic_price_for_order(order)
        if price is not None:
            return {"success": True, "price": price, "error_message": False, "warning_message": False}
        return super().rate_shipment(order)

