# -*- coding: utf-8 -*-
from odoo import api, models

# EXACT labels to allow (no category-based fallback)
ALLOWED_UOM_LABELS = ["m²", "m", "Unit", "Set", "Pair"]


def _allowed_uom_ids(env):
    """
    Resolve concrete UoM IDs by their labels once, translation-safe.
    No category constraints. Only exact labels are allowed.
    """
    Uom = env["uom.uom"].sudo()
    return Uom.search([("name", "in", ALLOWED_UOM_LABELS)]).ids or [0]  # [0] => empty safely


# -----------------------------
# Product Template
# -----------------------------
class ProductTemplate(models.Model):
    _inherit = "product.template"

    @api.onchange("uom_id")
    def _onchange_uom_id_limit(self):
        return {"domain": {"uom_id": [("id", "in", _allowed_uom_ids(self.env))]}}

    @api.onchange("uom_po_id")
    def _onchange_uom_po_id_limit(self):
        return {"domain": {"uom_po_id": [("id", "in", _allowed_uom_ids(self.env))]}}


# -----------------------------
# Product Variant
# -----------------------------
class ProductProduct(models.Model):
    _inherit = "product.product"

    @api.onchange("uom_id")
    def _onchange_variant_uom_id_limit(self):
        return {"domain": {"uom_id": [("id", "in", _allowed_uom_ids(self.env))]}}

    @api.onchange("uom_po_id")
    def _onchange_variant_uom_po_id_limit(self):
        return {"domain": {"uom_po_id": [("id", "in", _allowed_uom_ids(self.env))]}}


# -----------------------------
# Sales Order Line
# -----------------------------
class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    @api.onchange("product_id")
    def _onchange_product_id_limit_uom(self):
        return {"domain": {"product_uom": [("id", "in", _allowed_uom_ids(self.env))]}}

    @api.onchange("product_uom")
    def _onchange_product_uom_limit(self):
        return {"domain": {"product_uom": [("id", "in", _allowed_uom_ids(self.env))]}}


# -----------------------------
# Purchase Order Line
# -----------------------------
class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    @api.onchange("product_id")
    def _onchange_product_id_limit_uom(self):
        return {"domain": {"product_uom": [("id", "in", _allowed_uom_ids(self.env))]}}

    @api.onchange("product_uom")
    def _onchange_product_uom_limit(self):
        return {"domain": {"product_uom": [("id", "in", _allowed_uom_ids(self.env))]}}


# -----------------------------
# BoM + BoM Line
# -----------------------------
class MrpBom(models.Model):
    _inherit = "mrp.bom"

    @api.onchange("product_tmpl_id")
    def _onchange_product_limit_uom(self):
        return {"domain": {"product_uom_id": [("id", "in", _allowed_uom_ids(self.env))]}}

    @api.onchange("product_uom_id")
    def _onchange_bom_uom_limit(self):
        return {"domain": {"product_uom_id": [("id", "in", _allowed_uom_ids(self.env))]}}


class MrpBomLine(models.Model):
    _inherit = "mrp.bom.line"

    @api.onchange("product_id")
    def _onchange_product_limit_uom(self):
        return {"domain": {"product_uom_id": [("id", "in", _allowed_uom_ids(self.env))]}}

    @api.onchange("product_uom_id")
    def _onchange_bom_line_uom_limit(self):
        return {"domain": {"product_uom_id": [("id", "in", _allowed_uom_ids(self.env))]}}


# -----------------------------
# Manufacturing Order
# -----------------------------
class MrpProduction(models.Model):
    _inherit = "mrp.production"

    @api.onchange("product_id")
    def _onchange_product_limit_uom(self):
        return {"domain": {"product_uom_id": [("id", "in", _allowed_uom_ids(self.env))]}}

    @api.onchange("product_uom_id")
    def _onchange_mo_uom_limit(self):
        return {"domain": {"product_uom_id": [("id", "in", _allowed_uom_ids(self.env))]}}
