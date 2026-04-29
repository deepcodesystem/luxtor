# -*- coding: utf-8 -*-
import math
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    # ---------------------------------------------------------
    # Shared helpers
    # ---------------------------------------------------------
    def _lx_is_service_line(self, line):
        p = line.product_id
        if not p or line.display_type:
            return False
        code = (p.default_code or "").strip().upper()
        tcode = (p.product_tmpl_id.default_code or "").strip().upper()
        return code in ("INSTALL_SERVICE", "PRIORITY_SERVICE") or tcode in ("INSTALL_SERVICE", "PRIORITY_SERVICE")

    def _lx_is_accessory_product(self, product):
        """Align with controller _is_accessory_product() heuristic."""
        if not product:
            return False
        try:
            c = product.categ_id
            if c and ("access" in (c.complete_name or "").lower() or "access" in (c.name or "").lower()):
                return True
        except Exception:
            pass
        try:
            pubs = product.public_categ_ids
            for pc in pubs:
                if "access" in (pc.name or "").lower():
                    return True
        except Exception:
            pass
        return False

    def _lx_std_order_lines_for_parcels(self):
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
            if self._lx_is_service_line(l):
                continue
            res.append(l)
        return res

    def _lx_lookup_shipping_rate(self, zip_code):
        zip_code = (zip_code or "").strip()
        if not zip_code:
            return False
        return self.env["shipping.rate"].sudo().search([("zip_code", "=", zip_code)], limit=1)

    # ---------------------------------------------------------
    # FREE logic (same semantics as controller)
    # ---------------------------------------------------------
    def _lx_get_free_threshold(self):
        ICP = self.env["ir.config_parameter"].sudo()
        val = ICP.get_param("luxtor.lx_free_amount_order", default="5000")
        try:
            return float(val or 0.0)
        except Exception:
            return 5000.0

    def _lx_merch_total_excl_services(self):
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
            if self._lx_is_service_line(l):
                continue
            total += float(l.price_total or 0.0)
        return float(total)

    def _lx_apply_free_logic(self, raw_price):
        """
        Align with controller:
        - model can be forced by context (lx_free_force / lx_free_force_session)
        - controller uses session key lx_free_force
        """
        self.ensure_one()
        forced = bool(self.env.context.get("lx_free_force") or self.env.context.get("lx_free_force_session"))
        threshold = self._lx_get_free_threshold()
        merch_total = self._lx_merch_total_excl_services()

        if forced:
            return 0.0, True, "forced", threshold, merch_total, True

        if threshold and merch_total >= threshold:
            return 0.0, True, "order_amount_over_threshold", threshold, merch_total, False

        return float(raw_price or 0.0), False, None, threshold, merch_total, False

    # ---------------------------------------------------------
    # BoM + weight helpers (same approach as controller)
    # ---------------------------------------------------------
    def _lx_find_bom(self, product):
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
                except TypeError:
                    pass
                except Exception:
                    pass
                if getattr(tmpl, "bom_ids", False) and tmpl.bom_ids:
                    return tmpl.bom_ids[:1]
        except Exception:
            return False
        return False

    def _lx_raw_weight(self, product):
        try:
            return float(product.weight or 0.0)
        except Exception:
            return 0.0

    def _lx_is_countable_product(self, product):
        return bool(product and product.type in ("product", "consu"))

    def _lx_get_accessory_products_for_weight(self):
        Product = self.env["product.product"].sudo()
        ICP = self.env["ir.config_parameter"].sudo()

        motor_code = ICP.get_param("luxtor.motor_code", "MOTOR_28MM_230V")
        remote_code = ICP.get_param("luxtor.remote_code", "REMOTE_15CH")
        charger_code = ICP.get_param("luxtor.charger_code", "CHARGER_LIION")
        zigbee_name = ICP.get_param("luxtor.zigbee_gateway_name", "ZigBee")

        motor = Product.search([("default_code", "=", motor_code)], limit=1) or Product.search([("name", "ilike", "Tubular Motor")], limit=1)
        remote = Product.search([("default_code", "=", remote_code)], limit=1) or Product.search([("name", "ilike", "Remote")], limit=1)
        charger = Product.search([("default_code", "=", charger_code)], limit=1) or Product.search([("name", "ilike", "Charger")], limit=1)
        zigbee = Product.search([("name", "=", zigbee_name)], limit=1) or Product.search([("name", "ilike", "ZigBee")], limit=1)

        if not motor or not remote or not charger or not zigbee:
            raise UserError(_("Missing accessory products for weight calculation."))

        return motor, remote, charger, zigbee

    def _lx_get_ratios_for_weight(self):
        ICP = self.env["ir.config_parameter"].sudo()
        r_ratio = max(1, int(ICP.get_param("luxtor.remote_ratio", 5) or 5))
        c_ratio = max(1, int(ICP.get_param("luxtor.charger_ratio", 15) or 15))
        z_ratio = max(1, int(ICP.get_param("luxtor.zigbee_ratio", 30) or 30))
        return r_ratio, c_ratio, z_ratio

    def _lx_is_electric_variant_product(self, product):
        try:
            return bool(product and hasattr(product, "lx_is_electric_variant") and product.lx_is_electric_variant())
        except Exception:
            return False

    def _lx_is_motor_only_variant_product(self, product):
        try:
            return bool(product and hasattr(product, "lx_is_motor_only_variant") and product.lx_is_motor_only_variant())
        except Exception:
            return False

    def _lx_is_smartphone_variant_product(self, product):
        try:
            return bool(product and hasattr(product, "lx_is_smartphone_controlled_variant") and product.lx_is_smartphone_controlled_variant())
        except Exception:
            return False

    def _lx_bom_weight_per_unit_excluding(self, bom, exclude_product_ids=None, exclude_name_tokens=None):
        exclude_product_ids = set(exclude_product_ids or [])
        exclude_name_tokens = [t.strip().lower() for t in (exclude_name_tokens or []) if t and t.strip()]
        if not bom:
            return 0.0

        total = 0.0
        denom = float(bom.product_qty or 1.0) or 1.0

        for bl in bom.bom_line_ids.sudo():
            comp = bl.product_id
            if not comp:
                continue
            if comp.id in exclude_product_ids:
                continue
            if not self._lx_is_countable_product(comp):
                continue

            name = (comp.display_name or comp.name or "").lower()
            if any(tok in name for tok in exclude_name_tokens):
                continue

            w = self._lx_raw_weight(comp)
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

    # ---------------------------------------------------------
    # Brackets helpers
    # ---------------------------------------------------------
    def _lx_pick_brackets_by_kind(self, is_intracity):
        kind = "intra" if is_intracity else "inter"
        return self.env["delivery.bracket.lx"].sudo().search([("kind", "=", kind)], order="max_kg asc")

    def _lx_find_bracket_for_weight(self, weight, brackets):
        chosen = None
        for b in brackets:
            if (b.min_kg or 0.0) <= weight <= (b.max_kg or 0.0):
                chosen = b
                break
        if not chosen and brackets:
            chosen = brackets[-1]
        return chosen

    # ---------------------------------------------------------
    # FINAL: STANDARD (align with controller _compute_standard_city_raw_price)
    # ---------------------------------------------------------
    def _lx_compute_standard_price(self, zip_code=None):
        """
        STANDARD (by city) raw:
        - base = shipping.rate.price (ZIP)
        Parcels:
          - Each BoM/manufactured product line contributes ceil(qty) parcels.
          - Accessories (no BoM + accessory category) grouped into 1 parcel if present.
          - Extra tangible (no BoM + not accessory) grouped into 1 separate parcel if present.
        raw = base * parcels_total (min 1).
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
            if not self._lx_is_countable_product(p):
                continue

            bom = self._lx_find_bom(p)
            if bom:
                manufactured_parcels += int(math.ceil(qty_f))
            else:
                if self._lx_is_accessory_product(p):
                    has_accessory_group = True
                else:
                    has_extra_group = True

        parcels_total = int(manufactured_parcels) + (1 if has_accessory_group else 0) + (1 if has_extra_group else 0)
        if parcels_total <= 0:
            parcels_total = 1

        return float(base * float(parcels_total))

    # ---------------------------------------------------------
    # FINAL: EXPRESS (align with controller _compute_express_raw_price)
    # ---------------------------------------------------------
    def _lx_compute_express_price(self, zip_code=None):
        """
        EXPRESS (by weight) raw:
        - Weight uses qty_float (no truncation).
        - Each BoM/manufactured product line is ONE parcel rated by weight:
            raw = sum(bracket.unit_price per parcel).
        - Accessory decisions use ceil(qty) units; allocated across manufactured parcels (greedy by coverage).
        - Accessories (no BoM + accessory) => ONE grouped parcel by weight if present.
        - Extra tangible (no BoM + not accessory) => ONE grouped parcel by weight if present.
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

        exclude_ids = {motor.id, remote.id, charger.id, zigbee.id}
        exclude_tokens = ["charger", "zigbee", "remote", "tubular motor", "motor"]

        manufactured = []     # one parcel per BoM line
        accessory_cart = []   # grouped parcel
        extra_cart = []       # grouped parcel

        for l in self.order_line:
            if l.display_type:
                continue
            if getattr(l, "is_delivery", False) or getattr(l, "is_tip", False) or getattr(l, "is_downpayment", False):
                continue
            if self._lx_is_service_line(l):
                continue

            p = l.product_id
            qty_f = float(l.product_uom_qty or 0.0)
            if not p or qty_f <= 0:
                continue
            if not self._lx_is_countable_product(p):
                continue

            bom = self._lx_find_bom(p)
            if bom:
                manufactured.append({
                    "product": p,
                    "bom": bom,
                    "qty_float": qty_f,                  # weight
                    "units_ceil": int(math.ceil(qty_f)), # accessory decisions
                    "base_weight": 0.0,
                    "alloc": {"motor": 0, "remote": 0, "charger": 0, "zigbee": 0},
                })
            else:
                w = self._lx_raw_weight(p)
                wa = (w * qty_f) if w > 0.0 else 0.0
                if self._lx_is_accessory_product(p):
                    accessory_cart.append((p, qty_f, wa))
                else:
                    extra_cart.append((p, qty_f, wa))

        # Base weights for manufactured parcels (qty_float)
        for m in manufactured:
            per_unit = self._lx_bom_weight_per_unit_excluding(
                m["bom"],
                exclude_product_ids=exclude_ids,
                exclude_name_tokens=exclude_tokens,
            )
            m["base_weight"] = float(per_unit) * float(m["qty_float"] or 0.0)

        # Accessory decisions use ceil(units)
        motors_total_units = 0
        non_motor_only_units = 0
        smartphone_units = 0

        for m in manufactured:
            p = m["product"]
            u = int(m["units_ceil"] or 0)
            if u <= 0:
                continue
            if self._lx_is_electric_variant_product(p):
                motors_total_units += u
                if not self._lx_is_motor_only_variant_product(p):
                    non_motor_only_units += u
                    if self._lx_is_smartphone_variant_product(p):
                        smartphone_units += u

        remote_needed = int(math.ceil(non_motor_only_units / r_ratio)) if non_motor_only_units > 0 else 0
        charger_needed = int(math.ceil(non_motor_only_units / c_ratio)) if non_motor_only_units > 0 else 0
        zigbee_needed = int(math.ceil(smartphone_units / z_ratio)) if smartphone_units > 0 else 0

        # Motors: allocate per eligible parcel by its units_ceil
        for m in manufactured:
            if self._lx_is_electric_variant_product(m["product"]):
                m["alloc"]["motor"] = int(m["units_ceil"] or 0)

        # Greedy pack by unit coverage
        def _pack(kind, needed, coverage_units, eligible_fn):
            remaining = int(needed or 0)
            if remaining <= 0:
                return 0
            cov = int(coverage_units or 1)
            for m in manufactured:
                if remaining <= 0:
                    break
                if not eligible_fn(m):
                    continue
                units_left = int(m["units_ceil"] or 0)
                while remaining > 0 and units_left > 0:
                    m["alloc"][kind] += 1
                    remaining -= 1
                    units_left -= cov
            return remaining

        def _eligible_non_motor_only(m):
            p = m["product"]
            return bool(self._lx_is_electric_variant_product(p) and (not self._lx_is_motor_only_variant_product(p)))

        def _eligible_smartphone(m):
            p = m["product"]
            return bool(self._lx_is_electric_variant_product(p)
                        and (not self._lx_is_motor_only_variant_product(p))
                        and self._lx_is_smartphone_variant_product(p))

        rem_left = _pack("remote", remote_needed, r_ratio, _eligible_non_motor_only)
        chg_left = _pack("charger", charger_needed, c_ratio, _eligible_non_motor_only)
        zig_left = _pack("zigbee", zigbee_needed, z_ratio, _eligible_smartphone)

        # Fallback: attach remainder to first manufactured parcel if any
        if manufactured:
            if rem_left > 0:
                manufactured[0]["alloc"]["remote"] += rem_left
            if chg_left > 0:
                manufactured[0]["alloc"]["charger"] += chg_left
            if zig_left > 0:
                manufactured[0]["alloc"]["zigbee"] += zig_left

        # Price per parcel = bracket.unit_price, total = sum
        def _price_for_weight(w):
            if w <= 0.0:
                return 0.0
            br = self._lx_find_bracket_for_weight(w, brackets)
            if not br:
                return 0.0
            return float(br.unit_price or 0.0)

        total_price = 0.0
        total_weight = 0.0

        # Manufactured parcels
        for m in manufactured:
            bw = float(m["base_weight"] or 0.0)
            mw = self._lx_raw_weight(motor) * float(m["alloc"]["motor"] or 0)
            rw = self._lx_raw_weight(remote) * float(m["alloc"]["remote"] or 0)
            cw = self._lx_raw_weight(charger) * float(m["alloc"]["charger"] or 0)
            zw = self._lx_raw_weight(zigbee) * float(m["alloc"]["zigbee"] or 0)

            w_total = bw + mw + rw + cw + zw
            total_weight += w_total
            total_price += _price_for_weight(w_total)

        # Grouped accessories parcel
        accessory_weight = sum(float(wa or 0.0) for (_p, _qty_f, wa) in accessory_cart)
        if accessory_weight > 0.0:
            total_weight += accessory_weight
            total_price += _price_for_weight(accessory_weight)

        # Grouped extra tangible parcel
        extra_weight = sum(float(wa or 0.0) for (_p, _qty_f, wa) in extra_cart)
        if extra_weight > 0.0:
            total_weight += extra_weight
            total_price += _price_for_weight(extra_weight)

        if total_weight <= 0.0:
            return 0.0

        return float(total_price)

    # ---------------------------------------------------------
    # Apply/sync carrier (unchanged)
    # ---------------------------------------------------------
    def _lx_apply_delivery_line(self, carrier, price):
        self.ensure_one()
        order = self.sudo()
        carrier = carrier.sudo()

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
        self.ensure_one()
        order = self.sudo()

        carrier = order.carrier_id.sudo() if order.carrier_id else None
        if not carrier:
            return False

        zip_code = (order.partner_shipping_id.zip or "").strip()
        rate = order._lx_lookup_shipping_rate(zip_code)
        if not rate:
            return False

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
        self.ensure_one()
        carrier = carrier.sudo()
        zip_code = (zip_code or (self.partner_shipping_id.zip or "")).strip()
        rate = self._lx_lookup_shipping_rate(zip_code)
        if not rate:
            return 0.0

        name_norm = (carrier.name or "").strip().lower()
        if name_norm == "standard delivery":
            raw = self._lx_compute_standard_price(zip_code=zip_code)
        elif name_norm == "express delivery":
            raw = self._lx_compute_express_price(zip_code=zip_code)
        else:
            return 0.0

        final_price, *_ = self._lx_apply_free_logic(raw)
        return float(final_price or 0.0)


