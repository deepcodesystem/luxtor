# -*- coding: utf-8 -*-
import math
import logging
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

VIRTUAL_WIDTH_M = 1.00
WEBSITE_FACTOR = 1.0  # fallback if no ICP is set


class ProductProduct(models.Model):
    _inherit = "product.product"

    lx_location_id = fields.Many2one("luxtor.installation.space", string="Location")
    lx_color_ids = fields.Many2many(related="product_tmpl_id.lx_color_ids", readonly=False)
    lx_is_new_in = fields.Boolean(related="product_tmpl_id.lx_is_new_in", store=True, readonly=False)
    lx_is_weekly_deal = fields.Boolean(related="product_tmpl_id.lx_is_weekly_deal", store=True, readonly=False)
    lx_is_bestseller = fields.Boolean(related="product_tmpl_id.lx_is_bestseller", store=True, readonly=False)
    lx_is_trending = fields.Boolean(related="product_tmpl_id.lx_is_trending", store=True, readonly=False)
    lx_is_sale = fields.Boolean(related="product_tmpl_id.lx_is_sale", store=True, readonly=False)  # NEW

    # ---------------------------------------------------------------------
    # TAG SYNC (UPDATED: includes lx_is_sale)
    # ---------------------------------------------------------------------
    def _lx_tag_names_map(self):
        return {
            "lx_is_new_in": "New IN",
            "lx_is_weekly_deal": "weekly",
            "lx_is_bestseller": "Bestseller",
            "lx_is_trending": "Trending",
            "lx_is_sale": "Sale",  # NEW
        }

    def _lx_get_tag_field_target(self):
        """
        Prefer product.product.product_tag_ids if present,
        else fallback to product.template.product_tag_ids.
        """
        self.ensure_one()
        if "product_tag_ids" in self._fields:
            return self, "product_tag_ids"
        return self.product_tmpl_id, "product_tag_ids"

    def _lx_get_or_create_tag(self, name):
        Tag = self.env["product.tag"].sudo()
        tag = Tag.search([("name", "=", name)], limit=1)
        return tag or Tag.create({"name": name})

    def _lx_sync_one_toggle(self, field_name, enabled):
        self.ensure_one()
        tag_name = self._lx_tag_names_map().get(field_name)
        if not tag_name:
            return

        target_rec, m2m_field = self._lx_get_tag_field_target()
        current_ids = set(target_rec[m2m_field].ids)

        tag = self.env["product.tag"].sudo().search([("name", "=", tag_name)], limit=1)

        if enabled:
            if not tag:
                tag = self._lx_get_or_create_tag(tag_name)
            if tag.id not in current_ids:
                target_rec.sudo().write({m2m_field: [(4, tag.id)]})
        else:
            if tag and tag.id in current_ids:
                target_rec.sudo().write({m2m_field: [(3, tag.id)]})

    def _lx_sync_all_toggles(self):
        for product in self:
            for field_name in product._lx_tag_names_map().keys():
                product._lx_sync_one_toggle(field_name, bool(product[field_name]))

    @api.onchange("lx_is_new_in", "lx_is_weekly_deal", "lx_is_bestseller", "lx_is_trending", "lx_is_sale")
    def _onchange_lx_sync_tags(self):
        for product in self:
            product._lx_sync_all_toggles()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._lx_sync_all_toggles()
        return records

    def write(self, vals):
        res = super().write(vals)
        watched = set(self._lx_tag_names_map().keys())
        if watched.intersection(vals.keys()):
            self._lx_sync_all_toggles()
        return res


    # Reuse your factor reader
    def _lx_get_browser_factor(self):
        try:
            raw = self.env['ir.config_parameter'].sudo().get_param(
                'luxtor.lx_browser_factor_pct', default='100'
            )
            return float(raw or 100.0) / 100.0
        except Exception:
            return WEBSITE_FACTOR

    def _lx_virtual_total_for_width_with_bom(self, bom, width_m=VIRTUAL_WIDTH_M):
        """
        Force simulation with a specific BoM (no BoM discovery).
        Returns the 'amount' (margin part), not lst_price.
        """
        self.ensure_one()
        Mrp = self.env['mrp.production']
        mo = Mrp.new({
            'company_id': self.env.company.id,
            'product_id': self.id,
            'bom_id': bom.id,
            'lx_width_m': width_m,
        })
        # Prefer your manual-control-aware method if present, else fallback to _lx_virtual_calculate
        calc = getattr(mo, '_lx_virtual_calculate_manual_chain_control', None) or getattr(mo, '_lx_virtual_calculate')
        try:
            _cost, amount = calc(width_m=width_m)
            return float(amount or 0.0)
        except Exception:
            _logger.exception("Virtual calculation failed for %s with BoM %s", self.display_name, bom.display_name)
            return 0.0

    def _lx_has_manual_chain_control(self):
        """
        True iff variant has attribute:
          attribute_id.name == 'Control Type'
          value == 'Manual, Chain Controlled'
        """
        self.ensure_one()
        for ptav in self.product_template_attribute_value_ids:
            attr = ((ptav.attribute_id and ptav.attribute_id.name) or '').strip().lower()
            val = ((ptav.product_attribute_value_id and ptav.product_attribute_value_id.name) or '').strip().lower()
            if attr == 'control type' and val == 'manual, chain controlled':
                return True
        return False
    



