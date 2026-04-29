# -*- coding: utf-8 -*-
from datetime import datetime, time
import math
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _, tools
import logging
from odoo.exceptions import UserError
from odoo.http import request
from odoo.tools.misc import formatLang
from odoo.tools import float_compare
from odoo.exceptions import UserError, ValidationError



_logger = logging.getLogger(__name__)
_t = _
DIM_PRECISION = 2
PARAM_USED_PCT = "luxtor.lx_fabric_freeze_used_pct"
FREEZE_MSG = _("You can't continue: the related fabric is not enough in stock.")



class SaleOrder(models.Model):
    _inherit = 'sale.order'

    _LX_SYNC_SERVICE_CODES = frozenset({'INSTALL_SERVICE', 'PRIORITY_SERVICE'})

    priority = fields.Selection(
        [('normal', 'Normal'), ('special', 'Special')],
        string='Priority',
        compute='_compute_priority',
        store=True,
        readonly=True,
        default='normal',
    )

    priority_quantity = fields.Integer(default=0)
    priority_price = fields.Float(default=0.0)

    installation_type = fields.Selection([
        ('paid', 'Paid'),
        ('free', 'Free'),
    ], string='Installation Type', default='paid')

    installation_quantity = fields.Integer(default=0)
    installation_price = fields.Float(default=0.0)

    shipping_method_type = fields.Selection([
        ('standard', 'Standard'),
        ('express', 'Express'),
    ], string='Shipping Method', default='standard')
    shipping_city_id = fields.Many2one('shipping.rate', string='City/Suburb')
    shipping_quantity = fields.Integer(string='Shipping Quantity', default=0)
    shipping_price = fields.Float(string='Shipping Price', default=0.0)

    partner_phone = fields.Char(
        related="partner_id.phone",
        string="Phone",
        readonly=True,
        store=True,
    )

    delivery_date = fields.Date(
        string='Delivery Date', compute='_compute_delivery_date', store=True)

    lx_payment_terms = fields.Selection([
        ('upfront', '100% on Order'),
        ('half_half', '50% on Order & 50% on Delivery'),
    ], string="Payment Terms")

    lx_salesperson_id = fields.Many2one(
        'crm.team.member',
        string='Salesperson',
        help='Salesperson responsible for this order.'
    )

    check_measure = fields.Selection([
        ('not_required', 'Not Required'),
        ('required', 'Required'),
    ], string='Check Measure', default='not_required')

    remove_product = fields.Selection([
        ('no_removal', 'No Removal'),
        ('removal_disposal', 'Removal & Disposal'),
    ], string='Remove Product', default='no_removal')

    split_shipping = fields.Selection([
        ('not_permitted', 'Not Permitted'),
        ('permitted', 'Permitted'),
    ], string='Split Shipping', default='not_permitted')

    preferences = fields.Text(string='Preferences')

    lx_artisan_id = fields.Many2one(
        "res.partner",
        string="Artisan",
        index=True,
    )
    lx_artisan_commission_pct = fields.Float(
        string="Artisan Commission %",
        compute="_compute_lx_artisan_commission_pct",
        readonly=True,
    )
    lx_artisan_commission_amount = fields.Monetary(
        string="Artisan Commission Amount",
        currency_field="currency_id",
        compute="_compute_lx_artisan_commission_amount",
        readonly=True,
    )

    lx_production_state = fields.Selection(
        [
            ("not_started", "Not Started"),
            ("in_works", "In Works"),
            ("complete", "Complete"),
        ],
        string="Production",
        compute="_compute_lx_production_state",
        store=True,
        readonly=True,
    )

    @api.depends("lx_artisan_id", "lx_artisan_id.lx_account_rank")
    def _compute_lx_artisan_commission_pct(self):
        for order in self:
            order.lx_artisan_commission_pct = float(order.lx_artisan_id.lx_account_rank or 0.0)

    @api.depends("amount_untaxed", "state", "lx_artisan_id", "lx_artisan_id.lx_account_rank")
    def _compute_lx_artisan_commission_amount(self):
        for order in self:
            pct = float(order.lx_artisan_id.lx_account_rank or 0.0)
            base_amount = float(order.amount_untaxed or 0.0)
            commission = base_amount * pct / 100.0 if (order.lx_artisan_id and order.state != "cancel") else 0.0
            currency = order.currency_id or order.company_id.currency_id
            order.lx_artisan_commission_amount = currency.round(commission) if currency else commission

    @api.model
    def _lx_get_request_affiliate_partner(self):
        try:
            session = getattr(request, "session", None)
            httprequest = getattr(request, "httprequest", None)
        except Exception:
            return self.env["res.partner"]

        if not session or not httprequest:
            return self.env["res.partner"]

        artisan_id = session.get("lx_artisan_partner_id")
        if artisan_id:
            partner = self.env["res.partner"].sudo().browse(int(artisan_id)).exists()
            if partner and partner.lx_is_artisan:
                return partner

        session_key = getattr(session, "sid", None) or httprequest.cookies.get("session_id")
        if not session_key:
            return self.env["res.partner"]

        click = self.env["lx.affiliate.click"].sudo().search(
            [("session_key", "=", session_key), ("artisan_id", "!=", False)],
            order="create_date desc, id desc",
            limit=1,
        )
        return click.artisan_id if click and click.artisan_id.lx_is_artisan else self.env["res.partner"]

    def _lx_link_affiliate_click_trace(self):
        try:
            session = getattr(request, "session", None)
            httprequest = getattr(request, "httprequest", None)
        except Exception:
            return
        if not session or not httprequest:
            return
        session_key = getattr(session, "sid", None) or httprequest.cookies.get("session_id")
        if not session_key:
            return
        click = self.env["lx.affiliate.click"].sudo().search(
            [("session_key", "=", session_key)],
            order="create_date desc, id desc",
            limit=1,
        )
        if not click:
            return
        for order in self:
            vals = {}
            if order.lx_artisan_id and not click.artisan_id:
                vals["artisan_id"] = order.lx_artisan_id.id
            if not click.sale_order_id:
                vals["sale_order_id"] = order.id
            if vals:
                click.write(vals)

    @api.model
    def _lx_payment_choice_specs(self):
        return {
            "upfront": {
                "name": "100% on Order",
                "note": _("Full payment collected when the order is placed."),
                "lines": [
                    {"value": "balance", "delay": 0},
                ],
            },
            "half_half": {
                "name": "50% on Order & 50% on Delivery",
                "note": _(
                    "50% deposit on order confirmation and 50% remaining on delivery. "
                    "The website choice remains the source of truth for Luxtor checkout."
                ),
                "lines": [
                    {"value": "percent", "value_amount": 50.0, "delay": 0},
                    {"value": "balance", "delay": 0},
                ],
            },
        }

    @api.model
    def _lx_ensure_payment_term_records(self):
        try:
            PaymentTerm = self.env["account.payment.term"].sudo()
            PaymentTermLine = self.env["account.payment.term.line"].sudo()
        except KeyError:
            return {}

        line_fields = PaymentTermLine._fields
        parent_field = "payment_id" if "payment_id" in line_fields else ("payment_term_id" if "payment_term_id" in line_fields else False)
        delay_field = "nb_days" if "nb_days" in line_fields else ("days" if "days" in line_fields else False)
        result = {}

        for key, spec in self._lx_payment_choice_specs().items():
            term = PaymentTerm.search([("name", "=", spec["name"])], limit=1)
            if not term:
                term_vals = {"name": spec["name"]}
                if "note" in PaymentTerm._fields:
                    term_vals["note"] = spec["note"]
                term = PaymentTerm.create(term_vals)

            if not term.line_ids:
                for seq, line_def in enumerate(spec["lines"], start=1):
                    if not parent_field:
                        break
                    line_vals = {
                        "value": line_def["value"],
                    }
                    if parent_field:
                        line_vals[parent_field] = term.id
                    if "sequence" in line_fields:
                        line_vals["sequence"] = seq * 10
                    if line_def.get("value") == "percent" and "value_amount" in line_fields:
                        line_vals["value_amount"] = float(line_def.get("value_amount") or 0.0)
                    if delay_field:
                        line_vals[delay_field] = int(line_def.get("delay") or 0)
                    PaymentTermLine.create(line_vals)

            result[key] = term

        return result

    def _lx_apply_website_payment_terms(self, choice):
        self.ensure_one()
        specs = self._lx_payment_choice_specs()
        normalized = choice if choice in specs else "upfront"
        vals = {"lx_payment_terms": normalized}

        term = self._lx_ensure_payment_term_records().get(normalized)
        if term and "payment_term_id" in self._fields:
            vals["payment_term_id"] = term.id

        self.sudo().write(vals)
        return normalized

    def _lx_payment_choice_key(self):
        self.ensure_one()
        specs = self._lx_payment_choice_specs()
        return self.lx_payment_terms if self.lx_payment_terms in specs else "upfront"

    def _lx_payment_summary_values(self):
        self.ensure_one()
        choice = self._lx_payment_choice_key()
        specs = self._lx_payment_choice_specs()
        total = float(self.amount_total or 0.0)
        currency = self.currency_id or self.company_id.currency_id

        ratio = 0.5 if choice == "half_half" else 1.0
        due_now = total * ratio
        if currency:
            due_now = currency.round(due_now)
        remaining = max(total - due_now, 0.0)
        if currency:
            remaining = currency.round(remaining)

        if choice == "half_half":
            notice = _(
                "50%% of the order is due now. The remaining balance stays due on delivery."
            )
        else:
            notice = _(
                "The full order amount is due now and will be registered as one backend payment."
            )

        return {
            "choice": choice,
            "choice_label": specs.get(choice, {}).get("name") or "",
            "is_partial": choice == "half_half",
            "order_total": currency.round(total) if currency else total,
            "amount_due_now": due_now,
            "remaining_to_pay": remaining,
            "notice": notice,
        }

    def _lx_backend_payment_reference(self):
        self.ensure_one()
        summary = self._lx_payment_summary_values()
        base_name = self.name or _("Quotation %s") % self.id
        return "%s - %s" % (base_name, summary.get("choice_label") or _("Website Payment"))

    def _lx_is_receivable_line(self, line, partner=None):
        account = getattr(line, "account_id", False)
        if not account:
            return False
        account_type = getattr(account, "account_type", False) or getattr(account, "internal_type", False)
        if account_type not in ("asset_receivable", "liability_payable", "receivable", "payable"):
            return False
        if getattr(line, "reconciled", False):
            return False
        if partner and "partner_id" in line._fields and line.partner_id and line.partner_id != partner:
            return False
        return True

    def _lx_get_or_create_website_invoice(self):
        self.ensure_one()
        try:
            Move = self.env["account.move"].sudo()
        except KeyError:
            return False

        invoice = Move.browse()
        if "invoice_ids" in self._fields:
            existing = self.invoice_ids.sudo().filtered(
                lambda m: m.move_type == "out_invoice" and m.state != "cancel"
            )
            open_invoices = existing.filtered(
                lambda m: getattr(m, "payment_state", False) not in ("paid", "reversed", "invoicing_legacy")
            )
            invoice = (open_invoices[:1] or existing[:1])

        if not invoice and hasattr(self.sudo(), "_create_invoices"):
            try:
                created = self.sudo()._create_invoices()
                invoice = created.filtered(lambda m: m.move_type == "out_invoice" and m.state != "cancel")[:1]
            except Exception:
                _logger.exception("Luxtor website invoice creation failed for order %s", self.id)

        if invoice and getattr(invoice, "state", "draft") == "draft" and hasattr(invoice, "action_post"):
            invoice.sudo().action_post()

        return invoice

    def _lx_pick_backend_payment_journal(self):
        self.ensure_one()
        try:
            Journal = self.env["account.journal"].sudo()
        except KeyError:
            return False
        return Journal.search(
            [
                ("company_id", "=", self.company_id.id),
                ("type", "in", ("bank", "cash")),
            ],
            order="type, sequence, id",
            limit=1,
        )

    def _lx_reconcile_payment_with_invoice(self, payment, invoice):
        self.ensure_one()
        if not payment or not invoice or not getattr(payment, "move_id", False):
            return False

        partner = self.partner_invoice_id or self.partner_id
        invoice_lines = invoice.line_ids.filtered(lambda l: self._lx_is_receivable_line(l, partner=partner))
        payment_lines = payment.move_id.line_ids.filtered(lambda l: self._lx_is_receivable_line(l, partner=partner))
        if not invoice_lines or not payment_lines:
            return False

        reconciled = False
        for pay_line in payment_lines:
            candidates = invoice_lines.filtered(lambda inv_line: inv_line.account_id == pay_line.account_id and not inv_line.reconciled)
            if not candidates:
                candidates = invoice_lines.filtered(lambda inv_line: not inv_line.reconciled)
            if not candidates:
                continue
            try:
                (pay_line + candidates[:1]).reconcile()
                reconciled = True
            except Exception:
                _logger.exception(
                    "Luxtor website payment reconciliation failed for order %s (payment %s, invoice %s)",
                    self.id, getattr(payment, "id", False), getattr(invoice, "id", False),
                )
        return reconciled

    def _lx_register_invoice_payment(self, invoice, amount, ref, journal=None):
        self.ensure_one()
        if not invoice:
            return {"ok": False, "payment": False, "amount": 0.0}

        try:
            Register = self.env["account.payment.register"].sudo()
            Payment = self.env["account.payment"].sudo()
        except KeyError:
            return {"ok": False, "payment": False, "amount": 0.0}

        journal = journal or self._lx_pick_backend_payment_journal()
        if not journal:
            return {"ok": False, "payment": False, "amount": 0.0}

        currency = invoice.currency_id or self.currency_id or self.company_id.currency_id
        residual = float(getattr(invoice, "amount_residual", 0.0) or 0.0)
        register_amount = min(float(amount or 0.0), residual) if residual > 0.0 else float(amount or 0.0)
        if currency:
            register_amount = currency.round(register_amount)
        if register_amount <= 0.0:
            return {"ok": False, "payment": False, "amount": register_amount}

        ctx = dict(self.env.context)
        ctx.update({
            "active_model": "account.move",
            "active_ids": invoice.ids,
            "active_id": invoice.id,
        })
        register_model = Register.with_context(ctx)
        register_fields = register_model._fields

        vals = {}
        if "amount" in register_fields:
            vals["amount"] = register_amount
        if "journal_id" in register_fields:
            vals["journal_id"] = journal.id
        if "payment_date" in register_fields:
            vals["payment_date"] = fields.Date.context_today(self)
        if "communication" in register_fields:
            vals["communication"] = ref
        if "payment_method_line_id" in register_fields:
            method_line = getattr(journal, "inbound_payment_method_line_ids", False)
            method_line = method_line[:1] if method_line else False
            if method_line:
                vals["payment_method_line_id"] = method_line.id

        wizard = register_model.create(vals)
        payment = False
        try:
            if hasattr(wizard, "_create_payments"):
                payment = wizard._create_payments()
            elif hasattr(wizard, "action_create_payments"):
                wizard.action_create_payments()
        except Exception:
            _logger.exception(
                "Luxtor website register payment wizard failed for order %s and invoice %s",
                self.id, invoice.id,
            )
            return {"ok": False, "payment": False, "amount": register_amount}

        if payment:
            payment = payment[:1]
        else:
            payment_fields = Payment._fields
            ref_field = "ref" if "ref" in payment_fields else ("payment_reference" if "payment_reference" in payment_fields else False)
            domain = [
                ("partner_id", "=", (self.partner_invoice_id or self.partner_id).id),
                ("company_id", "=", self.company_id.id),
                ("amount", "=", register_amount),
                ("journal_id", "=", journal.id),
            ]
            if ref_field:
                domain.append((ref_field, "=", ref))
            payment = Payment.search(domain, order="id desc", limit=1)

        return {
            "ok": bool(payment),
            "payment": payment[:1] if payment else False,
            "amount": register_amount,
        }

    def _lx_finalize_backend_payment(self, payment):
        self.ensure_one()
        if not payment:
            return payment

        payment = payment.sudo()
        current_state = getattr(payment, "state", False)

        if current_state == "draft" and hasattr(payment, "action_post"):
            try:
                payment.action_post()
            except Exception:
                _logger.exception("Luxtor failed to post backend payment %s", getattr(payment, "id", False))

        current_state = getattr(payment, "state", False)
        if current_state in ("paid", "done", "posted"):
            return payment

        for method_name in (
            "action_validate",
            "action_validate_payment",
            "action_set_paid",
            "action_paid",
            "button_validate",
            "action_confirm",
        ):
            method = getattr(payment, method_name, None)
            if not method:
                continue
            try:
                method()
            except Exception:
                _logger.exception(
                    "Luxtor failed calling %s on backend payment %s",
                    method_name, getattr(payment, "id", False),
                )
            current_state = getattr(payment, "state", False)
            if current_state in ("paid", "done", "posted"):
                return payment

        state_field = payment._fields.get("state")
        selection = {}
        if state_field and getattr(state_field, "selection", False):
            try:
                selection = dict(state_field.selection)
            except Exception:
                selection = {}

        for target_state in ("paid", "done", "posted"):
            if target_state in selection and getattr(payment, "state", False) != target_state:
                try:
                    payment.write({"state": target_state})
                    break
                except Exception:
                    _logger.exception(
                        "Luxtor failed forcing backend payment %s to state %s",
                        getattr(payment, "id", False), target_state,
                    )
        return payment

    def _lx_create_website_backend_payment(self):
        self.ensure_one()
        summary = self._lx_payment_summary_values()
        amount = float(summary.get("amount_due_now") or 0.0)
        partner = self.partner_invoice_id or self.partner_id
        currency = self.currency_id or self.company_id.currency_id
        invoice = self._lx_get_or_create_website_invoice()
        if invoice:
            currency = invoice.currency_id or currency
            invoice_total = float(getattr(invoice, "amount_total", 0.0) or 0.0)
            invoice_residual = float(getattr(invoice, "amount_residual", 0.0) or invoice_total or 0.0)
            if summary.get("is_partial"):
                amount = invoice_total * 0.5
            else:
                amount = invoice_residual or invoice_total or amount
            if invoice_residual > 0.0:
                amount = min(amount, invoice_residual)
            if currency:
                amount = currency.round(amount)
        amount_label = formatLang(self.env, amount, currency_obj=currency)
        remaining_label = formatLang(
            self.env,
            float(summary.get("remaining_to_pay") or 0.0),
            currency_obj=currency,
        )
        ref = self._lx_backend_payment_reference()

        if amount <= 0.0:
            note = _("No backend payment was created because the amount due now is zero.")
            if hasattr(self, "message_post"):
                self.message_post(body=note)
            return {
                "ok": True,
                "created": False,
                "user_notice": note,
                "amount_due_now": amount,
                "remaining_to_pay": float(summary.get("remaining_to_pay") or 0.0),
            }

        try:
            Payment = self.env["account.payment"].sudo()
            Journal = self.env["account.journal"].sudo()
        except KeyError:
            note = _(
                "Payment terms were stored on the order, but no accounting payment model is available."
            )
            if hasattr(self, "message_post"):
                self.message_post(body=note)
            return {
                "ok": False,
                "created": False,
                "user_notice": note,
                "amount_due_now": amount,
                "remaining_to_pay": float(summary.get("remaining_to_pay") or 0.0),
            }

        payment_fields = Payment._fields
        ref_field = "ref" if "ref" in payment_fields else ("payment_reference" if "payment_reference" in payment_fields else False)
        search_domain = [
            ("partner_id", "=", partner.id),
            ("company_id", "=", self.company_id.id),
            ("amount", "=", amount),
        ]
        if ref_field:
            search_domain.append((ref_field, "=", ref))

        existing = Payment.search(search_domain, limit=1)
        if existing:
            reconciled = self._lx_reconcile_payment_with_invoice(existing, invoice) if invoice else False
            invoice = invoice.sudo().browse(invoice.id) if invoice else invoice
            remaining_amount = float(getattr(invoice, "amount_residual", 0.0) or 0.0) if invoice else float(summary.get("remaining_to_pay") or 0.0)
            remaining_label = formatLang(self.env, remaining_amount, currency_obj=currency)
            invoice_payment_state = getattr(invoice, "payment_state", False) if invoice else False
            user_notice = _(
                "A backend payment already exists for %(amount)s. Remaining to pay: %(remaining)s."
            ) % {
                "amount": amount_label,
                "remaining": remaining_label,
            }
            if invoice and invoice_payment_state:
                user_notice += " " + _("Invoice status: %s.") % invoice_payment_state
            return {
                "ok": True,
                "created": False,
                "payment_id": existing.id,
                "payment_state": getattr(existing, "state", "draft"),
                "invoice_id": invoice.id if invoice else False,
                "invoice_name": invoice.name if invoice else False,
                "invoice_payment_state": invoice_payment_state,
                "reconciled": reconciled,
                "user_notice": user_notice,
                "amount_due_now": amount,
                "remaining_to_pay": remaining_amount,
            }

        journal = self._lx_pick_backend_payment_journal()
        if not journal:
            note = _(
                "Payment terms were saved, but no bank or cash journal is configured to create the backend payment."
            )
            if hasattr(self, "message_post"):
                self.message_post(body=note)
            return {
                "ok": False,
                "created": False,
                "user_notice": note,
                "amount_due_now": amount,
                "remaining_to_pay": float(summary.get("remaining_to_pay") or 0.0),
            }

        if invoice:
            wizard_result = self._lx_register_invoice_payment(invoice, amount, ref, journal=journal)
            payment = wizard_result.get("payment")
            if wizard_result.get("ok") and payment:
                payment = self._lx_finalize_backend_payment(payment)
                amount = float(wizard_result.get("amount") or amount)
                amount_label = formatLang(self.env, amount, currency_obj=currency)
                invoice = invoice.sudo().browse(invoice.id)
                remaining_amount = float(getattr(invoice, "amount_residual", 0.0) or 0.0)
                remaining_label = formatLang(self.env, remaining_amount, currency_obj=currency)
                invoice_payment_state = getattr(invoice, "payment_state", False)
                user_notice = _(
                    "Backend payment created for %(amount)s. Remaining to pay: %(remaining)s."
                ) % {
                    "amount": amount_label,
                    "remaining": remaining_label,
                }
                if invoice_payment_state:
                    user_notice += " " + _("Invoice status: %s.") % invoice_payment_state
                if hasattr(self, "message_post"):
                    self.message_post(body=user_notice)
                return {
                    "ok": True,
                    "created": True,
                    "payment_id": payment.id,
                    "payment_state": getattr(payment, "state", "draft"),
                    "invoice_id": invoice.id if invoice else False,
                    "invoice_name": invoice.name if invoice else False,
                    "invoice_payment_state": invoice_payment_state,
                    "reconciled": bool(invoice_payment_state and invoice_payment_state != "not_paid"),
                    "user_notice": user_notice,
                    "amount_due_now": amount,
                    "remaining_to_pay": remaining_amount,
                }

        vals = {}
        if "payment_type" in payment_fields:
            vals["payment_type"] = "inbound"
        if "partner_type" in payment_fields:
            vals["partner_type"] = "customer"
        if "partner_id" in payment_fields:
            vals["partner_id"] = partner.id
        if "amount" in payment_fields:
            vals["amount"] = amount
        if "currency_id" in payment_fields:
            vals["currency_id"] = currency.id
        if "company_id" in payment_fields:
            vals["company_id"] = self.company_id.id
        if "journal_id" in payment_fields:
            vals["journal_id"] = journal.id
        if "date" in payment_fields:
            vals["date"] = fields.Date.context_today(self)
        if "memo" in payment_fields:
            vals["memo"] = ref
        if ref_field:
            vals[ref_field] = ref

        if "payment_method_line_id" in payment_fields:
            method_line = getattr(journal, "inbound_payment_method_line_ids", False)
            method_line = method_line[:1] if method_line else False
            if method_line:
                vals["payment_method_line_id"] = method_line.id
        elif "payment_method_id" in payment_fields:
            method_line = getattr(journal, "inbound_payment_method_line_ids", False)
            method_line = method_line[:1] if method_line else False
            if method_line and getattr(method_line, "payment_method_id", False):
                vals["payment_method_id"] = method_line.payment_method_id.id

        try:
            payment = Payment.create(vals)
            payment = self._lx_finalize_backend_payment(payment)

            payment_state = getattr(payment, "state", "draft")
            reconciled = self._lx_reconcile_payment_with_invoice(payment, invoice) if invoice else False
            invoice = invoice.sudo().browse(invoice.id) if invoice else invoice
            remaining_amount = float(getattr(invoice, "amount_residual", 0.0) or 0.0) if invoice else float(summary.get("remaining_to_pay") or 0.0)
            remaining_label = formatLang(self.env, remaining_amount, currency_obj=currency)
            invoice_payment_state = getattr(invoice, "payment_state", False) if invoice else False
            user_notice = _(
                "Backend payment created for %(amount)s. Remaining to pay: %(remaining)s."
            ) % {
                "amount": amount_label,
                "remaining": remaining_label,
            }
            if invoice and invoice_payment_state:
                user_notice += " " + _("Invoice status: %s.") % invoice_payment_state
            if hasattr(self, "message_post"):
                self.message_post(body=user_notice)
            return {
                "ok": True,
                "created": True,
                "payment_id": payment.id,
                "payment_state": payment_state,
                "invoice_id": invoice.id if invoice else False,
                "invoice_name": invoice.name if invoice else False,
                "invoice_payment_state": invoice_payment_state,
                "reconciled": reconciled,
                "user_notice": user_notice,
                "amount_due_now": amount,
                "remaining_to_pay": remaining_amount,
            }
        except Exception as err:
            _logger.exception("Luxtor website backend payment creation failed for order %s", self.id)
            note = _(
                "Payment terms were saved but the backend payment could not be created automatically: %s"
            ) % (str(err) or _("Unknown error"))
            if hasattr(self, "message_post"):
                self.message_post(body=note)
            return {
                "ok": False,
                "created": False,
                "user_notice": note,
                "amount_due_now": amount,
                "remaining_to_pay": float(summary.get("remaining_to_pay") or 0.0),
            }

    # ── Hide service lines from the cart display (website_order_line) ──────────
    # INSTALL_SERVICE and PRIORITY_SERVICE are backend-managed lines that should
    # never appear as editable cart rows in the frontend.

    _LX_HIDDEN_SERVICE_CODES = frozenset({'INSTALL_SERVICE', 'PRIORITY_SERVICE'})

    def _compute_website_order_line(self):
        super()._compute_website_order_line()
        for order in self:
            order.website_order_line = order.website_order_line.filtered(
                lambda l: (l.product_id.default_code or '').strip().upper()
                          not in self._LX_HIDDEN_SERVICE_CODES
            )

    def _lx_is_loyalty_summary_line(self, line):
        self.ensure_one()
        if not line or line.display_type:
            return False
        if "reward_id" in line._fields and line.reward_id:
            return True
        if "coupon_id" in line._fields and line.coupon_id:
            return True
        if "is_reward_line" in line._fields and line.is_reward_line:
            return True
        if "is_loyalty_line" in line._fields and line.is_loyalty_line:
            return True
        if "program_id" in line._fields and line.program_id:
            return True
        return "% on your order" in (line.name or "")

    def _lx_get_loyalty_summary_lines(self):
        self.ensure_one()
        return self.order_line.filtered(
            lambda line: not line.display_type and self._lx_is_loyalty_summary_line(line)
        )

    def _lx_get_loyalty_summary_display(self):
        self.ensure_one()
        lines = self._lx_get_loyalty_summary_lines()
        loyalty_label = False

        for line in lines:
            reward = line.reward_id if "reward_id" in line._fields else False
            if reward and reward.discount_mode == "percent" and reward.discount:
                loyalty_label = _("%s%% on your order") % ("%g" % reward.discount)
                break

            line_name = (line.name or "").strip()
            if "% on your order" in line_name:
                loyalty_label = line_name
                break

        return {
            "lines": lines,
            "loyalty_label": loyalty_label,
            "discount_total": sum(lines.mapped("price_subtotal")),
        }

    def _lx_has_welcome_coupon_applied(self, coupon=False):
        self.ensure_one()
        if not coupon:
            return False

        if "applied_coupon_ids" in self._fields and coupon in self.applied_coupon_ids:
            return True

        program = coupon.program_id if "program_id" in coupon._fields else False
        coupon_code = getattr(coupon, "code", False) or False
        for line in self._lx_get_loyalty_summary_lines():
            if "coupon_id" in line._fields and line.coupon_id == coupon:
                return True
            if (
                program
                and "reward_id" in line._fields
                and line.reward_id
                and line.reward_id.program_id == program
            ):
                return True
            if program and "program_id" in line._fields and line.program_id == program:
                return True
            if coupon_code and coupon_code in (line.name or ""):
                return True
        return False

    def _lx_is_service_line_code(self, line, codes=None):
        self.ensure_one()
        codes = codes or self._LX_SYNC_SERVICE_CODES
        product = line.product_id
        if not product or line.display_type:
            return False
        code = (product.default_code or '').strip().upper()
        tmpl_code = (product.product_tmpl_id.default_code or '').strip().upper()
        return code in codes or tmpl_code in codes

    def _lx_find_service_lines_by_code(self, code):
        self.ensure_one()
        service_code = (code or '').strip().upper()
        return self.order_line.filtered(
            lambda l: not l.display_type
            and l.product_id
            and (
                (l.product_id.default_code or '').strip().upper() == service_code
                or (l.product_id.product_tmpl_id.default_code or '').strip().upper() == service_code
            )
        )

    def _lx_qty_mrp_total_for_services(self):
        self.ensure_one()
        qty_total = 0.0
        Bom = self.env['mrp.bom'].sudo()

        tmpl_ids = set()
        lines = []
        for line in self.sudo().order_line:
            product = line.product_id
            if not product or line.display_type or self._lx_is_service_line_code(line):
                continue
            tid = product.product_tmpl_id.id
            tmpl_ids.add(tid)
            lines.append((line, tid))

        if not tmpl_ids:
            return 0.0

        boms = Bom.search([('product_tmpl_id', 'in', list(tmpl_ids))])
        has_bom_tmpl = set(boms.mapped('product_tmpl_id').ids)

        for line, tid in lines:
            if tid in has_bom_tmpl:
                qty_total += float(line.product_uom_qty or 0.0)
        return qty_total

    def _lx_sync_active_cart_services(self):
        self.ensure_one()
        if self.env.context.get('lx_skip_service_qty_sync'):
            return

        active_codes = [
            code for code in self._LX_SYNC_SERVICE_CODES
            if self._lx_find_service_lines_by_code(code)
        ]
        if not active_codes:
            return

        target_qty = float(self._lx_qty_mrp_total_for_services() or 0.0)
        for code in active_codes:
            lines = self._lx_find_service_lines_by_code(code)
            if not lines:
                continue

            keep = lines[:1]
            extra_lines = lines - keep

            if target_qty <= 0.0:
                super(SaleOrder, self.with_context(lx_skip_service_qty_sync=True))._cart_update_line_quantity(
                    line_id=keep.id,
                    quantity=0.0,
                )
            else:
                current_qty = float(keep.product_uom_qty or 0.0)
                if abs(current_qty - target_qty) > 1e-6:
                    super(SaleOrder, self.with_context(lx_skip_service_qty_sync=True))._cart_update_line_quantity(
                        line_id=keep.id,
                        quantity=target_qty,
                    )

            for extra in extra_lines:
                super(SaleOrder, self.with_context(lx_skip_service_qty_sync=True))._cart_update_line_quantity(
                    line_id=extra.id,
                    quantity=0.0,
                )

        try:
            from ..controllers.install_service import _reapply_free_logic, _invalidate_totals
            _reapply_free_logic(self.sudo())
            _invalidate_totals(self.sudo())
        except Exception:
            _logger.exception("Failed to reapply Luxtor website service rules after cart quantity sync.")

    def _cart_add(self, product_id: int, quantity: float = 1.0, *, uom_id: int | None = None, **kwargs) -> dict:
        result = super()._cart_add(product_id, quantity=quantity, uom_id=uom_id, **kwargs)
        self._lx_sync_active_cart_services()
        return result

    def _cart_update_line_quantity(self, line_id: int, quantity: float, **kwargs) -> dict:
        result = super()._cart_update_line_quantity(line_id=line_id, quantity=quantity, **kwargs)
        self._lx_sync_active_cart_services()
        return result

    @api.depends("name", "state")
    def _compute_lx_production_state(self):
        Mrp = self.env["mrp.production"].sudo()
        names = [o.name for o in self if o.name]
        mos_by_origin = {}
        if names:
            mos = Mrp.search([("origin", "in", names)])
            for mo in mos:
                mos_by_origin.setdefault(mo.origin, self.env["mrp.production"])
                mos_by_origin[mo.origin] |= mo

        for order in self:
            mos = Mrp.search([("sale_line_id.order_id", "=", order.id)])
            if not mos and order.name:
                mos = mos_by_origin.get(order.name, self.env["mrp.production"])

            if not mos:
                order.lx_production_state = "not_started"
                continue

            total = len(mos)
            done_count = len(mos.filtered(lambda m: m.state == "done"))

            if total > 0 and done_count == total:
                order.lx_production_state = "complete"
            elif done_count > 0:
                order.lx_production_state = "in_works"
            else:
                order.lx_production_state = "not_started"

    def action_open_production_monitor_lines(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Production Monitor Lines"),
            "res_model": "luxtor.production.monitor.line",
            "view_mode": "list,form",
            "domain": [("sale_order_id", "=", self.id)],
            "context": {"default_sale_order_id": self.id},
            "target": "current",
        }

    @api.depends('order_line.product_id', 'order_line.display_type')
    def _compute_priority(self):
        for order in self:
            special = False
            for line in order.order_line.filtered(lambda l: not l.display_type and l.product_id):
                if (line.product_id.default_code or '').strip() == 'PRIORITY_SERVICE':
                    special = True
                    break
            order.priority = 'special' if special else 'normal'

    def _default_validity_date(self):
        today = fields.Date.context_today(self)
        return today + relativedelta(days=30)

    def _add_business_days(self, base_date, days):
        from datetime import timedelta
        count = 0
        current_date = base_date
        while count < days:
            current_date += timedelta(days=1)
            if current_date.weekday() < 5:
                count += 1
        return current_date

    def _get_total_weight_kg(self):
        self.ensure_one()
        total = 0.0
        for line in self.order_line:
            p = line.product_id
            if not p or line.display_type:
                continue
            if p.type in ('product', 'consu'):
                total += (p.weight or 0.0) * line.product_uom_qty
        return total

    @api.model_create_multi
    def create(self, vals_list):
        artisan = self._lx_get_request_affiliate_partner()
        for vals in vals_list:
            if artisan and not vals.get("lx_artisan_id"):
                vals["lx_artisan_id"] = artisan.id
            if not vals.get('validity_date'):
                date_order_val = vals.get('date_order')
                if date_order_val:
                    base_dt = fields.Datetime.from_string(date_order_val)
                else:
                    base_dt = fields.Datetime.context_timestamp(self, datetime.now())
                vals['validity_date'] = base_dt.date() + relativedelta(days=30)

        orders = super().create(vals_list)

        for order in orders:
            order._generate_sequence_numbers_for_lines()
            if artisan and not order.lx_artisan_id:
                order.sudo().write({"lx_artisan_id": artisan.id})

        orders._lx_link_affiliate_click_trace()

        return orders

    def write(self, vals):
        if 'date_order' in vals:
            try:
                base_dt = fields.Datetime.from_string(vals['date_order'])
                vals['validity_date'] = base_dt.date() + relativedelta(days=30)
            except Exception:
                pass

        res = super().write(vals)

        recalc_delivery = 'priority' in vals or 'date_order' in vals
        for order in self:
            artisan = order._lx_get_request_affiliate_partner()
            if artisan and not order.lx_artisan_id:
                order.sudo().write({"lx_artisan_id": artisan.id})
            if recalc_delivery:
                order._compute_delivery_date()
                order.invalidate_recordset()

            # FIX: check for lines with NO sequence_number at all (None or False),
            # NOT empty string "". Section headers legitimately have sequence_number=""
            # and triggering regeneration every time they exist caused the old
            # sale_order.py version to overwrite the v2 numbering from lx_electric_blinds.py.
            if any(
                line.sequence_number is None or line.sequence_number is False
                for line in order.order_line
                if not line.display_type and not line.lx_is_electric_subtotal
            ):
                order._generate_sequence_numbers_for_lines()

        self._lx_link_affiliate_click_trace()
        return res

    @api.onchange('date_order')
    def _onchange_date_order(self):
        if self.date_order:
            self.validity_date = self.date_order.date() + relativedelta(days=30)

    @api.onchange('order_line')
    def _onchange_generate_sequence_numbers(self):
        for order in self:
            order._generate_sequence_numbers_for_lines()

    # ──────────────────────────────────────────────────────────────────────────
    # _generate_sequence_numbers_for_lines is intentionally NOT defined here.
    # The authoritative implementation lives in lx_electric_blinds.py and
    # handles section headers, subtotal notes, child lines (1.1, 1.2…),
    # storable products (type='product'), and service lines correctly.
    #
    # Having it in BOTH files caused the old v1 version here to overwrite
    # the v2 version from lx_electric_blinds.py (whichever loaded last won),
    # breaking sub-numbering and section handling.
    # ──────────────────────────────────────────────────────────────────────────

    @api.depends('date_order', 'priority', 'state', 'order_line.product_id', 'order_line.display_type')
    def _compute_delivery_date(self):
        for order in self:
            try:
                if not order.date_order:
                    order.delivery_date = False
                    continue

                base_dt = fields.Datetime.context_timestamp(order, order.date_order)

                if order.priority == 'special':
                    order.delivery_date = (
                        base_dt.date()
                        if base_dt.time() < time(12, 0)
                        else base_dt.date() + relativedelta(days=1)
                    )
                else:
                    order.delivery_date = order._add_business_days(base_dt.date(), 5)

            except Exception as e:
                _logger.exception("Error computing delivery date for order %s: %s", order.name, e)

    def _is_mrp_blind_line(self, line):
        if line.is_priority_line or line.is_installation_line:
            return False
        product = line.product_id
        if not product:
            return False
        return bool(product.product_tmpl_id.bom_ids)

    def _get_mrp_blinds_quantity(self):
        qty = 0
        for line in self.order_line:
            if self._is_mrp_blind_line(line):
                qty += line.product_uom_qty
        return qty

    def action_open_shipping_wizard(self):
        self.ensure_one()
        return {
            'name': _('Add a Shipping Method'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.shipping.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'active_id': self.id, 'default_order_id': self.id},
        }

    def _lx_find_bom(self, product, company=None, *args, **kwargs):
        self.ensure_one()
        company = company or self.company_id
        Bom = self.env['mrp.bom']
        bom = Bom.search([
            ('product_id', '=', product.id),
            ('company_id', 'in', [company.id, False]),
            ('type', '=', 'normal'),
        ], limit=1, order='sequence,id')
        if not bom:
            bom = Bom.search([
                ('product_tmpl_id', '=', product.product_tmpl_id.id),
                ('company_id', 'in', [company.id, False]),
                ('type', '=', 'normal'),
            ], limit=1, order='sequence,id')
        return bom

    def _cart_find_product_line(self, product_id=None, line_id=None, **kwargs):
        lines = super()._cart_find_product_line(product_id=product_id, line_id=line_id, **kwargs)
        if not lines:
            return lines

        w = kwargs.get("lx_width_m")
        h = kwargs.get("lx_height_m")
        loc = kwargs.get("lx_location_id")

        def _to_float(x):
            try:
                return float(str(x).replace(",", "."))
            except Exception:
                return None

        def _to_int(x):
            try:
                value = int(str(x).strip())
                return value if value > 0 else None
            except Exception:
                return None

        w = _to_float(w)
        h = _to_float(h)
        loc = _to_int(loc)
        motor_variant_id = self._lx_resolve_motor_only_variant_from_kwargs(**kwargs)
        if w is None and h is None and not loc and not motor_variant_id:
            return lines

        def _same(a, b):
            if a is None or b is None:
                return False
            return float_compare(float(a), float(b), precision_digits=DIM_PRECISION) == 0

        return lines.filtered(
            lambda l: (w is None or _same(l.lx_width_m, w)) and
                      (h is None or _same(l.lx_height_m, h)) and
                      (loc is None or (l.lx_location_id and l.lx_location_id.id == loc)) and
                      (
                          not motor_variant_id
                          or (
                              l.lx_motor_only_variant_id
                              and l.lx_motor_only_variant_id.id == motor_variant_id
                          )
                      )
        )

    def _cart_update(self, *args, **kwargs):
        res = super()._cart_update(*args, **kwargs)
        line_id = res.get("line_id")
        if not line_id:
            return res

        line = self.env["sale.order.line"].sudo().browse(line_id)

        def _f(x):
            if x is None:
                return None
            try:
                return float(str(x).replace(",", "."))
            except Exception:
                return None

        w_in = _f(kwargs.get("lx_width_m"))
        h_in = _f(kwargs.get("lx_height_m"))
        pu_in = _f(kwargs.get("lx_final_unit_price") or kwargs.get("lx_price_override"))
        loc_in = kwargs.get("lx_location_id")
        try:
            loc_id = int(loc_in or 0)
        except (TypeError, ValueError):
            loc_id = 0

        w = (w_in if (w_in is not None and w_in > 0) else (line.lx_width_m or None))
        h = (h_in if (h_in is not None and h_in > 0) else (line.lx_height_m or None))

        vals = {}
        if w_in is not None:
            vals["lx_width_m"] = w if (w and w > 0) else 1.0
        if h_in is not None:
            vals["lx_height_m"] = h if (h and h > 0) else 1.0
        if loc_id > 0:
            vals["lx_location_id"] = loc_id

        if vals:
            line.write(vals)
            w = line.lx_width_m or w
            h = line.lx_height_m or h

        price_unit = self._lx_compute_cart_line_price_unit(line, **kwargs)
        if price_unit is not None and price_unit > 0:
            line.sudo().write({"price_unit": price_unit})
            if getattr(line.product_template_id, "is_dimension_product", False):
                area = max(float(line.lx_width_m or 1.0), 1.0) * max(float(line.lx_height_m or 1.0), 1.0)
                final_unit = price_unit * (area if area > 0.0 else 1.0)
                line.sudo().write({"lx_final_unit_price": final_unit})

        if getattr(line.product_id, "is_dimension_product", False) and ((w is not None) or (h is not None)):
            base = line.product_id.get_product_multiline_description_sale() or line.product_id.display_name
            dims = f" ({(line.lx_width_m or 0):g} m × {(line.lx_height_m or 0):g} m)"
            variants = line._get_sale_order_line_multiline_description_variants()
            title = f"{base}{dims}"
            line.name = title + (f"\n{variants}" if variants else "")
            res.setdefault("notification_info", {})["name_short"] = title
        else:
            res.setdefault("notification_info", {})["name_short"] = line.product_id.display_name

        final_price = float(getattr(line, "lx_final_unit_price", 0.0) or 0.0)
        res.setdefault("notification_info", {})["price"] = final_price or line.price_unit
        return res

    def _lx_compute_cart_line_price_unit(self, order_line, **kwargs):
        """Return the persisted `price_unit` that should be stored on a cart line."""
        order_line.ensure_one()

        def _f(x):
            if x is None:
                return None
            try:
                return float(str(x).replace(",", "."))
            except Exception:
                return None

        pu_in = _f(kwargs.get("lx_final_unit_price") or kwargs.get("lx_price_override"))
        if pu_in is not None and pu_in > 0:
            w = _f(kwargs.get("lx_width_m")) or float(order_line.lx_width_m or 1.0)
            h = _f(kwargs.get("lx_height_m")) or float(order_line.lx_height_m or 1.0)
            area = max(w, 1.0) * max(h, 1.0)
            if getattr(order_line.product_id, "is_dimension_product", False):
                return pu_in / (area if area > 0 else 1.0)
            return pu_in

        product = order_line.product_id
        if not product or not getattr(product, "is_dimension_product", False):
            return None

        existing_price_unit = _f(order_line.price_unit)
        if existing_price_unit is not None and existing_price_unit > 0:
            return existing_price_unit

        try:
            if (
                hasattr(product, "lx_is_motor_only_variant")
                and product.lx_is_motor_only_variant()
                and hasattr(order_line, "_lx_compute_motor_only_price")
            ):
                price_unit = order_line._lx_compute_motor_only_price()
            else:
                price_unit = order_line._lx_compute_price_unit_like_wizard()
        except Exception:
            _logger.exception(
                "[Luxtor] Failed to recompute persisted cart price for line %s",
                order_line.id,
            )
            return None

        return price_unit if price_unit and price_unit > 0 else None

    def _lx_get_used_threshold_pct(self):
        icp = self.env["ir.config_parameter"].sudo()
        val = icp.get_param(PARAM_USED_PCT, default="95")
        try:
            pct = float(val)
        except Exception:
            pct = 95.0
        return max(0.0, min(100.0, pct))

    def _lx_as_fabric_product(self, fabric_ref):
        if not fabric_ref:
            return self.env["product.product"]
        if fabric_ref._name == "product.product":
            return fabric_ref
        if fabric_ref._name == "product.template":
            return fabric_ref.product_variant_id
        return getattr(fabric_ref, "product_variant_id", self.env["product.product"])

    def _lx_fabric_remaining_pct(self, order, fabric_prod):
        fabric_prod = fabric_prod.sudo()
        ctx = dict(self.env.context)
        if order.warehouse_id:
            ctx["warehouse"] = order.warehouse_id.id
        fp = fabric_prod.with_context(ctx)
        try:
            free_qty = float(fp.free_qty)
        except Exception:
            free_qty = 0.0
        try:
            base_qty = float(fp.virtual_available)
        except Exception:
            base_qty = 0.0
        base_qty = max(base_qty, 1.0)
        remaining_pct = (free_qty / base_qty) * 100.0
        return max(0.0, min(100.0, remaining_pct))

    def _lx_check_fabric_freeze_or_raise(self):
        threshold_used = self._lx_get_used_threshold_pct()
        for order in self:
            if order.state not in ("draft", "sent"):
                continue
            offenders = []
            for line in order.order_line:
                if line.display_type or not line.product_id:
                    continue
                pt = line.product_id.product_tmpl_id
                fabric_ref = getattr(pt, "lx_fabric_ref_id", False)
                if not fabric_ref:
                    continue
                fabric_prod = order._lx_as_fabric_product(fabric_ref)
                if not fabric_prod or not fabric_prod.exists():
                    offenders.append((line, 0.0, _("Related fabric not found.")))
                    continue
                remaining_pct = order._lx_fabric_remaining_pct(order, fabric_prod)
                used_pct = 100.0 - remaining_pct
                if used_pct >= threshold_used:
                    offenders.append((line, remaining_pct, fabric_prod.display_name))

            if offenders:
                lines_txt = []
                for sol, rem, fabric_name in offenders:
                    lines_txt.append(
                        _("- %s (Fabric: %s, Remaining: %s%%)")
                        % (sol.product_id.display_name, fabric_name, ("%.2f" % rem))
                    )
                raise ValidationError(
                    FREEZE_MSG + "\n\n" + _("Blocked lines:") + "\n" + "\n".join(lines_txt)
                )

    @api.constrains(
        "state", "warehouse_id", "order_line",
        "order_line.product_id", "order_line.product_uom_qty",
    )
    def _constrains_lx_fabric_stock_before_save(self):
        self._lx_check_fabric_freeze_or_raise()

    def action_confirm(self):
        res = super().action_confirm()

        Mrp = self.env['mrp.production']
        mrp_fields = Mrp._fields
        Loc = self.env['luxtor.location']
        other_loc = Loc.search([('name', '=', 'Other')], limit=1) or Loc.create({'name': 'Other'})

        def _is_electric(sol):
            return bool(sol.product_id and sol.product_id.lx_is_electric_variant())

        def _is_motor_only(sol):
            return bool(sol.product_id and sol.product_id.lx_is_motor_only_variant())

        def _get_accessories(order):
            motor_remote, motor_smart, remote, charger, zigbee = order._lx_get_accessory_products()
            icp = order.env['ir.config_parameter'].sudo()
            r_ratio = max(1, int(icp.get_param('luxtor.remote_ratio', 5)))
            c_ratio = max(1, int(icp.get_param('luxtor.charger_ratio', 15)))
            z_ratio = max(1, int(icp.get_param('luxtor.zigbee_ratio', 30)))
            return motor_remote, motor_smart, remote, charger, zigbee, r_ratio, c_ratio, z_ratio

        def _ensure_move_qty(mo, product, qty, prefix="⤶ "):
            if not product:
                return
            move = mo.move_raw_ids.filtered(lambda m: m.product_id.id == product.id)[:1]
            if qty and qty > 0:
                if move:
                    move.write({'product_uom_qty': float(qty)})
                else:
                    vals = {
                        'product_id': product.id,
                        'product_uom': product.uom_id.id,
                        'product_uom_qty': float(qty),
                        'location_id': mo.location_src_id.id,
                        'location_dest_id': mo.location_dest_id.id,
                    }
                    mo.write({'move_raw_ids': [(0, 0, vals)]})
            else:
                if move:
                    move.unlink()

        for order in self:
            motor_remote, motor_smart, remote, charger, zigbee, r_ratio, c_ratio, z_ratio = _get_accessories(order)

            motors_total = 0
            non_motor_only_total = 0
            for sol in order.order_line:
                if sol.display_type or not sol.product_id:
                    continue
                if _is_electric(sol):
                    q = int(sol.product_uom_qty or 0)
                    motors_total += q
                    if not _is_motor_only(sol):
                        non_motor_only_total += q

            remote_needed  = int(math.ceil(non_motor_only_total / r_ratio)) if non_motor_only_total > 0 else 0
            charger_needed = int(math.ceil(non_motor_only_total / c_ratio)) if non_motor_only_total > 0 else 0
            accessories_allocated = False

            for sol in order.order_line:
                if sol.product_id.type not in ('product', 'consu'):
                    continue
                qty = int(sol.product_uom_qty or 0)
                if qty <= 0:
                    continue

                bom = order._lx_find_bom(sol.product_id)
                if not bom:
                    continue

                w_m = getattr(sol, 'lx_width_m', 0.0) or 0.0
                h_m = getattr(sol, 'lx_height_m', 0.0) or 0.0

                for unit_idx in range(qty):
                    uom = sol.product_uom_id or sol.product_id.uom_id
                    mo_vals = {
                        'company_id': order.company_id.id,
                        'product_id': sol.product_id.id,
                        'product_uom_id': uom.id,
                        'product_qty': 1.0,
                        'bom_id': bom.id,
                        'origin': order.name,
                        'sale_line_id': sol.id,
                    }
                    if 'luxtor_location_id' in mrp_fields:
                        mo_vals['luxtor_location_id'] = other_loc.id
                    if 'lx_width_m' in mrp_fields:
                        mo_vals['lx_width_m'] = w_m
                    if 'lx_height_m' in mrp_fields:
                        mo_vals['lx_height_m'] = h_m

                    mo = Mrp.create(mo_vals)

                    if _is_electric(sol):
                        if _is_motor_only(sol):
                            # Motor Only: the motor is an SOL accessory child line,
                            # not an MO component.
                            # 1. Remove any tubular motor from BOM explosion.
                            motor_moves = mo.move_raw_ids.filtered(
                                lambda m: m.product_id.product_tmpl_id.lx_is_tubular_motor
                            )
                            if motor_moves:
                                motor_moves.unlink()
                            # 2. Remove ALL idler variants exploded from BOM
                            #    (BOM may contain multiple variants or a template component).
                            idler_moves = mo.move_raw_ids.filtered(
                                lambda m: m.product_id.product_tmpl_id.lx_is_idler
                            )
                            if idler_moves:
                                idler_moves.unlink()
                            # 3. Add only the correct idler for the selected motor variant,
                            #    positioned last (sequence = max existing + 10).
                            motor_var = sol.lx_motor_only_variant_id
                            if motor_var and motor_var.lx_idler_variant_id:
                                _ensure_move_qty(mo, motor_var.lx_idler_variant_id, 1)
                                idler_move = mo.move_raw_ids.filtered(
                                    lambda m: m.product_id.id == motor_var.lx_idler_variant_id.id
                                )[:1]
                                if idler_move and len(mo.move_raw_ids) > 1:
                                    others = mo.move_raw_ids - idler_move
                                    max_seq = max((m.sequence or 0) for m in others)
                                    idler_move.write({'sequence': max_seq + 10})
                        else:
                            _ensure_move_qty(mo, motor_remote, 1)
                            if not accessories_allocated:
                                if remote_needed > 0:
                                    _ensure_move_qty(mo, remote, remote_needed)
                                else:
                                    _ensure_move_qty(mo, remote, 0)
                                if charger_needed > 0:
                                    _ensure_move_qty(mo, charger, charger_needed)
                                else:
                                    _ensure_move_qty(mo, charger, 0)
                                accessories_allocated = True
                            else:
                                _ensure_move_qty(mo, remote, 0)
                                _ensure_move_qty(mo, charger, 0)

            template = self.env.ref(
                "luxtor_custom.mail_template_sale_order_customer_confirm",
                raise_if_not_found=False,
            )
            if template:
                order._portal_ensure_token()
                order.with_context(force_send=True).message_post_with_source(
                    template,
                    email_layout_xmlid='mail.mail_notification_layout_with_responsible_signature',
                    subtype_xmlid='mail.mt_comment',
                )

        return res

    def _lx_resolve_motor_only_variant_from_kwargs(self, **kwargs):
        """
        Resolve the selected tubular motor variant from website cart kwargs.

        Priority:
        1. `lx_motor_only_variant_id` when the frontend sends the raw variant id.
        2. Friendly label / code fallback using the tubular motor template:
           - field: product.template.lx_is_tubular_motor
           - PTAV field: product.template.attribute.value.lx_motor_label
           - Code attribute value name: e.g. AM28-1.8/30-ES-EZ
        """

        def _norm(value):
            return " ".join((value or "").strip().casefold().split())

        raw_variant_id = kwargs.get("lx_motor_only_variant_id")
        if raw_variant_id:
            try:
                variant_id = int(raw_variant_id)
            except (TypeError, ValueError):
                variant_id = 0
            if variant_id > 0:
                variant = self.env["product.product"].sudo().browse(variant_id).exists()
                if variant:
                    return variant.id

        wanted = _norm(
            kwargs.get("lx_motor_only_label")
            or kwargs.get("lx_motor_label")
            or kwargs.get("lx_motor_control_name")
            or kwargs.get("motor_control_name")
            or ""
        )
        if not wanted:
            return False

        motor_template = self.env["product.template"].sudo().search(
            [("lx_is_tubular_motor", "=", True)],
            limit=1,
        )
        if not motor_template:
            return False

        for variant in motor_template.product_variant_ids:
            code = ""
            label = ""
            for ptav in variant.product_template_attribute_value_ids:
                if (ptav.attribute_id.name or "").strip() == "Code":
                    code = (ptav.product_attribute_value_id.name or "").strip()
                    label = (getattr(ptav, "lx_motor_label", False) or "").strip()
                    break
            candidates = {
                _norm(label),
                _norm(code),
                _norm(variant.default_code or ""),
                _norm(variant.display_name or ""),
            }
            candidates.discard("")
            if wanted in candidates:
                return variant.id

        return False

    def _prepare_order_line_values(self, product_id, quantity, uom_id=None, **kwargs):
        """
        Forward our custom dimension/location fields and price override into SOL vals.

        V19 replaced _cart_update with _cart_add → _create_new_cart_line →
        _prepare_order_line_values, passing uom_id as positional arg 3.
        Price injection (lx_final_unit_price) must happen here — _cart_update
        is never called in V19.
        """
        if uom_id is not None:
            vals = super()._prepare_order_line_values(product_id, quantity, uom_id, **kwargs)
        else:
            vals = super()._prepare_order_line_values(product_id, quantity, **kwargs)

        def _f(x):
            if x is None:
                return None
            try:
                return float(str(x).replace(",", "."))
            except Exception:
                return None

        w = _f(kwargs.get("lx_width_m"))
        h = _f(kwargs.get("lx_height_m"))

        if w is not None and w > 0:
            vals["lx_width_m"] = w
        if h is not None and h > 0:
            vals["lx_height_m"] = h

        loc = kwargs.get("lx_location_id")
        if loc:
            try:
                loc_id = int(loc)
                if loc_id > 0:
                    vals["lx_location_id"] = loc_id
            except (TypeError, ValueError):
                pass

        mtr_id = self._lx_resolve_motor_only_variant_from_kwargs(**kwargs)
        if mtr_id:
            vals["lx_motor_only_variant_id"] = mtr_id

        # Price override — set by main.py from JS hidden input or server-side calc
        pu_in = _f(kwargs.get("lx_final_unit_price") or kwargs.get("lx_price_override"))
        if pu_in is not None and pu_in > 0:
            vals["lx_final_unit_price"] = pu_in
            W = (w if (w and w > 0) else 1.0)
            H = (h if (h and h > 0) else 1.0)
            area = W * H
            product = self.env["product.product"].sudo().browse(product_id)
            if getattr(product, "is_dimension_product", False):
                # lx_final_unit_price = unit_virtual × area; SOL needs price per m²
                vals["price_unit"] = pu_in / (area if area > 0 else 1.0)
            else:
                vals["price_unit"] = pu_in

        return vals

    def _prepare_order_line_update_values(self, order_line, quantity, **kwargs):
        """
        V19: called when _cart_add finds an existing matching line and updates its qty.
        _prepare_order_line_values is NOT called in this branch, so we must inject
        lx_final_unit_price here too — otherwise changing qty after adding to cart
        leaves the price at 0 (pricelist default).
        """
        vals = super()._prepare_order_line_update_values(order_line, quantity, **kwargs)

        def _f(x):
            if x is None:
                return None
            try:
                return float(str(x).replace(",", "."))
            except Exception:
                return None

        pu_in = _f(kwargs.get("lx_final_unit_price") or kwargs.get("lx_price_override"))
        loc = kwargs.get("lx_location_id")
        if loc:
            try:
                loc_id = int(loc)
                if loc_id > 0:
                    vals["lx_location_id"] = loc_id
            except (TypeError, ValueError):
                pass
        if pu_in is not None and pu_in > 0:
            vals["lx_final_unit_price"] = pu_in
            w = _f(kwargs.get("lx_width_m")) or float(order_line.lx_width_m or 1.0)
            h = _f(kwargs.get("lx_height_m")) or float(order_line.lx_height_m or 1.0)
            W = max(w, 1.0)
            H = max(h, 1.0)
            area = W * H
            if getattr(order_line.product_id, "is_dimension_product", False):
                vals["price_unit"] = pu_in / (area if area > 0 else 1.0)
            else:
                vals["price_unit"] = pu_in
            mtr_id = self._lx_resolve_motor_only_variant_from_kwargs(**kwargs)
            if mtr_id:
                vals["lx_motor_only_variant_id"] = mtr_id
            return vals

        price_unit = self._lx_compute_cart_line_price_unit(order_line, **kwargs)
        if price_unit is not None and price_unit > 0:
            vals["price_unit"] = price_unit

        mtr_id = self._lx_resolve_motor_only_variant_from_kwargs(**kwargs)
        if mtr_id:
            vals["lx_motor_only_variant_id"] = mtr_id

        return vals

    def _lx_sync_dimension_website_prices(self):
        for order in self:
            lines = order.order_line.filtered(
                lambda l: not l.display_type
                and l.product_id
                and getattr(l.product_template_id, "is_dimension_product", False)
            )
            changed = False
            for line in lines:
                final_price = float(getattr(line, "lx_final_unit_price", 0.0) or 0.0)
                area = max(float(line.lx_width_m or 1.0), 1.0) * max(float(line.lx_height_m or 1.0), 1.0)
                expected_rate = (final_price / area) if final_price > 0.0 and area > 0.0 else 0.0
                needs_fix = (
                    final_price <= 0.0
                    or float(line.price_unit or 0.0) <= 0.0
                    or float(line.price_subtotal or 0.0) <= 0.0
                    or (expected_rate > 0.0 and abs(float(line.price_unit or 0.0) - expected_rate) > 1e-6)
                )
                if not needs_fix:
                    continue
                if line._lx_sync_dimension_website_price():
                    changed = True
            if changed:
                order.invalidate_recordset(["amount_total", "amount_untaxed", "amount_tax", "amount_delivery"])