class DeliveryCarrier(models.Model):
    _inherit = "delivery.carrier"

    lx_carrier = fields.Selection(
        selection=[
            ('cathedis', 'CATHEDIS'),
            ('amana',    'AMANA'),
        ],
        string="Carrier",
    )

    def lx_get_checkout_provider_label(self):
        self.ensure_one()
        return (self._fields["lx_carrier"].string or _("Carrier")).strip()

    def lx_get_checkout_provider_value(self):
        self.ensure_one()
        selection = dict(self._fields["lx_carrier"].selection or [])
        value = (selection.get(self.lx_carrier) or "").strip()
        if self.lx_carrier == "cathedis":
            return "Cathedis"
        return value

    def lx_get_checkout_description(self):
        self.ensure_one()
        intro = _("Livraison prioritaire, assurée par") if (self.name or "").strip().lower().startswith("express") else _("Livraison rapide, assurée par")
        provider_label = self.lx_get_checkout_provider_label()
        provider_value = self.lx_get_checkout_provider_value()
        if provider_value:
            return '%s "%s" %s' % (intro, provider_label, provider_value)
        return intro

    def _lx_is_luxtor_dynamic(self):
        self.ensure_one()
        n = (self.name or "").strip().lower()
        return n in ("standard delivery", "express delivery")

    def _lx_dynamic_price_for_order(self, order):
        self.ensure_one()
        if not order or not self._lx_is_luxtor_dynamic():
            return None

        order = order.sudo()
        zip_code = (order.partner_shipping_id.zip or "").strip()

        if order.carrier_id and order.carrier_id.id == self.id:
            order._lx_sync_selected_carrier_delivery_line()
            dl = order.order_line.filtered(lambda l: getattr(l, "is_delivery", False))[:1]
            return float(dl.price_unit or 0.0) if dl else 0.0

        return order._lx_preview_carrier_price(self, zip_code=zip_code)

    def _get_price_available(self, order):
        price = self._lx_dynamic_price_for_order(order)
        if price is not None:
            return price
        return super()._get_price_available(order)

    def rate_shipment(self, order):
        price = self._lx_dynamic_price_for_order(order)
        if price is not None:
            return {"success": True, "price": price, "error_message": False, "warning_message": False}
        return super().rate_shipment(order)