class ProductTemplate(models.Model):
    _inherit = "product.template"

    waste_ids = fields.One2many(
            'luxtor.waste',
            'product_id',
            string="Waste / Remnants",
        )
    waste_processed = fields.Boolean(
        string="Waste Processed",
        help="Tick when all remnant / scrap decisions are done."
    )

    def action_view_waste(self):
        """Smart button: open waste lines for this MO."""
        self.ensure_one()
        action = self.env.ref("luxtor_custom.action_luxtor_waste").read()[0]
        action["domain"] = [("production_id", "=", self.id)]
        action["context"] = dict(self.env.context, default_production_id=self.id)
        return action

    # ---- Helpers ----
    def _lx_get_browser_factor(self):
        try:
            raw = self.env['ir.config_parameter'].sudo().get_param(
                'luxtor.lx_browser_factor_pct', default='100'
            )
            return float(raw or 100.0) / 100.0
        except Exception:
            return WEBSITE_FACTOR

    def _lx_candidate_boms(self):
        """
        All normal BoMs of this template (includes variant-specific and generic BoMs).
        Current company or global.
        """
        self.ensure_one()
        Bom = self.env['mrp.bom']
        return Bom.search([
            ('product_tmpl_id', '=', self.id),
            ('type', '=', 'normal'),
            ('company_id', 'in', [self.env.company.id, False]),
        ], order='sequence,id')

    def _lx_pick_variant_for_bom(self, bom):
        """
        NEW: pick only variants with Control Type == 'Manual, Chain controlled'.

        Logic:
        - If BoM is variant-specific (bom.product_id):
            - Use it only if it is manual-chain; otherwise return False (skip this BoM).
        - Else (generic/template BoM):
            - From this template's variants, choose the first manual-chain variant.
            - If none found, return False (skip this BoM).
        """
        self.ensure_one()
        Product = self.env['product.product']
        if bom.product_id:
            return bom.product_id if bom.product_id._lx_has_manual_chain_control() else False
        # Filter within this template's variants
        manual_chain_variants = self.product_variant_ids.filtered(lambda p: p._lx_has_manual_chain_control())
        return manual_chain_variants[:1] if manual_chain_variants else False

    def _lx_compute_lowest_manual_bom_price_data(self):
        """
        Compute the same initial "From" price used on the website:
        width=1.00m, manual-chain variants only, browser factor applied with ceil.
        """
        self.ensure_one()

        factor = float(self._lx_get_browser_factor() or 1.0)
        skipped_no_manual = 0
        results = []

        for bom in self._lx_candidate_boms():
            variant = self._lx_pick_variant_for_bom(bom)
            if not variant:
                skipped_no_manual += 1
                _logger.info("Skipped BoM %s: no manual-chain variant available", bom.display_name)
                continue

            try:
                base_amount = float(
                    variant._lx_virtual_total_for_width_with_bom(
                        bom, width_m=VIRTUAL_WIDTH_M
                    ) or 0.0
                )
            except Exception:
                _logger.exception("Simulation failed for BoM %s (variant %s)", bom.display_name, variant.display_name)
                base_amount = 0.0

            if base_amount <= 0.0:
                continue

            final_price = float(math.ceil(base_amount * factor))
            if final_price <= 0.0:
                continue

            results.append({
                "bom": bom,
                "variant": variant,
                "base_amount": base_amount,
                "final_price": final_price,
            })

        results.sort(key=lambda item: (
            item["final_price"],
            item["base_amount"],
            item["bom"].sequence,
            item["bom"].id,
        ))

        return {
            "factor": factor,
            "results": results,
            "chosen": results[0] if results else False,
            "skipped_no_manual": skipped_no_manual,
        }

    def _lx_sync_lowest_manual_bom_price(self):
        """
        Keep template list_price aligned with the cheapest valid manual-chain BoM.
        This prevents 0 DH on website initial render while preserving live recalculation.
        """
        for template in self:
            if template.env.context.get("lx_skip_auto_bom_price_sync"):
                continue

            data = template._lx_compute_lowest_manual_bom_price_data()
            chosen = data.get("chosen")
            if not chosen:
                continue

            target_price = float(chosen["final_price"] or 0.0)
            if target_price <= 0.0:
                continue

            current_price = float(template.list_price or 0.0)
            if math.isclose(current_price, target_price, rel_tol=0.0, abs_tol=0.0001):
                continue

            template.with_context(
                lx_skip_auto_bom_price_sync=True,
                tracking_disable=True,
                mail_notrack=True,
            ).sudo().write({
                "list_price": target_price,
            })

    @api.model_create_multi
    def create(self, vals_list):
        templates = super().create(vals_list)
        templates._lx_sync_lowest_manual_bom_price()
        return templates

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get("lx_skip_auto_bom_price_sync"):
            return res

        if set(vals.keys()) == {"list_price"}:
            return res

        self._lx_sync_lowest_manual_bom_price()
        return res

    def action_fetch_prices_from_boms(self):
        """
        On-click (Product Template form):
        - Only consider manual-chain variants (via _lx_pick_variant_for_bom).
        - For each BoM: simulate base amount at width=1.00m with that variant.
        - Apply browser factor; pick the lowest final price.
        - Write the chosen final price to this template's list_price.
        - Show a detailed debug notification.
        """
        self.ensure_one()

        # Helpers (no i18n, plain strings)
        TITLE = "Fetch Price (BoMs)"

        def notify(message, level="success", sticky=False, next_action=None):
            action = {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": TITLE,
                    "message": message,
                    "sticky": sticky,
                    "type": level,
                },
            }
            if next_action:
                action["params"]["next"] = next_action
            return action

        # Gather candidate BoMs
        boms = self._lx_candidate_boms()
        if not boms:
            return notify("No normal BoMs found on this product template.", level="warning")

        data = self._lx_compute_lowest_manual_bom_price_data()
        factor = data["factor"]
        results = data["results"]
        skipped_no_manual = data["skipped_no_manual"]

        if not results:
            msg = "No simulated prices. Either no manual-chain variants matched, or calculations returned 0."
            if skipped_no_manual:
                msg += f" Skipped due to Control Type filter: {skipped_no_manual} BoM(s)."
            return notify(msg, level="warning")

        chosen = data["chosen"]
        bom_w = chosen["bom"]
        var_w = chosen["variant"]
        base_w = chosen["base_amount"]
        final_w = chosen["final_price"]

        why = ""
        if len(results) > 1:
            base_r = results[1]["base_amount"]
            final_r = results[1]["final_price"]
            if final_w < final_r:
                if base_w < base_r:
                    why = f"Lower because base amount is smaller ({base_w:.2f} vs {base_r:.2f})."
                else:
                    why = "Lower after rounding (same factor, close base amounts)."
            else:
                why = "Tie-break on base/sequence."

        # WRITE the fetched price on the template's sale price
        try:
            self.with_context(
                skip_onchange=True,
                lx_skip_auto_bom_price_sync=True,
                tracking_disable=True,
                mail_notrack=True,
            ).sudo().write({"list_price": float(final_w)})
            write_note = "(Written to template sale price)"
        except Exception:
            _logger.exception("Failed to write list_price on template %s", self.display_name)
            write_note = "(Failed to write sale price — see logs)"

        # Compose debug lines (up to 4)
        lines = []
        for idx, item in enumerate(results[:4], start=1):
            bom = item["bom"]
            var = item["variant"]
            base = item["base_amount"]
            final = item["final_price"]
            bom_label = bom.display_name or bom.code or str(bom.id)
            var_label = var.display_name or getattr(var, "name", "Variant")
            lines.append(
                f"#{idx} BoM={bom_label} | Variant={var_label} | Base={base:.2f} | Factor={factor:.2f} | Final={final:.2f}"
            )

        header = (
            f"Lowest price selected: {final_w:.2f} "
            f"(BoM={bom_w.display_name or bom_w.code or bom_w.id}, "
            f"Variant={var_w.display_name}) {write_note}"
        )
        reason = f"Reason: {why or 'Lower final price with current factor.'}"
        if skipped_no_manual:
            reason += f" | Skipped non-manual-chain BoMs: {skipped_no_manual}"

        message = f"{header}\n{reason}\n\n" + "\n".join(lines)
        _logger.info("Template %s | %s", self.display_name, message)

        return notify(
            message,
            level="success",
            next_action={
                "type": "ir.actions.client",
                "tag": "reload",
            },
        )

class LuxtorInstallationSpace(models.Model):
    _name = "luxtor.installation.space"
    _description = "Installation Space (Client Usage)"
    _order = "name"

    name = fields.Char(
        string="Installation Space",
        required=True,
        index=True,
    )

    active = fields.Boolean(default=True)

class LxProductColor(models.Model):
    _name = "lx.product.color"
    _description = "Website Filter Color"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    color_hex = fields.Char(string="Hex", help="Example: #111827")

