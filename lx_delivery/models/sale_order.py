# -*- coding: utf-8 -*-
import math
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SaleOrderLine(models.Model):
    """Ajout des flags is_shipping_line / is_free_shipping_line sur sale.order.line."""

    _inherit = "sale.order.line"

    is_shipping_line = fields.Boolean(
        string="Is Shipping Line",
        default=False,
        help="Ligne de facturation de transport (Luxtor).",
    )
    is_free_shipping_line = fields.Boolean(
        string="Is Free Shipping Line",
        default=False,
        help="Ligne de livraison offerte (Luxtor).",
    )


# ─────────────────────────────────────────────────────────────────────────────
# sale.order — champs shipping + logique de calcul
# ─────────────────────────────────────────────────────────────────────────────

class SaleOrder(models.Model):
    """Extension sale.order : champs shipping Luxtor + calcul prix livraison."""

    _inherit = "sale.order"

    # Champs shipping
    shipping_method_type = fields.Selection(
        [("standard", "Standard"), ("express", "Express")],
        string="Shipping Method",
        default="standard",
    )
    shipping_city_id = fields.Many2one("shipping.rate", string="Shipping City")
    shipping_price = fields.Float(string="Shipping Price", default=0.0)
    shipping_quantity = fields.Integer(string="Shipping Quantity", default=0)

    # Termes de paiement Luxtor
    lx_payment_terms = fields.Selection(
        [("upfront", "100% on Order"), ("half_half", "50% on Order & 50% on Delivery")],
        string="Payment Terms",
        default="upfront",
    )

    # ── Helpers internes ──────────────────────────────────────────────────────

    def _lx_is_service_line(self, line):
        """True si la ligne correspond à INSTALL_SERVICE ou PRIORITY_SERVICE."""
        p = line.product_id
        if not p or line.display_type:
            return False
        code = (p.default_code or "").strip().upper()
        tcode = (p.product_tmpl_id.default_code or "").strip().upper()
        return code in ("INSTALL_SERVICE", "PRIORITY_SERVICE") or tcode in ("INSTALL_SERVICE", "PRIORITY_SERVICE")

    def _lx_is_accessory_product(self, product):
        """True si le produit appartient à une catégorie 'access*'."""
        if not product:
            return False
        try:
            c = product.categ_id
            if c and ("access" in (c.complete_name or "").lower() or "access" in (c.name or "").lower()):
                return True
        except Exception:
            pass
        try:
            for pc in product.public_categ_ids:
                if "access" in (pc.name or "").lower():
                    return True
        except Exception:
            pass
        return False

    def _lx_lookup_shipping_rate(self, zip_code):
        """Recherche shipping.rate par zip_code."""
        zip_code = (zip_code or "").strip()
        if not zip_code:
            return False
        return self.env["shipping.rate"].sudo().search([("zip_code", "=", zip_code)], limit=1)

    def _lx_get_free_threshold(self):
        """Retourne le seuil free shipping depuis icp (défaut 5000)."""
        ICP = self.env["ir.config_parameter"].sudo()
        val = ICP.get_param("luxtor.lx_free_amount_order", default="5000")
        try:
            return float(val or 0.0)
        except Exception:
            return 5000.0

    def _lx_merch_total_excl_services(self):
        """Total marchandise hors delivery / tip / downpayment / services / shipping lines."""
        self.ensure_one()
        total = 0.0
        for l in self.sudo().order_line:
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
            if self._lx_is_service_line(l):
                continue
            total += float(l.price_total or 0.0)
        return float(total)

    def _lx_apply_free_logic(self, raw_price):
        """
        Applique la logique free shipping.

        Priorité 1 : contexte lx_free_force / lx_free_force_session.
        Priorité 2 : merch_total ≥ threshold.

        Retourne (final_price, free_applied, free_reason, threshold, merch_total, forced).
        """
        self.ensure_one()
        forced = bool(
            self.env.context.get("lx_free_force")
            or self.env.context.get("lx_free_force_session")
        )
        threshold = self._lx_get_free_threshold()
        merch_total = self._lx_merch_total_excl_services()

        if forced:
            return 0.0, True, "forced", threshold, merch_total, True
        if threshold and merch_total >= threshold:
            return 0.0, True, "order_amount_over_threshold", threshold, merch_total, False

        return float(raw_price or 0.0), False, None, threshold, merch_total, False

    def _lx_std_order_lines_for_parcels(self):
        """Lignes pertinentes pour le calcul des colis standard."""
        self.ensure_one()
        res = []
        for l in self.order_line:
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
            if self._lx_is_service_line(l):
                continue
            res.append(l)
        return res

    def _lx_find_bom(self, product):
        """Recherche robuste de BoM (variante → template → bom_ids)."""
        try:
            p = product.sudo()
            Bom = self.env["mrp.bom"].sudo()
            try:
                bom = Bom._bom_find(product=p)
                if bom:
                    return bom
            except Exception:
                pass
            tmpl = p.product_tmpl_id.sudo()
            if tmpl:
                try:
                    bom = Bom._bom_find(product_tmpl=tmpl)
                    if bom:
                        return bom
                except Exception:
                    pass
                if getattr(tmpl, "bom_ids", False) and tmpl.bom_ids:
                    return tmpl.bom_ids[:1]
        except Exception:
            return False
        return False

    def _lx_bom_weight_per_unit_excluding(self, bom, exclude_product_ids=None, exclude_name_tokens=None):
        """Poids par unité depuis BoM, en excluant les composants accessoires."""
        exclude_product_ids = set(exclude_product_ids or [])
        exclude_name_tokens = [t.strip().lower() for t in (exclude_name_tokens or []) if t and t.strip()]
        if not bom:
            return 0.0
        total = 0.0
        denom = float(bom.product_qty or 1.0) or 1.0
        for bl in bom.bom_line_ids.sudo():
            comp = bl.product_id
            if not comp or comp.id in exclude_product_ids:
                continue
            if not (comp.type in ("product", "consu")):
                continue
            name = (comp.display_name or comp.name or "").lower()
            if any(tok and tok in name for tok in exclude_name_tokens):
                continue
            w = float(comp.weight or 0.0)
            if w <= 0.0:
                continue
            qty = float(bl.product_qty or 0.0)
            try:
                if bl.product_uom_id and comp.uom_id and bl.product_uom_id.id != comp.uom_id.id:
                    qty = bl.product_uom_id._compute_quantity(qty, comp.uom_id)
            except Exception:
                pass
            total += (w * qty) / denom
        return float(total)

    def _lx_pick_brackets_by_kind(self, is_intracity):
        """Tranches de poids globales pour le mode intra/inter."""
        kind = "intra" if is_intracity else "inter"
        return self.env["delivery.bracket.lx"].sudo().search([("kind", "=", kind)], order="max_kg asc")

    def _lx_find_bracket_for_weight(self, weight, brackets):
        """Trouve la tranche correspondant au poids, fallback sur la plus haute."""
        chosen = None
        for b in brackets:
            if (b.min_kg or 0.0) <= weight <= (b.max_kg or 0.0):
                chosen = b
                break
        if not chosen and brackets:
            chosen = brackets[-1]
        return chosen

    # ── Calcul Standard ───────────────────────────────────────────────────────

    def _lx_compute_standard_price(self, zip_code=None):
        """
        Calcule le prix Standard brut :
        base = shipping_rate.price × nb_colis_total

        Colis :
        - Chaque ligne BoM : ceil(qty) colis
        - Accessoires (no BoM + catégorie 'access*') : 1 colis groupé
        - Extra tangibles (no BoM + non accessoire) : 1 colis groupé séparé
        Minimum 1 colis.
        """
        self.ensure_one()
        zip_code = (zip_code or (self.partner_shipping_id.zip or "")).strip()
        rate = self._lx_lookup_shipping_rate(zip_code)
        if not rate:
            return 0.0

        base = float(getattr(rate, "price", 0.0) or 0.0)
        manufactured_parcels = 0
        has_accessory_group = False
        has_extra_group = False

        for line in self._lx_std_order_lines_for_parcels():
            p = line.product_id
            qty_f = float(line.product_uom_qty or 0.0)
            if not p or qty_f <= 0:
                continue
            if p.type not in ("product", "consu"):
                continue
            bom = self._lx_find_bom(p)
            if bom:
                manufactured_parcels += int(math.ceil(qty_f))
            elif self._lx_is_accessory_product(p):
                has_accessory_group = True
            else:
                has_extra_group = True

        parcels_total = (
            int(manufactured_parcels)
            + (1 if has_accessory_group else 0)
            + (1 if has_extra_group else 0)
        )
        if parcels_total <= 0:
            parcels_total = 1

        return float(base * float(parcels_total))

    # ── Calcul Express ────────────────────────────────────────────────────────

    def _lx_get_accessory_products_for_weight(self):
        """Retourne (motor, remote, charger, zigbee) depuis icp."""
        Product = self.env["product.product"].sudo()
        ICP = self.env["ir.config_parameter"].sudo()
        empty = Product.browse()

        motor_code = ICP.get_param("luxtor.motor_code", "MOTOR_28MM_230V")
        remote_code = ICP.get_param("luxtor.remote_code", "REMOTE_15CH")
        charger_code = ICP.get_param("luxtor.charger_code", "CHARGER_LIION")
        zigbee_name = ICP.get_param("luxtor.zigbee_gateway_name", "ZigBee")

        motor = (Product.search([("default_code", "=", motor_code)], limit=1)
                 or Product.search([("name", "=", "Tubular Motor")], limit=1)
                 or empty)
        remote = (Product.search([("default_code", "=", remote_code)], limit=1)
                  or Product.search([("name", "=", "Remote Control")], limit=1)
                  or empty)
        charger = (Product.search([("default_code", "=", charger_code)], limit=1)
                   or Product.search([("name", "=", "Charger")], limit=1)
                   or empty)
        zigbee = (Product.search([("name", "=", zigbee_name)], limit=1)
                  or Product.search([("name", "ilike", "ZigBee")], limit=1)
                  or empty)

        return motor, remote, charger, zigbee

    def _lx_get_ratios_for_weight(self):
        """Retourne (remote_ratio, charger_ratio, zigbee_ratio)."""
        ICP = self.env["ir.config_parameter"].sudo()
        return (
            max(1, int(ICP.get_param("luxtor.remote_ratio", 5) or 5)),
            max(1, int(ICP.get_param("luxtor.charger_ratio", 15) or 15)),
            max(1, int(ICP.get_param("luxtor.zigbee_ratio", 30) or 30)),
        )

    def _lx_compute_express_price(self, zip_code=None):
        """
        Calcule le prix Express brut.

        Chaque ligne BoM = 1 colis, tarifé par bracket.unit_price selon le poids total.
        Poids colis = (composants BoM excl. accessoires) × qty_float + accessoires virtuels alloués.
        Accessoires sans BoM → 1 colis groupé ; extras → 1 colis groupé.
        """
        self.ensure_one()
        zip_code = (zip_code or (self.partner_shipping_id.zip or "")).strip()
        rate = self._lx_lookup_shipping_rate(zip_code)
        if not rate:
            return 0.0

        is_intracity = bool(getattr(rate, "is_intracity", False))
        brackets = self._lx_pick_brackets_by_kind(is_intracity)
        if not brackets:
            return 0.0

        motor, remote, charger, zigbee = self._lx_get_accessory_products_for_weight()
        r_ratio, c_ratio, z_ratio = self._lx_get_ratios_for_weight()
        exclude_ids = {p.id for p in (motor, remote, charger, zigbee) if p}
        exclude_tokens = ["charger", "zigbee", "remote", "tubular motor", "motor"]

        manufactured = []
        accessory_weight = 0.0
        extra_weight = 0.0

        for l in self.order_line:
            if l.display_type:
                continue
            if getattr(l, "is_delivery", False) or getattr(l, "is_tip", False) or getattr(l, "is_downpayment", False):
                continue
            if getattr(l, "is_shipping_line", False) or getattr(l, "is_free_shipping_line", False):
                continue
            if self._lx_is_service_line(l):
                continue
            p = l.product_id
            qty_f = float(l.product_uom_qty or 0.0)
            if not p or qty_f <= 0 or p.type not in ("product", "consu"):
                continue
            bom = self._lx_find_bom(p)
            if bom:
                manufactured.append({
                    "product": p, "bom": bom,
                    "qty_float": qty_f,
                    "units_ceil": int(math.ceil(qty_f)),
                    "alloc": {"motor": 0, "remote": 0, "charger": 0, "zigbee": 0},
                })
            else:
                w = float(p.weight or 0.0) * qty_f
                if self._lx_is_accessory_product(p):
                    accessory_weight += w
                else:
                    extra_weight += w

        # Poids de base par colis BoM
        for m in manufactured:
            per_unit = self._lx_bom_weight_per_unit_excluding(
                m["bom"], exclude_product_ids=exclude_ids, exclude_name_tokens=exclude_tokens
            )
            m["base_weight"] = float(per_unit) * float(m["qty_float"])

        # Compteurs électriques
        motors_total = non_motor_only = smartphone = 0
        for m in manufactured:
            p = m["product"]
            u = m["units_ceil"]
            if hasattr(p, "lx_is_electric_variant") and self._safe_call(p.lx_is_electric_variant):
                motors_total += u
                if not (hasattr(p, "lx_is_motor_only_variant") and self._safe_call(p.lx_is_motor_only_variant)):
                    non_motor_only += u
                    if hasattr(p, "lx_is_smartphone_controlled_variant") and self._safe_call(p.lx_is_smartphone_controlled_variant):
                        smartphone += u

        remote_needed = (int(math.ceil(non_motor_only / r_ratio)) if non_motor_only > 0 else 0) if remote else 0
        charger_needed = (int(math.ceil(non_motor_only / c_ratio)) if non_motor_only > 0 else 0) if charger else 0
        zigbee_needed = (int(math.ceil(smartphone / z_ratio)) if smartphone > 0 else 0) if zigbee else 0

        # Allocation moteur par colis électrique
        for m in manufactured:
            p = m["product"]
            if motor and hasattr(p, "lx_is_electric_variant") and self._safe_call(p.lx_is_electric_variant):
                m["alloc"]["motor"] = m["units_ceil"]

        def _pack(kind, needed, cov, eligible_fn):
            remaining = int(needed or 0)
            if remaining <= 0:
                return
            for m in manufactured:
                if remaining <= 0:
                    break
                if not eligible_fn(m):
                    continue
                left = m["units_ceil"]
                while remaining > 0 and left > 0:
                    m["alloc"][kind] += 1
                    remaining -= 1
                    left -= cov
            if remaining > 0 and manufactured:
                manufactured[0]["alloc"][kind] += remaining

        def _is_electric(m):
            p = m["product"]
            return bool(hasattr(p, "lx_is_electric_variant") and self._safe_call(p.lx_is_electric_variant))

        def _is_non_motor_only(m):
            p = m["product"]
            return _is_electric(m) and not (hasattr(p, "lx_is_motor_only_variant") and self._safe_call(p.lx_is_motor_only_variant))

        def _is_smartphone(m):
            p = m["product"]
            return _is_non_motor_only(m) and (hasattr(p, "lx_is_smartphone_controlled_variant") and self._safe_call(p.lx_is_smartphone_controlled_variant))

        _pack("remote", remote_needed, r_ratio, _is_non_motor_only)
        _pack("charger", charger_needed, c_ratio, _is_non_motor_only)
        _pack("zigbee", zigbee_needed, z_ratio, _is_smartphone)

        def _price_for_weight(w):
            if w <= 0.0:
                return 0.0
            br = self._lx_find_bracket_for_weight(w, brackets)
            return float(br.unit_price or 0.0) if br else 0.0

        total_price = 0.0
        for m in manufactured:
            bw = float(m["base_weight"] or 0.0)
            mw = (float(motor.weight or 0.0) * float(m["alloc"]["motor"])) if motor else 0.0
            rw = (float(remote.weight or 0.0) * float(m["alloc"]["remote"])) if remote else 0.0
            cw = (float(charger.weight or 0.0) * float(m["alloc"]["charger"])) if charger else 0.0
            zw = (float(zigbee.weight or 0.0) * float(m["alloc"]["zigbee"])) if zigbee else 0.0
            total_price += _price_for_weight(bw + mw + rw + cw + zw)

        if accessory_weight > 0.0:
            total_price += _price_for_weight(accessory_weight)
        if extra_weight > 0.0:
            total_price += _price_for_weight(extra_weight)

        return float(total_price)

    @staticmethod
    def _safe_call(fn):
        """Appel sécurisé d'une méthode booléenne sur un produit."""
        try:
            return bool(fn())
        except Exception:
            return False

    # ── Delivery line helper ──────────────────────────────────────────────────

    def _lx_apply_delivery_line(self, carrier, price):
        """Applique le carrier et le prix de livraison sur la commande (robuste)."""
        self.ensure_one()
        order = self.sudo()
        try:
            order.write({"carrier_id": carrier.id})
        except Exception:
            pass

        for meth in ("set_delivery_line", "_set_delivery_line", "_create_delivery_line"):
            fn = getattr(order, meth, None)
            if not fn:
                continue
            try:
                fn(carrier, price)
                return True
            except TypeError:
                try:
                    fn(carrier)
                    dl = order.order_line.filtered(lambda l: getattr(l, "is_delivery", False))[:1]
                    if dl:
                        dl.write({"price_unit": float(price or 0.0)})
                    return True
                except Exception:
                    continue
            except Exception:
                continue

        dl = order.order_line.filtered(lambda l: getattr(l, "is_delivery", False))[:1]
        if dl:
            dl.write({"price_unit": float(price or 0.0)})
            return True
        return False

    def _lx_sync_selected_carrier_delivery_line(self):
        """Re-calcule et écrit le prix de livraison pour le carrier sélectionné."""
        self.ensure_one()
        order = self.sudo()
        carrier = order.carrier_id.sudo() if order.carrier_id else None
        if not carrier:
            return False

        zip_code = (order.partner_shipping_id.zip or "").strip()
        name_norm = (carrier.name or "").strip().lower()

        if name_norm == "standard delivery":
            raw = order._lx_compute_standard_price(zip_code=zip_code)
        elif name_norm == "express delivery":
            raw = order._lx_compute_express_price(zip_code=zip_code)
        else:
            return False

        final_price, *_ = order._lx_apply_free_logic(raw)
        return bool(order._lx_apply_delivery_line(carrier, float(final_price or 0.0)))

    def _lx_preview_carrier_price(self, carrier, zip_code=None):
        """Calcule le prix d'un carrier sans l'écrire sur la commande."""
        self.ensure_one()
        carrier = carrier.sudo()
        zip_code = (zip_code or (self.partner_shipping_id.zip or "")).strip()
        name_norm = (carrier.name or "").strip().lower()

        if name_norm == "standard delivery":
            raw = self._lx_compute_standard_price(zip_code=zip_code)
        elif name_norm == "express delivery":
            raw = self._lx_compute_express_price(zip_code=zip_code)
        else:
            return 0.0

        final_price, *_ = self._lx_apply_free_logic(raw)
        return float(final_price or 0.0)

    # ── Payment summary ───────────────────────────────────────────────────────

    def action_lx_open_shipping_wizard(self):
        """Ouvre le wizard de livraison pour la commande courante."""
        self.ensure_one()
        return {
            "name": _("Add Shipping"),
            "type": "ir.actions.act_window",
            "res_model": "sale.order.shipping.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"active_id": self.id},
        }

    def _lx_payment_summary_values(self):
        """
        Retourne un dict pour le template de paiement (50/50 ou 100%).

        Clés : terms, amount_total, amount_now, amount_later,
               currency_symbol, currency_position.
        """
        self.ensure_one()
        order = self.sudo()
        terms = (order.lx_payment_terms or "upfront")
        amount_total = float(order.amount_total or 0.0)
        currency = order.currency_id or order.company_id.currency_id

        if terms == "half_half":
            amount_now = currency.round(amount_total / 2.0) if currency else amount_total / 2.0
            amount_later = currency.round(amount_total - amount_now) if currency else amount_total - amount_now
        else:
            amount_now = amount_total
            amount_later = 0.0

        return {
            "terms": terms,
            "amount_total": amount_total,
            "amount_now": amount_now,
            "amount_later": amount_later,
            "currency_symbol": currency.symbol or "",
            "currency_position": currency.position or "after",
        }

