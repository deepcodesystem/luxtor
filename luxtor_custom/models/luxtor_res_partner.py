# -*- coding: utf-8 -*-
import re

from odoo import api, fields, models


def _lx_slugify(name: str) -> str:
    name = (name or "").strip()
    name = name.replace("'", " ")
    name = re.sub(r"\s+", "-", name)
    name = re.sub(r"[^A-Za-z0-9\-]", "-", name)
    name = re.sub(r"-{2,}", "-", name)
    name = name.strip("-").lower()
    return name or ""


class ResPartnerAccountType(models.Model):
    _name = "res.partner.account.type"
    _description = "Partner Account Type"
    _order = "name"

    name = fields.Char(required=True, index=True)
    rank = fields.Float(string="Markup")
    vendor_markdown = fields.Float(
        string="Vendor Markdown %",
        help="Percentage discount applied on accessories base vendor cost.",
    )


class ResPartner(models.Model):
    _inherit = "res.partner"

    lx_welcome_coupon_mail_sent = fields.Boolean(
        string="Welcome Coupon Email Sent",
        copy=False,
        default=False,
        help="Technical flag used to avoid sending the welcome coupon email more than once.",
    )

    lx_welcome_coupon_mail_sent_date = fields.Datetime(
        string="Welcome Coupon Email Sent On",
        copy=False,
        help="Timestamp of the first successful welcome coupon email send.",
    )

    lx_welcome_coupon_code = fields.Char(
        string="Welcome Coupon Code",
        copy=False,
        help="Last welcome coupon code sent to this customer.",
    )

    lx_welcome_coupon_mail_sent_to = fields.Char(
        string="Welcome Coupon Email Sent To",
        copy=False,
        readonly=True,
    )

    lx_account_type_id = fields.Many2one(
        "res.partner.account.type",
        string="Account Type",
        ondelete="set null",
        index=True,
        help="Classify the partner by pricing/account category.",
    )

    lx_account_rank = fields.Float(
        string="Markup",
        related="lx_account_type_id.rank",
        readonly=False,
    )

    lx_vendor_markdown = fields.Float(
        string="Vendor Markdown %",
        related="lx_account_type_id.vendor_markdown",
        readonly=False,
        help="Used to compute electric blind accessories price.",
    )

    lx_is_artisan = fields.Boolean(string="Artisan", default=False)

    lx_artisan_commission_pct = fields.Float(
        string="Commission %",
        compute="_compute_lx_artisan_commission_pct",
        inverse="_inverse_lx_artisan_commission_pct",
        readonly=False,
        help="Writable alias of the existing partner markup percentage.",
    )

    lx_affiliate_slug = fields.Char(
        string="Slug artisan",
        compute="_compute_lx_affiliate",
        store=True,
        index=True,
        readonly=True,
    )

    lx_affiliate_url = fields.Char(
        string="Lien artisan",
        compute="_compute_lx_affiliate",
        store=True,
        readonly=True,
    )

    # Separate compute method required by Odoo 19: mixing store=True and
    # store=False fields on one compute causes unexpected res_partner writes.
    lx_affiliate_code = fields.Char(
        string="Affiliate Code",
        compute="_compute_lx_affiliate_code",
        readonly=True,
    )

    lx_company_currency_id = fields.Many2one(
        "res.currency",
        string="Company Currency",
        compute="_compute_lx_artisan_stats",
    )

    # Keep the historical field name because existing DB views may still
    # reference it until the module is upgraded.
    sale_order_ids = fields.One2many(
        "sale.order",
        "lx_artisan_id",
        string="Commandes liees",
        readonly=True,
    )

    # Dedicated alias for newer UI code.
    lx_artisan_order_ids = fields.One2many(
        "sale.order",
        "lx_artisan_id",
        string="Commandes liees",
        compute="_compute_lx_artisan_order_ids",
        readonly=True,
    )

    lx_artisan_order_count = fields.Integer(
        string="Orders",
        compute="_compute_lx_artisan_stats",
    )
    lx_artisan_order_total = fields.Monetary(
        string="Referred Orders Total",
        compute="_compute_lx_artisan_stats",
        currency_field="lx_company_currency_id",
    )
    lx_artisan_commission_total = fields.Monetary(
        string="Commission Total",
        compute="_compute_lx_artisan_stats",
        currency_field="lx_company_currency_id",
    )

    @api.depends("lx_account_rank")
    def _compute_lx_artisan_commission_pct(self):
        for partner in self:
            partner.lx_artisan_commission_pct = float(partner.lx_account_rank or 0.0)

    def _inverse_lx_artisan_commission_pct(self):
        for partner in self:
            partner.lx_account_rank = float(partner.lx_artisan_commission_pct or 0.0)

    @api.depends("name", "lx_is_artisan")
    def _compute_lx_affiliate(self):
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/")
        for partner in self:
            if partner.lx_is_artisan:
                slug = _lx_slugify(partner.name)
                partner.lx_affiliate_slug = slug
                partner.lx_affiliate_url = f"{base_url}/shop/ref?artisan={slug}" if (base_url and slug) else False
            else:
                partner.lx_affiliate_slug = False
                partner.lx_affiliate_url = False

    @api.depends("lx_affiliate_slug")
    def _compute_lx_affiliate_code(self):
        for partner in self:
            partner.lx_affiliate_code = partner.lx_affiliate_slug or False

    @api.depends("sale_order_ids")
    def _compute_lx_artisan_order_ids(self):
        for partner in self:
            partner.lx_artisan_order_ids = partner.sale_order_ids

    @api.depends(
        "sale_order_ids.state",
        "sale_order_ids.amount_total",
        "sale_order_ids.lx_artisan_commission_amount",
    )
    def _compute_lx_artisan_stats(self):
        company_currency = self.env.company.currency_id
        for partner in self:
            partner.lx_company_currency_id = company_currency
            orders = partner.sale_order_ids.filtered(lambda so: so.state != "cancel")
            partner.lx_artisan_order_count = len(orders)
            partner.lx_artisan_order_total = sum(orders.mapped("amount_total"))
            partner.lx_artisan_commission_total = sum(orders.mapped("lx_artisan_commission_amount"))


class LxAffiliateClick(models.Model):
    _name = "lx.affiliate.click"
    _description = "Affiliate Click Trace"
    _order = "create_date desc"

    session_key = fields.Char(index=True, required=True)
    artisan_slug = fields.Char(index=True, required=True)
    artisan_id = fields.Many2one("res.partner", index=True, ondelete="set null")
    url = fields.Char()
    ip = fields.Char()
    user_agent = fields.Char()
    payload_json = fields.Json(string="Payload JSON")
    sale_order_id = fields.Many2one("sale.order", index=True, ondelete="set null")
