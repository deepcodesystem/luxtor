# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import re

class LxDimensionsController(http.Controller):

    # ---------- small helpers ----------
    def _convert_to_meters(self, value, unit):
        try:
            v = float(value or 0.0)
        except Exception:
            v = 0.0
        if unit == "m":
            return v
        if unit == "cm":
            return v / 100.0
        if unit == "mm":
            return v / 1000.0
        return v

    def _fmt_unit(self, value_m, unit="m"):
        decimals = 2 if unit == "m" else 0
        try:
            v = float(value_m or 0.0)
        except Exception:
            v = 0.0
        return f"{v:.{decimals}f} {unit}"

    def _extract_code_from_roller_name(self, name):
        # e.g. "[QM21-01] Roller Blind" -> "QM21-01"
        if not name:
            return False
        m = re.search(r'\[([^\]]+)\]\s*Roller\s*Blind', name, flags=re.IGNORECASE)
        return m.group(1).strip() if m else False

    def _max_width_m_for_template(self, tmpl):
        """Take max width from fabric.roller_width_ids (value_cm) if any,
        else fallback to tmpl.width_cm (m)."""
        if not tmpl:
            return 0.0

        # Prefer explicit fabric link when available
        fabric = getattr(tmpl, "lx_fabric_ref_id", False)
        if not fabric:
            # fallback: try to resolve fabric by default_code in name
            code = self._extract_code_from_roller_name(tmpl.name or "")
            if code:
                fabric = request.env["product.template"].sudo().search([("default_code", "=", code)], limit=1)

        # 1) fabric widths
        if fabric and hasattr(fabric, "roller_width_ids") and fabric.roller_width_ids:
            vals_cm = [float(getattr(rec, "value_cm", 0.0) or 0.0) for rec in fabric.roller_width_ids.sudo()]
            vals_cm = [v for v in vals_cm if v > 0]
            if vals_cm:
                return max(vals_cm) / 100.0

        # 2) fallback: legacy template width_cm
        if hasattr(tmpl, "width_cm") and tmpl.width_cm:
            return max(0.0, float(tmpl.width_cm) / 100.0)

        return 0.0

    def _max_height_m_for_template(self, tmpl, width_m):
        """Dynamic max height — mirrors lx_product_configurator._lx_max_height_for_width."""
        try:
            width_cm = float(width_m or 0.0) * 100.0
            if width_cm <= 0:
                return float(getattr(tmpl, "max_height", 0.0) or 0.0)

            fabric = getattr(tmpl, "lx_fabric_ref_id", False)
            weight = float(
                getattr(fabric, "lx_weight", 0.0) or getattr(tmpl, "lx_weight", 0.0) or 0.0
            )

            # Use same mechanism search as configurator: lx_is_roller_mechanism flag
            mech = request.env["product.template"].sudo().search(
                [("lx_is_roller_mechanism", "=", True)], limit=1
            )
            load = float(getattr(mech, "maximum_load", 0.0) or 0.0)

            if not (load and weight):
                return float(getattr(tmpl, "max_height", 0.0) or 0.0)

            h = (load / (width_cm * weight)) * 100_000.0

            # Day & Night uses half the load capacity
            if getattr(tmpl, "lx_is_day_night", False):
                h /= 2.0

            return round(max(0.0, h), 2)
        except Exception:
            return float(getattr(tmpl, "max_height", 0.0) or 0.0)

    # ---------- route ----------
    @http.route("/lx/dimensions/hints", type="json", auth="public", website=True, csrf=False)
    def dimensions_hints(self, product_id=None, product_tmpl_id=None, width=None, unit="m"):
        """Return min/max + hint strings for width/height, reusing the wizard logic."""
        env = request.env
        Product = env["product.product"].sudo()
        Template = env["product.template"].sudo()

        # Resolve template
        tmpl = None
        variant_id = int(product_id or 0)
        tmpl_id = int(product_tmpl_id or 0)
        if variant_id:
            prod = Product.browse(variant_id)
            if prod.exists():
                tmpl = prod.product_tmpl_id
        if not tmpl and tmpl_id:
            t = Template.browse(tmpl_id)
            tmpl = t if t.exists() else None

        if not tmpl:
            return {"ok": False, "error": "product_template_not_found"}

        # Inputs & constants
        width_m = self._convert_to_meters(width, unit or "m")
        min_w_m = 0.60
        min_h_m = 0.90

        # Compute maximums
        max_w_m = self._max_width_m_for_template(tmpl)
        if width_m > 0:
            max_h_m = self._max_height_m_for_template(tmpl, width_m)
        else:
            # No width entered yet — compute with reference width 1.0 m so hint is dynamic
            max_h_m = self._max_height_m_for_template(tmpl, 1.0)

        # Build hint strings in meters
        width_hint  = f"min: {self._fmt_unit(min_w_m, 'm')}" + (f" / max: {self._fmt_unit(max_w_m, 'm')}" if max_w_m > 0 else "")
        height_hint = f"min: {self._fmt_unit(min_h_m, 'm')}" + (f" / max: {self._fmt_unit(max_h_m, 'm')}" if max_h_m > 0 else "")

        return {
            "ok": True,
            "product": {"tmpl_id": tmpl.id, "name": tmpl.name},
            "width":  {"min_m": min_w_m, "max_m": max_w_m, "hint": width_hint},
            "height": {"min_m": min_h_m, "max_m": max_h_m, "hint": height_hint},
        }
