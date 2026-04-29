# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import re

class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    lx_verification_code = fields.Char(readonly=True, copy=False)
    lx_verif_token = fields.Char(copy=False, index=True)
    lx_sale_order_id = fields.Many2one("sale.order", copy=False, index=True, readonly=True)
    lx_code_email_sent_at = fields.Datetime(readonly=True, copy=False)
    lx_code_email_sent_to = fields.Char(readonly=True, copy=False)

    def _lx_extract_token_from_description(self):
        self.ensure_one()
        text = self.description or ""
        match = re.search(r"lx_verif_token\s*:\s*([A-Za-z0-9_\-]+)", text, flags=re.IGNORECASE)
        return match.group(1).strip() if match else False

    def action_verification_code(self):
        import secrets
        self.ensure_one()
        code = "%06d" % (secrets.randbelow(900000) + 100000)
        token = (self.lx_verif_token or "").strip() or self._lx_extract_token_from_description() or False
        order = self.lx_sale_order_id
        if token and not order:
            order = self.env["sale.order"].sudo().search([("lx_verif_token", "=", token)], limit=1)
        values = {"lx_verification_code": code}
        if token:
            values["lx_verif_token"] = token
        if order:
            values["lx_sale_order_id"] = order.id
        self.sudo().write(values)
        if order:
            order.sudo().write({
                "lx_verification_code": code,
                "lx_verification_ok": False,
            })
        self.message_post(body=_("Verification code : %s") % code)
        self.sudo().write({
            "lx_code_email_sent_at": False,
            "lx_code_email_sent_to": False,
        })
        return True

    def action_send_verification_code_email(self):
        self.ensure_one()
        if not self.lx_verification_code:
            raise UserError(_("Please generate a verification code first."))

        template = self.env.ref("luxtor_custom.mail_template_helpdesk_verification_code", raise_if_not_found=False)
        recipient = (
            (self.partner_id.email if self.partner_id else False)
            or getattr(self, "partner_email", False)
            or getattr(self, "email_from", False)
        )
        if not recipient:
            raise UserError(_("No recipient email was found on this ticket."))
        if not template:
            raise UserError(_("The verification code email template is missing."))

        template.sudo().send_mail(
            self.id,
            force_send=True,
            email_values={"email_to": recipient},
        )
        self.sudo().write({
            "lx_code_email_sent_at": fields.Datetime.now(),
            "lx_code_email_sent_to": recipient,
        })
        self.message_post(body=_("Verification code email sent to %s") % recipient)
        return True

    @api.model
    def lx_latest_code_global(self):
        """Return the newest non-empty verification code from any helpdesk ticket."""
        rec = self.sudo().search([('lx_verification_code', '!=', False)],
                                 order='write_date desc', limit=1)
        return rec.lx_verification_code or False

    @api.model
    def lx_latest_code_for_token(self, token):
        token = (token or "").strip()
        if not token:
            return False

        rec = self.sudo().search(
            [
                ('lx_verif_token', '=', token),
                ('lx_verification_code', '!=', False),
            ],
            order='write_date desc, id desc',
            limit=1,
        )
        if rec:
            return rec.lx_verification_code or False

        # Fallback for tickets created through the generic website form where
        # unknown fields may be injected into the description instead of the model field.
        rec = self.sudo().search(
            [
                ('description', 'ilike', token),
                ('lx_verification_code', '!=', False),
            ],
            order='write_date desc, id desc',
            limit=1,
        )
        return rec.lx_verification_code or False
