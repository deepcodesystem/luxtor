# -*- coding: utf-8 -*-
import math
import logging
from odoo import api, fields, models
from odoo.tools.translate import _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# ── Constantes chaînes plastiques ──────────────────────────────────────────────
PLASTIC_CHAIN_150_CODE = "BFPC-150"
PLASTIC_CHAIN_200_CODE = "BFPC-200"


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    # ── Dimensions ────────────────────────────────────────────────────────────
    lx_width_m = fields.Float(string="Width (m)", digits=(16, 4))
    lx_height_m = fields.Float(string="Height (m)", digits=(16, 4))

    lx_orientation = fields.Selection(
        [('widthwise', 'Widthwise'), ('heightwise', 'Heightwise')],
        string="Fabric Orientation",
        default='widthwise',
    )
    lx_roll_width_best = fields.Float(string="Selected Roll Width (m)", digits=(16, 4))

    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', readonly=True,
    )
    lx_total_cost_price = fields.Monetary(
        string="Total Cost Price",
        compute='_compute_lx_totals',
        store=True,
        currency_field='currency_id',
    )
    lx_total_amount = fields.Monetary(
        string="Total Amount",
        compute='_compute_lx_totals',
        store=True,
        currency_field='currency_id',
    )

    # ── Totaux ────────────────────────────────────────────────────────────────

    @api.depends('move_raw_ids.lx_cost_price', 'move_raw_ids.lx_amount')
    def _compute_lx_totals(self):
        for mo in self:
            mo.lx_total_cost_price = sum(float(m.lx_cost_price or 0.0) for m in mo.move_raw_ids)
            mo.lx_total_amount = sum(float(m.lx_amount or 0.0) for m in mo.move_raw_ids)

    # ── Contrainte ────────────────────────────────────────────────────────────

    @api.constrains('product_qty')
    def _check_qty_is_one(self):
        for mo in self:
            if mo.product_qty != 1:
                raise ValidationError(_("Manufacturing quantity must be exactly 1."))

    # =========================================================================
    # HELPERS TISSU
    # =========================================================================

    def _lx_get_fabric_template(self):
        self.ensure_one()
        tmpl = self.product_id.product_tmpl_id
        return tmpl.lx_fabric_ref_id or tmpl

    def _lx_get_Q_factor(self):
        """Q = 2 si le tissu est Day & Night (flag lx_is_day_night), sinon 1."""
        self.ensure_one()
        fabric = self._lx_get_fabric_template()
        return 2.0 if getattr(fabric, 'lx_is_day_night', False) else 1.0

    def _lx_get_fabric_allowance_m(self):
        """fabric_allowance du template tissu (cm → m), fallback ICP."""
        self.ensure_one()
        Param = self.env['ir.config_parameter'].sudo()
        fabric = self._lx_get_fabric_template()
        cm = float(getattr(fabric, 'fabric_allowance', 0.0) or 0.0)
        if not cm:
            cm = float(Param.get_param('luxtor.fabric_allowance_cm', '20') or 20.0)
        return cm / 100.0

    def _lx_get_all_roll_widths(self):
        """Largeurs des rouleaux (m) depuis les tags roller_width_ids du template tissu."""
        self.ensure_one()
        fabric = self._lx_get_fabric_template()
        widths = []
        tags = getattr(fabric, 'roller_width_ids', False)
        if tags:
            for t in tags:
                v = float(getattr(t, 'value_cm', 0.0) or 0.0)
                if v > 0:
                    widths.append(v / 100.0)
        else:
            w_cm = float(getattr(fabric, 'width_cm', 0.0) or 0.0)
            if w_cm > 0:
                widths.append(w_cm / 100.0)
        return sorted(set(widths))

    # =========================================================================
    # MOTEUR ORIENTATION
    # =========================================================================

    def _lx_pick_orientation_and_roll(self):
        """
        Retourne (W_rem, H_rem, roll_width_best, orientation_best) ou False.

        Formules :
          widthwise  → WASTE = roll_width - W - 0.03
          heightwise → WASTE = roll_width - 0.06 - H - A
        On garde le WASTE > 0 minimal.
        """
        self.ensure_one()
        if not self.lx_width_m or not self.lx_height_m:
            return False

        W = float(self.lx_width_m)
        H = float(self.lx_height_m)
        A = self._lx_get_fabric_allowance_m()
        Q = self._lx_get_Q_factor()

        widths = self._lx_get_all_roll_widths()
        if not widths:
            return False

        fabric = self._lx_get_fabric_template()
        tmpl_orientation = getattr(fabric, 'orientation', 'widthwise') or 'widthwise'
        if tmpl_orientation == 'width_heightwise':
            candidates = ['widthwise', 'heightwise']
        elif tmpl_orientation == 'heightwise':
            candidates = ['heightwise']
        else:
            candidates = ['widthwise']

        best_waste = None
        best_data = None

        for roll in widths:
            for orient in candidates:
                if orient == 'heightwise':
                    waste = roll - 0.06 - H - A
                    W_rem = waste
                    H_rem = max(W - 0.03, 0.0)
                else:
                    waste = roll - W - 0.03
                    W_rem = waste
                    H_rem = max(Q * H + A, 0.0)

                if waste <= 0.0:
                    continue
                if best_waste is None or waste < best_waste:
                    best_waste = waste
                    best_data = (W_rem, H_rem, roll, orient)

        return best_data or False

    def _lx_compute_remnant_dims(self):
        """Calcule et stocke orientation + roll_width_best. Retourne (W_rem, H_rem)."""
        self.ensure_one()
        if not self.lx_width_m or not self.lx_height_m:
            return 0.0, 0.0

        chosen = self._lx_pick_orientation_and_roll()
        if chosen:
            W_rem, H_rem, roll, orient = chosen
            self.lx_roll_width_best = roll
            self.lx_orientation = orient
            return W_rem, H_rem

        # Fallback : largeur de rouleau maximale avec l'orientation du template
        widths = self._lx_get_all_roll_widths()
        if not widths:
            return 0.0, 0.0

        W = float(self.lx_width_m)
        H = float(self.lx_height_m)
        A = self._lx_get_fabric_allowance_m()
        Q = self._lx_get_Q_factor()
        fabric = self._lx_get_fabric_template()
        tmpl_orientation = getattr(fabric, 'orientation', 'widthwise') or 'widthwise'
        fallback_orient = 'heightwise' if tmpl_orientation == 'heightwise' else 'widthwise'
        roll = max(widths)
        self.lx_roll_width_best = roll
        self.lx_orientation = fallback_orient
        if fallback_orient == 'heightwise':
            return max(roll - 0.06 - H - A, 0.0), max(W - 0.03, 0.0)
        return max(roll - W - 0.03, 0.0), max(Q * H + A, 0.0)

    # =========================================================================
    # HELPERS CHAÎNES PLASTIQUES
    # =========================================================================

    def _lx_get_chain_code(self, product):
        for ptav in (product.product_template_attribute_value_ids or []):
            attr = (ptav.attribute_id.name or "").strip()
            val = (ptav.product_attribute_value_id.name or "").strip()
            if attr == "Code" and val in (PLASTIC_CHAIN_150_CODE, PLASTIC_CHAIN_200_CODE):
                return val
        return False

    def _is_plastic_chain(self, product):
        if not product:
            return False
        tmpl = product.product_tmpl_id
        return bool(getattr(tmpl, 'lx_is_plastic_chain', False)) and bool(self._lx_get_chain_code(product))

    def _want_chain_150(self, height_m=None):
        h = float(height_m if height_m is not None else (self.lx_height_m or 0.0))
        return h <= 2.70

    def _filter_plastic_chain_in_raw_vals(self, raw_vals_list, height_m=None):
        """Garde une seule chaîne plastique selon la règle de hauteur."""
        if not raw_vals_list:
            return raw_vals_list

        Product = self.env['product.product']
        want_150 = self._want_chain_150(height_m)
        kept = []
        chains = []

        for vals in raw_vals_list:
            p = Product.browse(vals.get('product_id')) if vals.get('product_id') else False
            if p and self._is_plastic_chain(p):
                chains.append((vals, p))
            else:
                kept.append(vals)

        if not chains:
            return raw_vals_list

        for vals, p in chains:
            code = self._lx_get_chain_code(p)
            if want_150 and code == PLASTIC_CHAIN_150_CODE:
                kept.append(vals)
                break
            if not want_150 and code == PLASTIC_CHAIN_200_CODE:
                kept.append(vals)
                break

        return kept

    def _enforce_plastic_chain_singleton(self):
        for mo in self:
            want_150 = mo._want_chain_150(mo.lx_height_m)
            chain_moves = mo.move_raw_ids.filtered(lambda m: mo._is_plastic_chain(m.product_id))

            if not chain_moves:
                continue

            # Trouver la bonne et les mauvaises
            correct = False
            wrong = []
            for mv in chain_moves:
                code = mo._lx_get_chain_code(mv.product_id)
                is_correct = (want_150 and code == PLASTIC_CHAIN_150_CODE) or \
                             (not want_150 and code == PLASTIC_CHAIN_200_CODE)
                if is_correct and not correct:
                    correct = mv
                else:
                    wrong.append(mv)

            # Restaurer la bonne chaîne à qty=1 si elle est à 0
            if correct and correct.product_uom_qty == 0.0:
                try:
                    correct.sudo().write({'product_uom_qty': 1.0})
                except Exception as e:
                    _logger.warning("lx_mrp: cannot restore correct chain %s: %s", correct.id, e)

            # Zeroing les mauvaises
            for mv in wrong:
                try:
                    done_qty = getattr(mv, 'quantity_done', 0.0) or getattr(mv, 'quantity', 0.0) or 0.0
                    if done_qty:
                        continue
                    mv_sudo = mv.sudo()
                    if mv_sudo.state == 'assigned':
                        if hasattr(mv_sudo, '_do_unreserve'):
                            mv_sudo._do_unreserve()
                        mv_sudo.move_line_ids.sudo().unlink()
                    mv_sudo.write({'product_uom_qty': 0.0})
                except Exception as e:
                    _logger.warning("lx_mrp: cannot zero chain move %s: %s", mv.id, e)

    # =========================================================================
    # EXPLOSION BoM — SCALING DIMENSIONNEL
    # =========================================================================

    def _lx_apply_absolute_rules(self, raw_vals_list, width_m=None):
        """Brackets : qty = floor(((W-0.3)/0.95)+2)."""
        if not raw_vals_list:
            return raw_vals_list
        Product = self.env['product.product']
        w = float(width_m or 0.0)
        for vals in raw_vals_list:
            prod = Product.browse(vals.get('product_id'))
            tmpl = prod.product_tmpl_id if prod else False
            if tmpl and getattr(tmpl, 'is_mounting_bracket', False):
                qty_real = max(math.floor(((w - 0.3) / 0.95) + 2), 0) if w else 0
                vals['product_uom_qty'] = qty_real
                qty_snap = max(math.floor(((1.0 - 0.3) / 0.95) + 2), 0)
                vals['lx_bom_uom_qty'] = qty_snap
        return raw_vals_list

    def _lx_apply_dimension_scaling(self, raw_vals_list, width_m=None, height_m=None):
        """
        Scale les quantités à consommer depuis le snapshot lx_bom_uom_qty.

        Tissu (lx_is_fabric ou roller_width_ids) :
          widthwise  → qty = Q * H + A
          heightwise → qty = W - 0.03
        Composant linéaire (lx_qty_by_width, pas tissu) :
          qty = snap * W
        Autres → qty = snap
        """
        if not raw_vals_list:
            return raw_vals_list
        self.ensure_one()
        Param = self.env['ir.config_parameter'].sudo()
        Product = self.env['product.product']

        w = float(width_m or 0.0)
        h = float(height_m or 0.0)
        Q = self._lx_get_Q_factor()
        orientation = self.lx_orientation or 'widthwise'

        for vals in raw_vals_list:
            prod = Product.browse(vals.get('product_id'))
            tmpl = prod.product_tmpl_id if prod else False
            snap = float(vals.get('lx_bom_uom_qty') or vals.get('product_uom_qty') or 0.0)

            if not tmpl:
                continue
            if getattr(tmpl, 'is_mounting_bracket', False):
                continue

            has_w = bool(getattr(tmpl, 'lx_qty_by_width', False))
            is_fabric = bool(getattr(tmpl, 'lx_is_fabric', False)) or bool(getattr(tmpl, 'roller_width_ids', False))

            if is_fabric:
                cm = float(getattr(tmpl, 'fabric_allowance', 0.0) or 0.0)
                if not cm:
                    cm = float(Param.get_param('luxtor.fabric_allowance_cm', '20') or 20.0)
                A = cm / 100.0
                if orientation == 'heightwise':
                    base = max(w - 0.03, 0.0)
                else:
                    base = max(Q * h + A, 0.0)
                vals['product_uom_qty'] = base
            elif has_w:
                vals['product_uom_qty'] = snap * w
            else:
                vals['product_uom_qty'] = snap

        return raw_vals_list

    # =========================================================================
    # RECALCUL SUR MOVES EXISTANTS
    # =========================================================================

    def _recalc_to_consume_quantities(self):
        Param = self.env['ir.config_parameter'].sudo()
        for mo in self:
            w = float(mo.lx_width_m or 0.0)
            h = float(mo.lx_height_m or 0.0)
            Q = mo._lx_get_Q_factor()
            orientation = mo.lx_orientation or 'widthwise'

            for m in mo.move_raw_ids:
                tmpl = m.product_id.product_tmpl_id if m.product_id else False
                snap = float(getattr(m, 'lx_bom_uom_qty', None) or m.product_uom_qty or 0.0)

                if not tmpl:
                    continue
                # Les chaînes plastiques sont gérées exclusivement par _enforce_plastic_chain_singleton
                if mo._is_plastic_chain(m.product_id):
                    continue
                if getattr(tmpl, 'is_mounting_bracket', False):
                    m.product_uom_qty = max(math.floor(((w - 0.3) / 0.95) + 2), 0) if w else 0
                    continue

                has_w = bool(getattr(tmpl, 'lx_qty_by_width', False))
                is_fabric = bool(getattr(tmpl, 'lx_is_fabric', False)) or bool(getattr(tmpl, 'roller_width_ids', False))

                if is_fabric:
                    cm = float(getattr(tmpl, 'fabric_allowance', 0.0) or 0.0)
                    if not cm:
                        cm = float(Param.get_param('luxtor.fabric_allowance_cm', '20') or 20.0)
                    A = cm / 100.0
                    if orientation == 'heightwise':
                        base = max(w - 0.03, 0.0)
                    else:
                        base = max(Q * h + A, 0.0)
                    m.product_uom_qty = base
                elif has_w:
                    m.product_uom_qty = snap * w
                else:
                    m.product_uom_qty = snap

    # =========================================================================
    # ONCHANGE / WRITE / CREATE
    # =========================================================================

    @api.onchange('lx_width_m', 'lx_height_m')
    def _onchange_lx_dims(self):
        self._lx_compute_remnant_dims()
        self._recalc_to_consume_quantities()
        self._enforce_plastic_chain_singleton()

    def write(self, vals):
        res = super().write(vals)
        if any(k in vals for k in ('lx_width_m', 'lx_height_m')) and not self.env.context.get('lx_recalc_done'):
            self._lx_compute_remnant_dims()
            self.with_context(lx_recalc_done=True)._recalc_to_consume_quantities()
            self._enforce_plastic_chain_singleton()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        for mo in recs:
            mo._lx_compute_remnant_dims()
        recs._recalc_to_consume_quantities()
        recs._enforce_plastic_chain_singleton()
        return recs

    def action_confirm(self):
        res = super().action_confirm()
        # Après génération des moves par Odoo, appliquer nos règles
        self._recalc_to_consume_quantities()
        self._enforce_plastic_chain_singleton()
        return res
