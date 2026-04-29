# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ReportLuxtorShipmentLabel(models.AbstractModel):
    _name = "report.luxtor_custom.report_luxtor_shipment_label"
    _description = "Luxtor Shipment Label (from Production Monitor Line)"

    @api.model
    def _get_report_values(self, docids, data=None):
        Line = self.env["luxtor.production.monitor.line"].sudo()
        docs = Line.browse(docids).exists()

        def _partner_from_so(so):
            if not so:
                return self.env["res.partner"]
            # prefer shipping contact if available
            if "partner_shipping_id" in so._fields and so.partner_shipping_id:
                return so.partner_shipping_id
            return so.partner_id

        def _format_address(p):
            if not p:
                return ""
            parts = [p.street or "", p.street2 or ""]
            parts = [x.strip() for x in parts if x and x.strip()]
            return ", ".join(parts)

        def _weight_display(mo):
            w = _compute_weight_kg(mo)  # your existing function
            if not w or w <= 0:
                return "NC"
            return f"{w:.2f} KG"

        def _compute_weight_kg(mo):
            """
            Weight = sum(component_weight * qty)
            Uses raw moves as "components".
            """
            if not mo:
                return 0.0

            total = 0.0
            moves = mo.move_raw_ids if "move_raw_ids" in mo._fields else self.env["stock.move"]
            for mv in moves:
                product = mv.product_id
                if not product:
                    continue

                w = float(getattr(product, "weight", 0.0) or 0.0)

                # pick a qty field that exists and makes sense
                qty = 0.0
                if "quantity_done" in mv._fields and mv.quantity_done:
                    qty = float(mv.quantity_done)
                else:
                    qty = float(mv.product_uom_qty or 0.0)

                total += w * qty

            # keep nice rounding for label
            return round(total, 2)

        # Pre-compute "package x/total" by Sale Order
        lines_by_so = {}
        for ln in docs:
            so = ln.sale_order_id
            if so:
                lines_by_so.setdefault(so.id, self.env["luxtor.production.monitor.line"])
                lines_by_so[so.id] |= ln

        # Expand each SO group to all lines of that SO (so total is correct)
        # If you prefer: restrict to same monitor_id only, change the domain.
        for ln in docs:
            so = ln.sale_order_id
            if not so:
                continue
            all_lines = Line.search([("sale_order_id", "=", so.id)], order="sequence asc, id asc")
            lines_by_so[so.id] = all_lines

        values_by_id = {}

        for ln in docs:
            mo = ln.production_id
            so = ln.sale_order_id
            partner = _partner_from_so(so)

            # Package ratio
            package_ratio = ""
            if so and so.id in lines_by_so:
                group = lines_by_so[so.id]
                total = len(group)
                idx = 1
                # find position of current line in group order
                for i, gl in enumerate(group):
                    if gl.id == ln.id:
                        idx = i + 1
                        break
                package_ratio = f"{idx}/{total}" if total else ""

            # Dimensions from MO (your Luxtor fields)
            w_m = float(getattr(mo, "lx_width_m", 0.0) or 0.0) if mo else 0.0
            h_m = float(getattr(mo, "lx_height_m", 0.0) or 0.0) if mo else 0.0

            # Product details (variant display name)
            product_name = (mo.product_id.display_name or "") if (mo and mo.product_id) else ""

            # Package details string exactly like your Excel sample
            package_details = product_name
            if w_m or h_m:
                package_details = f"{package_details}\nWidth : {w_m:.2f} m , Height : {h_m:.2f}"

            # Date (MO)
            date_val = False
            for fname in ("date_start", "date_planned_start", "scheduled_date", "create_date"):
                if mo and fname in mo._fields and getattr(mo, fname):
                    date_val = getattr(mo, fname)
                    break
            date_str = ""
            if date_val:
                # render in user tz
                date_str = fields.Datetime.context_timestamp(self.env.user, date_val).strftime("%d/%m/%Y")

            values_by_id[ln.id] = {
                "mo_name": mo.name if mo else "",
                "date_str": date_str,
                "package_ratio": package_ratio,
                "package_details": package_details,

                "to_name": partner.name or "",
                "to_address": _format_address(partner),
                "to_city": partner.city or "",
                "to_zip": partner.zip or "",
                "to_phone": partner.phone or partner.mobile or "",

                "weight_kg": _compute_weight_kg(mo),
                "weight_display": _weight_display(mo),
            }

        return {
            "doc_ids": docs.ids,
            "doc_model": "luxtor.production.monitor.line",
            "docs": docs,
            "values_by_id": values_by_id,
        }
