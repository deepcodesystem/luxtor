# -*- coding: utf-8 -*-
import logging
from datetime import datetime, time

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


# ============================================================
# Helpers
# ============================================================
def _lx_monitor_state_from_mo_state(mo_state):
    """
    Map mrp.production.state -> luxtor monitor line state

    Requested mapping:
      - not_started  <= draft
      - in_works     <= confirmed
      - complete     <= done

    Practical reality on Odoo:
      - some DBs use progress/to_close too => treat them as in_works
      - cancel => not_started (you didn't ask for a 4th state)
    """
    st = (mo_state or "").strip()
    if st == "done":
        return "complete"
    if st in ("confirmed", "progress", "to_close"):
        return "in_works"
    return "not_started"
    


class LuxtorProductionMonitor(models.Model):
    _name = "luxtor.production.monitor"
    _description = "Luxtor Production Monitor"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"

    name = fields.Char(default="Production Monitor", readonly=True, tracking=True)
    date = fields.Date(required=True, default=fields.Date.context_today, tracking=True)

    line_ids = fields.One2many(
        "luxtor.production.monitor.line",
        "monitor_id",
        string="Lines",
        copy=False,
    )

    def action_generate(self):
        """
        Use EXACT mrp.production.date_start (Scheduled Date / Start).
        - Filter MOs whose date_start is within the selected day.
        - Fallback: if date_start is empty, use create_date day.
        - Post debug info in chatter.
        - Assigns sequence based on ordering:
            Date(MO) / Priority / Product / Roll width
        - Then recompute line_no as Excel-like: total..1 (DESC)
        """
        Mrp = self.env["mrp.production"].sudo()
        Sale = self.env["sale.order"].sudo()
        Line = self.env["luxtor.production.monitor.line"].sudo()

        if "date_start" not in Mrp._fields:
            raise UserError(_("Field date_start not found on Manufacturing Order in this database."))

        for monitor in self:
            if not monitor.date:
                raise UserError(_("Please select a date."))

            prev = len(monitor.line_ids)
            monitor.line_ids.unlink()

            day_start = datetime.combine(monitor.date, time.min)
            day_end = datetime.combine(monitor.date, time.max)
            start_s = fields.Datetime.to_string(day_start)
            end_s = fields.Datetime.to_string(day_end)

            domain = [
                "|",
                "&",
                ("date_start", ">=", start_s),
                ("date_start", "<=", end_s),
                "&",
                ("date_start", "=", False),
                "&",
                ("create_date", ">=", start_s),
                ("create_date", "<=", end_s),
            ]

            productions = Mrp.search(domain, order="date_start asc, create_date asc, id asc")

            rows = []
            so_missing = 0
            pr_rank = {"express": 0, "normal": 1}  # Express first

            for mo in productions:
                so = mo.sale_line_id.order_id if getattr(mo, "sale_line_id", False) else False
                if not so and mo.origin:
                    so = Sale.search([("name", "=", mo.origin)], limit=1)

                if not so:
                    so_missing += 1

                # default state from MO
                line_state = _lx_monitor_state_from_mo_state(mo.state)

                mo_dt = mo.date_start or mo.create_date or False
                pr = "express" if (so and getattr(so, "priority", False) == "special") else "normal"
                product_name = (mo.product_id.display_name or "") if mo.product_id else ""

                roll_w = 0.0
                if "lx_roll_width_best" in mo._fields:
                    roll_w = float(getattr(mo, "lx_roll_width_best") or 0.0)

                rows.append({
                    "mo": mo,
                    "so": so,
                    "state": line_state,
                    "mo_dt": mo_dt,
                    "pr_rank": pr_rank.get(pr, 9),
                    "product_name": product_name,
                    "roll_width": roll_w,
                })

            rows.sort(key=lambda r: (
                r["mo_dt"] or datetime.min,
                r["pr_rank"],
                r["product_name"],
                r["roll_width"],
                r["mo"].id,
            ))

            vals_list = []
            seq = 1
            for r in rows:
                vals_list.append({
                    "monitor_id": monitor.id,
                    "production_id": r["mo"].id,
                    "sale_order_id": r["so"].id if r["so"] else False,
                    "state": r["state"],     # keep field set for backward compatibility
                    "sequence": seq,         # stored ordering key
                })
                seq += 1

            created = 0
            if vals_list:
                Line.create(vals_list)
                created = len(vals_list)

                # IMPORTANT: recompute and WRITE line_no
                monitor.line_ids._lx_recompute_line_numbers_for_monitors(monitor)

                # IMPORTANT: sync state after creation (adds delivered logic safely)
                monitor.line_ids._lx_sync_state_from_sources()

            msg = (
                "Generate executed.\n"
                f"- Date: {monitor.date}\n"
                "- Date field: date_start\n"
                f"- Removed previous lines: {prev}\n"
                f"- MOs found: {len(productions)}\n"
                f"- Lines created: {created}\n"
                f"- Sales order not found for: {so_missing}\n"
                f"- Range: {start_s} -> {end_s}"
            )
            monitor.message_post(body=msg)
            _logger.info(msg)

        return True