# # class DeliveryCarrier(models.Model):
# #     _inherit = "delivery.carrier"

# #     bracket_ids = fields.One2many("delivery.bracket.lx", "carrier_id", string="Weight Brackets")
# #     intra_bracket_ids = fields.One2many(
# #         "delivery.bracket.lx", "carrier_id", string="Intracity Brackets", domain=[("kind", "=", "intra")]
# #     )
# #     inter_bracket_ids = fields.One2many(
# #         "delivery.bracket.lx", "carrier_id", string="Intercity Brackets", domain=[("kind", "=", "inter")]
# #     )

# #     # ------------------------- helpers -------------------------
# #     def _lx_get_free_threshold(self):
# #         ICP = self.env["ir.config_parameter"].sudo()
# #         try:
# #             return float(ICP.get_param("luxtor.lx_free_amount_order") or 0.0)
# #         except Exception:
# #             return 0.0

# #     def _lx_is_countable_product(self, product):
# #         """Only count storable/consumable items. Services are excluded."""
# #         # FIX: Odoo standard types are: product/consu/service
# #         return bool(product and product.type in ("product", "consu"))

# #     def _lx_raw_weight(self, product):
# #         """Return product.weight as float, or 0.0 if missing/invalid."""
# #         try:
# #             return float(product.weight or 0.0)
# #         except Exception:
# #             return 0.0

