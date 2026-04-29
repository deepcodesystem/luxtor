# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError

class LxValidateCodeWizard(models.TransientModel):
    _name = "lx.validate.code.wizard"
    _description = "Validate High-Value Order Code"

    code = fields.Char(string="Enter the code", required=True)

    def action_confirm(self):
        order = self.env['sale.order'].browse(self._context.get('active_id'))
        if not order:
            raise UserError(_("No sale order in context."))
        order.action_validate_verification_code(self.code)
        return {'type': 'ir.actions.act_window_close'}
