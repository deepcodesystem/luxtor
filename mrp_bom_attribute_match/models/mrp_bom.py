import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_log = logging.getLogger(__name__)


class MrpBomLine(models.Model):
    _inherit = "mrp.bom.line"

    product_id = fields.Many2one("product.product", "Component", required=False)
    product_backup_id = fields.Many2one(
        "product.product", help="Technical field to store previous value of product_id"
    )
    component_template_id = fields.Many2one(
        "product.template", "Component (product template)"
    )
    match_on_attribute_ids = fields.Many2many(
        "product.attribute",
        string="Match on Attributes",
        compute="_compute_match_on_attribute_ids",
        store=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if (
                not values.get("product_id")
                and "product_uom_id" not in values
                and "component_template_id" in values
                and values["component_template_id"]
            ):
                values["product_uom_id"] = (
                    self.env["product.template"]
                    .browse(values["component_template_id"])
                    .uom_id.id
                )
        return super().create(vals_list)

    @api.onchange("component_template_id")
    def _onchange_component_template_id(self):
        if self.component_template_id:
            if self.product_id:
                self.product_backup_id = self.product_id
                self.product_id = False
            comp_uom = self.component_template_id.uom_id
            if (
                comp_uom
                and self.product_uom_id
                and not self.product_uom_id._has_common_reference(comp_uom)
            ):
                self.product_uom_id = comp_uom
        else:
            if self.product_backup_id:
                self.product_id = self.product_backup_id
                self.product_backup_id = False
            prod_uom = self.product_id.uom_id
            if (
                prod_uom
                and self.product_uom_id
                and not self.product_uom_id._has_common_reference(prod_uom)
            ):
                self.product_uom_id = prod_uom

    @api.depends("component_template_id")
    def _compute_match_on_attribute_ids(self):
        for rec in self:
            if rec.component_template_id:
                rec.match_on_attribute_ids = (
                    rec.component_template_id.attribute_line_ids.attribute_id.filtered(
                        lambda x: x.create_variant != "no_variant"
                    )
                )
            else:
                rec.match_on_attribute_ids = False

    @api.constrains("component_template_id")
    def _check_component_attributes(self):
        for rec in self:
            cmp_tmpl = rec.component_template_id
            if not cmp_tmpl:
                continue
            bom_prod = rec.bom_id.product_tmpl_id
            comp_attrs = cmp_tmpl.valid_product_template_attribute_line_ids.attribute_id
            prod_attrs = bom_prod.valid_product_template_attribute_line_ids.attribute_id
            if not comp_attrs:
                raise ValidationError(
                    _(
                        "No match on attribute has been detected for Component "
                        "(Product Template) %s",
                        cmp_tmpl.display_name,
                    )
                )
            if not all(attr in prod_attrs for attr in comp_attrs):
                raise ValidationError(
                    _(
                        "Some attributes of the dynamic component are not included into"
                        " production product attributes."
                    )
                )

    @api.constrains("component_template_id", "bom_product_template_attribute_value_ids")
    def _check_variants_validity(self):
        for rec in self:
            if (
                not rec.bom_product_template_attribute_value_ids
                or not rec.component_template_id
            ):
                continue
            variant_attrs = rec.bom_product_template_attribute_value_ids.attribute_id
            same_attr_ids = set(rec.match_on_attribute_ids.ids) & set(variant_attrs.ids)
            same_attrs = self.env["product.attribute"].browse(same_attr_ids)
            if same_attrs:
                raise ValidationError(
                    _(
                        "You cannot use an attribute value for attribute(s) "
                        "%(attributes)s in the field \u201cApply on Variants\u201d as it's the "
                        "same attribute used in the field \u201cMatch on Attribute\u201d related "
                        "to the component %(component)s.",
                        attributes=", ".join(same_attrs.mapped("name")),
                        component=rec.component_template_id.name,
                    )
                )

    @api.onchange("match_on_attribute_ids")
    def _onchange_match_on_attribute_ids_check_component_attributes(self):
        if self.match_on_attribute_ids:
            self._check_component_attributes()

    @api.onchange("bom_product_template_attribute_value_ids")
    def _onchange_bom_product_template_attribute_value_ids_check_variants(self):
        if self.bom_product_template_attribute_value_ids:
            self._check_variants_validity()


class MrpBom(models.Model):
    _inherit = "mrp.bom"

    # flake8: noqa: C901
    def explode(
        self, product, quantity, picking_type=False, never_attribute_values=False
    ):
        """
        Explodes the BoM and creates two lists with all the information you need:
        bom_done and line_done.

        Extended to resolve component_template_id to a concrete product variant
        before processing each BoM line.
        """
        product_ids = set()
        product_boms = {}

        def update_product_boms():
            products = self.env["product.product"].browse(product_ids)
            product_boms.update(
                self._bom_find(
                    products,
                    picking_type=picking_type or self.picking_type_id,
                    company_id=self.company_id.id,
                    bom_type="phantom",
                )
            )
            for prod in products:
                product_boms.setdefault(prod, self.env["mrp.bom"])

        boms_done = [
            (
                self,
                self.env["mrp.bom.line"]._prepare_bom_done_values(
                    quantity, product, quantity, []
                ),
            )
        ]
        lines_done = []

        bom_lines = []
        for bom_line in self.bom_line_ids:
            bom_lines.append((bom_line, product, quantity, False))
            if bom_line.product_id:
                product_ids.add(bom_line.product_id.id)
        update_product_boms()
        product_ids.clear()

        while bom_lines:
            current_line, current_product, current_qty, parent_line = bom_lines[0]
            bom_lines = bom_lines[1:]

            if current_line._skip_bom_line(current_product, never_attribute_values):
                continue

            line_quantity = current_qty * current_line.product_qty

            # Resolve component_template_id to a concrete product variant
            component_template_product = self._get_component_template_product(
                current_line, product, current_line.product_id
            )
            if component_template_product:
                current_line.product_id = component_template_product
            else:
                # component_template_id is set but no matching variant found
                continue

            if current_line.product_id not in product_boms:
                update_product_boms()
                product_ids.clear()

            bom = product_boms.get(current_line.product_id)
            if bom:
                converted_line_quantity = current_line.product_uom_id._compute_quantity(
                    line_quantity / bom.product_qty, bom.product_uom_id, round=False
                )
                bom_lines = [
                    (line, current_line.product_id, converted_line_quantity, current_line)
                    for line in bom.bom_line_ids
                ] + bom_lines
                for bom_line in bom.bom_line_ids:
                    if bom_line.product_id not in product_boms:
                        product_ids.add(bom_line.product_id.id)
                boms_done.append(
                    (
                        bom,
                        current_line._prepare_bom_done_values(
                            converted_line_quantity, current_product, quantity, boms_done
                        ),
                    )
                )
            else:
                line_quantity = current_line.product_uom_id.round(
                    line_quantity, rounding_method="UP"
                )
                lines_done.append(
                    (
                        current_line,
                        current_line._prepare_line_done_values(
                            line_quantity, current_product, quantity, parent_line, boms_done
                        ),
                    )
                )

        lines_done = self._round_last_line_done(lines_done)
        return boms_done, lines_done

    def _get_component_template_product(
        self, bom_line, bom_product_id, line_product_id
    ):
        if bom_line.component_template_id:
            comp = bom_line.component_template_id
            comp_attr_ids = (
                comp.valid_product_template_attribute_line_ids.attribute_id.ids
            )
            valid_ptal = bom_product_id.valid_product_template_attribute_line_ids
            prod_attr_ids = valid_ptal.attribute_id.ids
            if not all(item in prod_attr_ids for item in comp_attr_ids):
                _log.info(
                    "Component skipped. Component attributes must be included into "
                    "product attributes to use component_template_id."
                )
                return False
            combination = self.env["product.template.attribute.value"]
            for ptav in bom_product_id.product_template_attribute_value_ids:
                combination |= self.env["product.template.attribute.value"].search(
                    [
                        ("product_tmpl_id", "=", comp.id),
                        ("attribute_id", "=", ptav.attribute_id.id),
                        (
                            "product_attribute_value_id",
                            "=",
                            ptav.product_attribute_value_id.id,
                        ),
                    ]
                )
            if len(combination) == 0:
                return False
            product_id = comp._get_variant_for_combination(combination)
            if product_id and product_id.active:
                return product_id
            return False
        else:
            return line_product_id

    @api.constrains("product_tmpl_id", "product_id")
    def _check_component_attributes(self):
        return self.bom_line_ids._check_component_attributes()

    @api.constrains("product_tmpl_id", "product_id")
    def _check_variants_validity(self):
        return self.bom_line_ids._check_variants_validity()