# #     def _lx_is_bom_product(self, product):
# #         """True if product has an MRP BoM (template or variant)."""
# #         if not product:
# #             return False
# #         if hasattr(product, "bom_count") and product.bom_count:
# #             return True
# #         tmpl = product.product_tmpl_id
# #         return bool((getattr(product, "bom_ids", False) and product.bom_ids) or (tmpl and tmpl.bom_ids))

# #     def _lx_pick_brackets(self, is_intracity):
# #         self.ensure_one()
# #         kind = "intra" if is_intracity else "inter"
# #         return self.env["delivery.bracket.lx"].search(
# #             [("carrier_id", "=", self.id), ("kind", "=", kind)], order="max_kg asc"
# #         )

# #     def _lx_find_bracket_for_weight(self, unit_weight, brackets):
# #         """Find bracket where min_kg <= unit_weight <= max_kg; fallback to highest."""
# #         chosen = None
# #         for b in brackets:
# #             if (b.min_kg or 0.0) <= unit_weight <= (b.max_kg or 0.0):
# #                 chosen = b
# #                 break
# #         if not chosen and brackets:
# #             chosen = brackets[-1]
# #         return chosen

# #     def _lx_is_standard_delivery(self):
# #         """Name-based, because you said you will create 2 methods: Standard + Express."""
# #         return (self.name or "").strip().lower() == "standard delivery"

