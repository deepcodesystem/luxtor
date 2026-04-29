# -*- coding: utf-8 -*-
from odoo import models

# NOTE: V19 checkout steps are website.checkout.step records (model-based),
# not Python list-of-tuples overrides as in V18.
#
# The Services step is registered via data/lx_checkout_steps.xml as a generic
# (website_id=False) record with sequence=125, step_href=/shop/service.
# Odoo's _create_checkout_steps() copies it per-website when a new website is created.
#
# For EXISTING websites already created before this module was installed, we use
# the post_init_hook defined below to copy the step.

class Website(models.Model):
    _inherit = "website"

    def _lx_ensure_services_step(self):
        """
        Ensure the /shop/service checkout step exists for every website.
        Also renames the built-in V19 steps to match our UX breadcrumb:
          /shop/cart     "Review Order" → "Order"
          /shop/checkout "Delivery"     → "Address"
        Called by post_init_hook (install) and by XML data (upgrade, noupdate=0).
        Safe to call on an empty recordset — searches all websites internally.
        """
        websites = self if self else self.sudo().search([])
        Step = self.env['website.checkout.step'].sudo()
        for website in websites:
            # 1. Create Services step if missing
            existing = Step.search([
                ('website_id', '=', website.id),
                ('step_href', '=', '/shop/service'),
            ], limit=1)
            if not existing:
                Step.create({
                    'name': 'Services',
                    'sequence': 125,
                    'step_href': '/shop/service',
                    'main_button_label': 'Continue',
                    'back_button_label': 'Back to services',
                    'website_id': website.id,
                    'is_published': True,
                })

            # 2. Rename built-in steps to match our breadcrumb labels
            _RENAMES = {
                '/shop/cart':     'Order',
                '/shop/checkout': 'Address',
            }
            for href, new_name in _RENAMES.items():
                steps = Step.search([
                    '|',
                    ('website_id', '=', website.id),
                    ('website_id', '=', False),
                    ('step_href', '=', href),
                ])
                for step in steps:
                    if step.name != new_name:
                        step.write({'name': new_name})
