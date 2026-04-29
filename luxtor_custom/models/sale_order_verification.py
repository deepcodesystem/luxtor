# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import secrets

class SaleOrder(models.Model):
    _inherit = "sale.order"

    # minimal persistent fields
    lx_verification_code = fields.Char(copy=False)
    lx_verification_email = fields.Char(copy=False)  # e-mail saisi côté site


    # computed helper used in views/website
    lx_verification_required = fields.Boolean(
        string="Verification Required",
        compute="_compute_verification_required",
        store=True
    )

    lx_verification_ok = fields.Boolean(
        string="Order Verification OK",
        default=False,
        help="Set to True when the customer's code is validated."
    )
    lx_verif_token = fields.Char(
        string="Verification Token (Order)",
        copy=False
    )

    @api.depends('amount_total', 'company_id')
    def _compute_verification_required(self):
        icp = self.env['ir.config_parameter'].sudo()
        limit = float(icp.get_param('luxtor.lx_order_limit_amount', default='0') or 0.0)
        for order in self:
            order.lx_verification_required = bool(limit and order.amount_total >= limit)

    def lx_ensure_verification_token(self):
        self.ensure_one()
        token = (self.lx_verif_token or "").strip()
        if token:
            return token

        token = secrets.token_urlsafe(24)
        self.sudo().write({"lx_verif_token": token})
        return token

    # --- API ---
    def action_send_verification_code(self):
        import secrets
        for order in self:
            if not order.lx_verification_required:
                raise UserError(_("This order doesn't exceed the configured limit. No verification needed."))
            if not order.partner_id.email:
                raise UserError(_("The customer has no email address."))

            # Générer un code 6 chiffres
            code = f"{secrets.randbelow(900000) + 100000}"

            # Sauvegarder le code
            order.sudo().write({
                "lx_verification_code": code,
                "lx_verification_ok": False,
            })

            # Charger le template
            template = self.env.ref(
                "luxtor_custom.mail_template_sale_order_limit_code",
                raise_if_not_found=False
            )

            if template:
                order._portal_ensure_token()  # pour générer le lien portail
                order.with_context(force_send=True).message_post_with_source(
                    template,
                    email_layout_xmlid='mail.mail_notification_layout_with_responsible_signature',
                    subtype_xmlid='mail.mt_comment',
                )

            #             # Définir le destinataire (sécurisé)
            # template.sudo().write({
            #     "email_to": order.partner_id.email,
            #     "email_layout_xmlid": "mail.mail_notification_layout_with_responsible_signature",
            # })

            # # Envoyer l'email en FR
            # template.sudo().with_context(lang="fr_FR").send_mail(order.id, force_send=True)

        return True


    def action_validate_verification_code(self, code: str):
        self.ensure_one()
        if not self.lx_verification_required:
            return True  # not needed
        if not code or code.strip() != (self.lx_verification_code or ""):
            raise ValidationError(_("Invalid code."))
        self.sudo().write({"lx_verification_ok": True})
        return True

    # hard guard for all confirmation flows
    def action_confirm(self):
        for order in self:
            if order.lx_verification_required and not order.lx_verification_ok:
                order.action_send_verification_code()
                raise UserError(_("High-value order: verify the email code before confirming."))
        return super().action_confirm()