# _logger = logging.getLogger(__name__)
# _t = _  # alias anti-collision : on utilise _t(...) partout
# DIM_PRECISION = 2  # how strictly to compare sizes (2 decimals)
# PARAM_USED_PCT = "luxtor.lx_fabric_freeze_used_pct"  # ex: 95
# FREEZE_MSG = _("You can't continue: the related fabric is not enough in stock.")



# class SaleOrder(models.Model):
#     _inherit = 'sale.order'

#     # Computed + stored + readonly priority
#     priority = fields.Selection(
#         [('normal', 'Normal'), ('special', 'Special')],
#         string='Priority',
#         compute='_compute_priority',
#         store=True,
#         readonly=True,
#         default='normal',
#     )

#     priority_quantity = fields.Integer(default=0)
#     priority_price = fields.Float(default=0.0)

#     installation_type = fields.Selection([
#         ('paid', 'Paid'),
#         ('free', 'Free'),
#     ], string='Installation Type', default='paid')

#     installation_quantity = fields.Integer(default=0)
#     installation_price = fields.Float(default=0.0)

#     shipping_method_type = fields.Selection([
#         ('standard', 'Standard'),
#         ('express', 'Express'),
#     ], string='Shipping Method', default='standard')
#     shipping_city_id = fields.Many2one('shipping.rate', string='City/Suburb')
#     shipping_quantity = fields.Integer(string='Shipping Quantity', default=0)
#     shipping_price = fields.Float(string='Shipping Price', default=0.0)