class LuxtorProductionMonitorLine(models.Model):
    _name = "luxtor.production.monitor.line"
    _description = "Luxtor Production Monitor Line"
    _order = "id desc"

    monitor_id = fields.Many2one(
        "luxtor.production.monitor",
        required=True,
        ondelete="cascade",
        index=True,
    )

    production_id = fields.Many2one(
        "mrp.production",
        string="Manufacturing Order",
        required=True,
        ondelete="cascade",
        index=True,
    )

    # MO reference columns
    mo_ref = fields.Char(related="production_id.name", string="MO Ref", store=True, readonly=True)
    mo_name = fields.Char(related="production_id.name", store=True, readonly=True)  # compatibility

    sale_order_id = fields.Many2one(
        "sale.order",
        string="Sales Order",
        index=True,
    )

    # Keep same field (stored/writable) to NOT break existing views/widgets/logic.
    # Add delivered as 4th value (requested).
    state = fields.Selection(
        [
            ("not_started", "Not Started"),
            ("in_works", "In Works"),
            ("complete", "Complete"),
            ("delivered", "Delivered"),
        ],
        default="not_started",
        required=True,
        index=True,
    )

    # Stored numbering
    sequence = fields.Integer(string="Sequence", default=0, index=True)
    line_no = fields.Integer(string="Line No.", default=0, index=True)  # must be writable

    roll_width = fields.Float(
        string="Roll Width",
        compute="_compute_roll_width",
        store=False,
        readonly=True,
    )

    product_id = fields.Many2one(related="production_id.product_id", store=True, readonly=True)
    mo_state = fields.Selection(related="production_id.state", store=True, readonly=True)

    width_m = fields.Float(string="Width", compute="_compute_dimensions", store=False, readonly=True)
    height_m = fields.Float(string="Height", compute="_compute_dimensions", store=False, readonly=True)

    priority = fields.Selection(
        [
            ("normal", "Normal"),
            ("express", "Express"),
        ],
        string="Priority",
        compute="_compute_priority",
        store=False,
        readonly=True,
    )

    state_color = fields.Integer(string="State Color", compute="_compute_state_color", store=False)

    # ------------------------------------------------------------
    # Sync helpers (do NOT break existing logic)
    # ------------------------------------------------------------
    def _lx_sync_state_from_mo(self):
        """
        Backward-compatible helper: sync from MO only.
        """
        for rec in self:
            mo = rec.production_id
            if not mo:
                continue
            desired = _lx_monitor_state_from_mo_state(mo.state)
            if rec.state != desired:
                rec.sudo().write({"state": desired})

    def _lx_so_is_delivered(self, so):
        """
        Safe detection of "delivered" without assuming a specific module.
        Priority:
          1) sale_stock delivery_status == 'delivered' (if exists)
          2) all outgoing pickings done (if picking_ids exists)
        """
        if not so:
            return False

        if "delivery_status" in so._fields:
            return (so.delivery_status == "delivered")

        if "picking_ids" in so._fields and so.picking_ids:
            outgoing = so.picking_ids.filtered(lambda p: p.picking_type_code == "outgoing")
            return bool(outgoing) and all(p.state == "done" for p in outgoing)

        return False

    def _lx_sync_state_from_sources(self):
        """
        Main sync (keeps existing logic, adds delivered on top):
          - If SO is delivered -> delivered
          - Else follow MO mapping (draft/confirmed/done)
        """
        for rec in self:
            so = rec.sale_order_id
            if rec._lx_so_is_delivered(so):
                desired = "delivered"
            else:
                mo = rec.production_id
                desired = _lx_monitor_state_from_mo_state(mo.state) if mo else "not_started"

            if rec.state != desired:
                rec.sudo().write({"state": desired})

    @api.depends("state")
    def _compute_state_color(self):
        for rec in self:
            if rec.state == "not_started":
                rec.state_color = 1
            elif rec.state == "in_works":
                rec.state_color = 2
            elif rec.state == "complete":
                rec.state_color = 10
            elif rec.state == "delivered":
                rec.state_color = 4
            else:
                rec.state_color = 0

    @api.depends("production_id", "production_id.lx_roll_width_best")
    def _compute_roll_width(self):
        for rec in self:
            rw = 0.0
            mo = rec.production_id
            if mo and "lx_roll_width_best" in mo._fields:
                rw = float(getattr(mo, "lx_roll_width_best") or 0.0)
            rec.roll_width = rw

    @api.depends(
        "production_id",
        "production_id.sale_line_id",
        "production_id.sale_line_id.lx_width_m",
        "production_id.sale_line_id.lx_height_m",
    )
    def _compute_dimensions(self):
        for rec in self:
            w = 0.0
            h = 0.0
            mo = rec.production_id

            if mo:
                if "lx_width_m" in mo._fields:
                    w = float(getattr(mo, "lx_width_m") or 0.0)
                if "lx_height_m" in mo._fields:
                    h = float(getattr(mo, "lx_height_m") or 0.0)

                if (not w or not h) and mo.sale_line_id:
                    w = w or float(mo.sale_line_id.lx_width_m or 0.0)
                    h = h or float(mo.sale_line_id.lx_height_m or 0.0)

            rec.width_m = w
            rec.height_m = h

    @api.depends("sale_order_id.priority")
    def _compute_priority(self):
        for rec in self:
            if rec.sale_order_id and rec.sale_order_id.priority == "special":
                rec.priority = "express"
            else:
                rec.priority = "normal"

    # -----------------------------
    # Line No recomputation (fix)
    # -----------------------------
    def _lx_recompute_line_numbers_for_monitors(self, monitors):
        """
        For each monitor:
        - Take lines ordered by sequence asc (our logical ordering key)
        - Assign line_no = total..1 (DESC like Excel)
        """
        monitors = monitors.filtered(lambda m: m and m.id)
        if not monitors:
            return

        for mon in monitors:
            lines = mon.line_ids.sorted(key=lambda l: (l.sequence or 0, l.id))
            total = len(lines)
            if not total:
                continue

            for idx, line in enumerate(lines):
                new_no = total - idx
                if line.line_no != new_no:
                    line.sudo().write({"line_no": new_no})

    # ------------------------------------------------------------
    # Create/Write hooks (keep your old behavior + sync state)
    # ------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)

        # Keep existing line_no logic
        monitors = recs.mapped("monitor_id")
        recs._lx_recompute_line_numbers_for_monitors(monitors)

        # NEW: ensure initial state matches sources (SO delivered > MO mapping)
        recs._lx_sync_state_from_sources()

        return recs

    def write(self, vals):
        res = super().write(vals)

        # Keep existing line_no logic
        monitors = self.mapped("monitor_id")
        self._lx_recompute_line_numbers_for_monitors(monitors)

        # NEW: sync on relevant changes (keeps old behavior, adds delivered)
        if "production_id" in vals or "sale_order_id" in vals or "state" in vals:
            self._lx_sync_state_from_sources()

        return res

    def unlink(self):
        monitors = self.mapped("monitor_id")
        res = super().unlink()
        self._lx_recompute_line_numbers_for_monitors(monitors)
        return res

    def action_open_mo(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Manufacturing Order"),
            "res_model": "mrp.production",
            "view_mode": "form",
            "res_id": self.production_id.id,
            "target": "current",
        }
    
    def action_open_label(self):
        self.ensure_one()
        return self.env.ref("luxtor_custom.action_report_luxtor_shipment_label").sudo().report_action(self.sudo())




    def action_open_sale_order(self):
        self.ensure_one()
        if not self.sale_order_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("Sales Order"),
            "res_model": "sale.order",
            "view_mode": "form",
            "res_id": self.sale_order_id.id,
            "target": "current",
        }

    def _lx_get_mo_report_action(self):
        self.ensure_one()
        for xmlid in (
            "mrp.action_report_production_order",
            "mrp.action_report_mrp_production",
        ):
            try:
                act = self.env.ref(xmlid)
                if act:
                    return act
            except Exception:
                continue
        return False

    def action_print_production_sheet(self, use_internal_layout=False):
        """Print YOUR custom Production Sheet report for this monitor line."""
        self.ensure_one()
        report = self.env.ref("luxtor_custom.action_report_lx_production_sheet", raise_if_not_found=False)
        ctx = dict(self.env.context or {})
        ctx["lx_use_internal_layout"] = bool(use_internal_layout)
        return report.with_context(ctx).report_action(self)
    
    # ------------------------------------------------------------
    # Delivery Note (CUSTOM, prepared from SO, printed from monitor line)
    # ------------------------------------------------------------
    def _lx_get_related_outgoing_pickings(self):
        """
        Collect outgoing pickings linked to this line's sale_order_id.
        Prefer pickings from the SO; do not assume extra modules.
        """
        self.ensure_one()
        so = self.sale_order_id
        if not so:
            return self.env["stock.picking"]

        if "picking_ids" not in so._fields or not so.picking_ids:
            return self.env["stock.picking"]

        return so.picking_ids.filtered(lambda p: p.picking_type_code == "outgoing")

    def _lx_get_shipping_cost_from_so(self, so):
        """
        Prepared shipping cost from Sale Order (delivery line).
        Works for website orders and backoffice orders.
        """
        if not so:
            return 0.0

        # Standard Odoo: delivery line has is_delivery = True
        if "order_line" in so._fields:
            delivery_lines = so.order_line.filtered(lambda l: getattr(l, "is_delivery", False))
            if delivery_lines:
                # use subtotal to match typical "Shipping Cost" expectation
                return sum(delivery_lines.mapped("price_subtotal"))

        # Fallbacks (if some customization exists)
        if "delivery_price" in so._fields:
            return float(so.delivery_price or 0.0)

        return 0.0

    def _lx_get_cod_amount_from_so(self, so):
        """
        COD amount: keep it simple and stable.
        If you have a dedicated COD field later, swap here.
        """
        if not so:
            return 0.0
        return float(so.amount_total or 0.0)

    def _lx_get_total_packages(self, pickings):
        """
        Total packages:
        - If packages exist on move lines, count unique packages.
        - Else fallback to number of outgoing pickings.
        """
        if not pickings:
            return 0

        packages = self.env["stock.quant.package"]
        for p in pickings:
            # Common: move_line_ids has result_package_id
            if "move_line_ids" in p._fields and p.move_line_ids:
                packages |= p.move_line_ids.mapped("result_package_id")
            # Some versions: package_ids exists
            if "package_ids" in p._fields and p.package_ids:
                packages |= p.package_ids

        packages = packages.filtered(lambda x: x)
        return len(packages) if packages else len(pickings)

    def _lx_prepare_delivery_note_values(self):
        """
        Prepared values for the custom Delivery Note report (like your screenshot).
        """
        self.ensure_one()
        so = self.sale_order_id
        if not so:
            raise UserError(_("No Sales Order linked to this line."))

        # Must be confirmed (NOT draft/sent)
        if so.state not in ("sale", "done"):
            raise UserError(_("Sales Order must be confirmed to print the Delivery Note."))

        outgoing = self._lx_get_related_outgoing_pickings()
        if not outgoing:
            raise UserError(_("No delivery transfer found for this Sales Order."))

        # Prefer delivered pickings, else latest outgoing
        done_pickings = outgoing.filtered(lambda p: p.state == "done")
        pickings_to_use = done_pickings or outgoing

        # stable ordering (latest first)
        pickings_to_use = pickings_to_use.sorted(
            key=lambda p: (p.date_done or p.scheduled_date or p.create_date or p.id),
            reverse=True
        )

        # Contact (shipping contact first, fallback to partner)
        partner = so.partner_shipping_id or so.partner_id

        carrier_name = ""
        if "carrier_id" in so._fields and so.carrier_id:
            carrier_name = so.carrier_id.display_name
        elif pickings_to_use and "carrier_id" in pickings_to_use[0]._fields and pickings_to_use[0].carrier_id:
            carrier_name = pickings_to_use[0].carrier_id.display_name

        shipping_cost = self._lx_get_shipping_cost_from_so(so)
        cod_amount = self._lx_get_cod_amount_from_so(so)
        total_packages = self._lx_get_total_packages(pickings_to_use)

        # What customer ordered (exclude delivery line + display lines)
        order_lines = so.order_line
        order_lines = order_lines.filtered(lambda l: not getattr(l, "display_type", False))
        order_lines = order_lines.filtered(lambda l: not getattr(l, "is_delivery", False))

        return {
            "so": so,
            "partner": partner,
            "pickings": pickings_to_use,
            "carrier_name": carrier_name,
            "total_packages": total_packages,
            "shipping_cost": shipping_cost,
            "cod_amount": cod_amount,
            "order_lines": order_lines,
        }

    def action_print_delivery_note(self):
        """
        Button: print Delivery Note (CUSTOM template).
        - Requires confirmed Sales Order
        - Uses prepared values from SO (carrier, shipping cost, COD)
        - No dependency on MO being done (works with confirmed MOs)
        - Printed from luxtor.production.monitor.line
        """
        self.ensure_one()
        # Validate + ensure values can be prepared (raises user-friendly errors)
        self._lx_prepare_delivery_note_values()

        report = self.env.ref("luxtor_custom.action_report_lx_delivery_note", raise_if_not_found=False)
        if not report:
            raise UserError(_("Delivery Note report action not found."))

        return report.sudo().report_action(self.sudo())


