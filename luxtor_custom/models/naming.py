# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


_QUOTATION_DEFAULTS = {False, "/", "New"}


class SaleOrder(models.Model):
    _inherit = "sale.order"

    # Devis name at creation: Q/00001
    @api.model_create_multi
    def create(self, vals_list):
        Company = self.env["res.company"]
        for vals in vals_list:
            if vals.get("name") in _QUOTATION_DEFAULTS or not vals.get("name"):
                company = Company.browse(vals["company_id"]) if vals.get("company_id") else self.env.company
                seq = self.env["ir.sequence"].with_company(company).next_by_code(
                    "custom.seq.sale.quotation"
                )
                vals["name"] = seq or _("New")
        return super().create(vals_list)

    def _is_quotation_name(self, name):
        if not name or name in _QUOTATION_DEFAULTS:
            return True
        return str(name).startswith("Q/")

    # Convert to SO/00001 at confirmation
    def action_confirm(self):
        for order in self:
            if order._is_quotation_name(order.name):
                new_name = self.env["ir.sequence"].with_company(order.company_id).next_by_code(
                    "custom.seq.sale.order"
                )
                if not new_name:
                    raise UserError(_("No sequence found for Sales Orders (code: custom.seq.sale.order)."))
                order.name = new_name
        return super().action_confirm()


class AccountJournal(models.Model):
    _inherit = "account.journal"

    sequence_override_custom = fields.Boolean(string="Use custom invoice sequence")
    sequence_id_custom = fields.Many2one(
        "ir.sequence",
        string="Custom Sequence",
        help="If set and override enabled, invoices posted on this journal use this sequence.",
    )


class AccountMove(models.Model):
    _inherit = "account.move"

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        for move in posted:
            if move.move_type not in ("out_invoice", "out_refund"):
                continue

            journal = move.journal_id
            if not journal.sequence_override_custom:
                continue

            seq = journal.sequence_id_custom or self.env.ref(
                "custom_doc_sequences.seq_account_invoice_custom",
                raise_if_not_found=False,
            )
            if not seq:
                raise UserError(
                    _(
                        "No custom invoice sequence found. Configure it on the journal or install the provided INV sequence."
                    )
                )

            if move.name in ("/", False, "New") or str(move.name).startswith("INV/"):
                move.name = seq.with_company(move.company_id).next_by_id()

        return posted


# class SaleOrder(models.Model):
#     _inherit = "sale.order"

#     # Devis name at creation: Q/00001
#     @api.model
#     def create(self, vals):
#         if vals.get("name") in _QUOTATION_DEFAULTS or not vals.get("name"):
#             seq = self.env["ir.sequence"].with_company(vals.get("company_id")).next_by_code(
#                 "custom.seq.sale.quotation"
#             )
#             vals["name"] = seq or _("New")
#         return super().create(vals)

#     def _is_quotation_name(self, name):
#         if not name or name in _QUOTATION_DEFAULTS:
#             return True
#         return name.startswith("Q/")

#     # Convert to SO/00001 at confirmation
#     def action_confirm(self):
#         for order in self:
#             if self._is_quotation_name(order.name):
#                 new_name = self.env["ir.sequence"].with_company(order.company_id.id).next_by_code(
#                     "custom.seq.sale.order"
#                 )
#                 if not new_name:
#                     raise UserError(_("No sequence found for Sales Orders (code: custom.seq.sale.order)."))
#                 order.name = new_name
#         return super().action_confirm()


# class AccountJournal(models.Model):
#     _inherit = "account.journal"

#     sequence_override_custom = fields.Boolean(string="Use custom invoice sequence")
#     sequence_id_custom = fields.Many2one(
#         "ir.sequence",
#         string="Custom Sequence",
#         help="If set and override enabled, invoices posted on this journal use this sequence.",
#     )


# class AccountMove(models.Model):
#     _inherit = "account.move"

#     def _post(self, soft=True):
#         posted = super()._post(soft=soft)
#         for move in posted:
#             if move.move_type not in ("out_invoice", "out_refund"):
#                 continue

#             journal = move.journal_id
#             if not journal.sequence_override_custom:
#                 continue

#             seq = journal.sequence_id_custom or self.env.ref(
#                 "custom_doc_sequences.seq_account_invoice_custom", raise_if_not_found=False
#             )
#             if not seq:
#                 raise UserError(
#                     _("No custom invoice sequence found. Configure it on the journal or install the provided INV sequence.")
#                 )

#             if move.name in ("/", False, "New") or str(move.name).startswith("INV/"):
#                 move.name = seq.with_company(move.company_id.id).next_by_id()
#         return posted