#     partner_phone = fields.Char(
#         related="partner_id.phone",
#         string="Phone",
#         readonly=True,
#         store=True,
#     )


#     delivery_date = fields.Date(
#         string='Delivery Date', compute='_compute_delivery_date', store=True)

#     lx_payment_terms = fields.Selection([
#         ('upfront', '100% Up-front'),
#         ('half_half', '50% Deposit & 50% On delivery'),
#     ], string="Payment Terms")

#     lx_salesperson_id = fields.Many2one(
#         'crm.team.member',
#         string='Salesperson',
#         help='Salesperson responsible for this order.'
#     )

#     check_measure = fields.Selection([
#         ('not_required', 'Not Required'),
#         ('required', 'Required'),
#     ], string='Check Measure', default='not_required')

#     remove_product = fields.Selection([
#         ('no_removal', 'No Removal'),
#         ('removal_disposal', 'Removal & Disposal'),
#     ], string='Remove Product', default='no_removal')

#     split_shipping = fields.Selection([
#         ('not_permitted', 'Not Permitted'),
#         ('permitted', 'Permitted'),
#     ], string='Split Shipping', default='not_permitted')

#     preferences = fields.Text(string='Preferences')
    
#     lx_artisan_id = fields.Many2one(
#         "res.partner",
#         string="Artisan",
#         readonly=True,
#         index=True,
#         help="Artisan à l'origine de cette commande.",
#     )