class ReportLuxtorDeliveryNote(models.AbstractModel):
    _name = "report.luxtor_custom.report_lx_delivery_note"
    _description = "Luxtor Delivery Note Report"

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env["luxtor.production.monitor.line"].browse(docids).exists()
        if not docs:
            return {"docs": docs}

        prepared_map = {}
        for d in docs:
            prepared = d._lx_prepare_delivery_note_values()
            so = prepared["so"]

            currency = so.currency_id if "currency_id" in so._fields else self.env.company.currency_id

            # release date: from first picking in prepared pickings list
            release_date = False
            pickings = prepared.get("pickings")
            if pickings:
                p0 = pickings[0]
                dt = (p0.date_done or p0.scheduled_date)
                if dt:
                    # keep it simple (date only)
                    release_date = fields.Date.to_string(fields.Datetime.to_datetime(dt).date())

            prepared_map[d.id] = {
                "so": so,
                "partner": prepared["partner"],
                "pickings": prepared["pickings"],
                "carrier_name": prepared["carrier_name"],
                "total_packages": prepared["total_packages"],
                "shipping_cost": prepared["shipping_cost"],
                "cod_amount": prepared["cod_amount"],
                "order_lines": prepared["order_lines"],
                "currency": currency,
                "release_date": release_date,
            }

        return {
            "doc_ids": docs.ids,
            "doc_model": "luxtor.production.monitor.line",
            "docs": docs,
            "prepared_map": prepared_map,
        }



