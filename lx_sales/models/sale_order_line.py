# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.addons.lx_base.utils import (
    LX_MIN_WIDTH_M, LX_MIN_HEIGHT_M,
)

_logger = logging.getLogger(__name__)


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    # ── BOM and Roller config field ─────────────────────────────────────────────────────
    bom_id = fields.Many2one('mrp.bom', string='Nomenclature (BOM)',
        domain="[('product_tmpl_id', '=', product_template_id), "
               " ('active', '=', True)]", help="Bill of materials for the product")
    lx_control_side = fields.Selection(
        [('right', 'Right'), ('left', 'Left')],
        string='Control Side',
        default='right'
    )
    lx_roll_direction = fields.Selection(
        [('standard', 'Standard'), ('reverse', 'Reverse')],
        string='Roll Direction',
        default='standard'
    )
    lx_fitting_method = fields.Selection(
        [('wall', 'Wall Mount'), ('ceiling', 'Ceiling Mount')],
        string='Fitting Method',
        default='wall'
    )

    # ── Champs dimensions ─────────────────────────────────────────────────────
    lx_width_m = fields.Float(
        string="Width (m)",
        digits=(16, 4),
        default=0.0,
        help="Width in meters (synced with product attributes)"
    )
    lx_height_m = fields.Float(
        string="Height (m)",
        digits=(16, 4),
        default=0.0,
        help="Height in meters (synced with product attributes)"
    )

    is_dimension_product = fields.Boolean(
        related='product_id.product_tmpl_id.is_dimension_product',
        store=False,
    )

    size = fields.Float(
        string="Size (m²)",
        compute='_compute_size',
        store=True,
        digits=(16, 4),
    )

    # =========================================================================
    # COMPUTES
    # =========================================================================

    @api.onchange('product_id')
    def _onchange_product_id_bom(self):
        self.bom_id = False
        if not self.product_id:
            return

        company_id = self.order_id.company_id.id or self.env.company.id

        # Cherche le BOM le plus spécifique : variante d'abord, puis template
        bom = self.env['mrp.bom'].search([
            ('type', '=', 'normal'),
            ('product_id', '=', self.product_id.id),  # variante exacte
            '|',
            ('company_id', '=', company_id),
            ('company_id', '=', False),
        ], limit=1, order='sequence asc')

        if not bom:
            # Fallback sur le template si pas de BOM spécifique à la variante
            bom = self.env['mrp.bom'].search([
                ('type', '=', 'normal'),
                ('product_tmpl_id', '=', self.product_id.product_tmpl_id.id),
                ('product_id', '=', False),  # BOM générique template
                '|',
                ('company_id', '=', company_id),
                ('company_id', '=', False),
            ], limit=1, order='sequence asc')

        if bom:
            self.bom_id = bom

    @api.depends('lx_width_m', 'lx_height_m')
    def _compute_size(self):
        for line in self:
            w = line.lx_width_m or 0.0
            h = line.lx_height_m or 0.0
            line.size = w * h if (w > 0 and h > 0) else 0.0

    @api.depends('lx_width_m', 'lx_height_m', 'product_uom_qty', 'price_unit', 'tax_ids', 'discount')
    def _compute_amount(self):
        # Le price_unit contient déjà base_price × H × W (via _get_pricelist_price),
        # donc on utilise product_uom_qty tel quel — PAS de multiplication par size.
        return super()._compute_amount()

    def _get_pricelist_price(self):
        """Multiplie le prix catalogue par la surface (m²) pour les stores.
        Lecture : attributs customs d'abord, puis fallback lx_width_m/lx_height_m."""
        if not self.product_id or not self.product_id.product_tmpl_id.lx_is_store:
            return super()._get_pricelist_price()

        height = self._get_dimension_custom_value('lx_base.product_attribute_height_m')
        width = self._get_dimension_custom_value('lx_base.product_attribute_width_m')

        # Fallback : lire depuis les champs directs si les attributs ne sont pas sync
        if not height or not width:
            height = self.lx_height_m or 0.0
            width = self.lx_width_m or 0.0
        if not height or not width:
            return super()._get_pricelist_price()

        if self.order_id.pricelist_id:
            base_price = self.order_id.pricelist_id._get_product_price(
                self.product_id, self.product_uom_qty, currency=self.order_id.currency_id
            )
        else:
            base_price = self.product_id.list_price
        return base_price * height * width

    # =========================================================================
    # VALIDATION DIMENSIONS
    # =========================================================================

    def lx_validate_dimensions(self, width_m=None, height_m=None):
        """Valide W et H selon les contraintes du template produit.
        Lève UserError si invalide."""
        self.ensure_one()
        tmpl = self.product_id.product_tmpl_id if self.product_id else False
        if not tmpl or not tmpl.is_dimension_product:
            return

        w = float(width_m if width_m is not None else (self.lx_width_m or 0.0))
        h = float(height_m if height_m is not None else (self.lx_height_m or 0.0))

        if w == 0.0 and h == 0.0:
            return
        if w <= 0 or h <= 0:
            raise UserError(_("Width and height must be greater than zero."))
        if w < LX_MIN_WIDTH_M:
            raise UserError(_("Minimum width is %.2f m.") % LX_MIN_WIDTH_M)
        if h < LX_MIN_HEIGHT_M:
            raise UserError(_("Minimum height is %.2f m.") % LX_MIN_HEIGHT_M)

        hints = tmpl.lx_dims_hints(width_m=w)
        max_w = hints.get('max_width_m', 0.0)
        max_h = hints.get('max_height_m', 0.0)
        if max_w and w > max_w:
            raise UserError(_("Maximum width is %.2f m.") % max_w)
        if max_h and h > max_h:
            raise UserError(_("Maximum height is %.2f m.") % max_h)

    # =========================================================================
    # CREATE / WRITE
    # =========================================================================

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        if self.env.context.get('lx_skip_reprice'):
            return lines
        for line, vals in zip(lines, vals_list):
            if not line.product_id:
                continue
            if not line.product_id.product_tmpl_id.is_dimension_product:
                continue

            # Synchroniser depuis les attributs custom si pas de valeurs explicites
            if not vals.get('lx_width_m') and not vals.get('lx_height_m'):
                dim_vals = line._sync_dimensions_from_attributes()
                if dim_vals:
                    _logger.info(f"Syncing dimensions on create: {dim_vals}")
                    line.with_context(lx_skip_reprice=True).write(dim_vals)

            if line.lx_width_m or line.lx_height_m:
                line.lx_validate_dimensions()
        return lines

    def write(self, vals):
        # Si on modifie product_custom_attribute_value_ids, synchroniser vers lx_width_m/lx_height_m
        if 'product_custom_attribute_value_ids' in vals and not self.env.context.get('lx_skip_sync'):
            # D'abord faire le write pour que les custom values soient à jour
            res = super().write(vals)

            # Ensuite synchroniser les dimensions pour chaque ligne
            for line in self:
                if line.product_id and line.product_id.product_tmpl_id.is_dimension_product:
                    dim_vals = line._sync_dimensions_from_attributes()
                    if dim_vals:
                        _logger.info(f"Syncing dimensions from attributes: {dim_vals}")
                        # Écrire les dimensions avec le contexte skip_sync pour éviter boucle
                        line.with_context(lx_skip_sync=True).write(dim_vals)

            return res

        res = super().write(vals)
        if self.env.context.get('lx_skip_reprice'):
            return res
        if not any(k in vals for k in ('lx_width_m', 'lx_height_m', 'product_id')):
            return res
        for line in self:
            if not line.product_id:
                continue
            if not line.product_id.product_tmpl_id.is_dimension_product:
                continue
            line.lx_validate_dimensions()
            # Recalculer price_unit quand les dimensions changent
            if any(k in vals for k in ('lx_width_m', 'lx_height_m')):
                line.price_unit = line._get_pricelist_price()
        return res

    def _get_sale_order_line_configurator_values(self):
        """
        Surcharge pour inclure les dimensions dans le payload JSON
        retourné au configurateur OWL.
        Synchronise aussi depuis les attributs custom si présents.
        """
        values = super()._get_sale_order_line_configurator_values()

        # Synchroniser depuis les attributs custom si pas encore défini
        if not self.lx_width_m or not self.lx_height_m:
            self._sync_dimensions_from_attributes()

        values.update({
            'lx_width_m': self.lx_width_m or 0.0,
            'lx_height_m': self.lx_height_m or 0.0,
        })
        return values

    def _update_from_configurator_values(self, configurator_values):
        """
        Surcharge pour écrire les dimensions reçues du configurateur
        sur la ligne de commande ET sur les attributs custom.
        """
        super()._update_from_configurator_values(configurator_values)
        lx_width_m = configurator_values.get('lx_width_m')
        lx_height_m = configurator_values.get('lx_height_m')
        vals = {}
        if lx_width_m is not None:
            vals['lx_width_m'] = float(lx_width_m)
        if lx_height_m is not None:
            vals['lx_height_m'] = float(lx_height_m)
        if vals:
            self.write(vals)
            # Synchroniser vers les attributs custom
            self._sync_dimensions_to_attributes()

    # =========================================================================
    # SYNCHRONISATION DIMENSIONS <-> ATTRIBUTS
    # =========================================================================

    def _get_dimension_custom_value(self, attr_xmlid):
        """Lit la valeur custom d'un attribut dimension depuis la ligne de commande.

        :param attr_xmlid: XML ID complet de l'attribut (ex: 'lx_base.product_attribute_height_m')
        :return: float or None
        """
        self.ensure_one()
        attr = self.env.ref(attr_xmlid, raise_if_not_found=False)
        if not attr:
            return None
        for custom_val in self.product_custom_attribute_value_ids:
            ptav = custom_val.custom_product_template_attribute_value_id
            if ptav.attribute_id == attr:
                try:
                    return float(custom_val.custom_value)
                except (ValueError, TypeError):
                    return None
        return None

    def _sync_dimensions_from_attributes(self):
        """
        Lit les valeurs custom des attributs Largeur/Hauteur et retourne
        un dict avec lx_width_m et lx_height_m pour write().
        """
        self.ensure_one()
        if not self.product_custom_attribute_value_ids:
            return {}

        width_attr = self.env.ref('lx_base.product_attribute_width_m', raise_if_not_found=False)
        height_attr = self.env.ref('lx_base.product_attribute_height_m', raise_if_not_found=False)

        vals = {}
        for custom_val in self.product_custom_attribute_value_ids:
            if width_attr and custom_val.custom_product_template_attribute_value_id.attribute_id == width_attr:
                try:
                    vals['lx_width_m'] = float(custom_val.custom_value or 0.0)
                except (ValueError, TypeError):
                    _logger.warning(f"Invalid width value: {custom_val.custom_value}")
                    pass
            elif height_attr and custom_val.custom_product_template_attribute_value_id.attribute_id == height_attr:
                try:
                    vals['lx_height_m'] = float(custom_val.custom_value or 0.0)
                except (ValueError, TypeError):
                    _logger.warning(f"Invalid height value: {custom_val.custom_value}")
                    pass

        return vals

    def _sync_dimensions_to_attributes(self):
        """
        Écrit lx_width_m et lx_height_m dans les valeurs custom des attributs
        si les attributs dimension existent sur le produit.
        """
        self.ensure_one()
        if not self.product_id or not self.product_id.product_tmpl_id.is_dimension_product:
            return

        width_attr = self.env.ref('lx_base.product_attribute_width_m', raise_if_not_found=False)
        height_attr = self.env.ref('lx_base.product_attribute_height_m', raise_if_not_found=False)

        if not width_attr or not height_attr:
            return

        # Trouver les PTAVs correspondants sur le template
        tmpl = self.product_id.product_tmpl_id
        width_ptav = tmpl.attribute_line_ids.filtered(
            lambda l: l.attribute_id == width_attr
        ).product_template_value_ids.filtered(lambda v: v.is_custom)[:1]

        height_ptav = tmpl.attribute_line_ids.filtered(
            lambda l: l.attribute_id == height_attr
        ).product_template_value_ids.filtered(lambda v: v.is_custom)[:1]

        if not width_ptav or not height_ptav:
            return

        # Créer ou mettre à jour les custom values
        CustomValue = self.env['product.attribute.custom.value']

        # Width
        width_custom = self.product_custom_attribute_value_ids.filtered(
            lambda v: v.custom_product_template_attribute_value_id == width_ptav
        )
        if width_custom:
            width_custom.write({'custom_value': str(self.lx_width_m or 0.0)})
        else:
            CustomValue.create({
                'sale_order_line_id': self.id,
                'custom_product_template_attribute_value_id': width_ptav.id,
                'custom_value': str(self.lx_width_m or 0.0),
            })

        # Height
        height_custom = self.product_custom_attribute_value_ids.filtered(
            lambda v: v.custom_product_template_attribute_value_id == height_ptav
        )
        if height_custom:
            height_custom.write({'custom_value': str(self.lx_height_m or 0.0)})
        else:
            CustomValue.create({
                'sale_order_line_id': self.id,
                'custom_product_template_attribute_value_id': height_ptav.id,
                'custom_value': str(self.lx_height_m or 0.0),
            })