#     lx_production_state = fields.Selection(
#         [
#             ("not_started", "Not Started"),
#             ("in_works", "In Works"),
#             ("complete", "Complete"),
#         ],
#         string="Production",
#         compute="_compute_lx_production_state",
#         store=True,
#         readonly=True,
#     )

#     @api.depends("name", "state")
#     def _compute_lx_production_state(self):
#         """
#         Rules:
#         - In Works: At least one Manufacturing order related to the order is completed (done).
#         - Complete: When all Manufacturing orders of a single Sales order are completed (done).
#         - Else: Not Started.

#         We compute from mrp.production:
#         - primary link: sale_line_id.order_id = order.id
#         - fallback: origin == order.name
#         """
#         Mrp = self.env["mrp.production"].sudo()

#         # Prefetch by origin for the fallback in batch (avoid N searches)
#         names = [o.name for o in self if o.name]
#         mos_by_origin = {}
#         if names:
#             mos = Mrp.search([("origin", "in", names)])
#             for mo in mos:
#                 mos_by_origin.setdefault(mo.origin, self.env["mrp.production"])
#                 mos_by_origin[mo.origin] |= mo

#         for order in self:
#             # Primary: MOs linked through sale_line_id
#             mos = Mrp.search([("sale_line_id.order_id", "=", order.id)])