# #     # ------------------------- CITY compute (Standard) -------------------------
# #     def _lx_compute_city_rate_for_order(self, order, shipping_rate):
# #         """
# #         Standard Delivery => City/ZIP price stored in shipping.rate.price
# #         Standard is NOT free by default.
# #         Free only if order.amount_total >= threshold (keeps your existing config behavior).
# #         """
# #         self.ensure_one()

# #         amount_total = float(order.amount_total or 0.0)
# #         free_threshold = self._lx_get_free_threshold()
# #         zip_code = (order.partner_shipping_id.zip or "").strip()

# #         raw_price = float(getattr(shipping_rate, "price", 0.0) or 0.0)

# #         free_applied = bool(free_threshold and amount_total >= free_threshold)
# #         final_price = 0.0 if free_applied else raw_price
# #         free_reason = "order_amount_over_threshold" if free_applied else None

# #         debug = {
# #             "zip": zip_code,
# #             "is_intracity": bool(getattr(shipping_rate, "is_intracity", False)),
# #             "free_threshold": free_threshold,
# #             "amount_total": amount_total,
# #             "free_applied": free_applied,
# #             "free_reason": free_reason,
# #             "formula": "CITY price from shipping.rate.price (Standard Delivery)",
# #             "calc": {"raw_price": raw_price, "final_price": final_price},
# #             "carrier_id": self.id,
# #             "carrier_name": self.name,
# #             "order_lines": [],
# #         }
# #         return final_price, debug

