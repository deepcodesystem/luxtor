# -*- coding: utf-8 -*-
from odoo import api, fields, models
import re

class ProductTemplate(models.Model):
    _inherit = "product.template"

    def _lx_extract_code_from_roller_name(self, name):
        if not name:
            return False
        m = re.search(r'\[([^\]]+)\]\s*Roller\s*Blind', name, flags=re.IGNORECASE)
        return m.group(1).strip() if m else False

    def _lx_max_width_m_from_fabric_or_tmpl(self):
        """Return dict {tmpl_id: max_w_m}."""
        res = {}
        for tmpl in self:
            max_w_m = 0.0
            fabric = getattr(tmpl, "lx_fabric_ref_id", False)
            if not fabric:
                code = tmpl._lx_extract_code_from_roller_name(tmpl.name or "")
                if code:
                    fabric = self.env["product.template"].sudo().search([("default_code", "=", code)], limit=1)

            if fabric and getattr(fabric, "roller_width_ids", False):
                vals_cm = [float(getattr(rec, "value_cm", 0.0) or 0.0) for rec in fabric.roller_width_ids.sudo()]
                vals_cm = [v for v in vals_cm if v > 0]
                if vals_cm:
                    max_w_m = max(vals_cm) / 100.0

            if not max_w_m and getattr(tmpl, "width_cm", False):
                try:
                    max_w_m = max(0.0, float(tmpl.width_cm or 0.0) / 100.0)
                except Exception:
                    max_w_m = 0.0
            res[tmpl.id] = max_w_m
        return res

    def _lx_max_height_from_width(self, width_m):
        """Return dict {tmpl_id: max_h_m} computed via mechanism load & fabric weight;
        fallback to tmpl.max_height when inputs are insufficient.
        """
        res = {}
        mech = self.env["product.template"].sudo().search([("default_code", "=", "MS")], limit=1)
        load = float(getattr(mech, "maximum_load", 0.0) or 0.0)

        for tmpl in self:
            divisor = 1.0
            cat = getattr(tmpl, "categ_id", False)
            if cat and "Day & Night" in (cat.name or ""):
                divisor = 2.0

            fabric = getattr(tmpl, "lx_fabric_ref_id", False)
            weight = float((getattr(fabric, "lx_weight", 0.0) or getattr(tmpl, "lx_weight", 0.0) or 0.0))
            width_cm = max(0.0, float(width_m or 0.0) * 100.0)

            if width_cm <= 0.0 or weight <= 0.0 or load <= 0.0 or divisor <= 0.0:
                try:
                    res[tmpl.id] = float(getattr(tmpl, "max_height", 0.0) or 0.0)
                except Exception:
                    res[tmpl.id] = 0.0
                continue

            # Same formula you already use
            h_m = (load / (width_cm * weight)) / divisor * 100000.0
            res[tmpl.id] = max(0.0, round(h_m, 4))
        return res

    @api.model
    def lx_dimensions_hints_backend(self, product_id=None, product_tmpl_id=None, width_m=None, unit="m"):
        """Backend-safe: return the same structure as /lx/dimensions/hints, but via call_kw."""
        Product = self.env["product.product"].sudo()
        Template = self.env["product.template"].sudo()

        tmpl = None
        if product_id:
            p = Product.browse(int(product_id))
            if p.exists():
                tmpl = p.product_tmpl_id
        if not tmpl and product_tmpl_id:
            t = Template.browse(int(product_tmpl_id))
            tmpl = t if t.exists() else None

        if not tmpl:
            return {"ok": False, "error": "product_template_not_found"}

        # constants (meters)
        min_w_m = 0.60
        min_h_m = 0.90

        # compute maximums
        max_w_map = tmpl._lx_max_width_m_from_fabric_or_tmpl()
        max_w_m = max_w_map.get(tmpl.id, 0.0)

        if width_m and float(width_m or 0.0) > 0:
            max_h_map = tmpl._lx_max_height_from_width(float(width_m))
            max_h_m = max_h_map.get(tmpl.id, 0.0)
        else:
            try:
                max_h_m = float(getattr(tmpl, "max_height", 0.0) or 0.0)
            except Exception:
                max_h_m = 0.0

        # hints
        def _fmt(v):
            return f"{float(v or 0.0):.2f} m"

        width_hint  = f"min: {_fmt(min_w_m)}" + (f" / max: {_fmt(max_w_m)}" if max_w_m > 0 else "")
        height_hint = f"min: {_fmt(min_h_m)}" + (f" / max: {_fmt(max_h_m)}" if max_h_m > 0 else "")

        return {
            "ok": True,
            "product": {"tmpl_id": tmpl.id, "name": tmpl.name},
            "width":  {"min_m": min_w_m, "max_m": max_w_m, "hint": width_hint},
            "height": {"min_m": min_h_m, "max_m": max_h_m, "hint": height_hint},
        }