#             # Fallback: by origin
#             if not mos and order.name:
#                 mos = mos_by_origin.get(order.name, self.env["mrp.production"])

#             if not mos:
#                 order.lx_production_state = "not_started"
#                 continue

#             total = len(mos)
#             done_count = len(mos.filtered(lambda m: m.state == "done"))

#             if total > 0 and done_count == total:
#                 order.lx_production_state = "complete"
#             elif done_count > 0:
#                 order.lx_production_state = "in_works"
#             else:
#                 order.lx_production_state = "not_started"

#     def action_open_production_monitor_lines(self):
#         self.ensure_one()
#         return {
#             "type": "ir.actions.act_window",
#             "name": _("Production Monitor Lines"),
#             "res_model": "luxtor.production.monitor.line",
#             "view_mode": "list,form",
#             "domain": [("sale_order_id", "=", self.id)],
#             "context": {"default_sale_order_id": self.id},
#             "target": "current",
#         }

    

#     # -------- compute: priority --------
#     @api.depends(
#         'order_line.product_id',           # react when products change
#         'order_line.display_type',         # ignore section/note lines
#     )
#     def _compute_priority(self):
#         """priority = 'special' if any SOL has product default_code == 'PRIORITY_SERVICE' else 'normal'."""
#         for order in self:
#             special = False
#             for line in order.order_line.filtered(lambda l: not l.display_type and l.product_id):
#                 # use internal reference on product.variant (default_code)
#                 if (line.product_id.default_code or '').strip() == 'PRIORITY_SERVICE':
#                     special = True
#                     break
#             order.priority = 'special' if special else 'normal'