class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    lx_state_monitoring = fields.Selection(
        [
            ("not_started", "Not Started"),
            ("in_works", "In Works"),
            ("complete", "Complete"),
            ("delivered", "Delivered"),
        ],
        string="State Monitoring",
        compute="_compute_lx_state_monitoring",
        store=False,
        readonly=True,
    )

    @api.depends("order_id")
    def _compute_lx_state_monitoring(self):
        MonitorLine = self.env["luxtor.production.monitor.line"].sudo()

        orders = self.mapped("order_id")
        order_ids = orders.ids

        lines_by_order = {oid: self.env["luxtor.production.monitor.line"] for oid in order_ids}

        if order_ids:
            monitor_lines = MonitorLine.search([("sale_order_id", "in", order_ids)])
            for ml in monitor_lines:
                if ml.sale_order_id:
                    lines_by_order[ml.sale_order_id.id] |= ml

        def _state_from_monitor_lines(lines):
            if not lines:
                return "not_started"

            states = set(lines.mapped("state"))

            # final state
            if states == {"delivered"}:
                return "delivered"

            # if all are finished (complete/delivered), return complete unless all delivered
            if states.issubset({"complete", "delivered"}):
                return "complete"

            if "in_works" in states or "complete" in states or "delivered" in states:
                return "in_works"

            return "not_started"

        for line in self:
            monitor_lines = lines_by_order.get(line.order_id.id)
            line.lx_state_monitoring = _state_from_monitor_lines(monitor_lines)