# #     # ------------------------- WEIGHT compute (Express) -------------------------
# #     def _lx_order_lines_snapshot(self, order, is_intra, brackets):
# #         rows = []
# #         non_bom_total_weight = 0.0

# #         for line in order.order_line:
# #             if line.display_type or not line.product_id:
# #                 continue
# #             p = line.product_id
# #             qty = float(line.product_uom_qty or 0.0)

# #             # 1) Exclude services
# #             if not self._lx_is_countable_product(p):
# #                 rows.append({
# #                     "product": p.display_name,
# #                     "has_bom": False,
# #                     "qty": qty,
# #                     "unit_weight_for_bracket": 0.0,
# #                     "bracket": None,
# #                     "per_unit_shipping_price": 0.0,
# #                     "line_shipping": 0.0,
# #                     "note": "ignored (service type)"
# #                 })
# #                 continue

# #             w = self._lx_raw_weight(p)

# #             # 2) Ignore lines with missing/zero weight
# #             if w <= 0.0:
# #                 rows.append({
# #                     "product": p.display_name,
# #                     "has_bom": self._lx_is_bom_product(p),
# #                     "qty": qty,
# #                     "unit_weight_for_bracket": 0.0,
# #                     "bracket": None,
# #                     "per_unit_shipping_price": 0.0,
# #                     "line_shipping": 0.0,
# #                     "note": "ignored (no weight)"
# #                 })
# #                 continue

# #             has_bom = self._lx_is_bom_product(p)
# #             if not has_bom:
# #                 # Non-BoM with positive weight → aggregate later
# #                 non_bom_total_weight += w * qty
# #                 rows.append({
# #                     "product": p.display_name,
# #                     "has_bom": False,
# #                     "qty": qty,
# #                     "unit_weight_for_bracket": 0.0,
# #                     "bracket": None,
# #                     "per_unit_shipping_price": 0.0,
# #                     "line_shipping": 0.0,
# #                     "note": "aggregated later (no BoM, weight>0)",
# #                 })
# #                 continue

# #             # BoM product with positive unit weight → priced per unit
# #             unit_w = w  # quantity ignored for bracket selection
# #             br = self._lx_find_bracket_for_weight(unit_w, brackets)
# #             per_unit_price = float(br.unit_price or 0.0) if br else 0.0
# #             line_total = per_unit_price * qty

# #             rows.append({
# #                 "product": p.display_name,
# #                 "has_bom": True,
# #                 "qty": qty,
# #                 "unit_weight_for_bracket": unit_w,
# #                 "bracket": br and {
# #                     "min_kg": float(br.min_kg or 0.0),
# #                     "max_kg": float(br.max_kg or 0.0),
# #                     "unit_price": per_unit_price,
# #                 } or None,
# #                 "per_unit_shipping_price": per_unit_price,
# #                 "line_shipping": line_total,
# #                 "note": "counted (BoM, weight>0)",
# #             })

# #         # Add a single aggregated row for all non-BoM items (1 unit at summed weight)
# #         if non_bom_total_weight > 0.0:
# #             br = self._lx_find_bracket_for_weight(non_bom_total_weight, brackets)
# #             aggregated_unit_price = float(br.unit_price or 0.0) if br else 0.0
# #             rows.append({
# #                 "product": "Non-BoM aggregated",
# #                 "has_bom": False,
# #                 "qty": 1.0,
# #                 "unit_weight_for_bracket": non_bom_total_weight,
# #                 "bracket": br and {
# #                     "min_kg": float(br.min_kg or 0.0),
# #                     "max_kg": float(br.max_kg or 0.0),
# #                     "unit_price": aggregated_unit_price,
# #                 } or None,
# #                 "per_unit_shipping_price": aggregated_unit_price,
# #                 "line_shipping": aggregated_unit_price,
# #                 "note": "counted as 1 unit (sum of non-BoM weights)",
# #             })