#     # -------- helpers --------
#     def _default_validity_date(self):
#         today = fields.Date.context_today(self)
#         return today + relativedelta(days=30)

#     def _add_business_days(self, base_date, days):
#         from datetime import timedelta
#         count = 0
#         current_date = base_date
#         while count < days:
#             current_date += timedelta(days=1)
#             if current_date.weekday() < 5:
#                 count += 1
#         return current_date
    
#     # -------- Wizard Shipping --------
#     def _get_total_weight_kg(self):
#         self.ensure_one()
#         total = 0.0
#         for line in self.order_line:
#             p = line.product_id
#             if not p or line.display_type:
#                 continue
#             # only physical products
#             if p.type in ('product', 'consu'):
#                 # product weight is in Kg by default in Odoo
#                 total += (p.weight or 0.0) * line.product_uom_qty
#         return total

#     # -------- create/write/onchanges --------
#     @api.model_create_multi
#     def create(self, vals_list):
#         for vals in vals_list:
#             if not vals.get('validity_date'):
#                 date_order_val = vals.get('date_order')
#                 if date_order_val:
#                     base_dt = fields.Datetime.from_string(date_order_val)
#                 else:
#                     base_dt = fields.Datetime.context_timestamp(self, datetime.now())
#                 vals['validity_date'] = base_dt.date() + relativedelta(days=30)