# # ============================================================
# # Helpers
# # ============================================================
# def _lx_monitor_state_from_mo_state(mo_state):
#     """
#     Map mrp.production.state -> luxtor monitor line state

#     Requested mapping:
#       - not_started  <= draft
#       - in_works     <= confirmed
#       - complete     <= done

#     Practical reality on Odoo:
#       - some DBs use progress/to_close too => treat them as in_works
#       - cancel => not_started (you didn't ask for a 4th state)
#     """
#     st = (mo_state or "").strip()
#     if st == "done":
#         return "complete"
#     if st in ("confirmed", "progress", "to_close"):
#         return "in_works"
#     return "not_started"


# class LuxtorProductionMonitor(models.Model):
#     _name = "luxtor.production.monitor"
#     _description = "Luxtor Production Monitor"
#     _inherit = ["mail.thread", "mail.activity.mixin"]
#     _order = "date desc, id desc"

#     name = fields.Char(default="Production Monitor", readonly=True, tracking=True)
#     date = fields.Date(required=True, default=fields.Date.context_today, tracking=True)

#     line_ids = fields.One2many(
#         "luxtor.production.monitor.line",
#         "monitor_id",
#         string="Lines",
#         copy=False,
#     )

#     def action_generate(self):
#         """
#         Use EXACT mrp.production.date_start (Scheduled Date / Start).
#         - Filter MOs whose date_start is within the selected day.
#         - Fallback: if date_start is empty, use create_date day.
#         - Post debug info in chatter.
#         - Assigns sequence based on ordering:
#             Date(MO) / Priority / Product / Roll width
#         - Then recompute line_no as Excel-like: total..1 (DESC)
#         """
#         Mrp = self.env["mrp.production"].sudo()
#         Sale = self.env["sale.order"].sudo()
#         Line = self.env["luxtor.production.monitor.line"].sudo()

#         if "date_start" not in Mrp._fields:
#             raise UserError(_("Field date_start not found on Manufacturing Order in this database."))

#         for monitor in self:
#             if not monitor.date:
#                 raise UserError(_("Please select a date."))

#             prev = len(monitor.line_ids)
#             monitor.line_ids.unlink()