# #         return rows

# #     def _lx_compute_rate_for_order(self, order, shipping_rate):
# #         """
# #         EXPRESS (weight):
# #         - Uses intracity/intercity brackets based on shipping_rate.is_intracity
# #         - Services excluded, zero-weight ignored
# #         - BoM products per unit, non-BoM aggregated
# #         - Free shipping by threshold (kept as-is; controller decides Standard vs Express)
# #         """
# #         self.ensure_one()
# #         amount_total = float(order.amount_total or 0.0)
# #         free_threshold = self._lx_get_free_threshold()
# #         zip_code = (order.partner_shipping_id.zip or "").strip()
# #         is_intra = bool(getattr(shipping_rate, "is_intracity", False))

# #         # Compute per-line and sum
# #         brackets = self._lx_pick_brackets(is_intra)
# #         if not brackets:
# #             raise UserError(_("No %s weight brackets found on carrier '%s'.") % (
# #                 "Intracity" if is_intra else "Intercity", self.name))

# #         raw_total = 0.0
# #         per_line_debug = []
# #         non_bom_total_weight = 0.0

# #         for line in order.order_line:
# #             if line.display_type or not line.product_id:
# #                 continue
# #             p = line.product_id
# #             qty = float(line.product_uom_qty or 0.0)

# #             # Exclude services
# #             if not self._lx_is_countable_product(p):
# #                 per_line_debug.append({
# #                     "product": p.display_name,
# #                     "has_bom": False,
# #                     "qty": qty,
# #                     "unit_weight_for_bracket": 0.0,
# #                     "bracket": None,
# #                     "per_unit_shipping_price": 0.0,
# #                     "line_shipping": 0.0,
# #                     "note": "ignored (service type)"
# #                 })
# #                 continue

# #             w = self._lx_raw_weight(p)

# #             # Ignore lines with no/zero weight
# #             if w <= 0.0:
# #                 per_line_debug.append({
# #                     "product": p.display_name,
# #                     "has_bom": self._lx_is_bom_product(p),
# #                     "qty": qty,
# #                     "unit_weight_for_bracket": 0.0,
# #                     "bracket": None,
# #                     "per_unit_shipping_price": 0.0,
# #                     "line_shipping": 0.0,
# #                     "note": "ignored (no weight)"
# #                 })
# #                 continue

# #             if not self._lx_is_bom_product(p):
# #                 # Non-BoM: accumulate total weight (to charge once)
# #                 non_bom_total_weight += w * qty
# #                 per_line_debug.append({
# #                     "product": p.display_name,
# #                     "has_bom": False,
# #                     "qty": qty,
# #                     "unit_weight_for_bracket": 0.0,
# #                     "bracket": None,
# #                     "per_unit_shipping_price": 0.0,
# #                     "line_shipping": 0.0,
# #                     "note": "aggregated later (no BoM, weight>0)"
# #                 })
# #                 continue

# #             # BoM product: per-unit pricing with positive unit weight
# #             unit_w = w
# #             br = self._lx_find_bracket_for_weight(unit_w, brackets)
# #             if not br:
# #                 raise UserError(_("No matching bracket for unit weight %.2f kg on '%s'.") % (unit_w, self.name))
# #             per_unit_price = float(br.unit_price or 0.0)
# #             line_total = per_unit_price * qty
# #             raw_total += line_total

# #             per_line_debug.append({
# #                 "product": p.display_name,
# #                 "has_bom": True,
# #                 "qty": qty,
# #                 "unit_weight_for_bracket": unit_w,
# #                 "bracket": {
# #                     "min_kg": float(br.min_kg or 0.0),
# #                     "max_kg": float(br.max_kg or 0.0),
# #                     "unit_price": per_unit_price,
# #                 },
# #                 "per_unit_shipping_price": per_unit_price,
# #                 "line_shipping": line_total,
# #                 "note": "counted (BoM, weight>0)",
# #             })