#         orders = super().create(vals_list)

#         for order in orders:
#             order._generate_sequence_numbers_for_lines()

#         return orders

#     def write(self, vals):
#         if 'date_order' in vals:
#             try:
#                 base_dt = fields.Datetime.from_string(vals['date_order'])
#                 vals['validity_date'] = base_dt.date() + relativedelta(days=30)
#             except Exception:
#                 pass

#         res = super().write(vals)

#         # keep your existing delivery recompute trigger
#         recalc_delivery = 'priority' in vals or 'date_order' in vals
#         for order in self:
#             if recalc_delivery:
#                 order._compute_delivery_date()
#                 order.invalidate_recordset()
#             if any(not line.sequence_number for line in order.order_line):
#                 order._generate_sequence_numbers_for_lines()
#         return res

#     @api.onchange('date_order')
#     def _onchange_date_order(self):
#         if self.date_order:
#             self.validity_date = self.date_order.date() + relativedelta(days=30)

#     @api.onchange('order_line')
#     def _onchange_generate_sequence_numbers(self):
#         for order in self:
#             order._generate_sequence_numbers_for_lines()

#     def _generate_sequence_numbers_for_lines(self):
#         for order in self:
#             seq = 1
#             for line in order.order_line.sorted('sequence'):
#                 if line.product_template_id and line.product_template_id.type in ['consu', 'combo']:
#                     line.sequence_number = str(seq)
#                     seq += 1
#                 elif (line.product_template_id or line.is_priority_line or
#                       line.is_installation_line or line.is_shipping_line):
#                     line.sequence_number = '#'

#     # Include order_line.product_id so delivery recomputes immediately when a priority line is added/removed
#     @api.depends('date_order', 'priority', 'state', 'order_line.product_id', 'order_line.display_type')
#     def _compute_delivery_date(self):
#         for order in self:
#             try:
#                 if not order.date_order:
#                     order.delivery_date = False
#                     continue

#                 base_dt = fields.Datetime.context_timestamp(order, order.date_order)

#                 # keep your “if special then else then” logic as-is
#                 if order.priority == 'special':
#                     order.delivery_date = (
#                         base_dt.date()
#                         if base_dt.time() < time(12, 0)
#                         else base_dt.date() + relativedelta(days=1)
#                     )
#                 else:
#                     order.delivery_date = order._add_business_days(base_dt.date(), 5)

#             except Exception as e:
#                 _logger.exception("Error computing delivery date for order %s: %s", order.name, e)

#     # -------- MRP helpers --------
#     def _is_mrp_blind_line(self, line):
#         if line.is_priority_line or line.is_installation_line:
#             return False
#         product = line.product_id
#         if not product:
#             return False
#         return bool(product.product_tmpl_id.bom_ids)

#     def _get_mrp_blinds_quantity(self):
#         qty = 0
#         for line in self.order_line:
#             if self._is_mrp_blind_line(line):
#                 qty += line.product_uom_qty
#         return qty


#     def action_open_shipping_wizard(self):
#         self.ensure_one()
#         return {
#             'name': _('Add a Shipping Method'),
#             'type': 'ir.actions.act_window',
#             'res_model': 'sale.order.shipping.wizard',
#             'view_mode': 'form',
#             'target': 'new',
#             'context': {'active_id': self.id, 'default_order_id': self.id},
#         }
    
    
#     def _lx_find_bom(self, product, company=None, *args, **kwargs):
#         self.ensure_one()
#         company = company or self.company_id

#         Bom = self.env['mrp.bom']
#         bom = Bom.search([
#             ('product_id', '=', product.id),
#             ('company_id', 'in', [company.id, False]),
#             ('type', '=', 'normal'),
#         ], limit=1, order='sequence,id')

#         if not bom:
#             bom = Bom.search([
#                 ('product_tmpl_id', '=', product.product_tmpl_id.id),
#                 ('company_id', 'in', [company.id, False]),
#                 ('type', '=', 'normal'),
#             ], limit=1, order='sequence,id')

#         return bom




#     # --------  Website waiting for code --------

#     def _cart_find_product_line(self, product_id=None, line_id=None, **kwargs):
#         """Only merge when variant AND (width,height) match."""
#         lines = super()._cart_find_product_line(product_id=product_id, line_id=line_id, **kwargs)
#         if not lines:
#             return lines

#         w = kwargs.get("lx_width_m")
#         h = kwargs.get("lx_height_m")
#         if w is None and h is None:
#             return lines

#         def _to_float(x):
#             try:
#                 return float(str(x).replace(",", "."))
#             except Exception:
#                 return None

#         w = _to_float(w)
#         h = _to_float(h)

#         def _same(a, b):
#             # both must be set and equal within precision
#             if a is None or b is None:
#                 return False
#             return float_compare(float(a), float(b), precision_digits=DIM_PRECISION) == 0

#         return lines.filtered(
#             lambda l: (w is None or _same(l.lx_width_m, w)) and
#                       (h is None or _same(l.lx_height_m, h))
#         )

#     def _cart_update(self, *args, **kwargs):
#         # 1) Let core (and any other customizations) do their work first.
#         res = super()._cart_update(*args, **kwargs)
#         line_id = res.get("line_id")
#         if not line_id:
#             return res

#         line = self.env["sale.order.line"].sudo().browse(line_id)

#         # 2) Read incoming extras safely (keep your override path)
#         def _f(x):
#             if x is None:
#                 return None
#             try:
#                 return float(str(x).replace(",", "."))
#             except Exception:
#                 return None

#         w_in = _f(kwargs.get("lx_width_m"))
#         h_in = _f(kwargs.get("lx_height_m"))
#         pu_in = _f(kwargs.get("lx_final_unit_price") or kwargs.get("lx_price_override"))

#         # Use the newly provided dim if >0, otherwise fall back to existing line values (do not erase).
#         w = (w_in if (w_in is not None and w_in > 0) else (line.lx_width_m or None))
#         h = (h_in if (h_in is not None and h_in > 0) else (line.lx_height_m or None))

#         # 3) Persist fields only when supplied; clamp to 1.0 minimal positive for dimensional products
#         vals = {}
#         if w_in is not None:
#             vals["lx_width_m"] = w if (w and w > 0) else 1.0
#         if h_in is not None:
#             vals["lx_height_m"] = h if (h and h > 0) else 1.0
#         if pu_in is not None and pu_in > 0:
#             # We'll possibly normalize below for dimensional products before writing.
#             pass

#         if vals:
#             line.write(vals)
#             # refresh local w/h from line in case we clamped
#             w = line.lx_width_m or w
#             h = line.lx_height_m or h

#         # 4) Compute safe area and price unit
#         # Never multiply None: fallback to 1.0 so non-dimensional products keep pu as-is.
#         W = (w or 1.0)
#         H = (h or 1.0)
#         area = W * H  # always valid float now

#         if pu_in is not None and pu_in > 0:
#             price_unit = pu_in
#             # Only divide by area when the product is flagged as dimensional
#             if getattr(line.product_id, "is_dimension_product", False):
#                 # Prevent divide by zero (after fallback this can't be 0, but guard anyway)
#                 price_unit = pu_in / (area if area > 0 else 1.0)

#             line.sudo().write({
#                 "price_unit": price_unit,
#             })