#             day_start = datetime.combine(monitor.date, time.min)
#             day_end = datetime.combine(monitor.date, time.max)
#             start_s = fields.Datetime.to_string(day_start)
#             end_s = fields.Datetime.to_string(day_end)

#             domain = [
#                 "|",
#                 "&",
#                 ("date_start", ">=", start_s),
#                 ("date_start", "<=", end_s),
#                 "&",
#                 ("date_start", "=", False),
#                 "&",
#                 ("create_date", ">=", start_s),
#                 ("create_date", "<=", end_s),
#             ]

#             # Pull candidates; final ordering computed below
#             productions = Mrp.search(domain, order="date_start asc, create_date asc, id asc")

#             rows = []
#             so_missing = 0
#             pr_rank = {"express": 0, "normal": 1}  # Express first

#             for mo in productions:
#                 so = mo.sale_line_id.order_id if getattr(mo, "sale_line_id", False) else False
#                 if not so and mo.origin:
#                     so = Sale.search([("name", "=", mo.origin)], limit=1)

#                 if not so:
#                     so_missing += 1

#                 # UPDATED: state is now synced with MO state (draft/confirmed/done)
#                 line_state = _lx_monitor_state_from_mo_state(mo.state)

#                 mo_dt = mo.date_start or mo.create_date or False
#                 pr = "express" if (so and getattr(so, "priority", False) == "special") else "normal"
#                 product_name = (mo.product_id.display_name or "") if mo.product_id else ""

#                 roll_w = 0.0
#                 if "lx_roll_width_best" in mo._fields:
#                     roll_w = float(getattr(mo, "lx_roll_width_best") or 0.0)

#                 rows.append({
#                     "mo": mo,
#                     "so": so,
#                     "state": line_state,
#                     "mo_dt": mo_dt,
#                     "pr_rank": pr_rank.get(pr, 9),
#                     "product_name": product_name,
#                     "roll_width": roll_w,
#                 })

#             # Sort by: Date(MO) / Priority / Product / Roll width
#             rows.sort(key=lambda r: (
#                 r["mo_dt"] or datetime.min,
#                 r["pr_rank"],
#                 r["product_name"],
#                 r["roll_width"],
#                 r["mo"].id,
#             ))

#             vals_list = []
#             seq = 1
#             for r in rows:
#                 vals_list.append({
#                     "monitor_id": monitor.id,
#                     "production_id": r["mo"].id,
#                     "sale_order_id": r["so"].id if r["so"] else False,
#                     "state": r["state"],     # keep field set for backward compatibility
#                     "sequence": seq,         # stored ordering key
#                 })
#                 seq += 1

#             created = 0
#             if vals_list:
#                 Line.create(vals_list)
#                 created = len(vals_list)

#                 # IMPORTANT: recompute and WRITE line_no (this fixes your issue)
#                 monitor.line_ids._lx_recompute_line_numbers_for_monitors(monitor)

#             msg = (
#                 "Generate executed.\n"
#                 f"- Date: {monitor.date}\n"
#                 "- Date field: date_start\n"
#                 f"- Removed previous lines: {prev}\n"
#                 f"- MOs found: {len(productions)}\n"
#                 f"- Lines created: {created}\n"
#                 f"- Sales order not found for: {so_missing}\n"
#                 f"- Range: {start_s} -> {end_s}"
#             )
#             monitor.message_post(body=msg)
#             _logger.info(msg)

#         return True


# class LuxtorProductionMonitorLine(models.Model):
#     _name = "luxtor.production.monitor.line"
#     _description = "Luxtor Production Monitor Line"
#     _order = "id desc"

#     monitor_id = fields.Many2one(
#         "luxtor.production.monitor",
#         required=True,
#         ondelete="cascade",
#         index=True,
#     )

#     production_id = fields.Many2one(
#         "mrp.production",
#         string="Manufacturing Order",
#         required=True,
#         ondelete="cascade",
#         index=True,
#     )

#     # MO reference columns
#     mo_ref = fields.Char(related="production_id.name", string="MO Ref", store=True, readonly=True)
#     mo_name = fields.Char(related="production_id.name", store=True, readonly=True)  # compatibility

#     sale_order_id = fields.Many2one(
#         "sale.order",
#         string="Sales Order",
#         index=True,
#     )

#     # Keep same field (stored/writable) to NOT break existing views/widgets/logic,
#     # but we will keep it synced via create/write hooks + action_print + MO state.
#     state = fields.Selection(
#         [
#             ("not_started", "Not Started"),
#             ("in_works", "In Works"),
#             ("complete", "Complete"),
#         ],
#         default="not_started",
#         required=True,
#         index=True,
#     )

#     # Stored numbering
#     sequence = fields.Integer(string="Sequence", default=0, index=True)
#     line_no = fields.Integer(string="Line No.", default=0, index=True)  # must be writable