# #         # Aggregate non-BoM products as a single package by summed total weight
# #         if non_bom_total_weight > 0.0:
# #             br = self._lx_find_bracket_for_weight(non_bom_total_weight, brackets)
# #             if not br:
# #                 raise UserError(_("No matching bracket for total non-BoM weight %.2f kg on '%s'.") % (non_bom_total_weight, self.name))
# #             aggregated_price = float(br.unit_price or 0.0) * 1.0
# #             raw_total += aggregated_price
# #             per_line_debug.append({
# #                 "product": "Non-BoM aggregated",
# #                 "has_bom": False,
# #                 "qty": 1.0,
# #                 "unit_weight_for_bracket": non_bom_total_weight,
# #                 "bracket": {
# #                     "min_kg": float(br.min_kg or 0.0),
# #                     "max_kg": float(br.max_kg or 0.0),
# #                     "unit_price": float(br.unit_price or 0.0),
# #                 },
# #                 "per_unit_shipping_price": float(br.unit_price or 0.0),
# #                 "line_shipping": aggregated_price,
# #                 "note": "counted as 1 unit (sum of non-BoM weights)",
# #             })

# #         free_applied = bool(free_threshold and amount_total >= free_threshold)
# #         final_price = 0.0 if free_applied else raw_total
# #         free_reason = "order_amount_over_threshold" if free_applied else None

# #         debug = {
# #             "zip": zip_code,
# #             "is_intracity": is_intra,
# #             "free_threshold": free_threshold,
# #             "amount_total": amount_total,
# #             "free_applied": free_applied,
# #             "free_reason": free_reason,
# #             "formula": "BoM per-unit sum + aggregated non-BoM total-weight bracket (1 unit) [services excluded; zero-weight ignored]",
# #             "calc": {"raw_price": raw_total, "final_price": final_price},
# #             "carrier_id": self.id,
# #             "carrier_name": self.name,
# #             "order_lines": per_line_debug,
# #         }
# #         return final_price, debug

# #     # ------------------------- compatibility (kept) -------------------------
# #     def rate_shipment(self, order):
# #         """
# #         Keep compatibility:
# #         - For Standard: return CITY price
# #         - For others: return WEIGHT price
# #         - If missing zip or missing shipping.rate => fallback to super
# #         """
# #         res = super().rate_shipment(order)
# #         try:
# #             zip_code = (order.partner_shipping_id.zip or "").strip()
# #             if not zip_code:
# #                 return res

# #             shipping_rate = self.env["shipping.rate"].sudo().search([("zip_code", "=", zip_code)], limit=1)
# #             if not shipping_rate:
# #                 return res

# #             if self._lx_is_standard_delivery():
# #                 price, _ = self._lx_compute_city_rate_for_order(order, shipping_rate)
# #             else:
# #                 price, _ = self._lx_compute_rate_for_order(order, shipping_rate)

# #             return {"success": True, "price": price, "warning_message": False, "carrier_id": self.id}
# #         except Exception as e:
# #             return {"success": False, "price": 0.0, "error_message": str(e), "carrier_id": self.id}

# #     # ------------------------- bracket rules generation (kept) -------------------------
# #     def _ensure_defaults_if_empty(self, kind):
# #         """
# #         NEW RULE: No hardcoded defaults.
# #         Do not auto-create brackets.
# #         """
# #         self.ensure_one()
# #         target = self.intra_bracket_ids if kind == "intra" else self.inter_bracket_ids
# #         if not target:
# #             raise UserError(_("No %s brackets found on carrier '%s'. Please configure brackets manually.") % (
# #                 "Intracity" if kind == "intra" else "Intercity", self.name
# #             ))

# #     def _generate_rules_from_kind(self, kind):
# #         self.ensure_one()
# #         self._ensure_defaults_if_empty(kind)
# #         brackets = self.bracket_ids.filtered(lambda b: b.kind == kind).sorted(key=lambda b: b.max_kg)
# #         if not brackets:
# #             raise UserError(_("No brackets found to generate rules."))
# #         self.price_rule_ids.filtered(lambda r: r.variable == "weight").unlink()
# #         self.env["delivery.price.rule"].create([{
# #             "carrier_id": self.id, "variable": "weight", "operator": "<=",
# #             "max_value": b.max_kg, "list_base_price": 0.0, "list_price": b.unit_price,
# #         } for b in brackets])

# #     def action_generate_intra_rules(self):
# #         for c in self:
# #             c._generate_rules_from_kind("intra")
# #         return True

# #     def action_generate_inter_rules(self):
# #         for c in self:
# #             c._generate_rules_from_kind("inter")
# #         return True