#         # 5) Line title with dimensions — only if product is dimensional
#         if getattr(line.product_id, "is_dimension_product", False) and ((w is not None) or (h is not None)):
#             base = line.product_id.get_product_multiline_description_sale() or line.product_id.display_name
#             dims = f" ({(line.lx_width_m or 0):g} m × {(line.lx_height_m or 0):g} m)"
#             variants = line._get_sale_order_line_multiline_description_variants()
#             title = f"{base}{dims}"
#             line.name = title + (f"\n{variants}" if variants else "")
#             res.setdefault("notification_info", {})["name_short"] = title
#         else:
#             # Keep the default name (don't append dims)
#             res.setdefault("notification_info", {})["name_short"] = line.product_id.display_name

#         # 6) Keep the mini-popup price consistent with the line
#         res.setdefault("notification_info", {})["price"] = line.price_unit

#         return res
    
#     def _lx_get_used_threshold_pct(self):
#         icp = self.env["ir.config_parameter"].sudo()
#         val = icp.get_param(PARAM_USED_PCT, default="95")
#         try:
#             pct = float(val)
#         except Exception:
#             pct = 95.0
#         return max(0.0, min(100.0, pct))

#     def _lx_as_fabric_product(self, fabric_ref):
#         if not fabric_ref:
#             return self.env["product.product"]
#         if fabric_ref._name == "product.product":
#             return fabric_ref
#         if fabric_ref._name == "product.template":
#             return fabric_ref.product_variant_id
#         return getattr(fabric_ref, "product_variant_id", self.env["product.product"])

#     def _lx_fabric_remaining_pct(self, order, fabric_prod):
#         fabric_prod = fabric_prod.sudo()

#         ctx = dict(self.env.context)
#         if order.warehouse_id:
#             ctx["warehouse"] = order.warehouse_id.id
#         fp = fabric_prod.with_context(ctx)

#         try:
#             free_qty = float(fp.free_qty)
#         except Exception:
#             free_qty = 0.0

#         try:
#             base_qty = float(fp.virtual_available)
#         except Exception:
#             base_qty = 0.0

#         base_qty = max(base_qty, 1.0)
#         remaining_pct = (free_qty / base_qty) * 100.0
#         return max(0.0, min(100.0, remaining_pct))

#     def _lx_check_fabric_freeze_or_raise(self):
#         threshold_used = self._lx_get_used_threshold_pct()

#         for order in self:
#             # Only block while editing quotation (before confirm)
#             if order.state not in ("draft", "sent"):
#                 continue

#             offenders = []
#             for line in order.order_line:
#                 if line.display_type or not line.product_id:
#                     continue

#                 pt = line.product_id.product_tmpl_id
#                 fabric_ref = getattr(pt, "lx_fabric_ref_id", False)
#                 if not fabric_ref:
#                     continue  # only products having related fabric

#                 fabric_prod = order._lx_as_fabric_product(fabric_ref)
#                 if not fabric_prod or not fabric_prod.exists():
#                     offenders.append((line, 0.0, _("Related fabric not found.")))
#                     continue

#                 remaining_pct = order._lx_fabric_remaining_pct(order, fabric_prod)
#                 used_pct = 100.0 - remaining_pct

#                 if used_pct >= threshold_used:
#                     offenders.append((line, remaining_pct, fabric_prod.display_name))

#             if offenders:
#                 lines_txt = []
#                 for sol, rem, fabric_name in offenders:
#                     lines_txt.append(
#                         _("- %s (Fabric: %s, Remaining: %s%%)")
#                         % (sol.product_id.display_name, fabric_name, ("%.2f" % rem))
#                     )

#                 raise ValidationError(
#                     FREEZE_MSG + "\n\n" + _("Blocked lines:") + "\n" + "\n".join(lines_txt)
#                 )

#     @api.constrains(
#         "state",
#         "warehouse_id",
#         "order_line",
#         "order_line.product_id",
#         "order_line.product_uom_qty",
#     )
#     def _constrains_lx_fabric_stock_before_save(self):
#         self._lx_check_fabric_freeze_or_raise()

#     # --------  confirm action --------
    
#     def action_confirm(self):
#         # keep default flow
#         res = super().action_confirm()

#         import math  # ensure available

#         Mrp = self.env['mrp.production']
#         mrp_fields = Mrp._fields
#         Loc = self.env['luxtor.location']
#         other_loc = Loc.search([('name', '=', 'Other')], limit=1) or Loc.create({'name': 'Other'})

#         def _is_electric(sol):
#             return bool(sol.product_id and sol.product_id.lx_is_electric_variant())

#         def _is_motor_only(sol):
#             return bool(sol.product_id and sol.product_id.lx_is_motor_only_variant())

#         def _get_accessories(order):
#             motor_remote, motor_smart, remote, charger, zigbee = order._lx_get_accessory_products()
#             icp = order.env['ir.config_parameter'].sudo()
#             r_ratio = max(1, int(icp.get_param('luxtor.remote_ratio', 5)))
#             c_ratio = max(1, int(icp.get_param('luxtor.charger_ratio', 15)))
#             z_ratio = max(1, int(icp.get_param('luxtor.zigbee_ratio', 30)))
#             return motor_remote, motor_smart, remote, charger, zigbee, r_ratio, c_ratio, z_ratio


#         def _ensure_move_qty(mo, product, qty, prefix="⤶ "):
#             """
#             Set (or create) a raw move for 'product' with 'qty'.
#             If qty==0, remove the move if present.
#             """
#             if not product:
#                 return
#             move = mo.move_raw_ids.filtered(lambda m: m.product_id.id == product.id)[:1]
#             if qty and qty > 0:
#                 name = f"{prefix}{product.display_name}"
#                 if move:
#                     move.write({'product_uom_qty': float(qty), 'name': name})
#                 else:
#                     # locations are required on moves
#                     vals = {
#                         'name': name,
#                         'product_id': product.id,
#                         'product_uom': product.uom_id.id,
#                         'product_uom_qty': float(qty),
#                         'location_id': mo.location_src_id.id,
#                         'location_dest_id': mo.location_dest_id.id,
#                     }
#                     mo.write({'move_raw_ids': [(0, 0, vals)]})
#             else:
#                 if move:
#                     move.unlink()

#         for order in self:
#             motor_remote, motor_smart, remote, charger, zigbee, r_ratio, c_ratio, z_ratio = _get_accessories(order)


#             # ---- compute totals for accessories (exclude Motor only) ----
#             motors_total = 0
#             non_motor_only_total = 0
#             for sol in order.order_line:
#                 if sol.display_type or not sol.product_id:
#                     continue
#                 if _is_electric(sol):
#                     q = int(sol.product_uom_qty or 0)
#                     motors_total += q
#                     if not _is_motor_only(sol):
#                         non_motor_only_total += q

#             remote_needed  = int(math.ceil(non_motor_only_total / r_ratio)) if non_motor_only_total > 0 else 0
#             charger_needed = int(math.ceil(non_motor_only_total / c_ratio)) if non_motor_only_total > 0 else 0

#             accessories_allocated = False  # allocate remotes/chargers once

#             for sol in order.order_line:
#                 if sol.product_id.type not in ('product', 'consu'):
#                     continue
#                 qty = int(sol.product_uom_qty or 0)
#                 if qty <= 0:
#                     continue

#                 bom = order._lx_find_bom(sol.product_id)
#                 if not bom:
#                     continue

#                 w_m = getattr(sol, 'lx_width_m', 0.0) or 0.0
#                 h_m = getattr(sol, 'lx_height_m', 0.0) or 0.0

#                 for unit_idx in range(qty):
#                     uom = sol.product_uom_id or sol.product_id.uom_id

#                     mo_vals = {
#                         'company_id': order.company_id.id,
#                         'product_id': sol.product_id.id,
#                         'product_uom_id': uom.id,
#                         'product_qty': 1.0,
#                         'bom_id': bom.id,
#                         'origin': order.name,
#                         'sale_line_id': sol.id,
#                     }
#                     if 'luxtor_location_id' in mrp_fields:
#                         mo_vals['luxtor_location_id'] = other_loc.id
#                     if 'lx_width_m' in mrp_fields:
#                         mo_vals['lx_width_m'] = w_m
#                     if 'lx_height_m' in mrp_fields:
#                         mo_vals['lx_height_m'] = h_m

#                     mo = Mrp.create(mo_vals)  # leave in draft; components visible in tab

#                     if _is_electric(sol):
#                         # Always ensure 1 motor component (if BoM already has it, this will just set qty=1)
#                         _ensure_move_qty(mo, motor_remote, 1)

#                         if (not accessories_allocated) and (not _is_motor_only(sol)):
#                             # First electric MO that isn't 'Motor only' gets ALL remotes/chargers
#                             if remote_needed > 0:
#                                 _ensure_move_qty(mo, remote, remote_needed)
#                             else:
#                                 _ensure_move_qty(mo, remote, 0)
#                             if charger_needed > 0:
#                                 _ensure_move_qty(mo, charger, charger_needed)
#                             else:
#                                 _ensure_move_qty(mo, charger, 0)
#                             accessories_allocated = True
#                         else:
#                             # All subsequent electric MOs (or motor-only): no remote/charger
#                             _ensure_move_qty(mo, remote, 0)
#                             _ensure_move_qty(mo, charger, 0)

#                     # (Optionally confirm here)
#                     # mo.action_confirm()

#             # -- email block unchanged --
#             template = self.env.ref(
#                 "luxtor_custom.mail_template_sale_order_customer_confirm",
#                 raise_if_not_found=False,
#             )
#             if template:
#                 order._portal_ensure_token()
#                 order.with_context(force_send=True).message_post_with_source(
#                     template,
#                     email_layout_xmlid='mail.mail_notification_layout_with_responsible_signature',
#                     subtype_xmlid='mail.mt_comment',
#                 )

#         return res


#     def _prepare_order_line_values(self, product_id, quantity, **kwargs):
#         """
#         In Odoo 19, the configurator uses record._update() (OWL form layer),
#         NOT a JSON-RPC route. lx_width_m / lx_height_m arrive here via
#         SaleOrderLineProductField patched to call record._update({lx_width_m, lx_height_m})
#         after applyProduct, which triggers onchange → _onchange_dims_validate_and_reprice.
        
#         This method is kept for compatibility with any other callers (e.g. website cart).
#         We only write when values are real positives to avoid spurious recomputation.
#         """
#         vals = super()._prepare_order_line_values(product_id, quantity, **kwargs)
#         w = kwargs.get("lx_width_m")
#         h = kwargs.get("lx_height_m")
#         if w:
#             try:
#                 vals["lx_width_m"] = float(w)
#             except (TypeError, ValueError):
#                 pass
#         if h:
#             try:
#                 vals["lx_height_m"] = float(h)
#             except (TypeError, ValueError):
#                 pass
#         return vals