#     roll_width = fields.Float(
#         string="Roll Width",
#         compute="_compute_roll_width",
#         store=False,
#         readonly=True,
#     )

#     product_id = fields.Many2one(related="production_id.product_id", store=True, readonly=True)
#     mo_state = fields.Selection(related="production_id.state", store=True, readonly=True)

#     width_m = fields.Float(string="Width", compute="_compute_dimensions", store=False, readonly=True)
#     height_m = fields.Float(string="Height", compute="_compute_dimensions", store=False, readonly=True)

#     priority = fields.Selection(
#         [
#             ("normal", "Normal"),
#             ("express", "Express"),
#         ],
#         string="Priority",
#         compute="_compute_priority",
#         store=False,
#         readonly=True,
#     )

#     state_color = fields.Integer(string="State Color", compute="_compute_state_color", store=False)

#     # ------------------------------------------------------------
#     # Sync helpers (do NOT break existing logic)
#     # ------------------------------------------------------------
#     def _lx_sync_state_from_mo(self):
#         """
#         Hard-sync this record's `state` from the linked MO.
#         Kept as WRITE (not compute field) to avoid breaking:
#           - existing view widgets
#           - any domain/search on `state`
#           - your SO line compute that searches monitor lines by state
#         """
#         for rec in self:
#             mo = rec.production_id
#             if not mo:
#                 continue
#             desired = _lx_monitor_state_from_mo_state(mo.state)
#             if rec.state != desired:
#                 rec.sudo().write({"state": desired})

#     @api.depends("state")
#     def _compute_state_color(self):
#         for rec in self:
#             if rec.state == "not_started":
#                 rec.state_color = 1
#             elif rec.state == "in_works":
#                 rec.state_color = 2
#             elif rec.state == "complete":
#                 rec.state_color = 10
#             else:
#                 rec.state_color = 0

#     @api.depends("production_id", "production_id.lx_roll_width_best")
#     def _compute_roll_width(self):
#         for rec in self:
#             rw = 0.0
#             mo = rec.production_id
#             if mo and "lx_roll_width_best" in mo._fields:
#                 rw = float(getattr(mo, "lx_roll_width_best") or 0.0)
#             rec.roll_width = rw

#     @api.depends(
#         "production_id",
#         "production_id.sale_line_id",
#         "production_id.sale_line_id.lx_width_m",
#         "production_id.sale_line_id.lx_height_m",
#     )
#     def _compute_dimensions(self):
#         for rec in self:
#             w = 0.0
#             h = 0.0
#             mo = rec.production_id

#             if mo:
#                 if "lx_width_m" in mo._fields:
#                     w = float(getattr(mo, "lx_width_m") or 0.0)
#                 if "lx_height_m" in mo._fields:
#                     h = float(getattr(mo, "lx_height_m") or 0.0)

#                 if (not w or not h) and mo.sale_line_id:
#                     w = w or float(mo.sale_line_id.lx_width_m or 0.0)
#                     h = h or float(mo.sale_line_id.lx_height_m or 0.0)

#             rec.width_m = w
#             rec.height_m = h

#     @api.depends("sale_order_id.priority")
#     def _compute_priority(self):
#         for rec in self:
#             if rec.sale_order_id and rec.sale_order_id.priority == "special":
#                 rec.priority = "express"
#             else:
#                 rec.priority = "normal"

#     # -----------------------------
#     # Line No recomputation (fix)
#     # -----------------------------
#     def _lx_recompute_line_numbers_for_monitors(self, monitors):
#         """
#         For each monitor:
#         - Take lines ordered by sequence asc (our logical ordering key)
#         - Assign line_no = total..1 (DESC like Excel)
#         """
#         monitors = monitors.filtered(lambda m: m and m.id)
#         if not monitors:
#             return

#         for mon in monitors:
#             lines = mon.line_ids.sorted(key=lambda l: (l.sequence or 0, l.id))
#             total = len(lines)
#             if not total:
#                 continue

#             for idx, line in enumerate(lines):
#                 new_no = total - idx
#                 if line.line_no != new_no:
#                     line.sudo().write({"line_no": new_no})

#     # ------------------------------------------------------------
#     # Create/Write hooks (keep your old behavior + sync state)
#     # ------------------------------------------------------------
#     @api.model_create_multi
#     def create(self, vals_list):
#         recs = super().create(vals_list)

#         # Keep existing line_no logic
#         monitors = recs.mapped("monitor_id")
#         recs._lx_recompute_line_numbers_for_monitors(monitors)

#         # NEW: ensure initial state matches MO (draft/confirmed/done)
#         # (covers case where vals_list had old state or missing)
#         for rec in recs:
#             mo = rec.production_id
#             if mo:
#                 desired = _lx_monitor_state_from_mo_state(mo.state)
#                 if rec.state != desired:
#                     rec.sudo().write({"state": desired})

