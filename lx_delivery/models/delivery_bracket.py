# -*- coding: utf-8 -*-
import math
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


# ─────────────────────────────────────────────────────────────────────────────
# Fonctions pures top-level — importables par wizards ET controllers
# ─────────────────────────────────────────────────────────────────────────────

def lx_raw_weight(product):
    """Retourne product.weight en float, 0.0 si absent/invalide."""
    try:
        return float(product.weight or 0.0)
    except Exception:
        return 0.0


def lx_is_countable_product(product):
    """True si le produit est stockable ou consommable (pas service)."""
    return bool(product and product.type in ("product", "consu"))


def lx_has_bom(product):
    """True si le produit possède une BoM MRP."""
    if not product:
        return False
    try:
        p = product.sudo()
        if getattr(p, "bom_count", 0):
            return True
        tmpl = p.product_tmpl_id.sudo()
        return bool((getattr(p, "bom_ids", False) and p.bom_ids)
                    or (tmpl and getattr(tmpl, "bom_ids", False) and tmpl.bom_ids))
    except Exception:
        return False


def lx_pick_brackets(env, carrier_lx, is_intracity):
    """
    Retourne les tranches de poids triées pour le carrier_lx et le mode intra/inter.
    Si carrier_lx est fourni, filtre par carrier_lx_id ; sinon retourne toutes les tranches du kind.
    """
    kind = "intra" if is_intracity else "inter"
    domain = [("kind", "=", kind)]
    if carrier_lx:
        domain.append(("carrier_lx_id", "=", carrier_lx.id))
    brackets = env["delivery.bracket.lx"].sudo().search(domain, order="max_kg asc")
    if not brackets and carrier_lx:
        # Fallback : tranches globales sans filtre carrier
        brackets = env["delivery.bracket.lx"].sudo().search(
            [("kind", "=", kind)], order="max_kg asc"
        )
    return brackets


def lx_find_bracket_for_weight(weight, brackets):
    """
    Trouve la tranche correspondant au poids.
    Fallback sur la tranche la plus haute si aucune ne correspond exactement.
    """
    chosen = None
    for b in brackets:
        if (b.min_kg or 0.0) <= weight <= (b.max_kg or 0.0):
            chosen = b
            break
    if not chosen and brackets:
        chosen = brackets[-1]
    return chosen


def lx_order_lines_for_weight(order):
    """
    Retourne les lignes pertinentes pour le calcul du poids express :
    exclut display / delivery / tip / downpayment / is_shipping_line /
    is_free_shipping_line / INSTALL_SERVICE / PRIORITY_SERVICE.
    """
    res = []
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
        if p:
            code = (p.default_code or "").strip().upper()
            tcode = (p.product_tmpl_id.default_code or "").strip().upper()
            if code in ("INSTALL_SERVICE", "PRIORITY_SERVICE") or tcode in ("INSTALL_SERVICE", "PRIORITY_SERVICE"):
                continue
        res.append(l)
    return res


# ─────────────────────────────────────────────────────────────────────────────
# Modèle delivery.bracket.lx
# ─────────────────────────────────────────────────────────────────────────────

class DeliveryBracketLx(models.Model):
    """Tranches de poids pour le mode Express (intracity / intercity)."""

    _name = "delivery.bracket.lx"
    _description = "Weight pricing bracket (intracity/intercity)"
    _order = "carrier_lx_id, kind, min_kg, max_kg"

    KIND_SELECTION = [
        ("intra", "Intracity"),
        ("inter", "Intercity"),
    ]

    carrier_lx_id = fields.Many2one(
        "delivery.carrier.lx",
        string="LX Carrier Config",
        required=False,
        ondelete="cascade",
        index=True,
    )
    # Gardé pour rétrocompatibilité — auto-synchronisé vers carrier_lx_id
    carrier_id = fields.Many2one(
        "delivery.carrier",
        string="Carrier (legacy)",
        required=False,
        ondelete="cascade",
        index=True,
    )
    kind = fields.Selection(KIND_SELECTION, string="Kind", required=True, index=True)
    min_kg = fields.Float(string="Min (kg)", required=True, index=True)
    max_kg = fields.Float(string="Max (kg)", required=True, index=True)
    unit_price = fields.Float(string="Unit Price", required=True)

    @api.constrains("min_kg", "max_kg")
    def _check_range(self):
        for rec in self:
            if rec.min_kg < 0 or rec.max_kg <= 0 or rec.max_kg <= rec.min_kg:
                raise ValidationError(_("Invalid bracket range: min must be ≥ 0, max > 0 and max > min."))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._lx_sync_carrier_lx()
        return records

    def write(self, vals):
        res = super().write(vals)
        if "carrier_id" in vals:
            self._lx_sync_carrier_lx()
        return res

    def _lx_sync_carrier_lx(self):
        """Auto-lie carrier_lx_id depuis carrier_id (legacy) si absent."""
        for rec in self:
            if not rec.carrier_lx_id and rec.carrier_id:
                lx = self.env["delivery.carrier.lx"].sudo().search(
                    [("carrier_id", "=", rec.carrier_id.id)], limit=1
                )
                if lx:
                    rec.carrier_lx_id = lx.id

