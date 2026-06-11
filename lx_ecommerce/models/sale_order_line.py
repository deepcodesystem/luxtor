from odoo import api, fields, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    lx_auto_associated_line = fields.Boolean(
        string="Auto Associated Product",
        default=False,
        help="Line auto-added from attribute-based associated products",
    )

    def _apply_free_install_logic(self):
        """Applique (ou retire) la gratuité sur ce service d'installation
        selon le seuil configuré sur le template produit."""
        self.ensure_one()
        if not self.product_id.product_tmpl_id.lx_is_installation_service:
            return
        threshold = self.product_id.product_tmpl_id.lx_install_free_threshold
        if not threshold:
            return
        order = self.order_id
        merch_total = order._merch_total_excl_services()
        if merch_total >= threshold and self.discount < 100:
            self.with_context(skip_free_install=True).discount = 100.0
        elif merch_total < threshold and self.discount >= 100:
            self.with_context(skip_free_install=True).discount = 0.0

    def _is_auto_associated_line(self, line):
        if not line.linked_line_id or not line.linked_line_id.product_id:
            return False
        main_product = line.linked_line_id.product_id
        for ptav in main_product.product_template_attribute_value_ids:
            if line.product_id in ptav.lx_associated_product_ids:
                return True
        return False

    @api.model
    def create(self, vals_list):
        lines = super().create(vals_list)

        for line in lines:
            if not line.linked_line_id:
                continue
            if line.product_id.product_tmpl_id.lx_is_installation_service or line.lx_auto_associated_line:
                line.product_uom_qty = line.linked_line_id.product_uom_qty

        orders = lines.mapped('order_id')
        for order in orders:
            order._reapply_free_install_logic()

        return lines

    def write(self, vals):
        if self._context.get('skip_free_install'):
            return super().write(vals)

        result = super().write(vals)

        if 'product_uom_qty' in vals:
            for line in self:
                linked = line.linked_line_ids.filtered(
                    lambda l: l.product_id.product_tmpl_id.lx_is_installation_service
                    or l.lx_auto_associated_line
                    or self._is_auto_associated_line(l)
                )
                if linked:
                    linked.with_context(skip_installation_sync=True).write({
                        'product_uom_qty': line.product_uom_qty
                    })
                line.order_id._reapply_free_install_logic()

        return result

    def unlink(self):
        orders = self.mapped('order_id')

        to_remove = self.env['sale.order.line']
        for line in self:
            to_remove |= line.linked_line_ids.filtered(
                lambda l: l.product_id.product_tmpl_id.lx_is_installation_service
                or l.lx_auto_associated_line
                or self._is_auto_associated_line(l)
            )

        if to_remove:
            to_remove.unlink()

        result = super().unlink()

        for order in orders:
            order._reapply_free_install_logic()

        return result