#         return recs

#     def write(self, vals):
#         res = super().write(vals)

#         # Keep existing line_no logic
#         monitors = self.mapped("monitor_id")
#         self._lx_recompute_line_numbers_for_monitors(monitors)

#         # NEW: if production changed OR anything wrote, re-sync state from MO
#         # (doesn't block manual write, but will bring it back to MO state)
#         if "production_id" in vals or "state" in vals:
#             for rec in self:
#                 mo = rec.production_id
#                 if mo:
#                     desired = _lx_monitor_state_from_mo_state(mo.state)
#                     if rec.state != desired:
#                         rec.sudo().write({"state": desired})

#         return res

#     def unlink(self):
#         monitors = self.mapped("monitor_id")
#         res = super().unlink()
#         self._lx_recompute_line_numbers_for_monitors(monitors)
#         return res

#     def action_open_mo(self):
#         self.ensure_one()
#         return {
#             "type": "ir.actions.act_window",
#             "name": _("Manufacturing Order"),
#             "res_model": "mrp.production",
#             "view_mode": "form",
#             "res_id": self.production_id.id,
#             "target": "current",
#         }

#     def _lx_get_mo_report_action(self):
#         self.ensure_one()
#         for xmlid in (
#             "mrp.action_report_production_order",
#             "mrp.action_report_mrp_production",
#         ):
#             try:
#                 act = self.env.ref(xmlid)
#                 if act:
#                     return act
#             except Exception:
#                 continue
#         return False

#     # def action_print(self):
#     #     """
#     #     REQUIRED BEHAVIOR:
#     #     - Clicking Print on monitoring line should switch to in_works
#     #       BUT also confirm the MO (if draft) before printing.
#     #     - If MO is later marked done, monitoring must become complete.

#     #     We keep your print logic (report detection) and we do NOT break line_no, etc.
#     #     We only add confirmation + state sync.
#     #     """
#     #     self.ensure_one()
#     #     mo = self.production_id
#     #     if not mo:
#     #         return True

#     #     # 1) If MO is draft -> confirm it
#     #     # This will put MO in confirmed/progress depending on Odoo,
#     #     # and we then sync monitor state accordingly.
#     #     if mo.state == "draft" and hasattr(mo, "action_confirm"):
#     #         mo.action_confirm()

#     #     # 2) Sync monitor state from MO (now should be in_works)
#     #     self._lx_sync_state_from_mo()

#     #     # 3) Print (keep your existing logic)
#     #     if hasattr(mo, "action_print_production_order"):
#     #         return mo.action_print_production_order()

#     #     report_action = self._lx_get_mo_report_action()
#     #     if report_action:
#     #         return report_action.report_action(mo)

#     #     return self.action_open_mo()

#     def action_print_production_sheet(self, use_internal_layout=False):
#         """Print YOUR custom Production Sheet report for this monitor line."""
#         self.ensure_one()
#         report = self.env.ref("luxtor_custom.action_report_lx_production_sheet", raise_if_not_found=False)
#         ctx = dict(self.env.context or {})
#         ctx["lx_use_internal_layout"] = bool(use_internal_layout)
#         return report.with_context(ctx).report_action(self)
    
# class SaleOrderLine(models.Model):
#     _inherit = "sale.order.line"

#     lx_state_monitoring = fields.Selection(
#         [
#             ("not_started", "Not Started"),
#             ("in_works", "In Works"),
#             ("complete", "Complete"),
#         ],
#         string="State Monitoring",
#         compute="_compute_lx_state_monitoring",
#         store=False,
#         readonly=True,
#     )

#     @api.depends("order_id")
#     def _compute_lx_state_monitoring(self):
#         MonitorLine = self.env["luxtor.production.monitor.line"].sudo()

#         orders = self.mapped("order_id")
#         order_ids = orders.ids

#         lines_by_order = {oid: self.env["luxtor.production.monitor.line"] for oid in order_ids}

#         if order_ids:
#             monitor_lines = MonitorLine.search([("sale_order_id", "in", order_ids)])
#             for ml in monitor_lines:
#                 if ml.sale_order_id:
#                     lines_by_order[ml.sale_order_id.id] |= ml

#         def _state_from_monitor_lines(lines):
#             if not lines:
#                 return "not_started"

#             states = set(lines.mapped("state"))

#             if states == {"complete"}:
#                 return "complete"

#             if "in_works" in states or "complete" in states:
#                 return "in_works"

#             return "not_started"

#         for line in self:
#             monitor_lines = lines_by_order.get(line.order_id.id)
#             line.lx_state_monitoring = _state_from_monitor_lines(monitor_lines)



