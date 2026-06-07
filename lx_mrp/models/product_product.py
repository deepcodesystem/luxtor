from odoo import Command, models
from odoo.tools import float_round


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def _set_price_from_bom(self, boms_to_recompute=False):
        self.ensure_one()
        bom = self.env['mrp.bom']._bom_find(self)[self]
        if bom:
            self.standard_price = self._lx_compute_bom_price(
                bom, boms_to_recompute=boms_to_recompute
            )

    def _lx_compute_bom_price(self, bom, boms_to_recompute=False, byproduct_bom=False):
        self.ensure_one()
        if not bom:
            return 0
        if not boms_to_recompute:
            boms_to_recompute = []

        bom = self._lx_resolve_component_templates(bom)

        total = 0
        for opt in bom.operation_ids:
            if opt._skip_operation_line(self):
                continue
            total += opt.cost

        for line in bom.bom_line_ids:
            if line._skip_bom_line(self):
                continue
            if line.child_bom_id and line.child_bom_id in boms_to_recompute:
                child_total = self._lx_compute_bom_price(
                    line.child_bom_id, boms_to_recompute=boms_to_recompute
                )
                total += line.product_id.uom_id._compute_price(
                    child_total, line.product_uom_id
                ) * line.product_qty
            else:
                unit_cost = line.product_id.lx_adjusted_cost or line.product_id.standard_price or 0.0
                total += line.product_id.uom_id._compute_price(
                    unit_cost, line.product_uom_id
                ) * line.product_qty

        if byproduct_bom:
            byproduct_lines = bom.byproduct_ids.filtered(
                lambda b: b.product_id == self and b.cost_share != 0
            )
            product_uom_qty = 0
            for line in byproduct_lines:
                product_uom_qty += line.product_uom_id._compute_quantity(
                    line.product_qty, self.uom_id, round=False
                )
            byproduct_cost_share = sum(byproduct_lines.mapped('cost_share'))
            if byproduct_cost_share and product_uom_qty:
                return total * byproduct_cost_share / 100 / product_uom_qty
        else:
            byproduct_cost_share = sum(bom.byproduct_ids.mapped('cost_share'))
            if byproduct_cost_share:
                total *= float_round(
                    1 - byproduct_cost_share / 100, precision_rounding=0.0001
                )
            return bom.product_uom_id._compute_price(total / bom.product_qty, self.uom_id)
        return 0.0

    def _lx_resolve_component_templates(self, bom):
        resolve = getattr(bom, '_get_component_template_product', None)
        if not resolve:
            return bom
        has_templates = any(
            line.component_template_id for line in bom.bom_line_ids
        )
        if not has_templates:
            return bom
        virtual = bom.new(origin=bom)
        to_ignore = []
        for line in virtual.bom_line_ids:
            if line._skip_bom_line(self) or not line.component_template_id:
                continue
            variant = resolve(line, self, line.product_id)
            if not variant:
                to_ignore.append(line.id)
                continue
            line.product_id = variant
        if to_ignore:
            virtual.bom_line_ids = [Command.unlink(id) for id in to_ignore]
        return virtual
