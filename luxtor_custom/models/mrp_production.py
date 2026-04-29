# -*- coding: utf-8 -*-
import math
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)

REMNANT_FMT = "W{w:.2f} * H{h:.2f}"
HEADRAIL_PRODUCT_ID_VALUE = "R-002-21"
ADHESIVE_PRODUCT_ID_VALUE = "ZFE-09"

# --- Plastic chain selectors -----------------------------------------------
PLASTIC_CHAIN_150_CODE = "BFPC-150"
PLASTIC_CHAIN_200_CODE = "BFPC-200"


def _norm(s):
    return (s or "").strip().upper()

def lx_truncate_2(value):
    return math.floor((value or 0.0) * 100.0) / 100.0


class MrpProduction(models.Model):
    """
    Extension Luxtor de mrp.production.

    Rôles principaux :
      - Gérer les dimensions (lx_width_m, lx_height_m) et les quantités à consommer.
      - Appliquer les règles business (brackets, chaînes plastiques, adhésif).
      - Gérer le moteur de chutes / remanents (luxtor.waste + WH/Treasure).
      - Choisir l'orientation de coupe (widthwise / heightwise) et la largeur
        de rouleau optimale en s'inspirant du fichier the.
    """
    _inherit = 'mrp.production'
    _order = "create_date desc"

    # ---------- Basic fields ----------
    luxtor_location_id = fields.Many2one("luxtor.location", string="Location")
    x_control_side = fields.Selection(
        [('right', 'Right'), ('left', 'Left')],
        string='Control Side',
        default='right'
    )
    x_roll_direction = fields.Selection(
        [('standard', 'Standard'), ('reverse', 'Reverse')],
        string='Roll Direction',
        default='standard'
    )
    x_fitting_method = fields.Selection(
        [('wall', 'Wall Mount'), ('ceiling', 'Ceiling Mount')],
        string='Fitting Method',
        default='wall'
    )

    lx_width_m = fields.Float(string="Width", help="Configured width in metres.")
    lx_height_m = fields.Float(string="Height", help="Configured height in metres.")

    # Orientation choisie par le moteur de coupe (widthwise / heightwise)
    lx_orientation = fields.Selection(
        [('widthwise', 'Widthwise'), ('heightwise', 'Heightwise')],
        string="Fabric Orientation",
        default='widthwise',
        help="Cutting orientation selected by the remnant engine."
    )

    # Largeur de rouleau (en mètres) sélectionnée par le moteur
    lx_roll_width_best = fields.Float(
        string="Selected Roll Width (m)",
        help="Roll width (in metres) used by the remnant calculation."
    )

    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        readonly=True
    )
    lx_total_cost_price = fields.Monetary(
        string="Total Cost Price",
        compute='_compute_lx_totals',
        store=True,
        currency_field='currency_id'
    )
    lx_total_amount = fields.Monetary(
        string="Total Amount",
        compute='_compute_lx_totals',
        store=True,
        currency_field='currency_id'
    )

    x_lot_prefix = fields.Char(string='LoT Prefix')
    x_lot_seq = fields.Char(string="LoT Seq")
    x_lot_number = fields.Char(string='LoT Number')
    x_remnant_text = fields.Char(string='Remnant')

    # --- Waste feature -------------------------------------------------
    waste_ids = fields.One2many(
        'luxtor.waste', 'production_id', string="Waste / Remnants"
    )
    waste_processed = fields.Boolean(
        string="Waste Processed",
        default=False,
        help="Set when remnant / waste stock moves have been generated for this MO."
    )

    waste_main_id = fields.Many2one(
        'luxtor.waste',
        string="Waste Processing",
        compute='_compute_waste_main',
        store=False,
        readonly=True,
        help="First waste/remnant line related to this manufacturing order."
    )

    remnant_reused_id = fields.Many2one(
        'luxtor.waste',
        string="Remnant Used",
        readonly=True,
        help="If set, this MO reused the given remnant instead of consuming new fabric."
    )

    lx_remnant_candidate_id = fields.Many2one(
        "luxtor.waste",
        string="Remnant Candidate (draft)",
        readonly=True,
        copy=False,
        help="Best remnant candidate prepared at draft stage (if any).",
    )
    lx_remnant_candidate_lot_id = fields.Many2one(
        "stock.lot",
        string="Candidate Lot (draft)",
        readonly=True,
        copy=False,
        help="Lot linked to the remnant candidate prepared at draft stage (if any).",
    )


    # ================================================================
    # REMNANT PURCHASE ORDER HELPERS
    # ================================================================
    def _lx_get_remnant_vendor(self):
        """
        Vendor used for 0-DH remnant POs.

        Priority:
          1) ir.config_parameter 'luxtor.remnant_vendor_id'
          2) company partner
          3) first supplier-ranked partner
        """
        self.ensure_one()
        Param = self.env['ir.config_parameter'].sudo()
        Partner = self.env['res.partner'].sudo()

        partner_id = int(Param.get_param('luxtor.remnant_vendor_id', '0') or 0)
        vendor = Partner.browse(partner_id).exists() if partner_id else False

        if not vendor:
            vendor = self.company_id.partner_id

        if not vendor:
            vendor = Partner.search([('supplier_rank', '>', 0)], limit=1)

        return vendor

    def _lx_create_remnant_po(self, fabric_move, qty_rem, width_m, treasure):
        """
        Create a 0-DH Purchase Order for the remnant instead of an
        internal Stock -> Treasure move.

        - product_qty (POL) = qty_rem (ALWAYS height in lm)
        - width (POL)       = width_m (remnant width in m)
        - price_unit        = 0
        - PO is confirmed
        - Incoming picking is auto-done to WH/Treasure
        - Existing POL logic _find_or_create_lot_by_width() assigns/creates lot

        Returns: (po, pol, lot, move)
        """
        self.ensure_one()
        PurchaseOrder = self.env['purchase.order'].sudo()
        PurchaseOrderLine = self.env['purchase.order.line'].sudo()
        StockMoveLine = self.env['stock.move.line'].sudo()
        Warehouse = self.env['stock.warehouse'].sudo()

        vendor = self._lx_get_remnant_vendor()
        if not vendor:
            _logger.warning(
                "[WASTE DEBUG] _lx_create_remnant_po: no vendor found for MO %s.",
                self.name,
            )
            return False, False, False, False

        # Default incoming picking type for this company
        wh = Warehouse.search([('company_id', '=', self.company_id.id)], limit=1)
        picking_type = wh.in_type_id if wh else False

        # ------------------------------------------------------------------
        # 1) Create PO (0 DH)
        # ------------------------------------------------------------------
        po_vals = {
            'partner_id': vendor.id,
            'company_id': self.company_id.id,
            'currency_id': self.company_id.currency_id.id,
            'origin': "Remnant %s" % (self.name or ''),
        }
        if picking_type:
            po_vals['picking_type_id'] = picking_type.id

        po = PurchaseOrder.create(po_vals)

        pol_vals = {
            'order_id': po.id,
            'product_id': fabric_move.product_id.id,
            'name': fabric_move.product_id.display_name,
            'product_qty': qty_rem,              # ALWAYS HEIGHT in lm
            'product_uom': fabric_move.product_uom.id,
            'price_unit': 0.0,
            'date_planned': fields.Datetime.now(),
            'width': width_m or 0.0,             # remnant width in m → drives lot.width_cm
        }
        pol = PurchaseOrderLine.create(pol_vals)

        # At this point, pol._find_or_create_lot_by_width() has run
        lot = pol.lot_id

        po.button_confirm()

        # ------------------------------------------------------------------
        # 2) Auto-receipt to WH/Treasure
        # ------------------------------------------------------------------
        picking = po.picking_ids[:1]
        move = False
        if picking:
            # Force dest WH/Treasure
            picking.move_ids_without_package.write({'location_dest_id': treasure.id})

            # Pick the move for our product
            move = picking.move_ids_without_package.filtered(
                lambda m: m.product_id == fabric_move.product_id
            )[:1] or picking.move_ids_without_package[:1]

            if move:
                # qty_done = height in lm
                if hasattr(move, 'quantity_done'):
                    move.quantity_done = qty_rem

                # Move lines
                if move.move_line_ids:
                    for ml in move.move_line_ids:
                        ml.qty_done = qty_rem
                        ml.location_dest_id = treasure.id
                        if lot:
                            ml.lot_id = lot.id
                else:
                    StockMoveLine.create({
                        'move_id': move.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'qty_done': qty_rem,
                        'location_id': move.location_id.id,
                        'location_dest_id': treasure.id,
                        'lot_id': lot.id if lot else False,
                    })

            picking._action_done()

        _logger.info(
            "[WASTE DEBUG] _lx_create_remnant_po: created PO %s / line %s / lot=%s for MO %s (qty_rem=%.4f, width=%.4f).",
            po.name if po else 'n/a',
            pol.id if pol else 'n/a',
            lot.name if lot else 'n/a',
            self.name,
            qty_rem,
            width_m,
        )

        return po, pol, lot, move

    # ================================================================
    # BASIC COMPUTATIONS
    # ================================================================

    @api.depends('waste_ids')
    def _compute_waste_main(self):
        """
        Pick the first waste record for this MO (if any).
        This is used purely for the many2one field on the MO form.
        """
        for mo in self:
            mo.waste_main_id = mo.waste_ids[:1].id if mo.waste_ids else False

    # @api.depends('move_raw_ids')
    # def _compute_lx_totals(self):
    #     """
    #     Aggregate cost/amount from raw material moves.
    #     """
    #     for mo in self:
    #         total_cost = sum(float(m.lx_cost_price or 0.0) for m in mo.move_raw_ids)
    #         total_amount = sum(float(m.lx_amount or 0.0) for m in mo.move_raw_ids)
    #         mo.lx_total_cost_price = total_cost
    #         mo.lx_total_amount = total_amount

    @api.depends('move_raw_ids')
    def _compute_lx_totals(self):
        for mo in self:
            total_cost = sum(float(m.lx_cost_price or 0.0) for m in mo.move_raw_ids)
            total_amount = sum(float(m.lx_amount or 0.0) for m in mo.move_raw_ids)

            mo.lx_total_cost_price = lx_truncate_2(total_cost)
            mo.lx_total_amount = lx_truncate_2(total_amount)

    @api.depends('lx_width_m', 'lx_height_m')
    def _compute_remnant(self):
        """
        Simple textual representation of W*H (indépendant du moteur).
        """
        for mo in self:
            mo.x_remnant_text = REMNANT_FMT.format(
                w=(mo.lx_width_m or 0.0),
                h=(mo.lx_height_m or 0.0),
            )

    @api.constrains('product_qty')
    def _check_qty_is_one(self):
        """
        Un OF Luxtor = 1 pièce (le reste se fait via dimensions).
        """
        for mo in self:
            if mo.product_qty != 1:
                raise ValidationError(_("Manufacturing quantity must be exactly 1."))

    # ================================================================
    # PTAV / HEADRAIL / ADHESIVE HELPERS
    # ================================================================
    def _product_has_ptav_value(self, product, attr_name, value_name):
        if not product:
            return False
        for ptav in product.product_template_attribute_value_ids:
            if (
                ptav.attribute_id
                and (ptav.attribute_id.name or "").strip().lower()
                == (attr_name or "").strip().lower()
                and ptav.product_attribute_value_id
                and (ptav.product_attribute_value_id.name or "").strip().lower()
                == (value_name or "").strip().lower()
            ):
                return True
        return False

    def _is_headrail_r_002_21(self, product):
        tmpl = product.product_tmpl_id if product else False
        if tmpl and getattr(tmpl, 'lx_is_cassette', False):
            return True
        return self._product_has_ptav_value(
            product, "Product ID", HEADRAIL_PRODUCT_ID_VALUE
        )

    # ================================================================
    # PLASTIC CHAIN HELPERS
    # ================================================================

    def _lx_get_chain_code_value(self, product):
        """
        Return chain code value from attribute 'Code' if product is a plastic chain.
        """
        if not product:
            return False

        for ptav in product.product_template_attribute_value_ids:
            attr = (ptav.attribute_id.name or "").strip()
            val = (ptav.product_attribute_value_id.name or "").strip()

            if attr == "Code" and val in (PLASTIC_CHAIN_150_CODE, PLASTIC_CHAIN_200_CODE):
                return val

        return False


    def _is_plastic_chain(self, product):
        """
        Plastic chain = template flag + attribute Code value present.
        """
        if not product:
            return False

        tmpl = product.product_tmpl_id
        if not tmpl or not getattr(tmpl, "lx_is_plastic_chain", False):
            return False

        return bool(self._lx_get_chain_code_value(product))


    def _is_chain_150(self, product):
        if not self._is_plastic_chain(product):
            return False
        return self._lx_get_chain_code_value(product) == PLASTIC_CHAIN_150_CODE


    def _is_chain_200(self, product):
        if not self._is_plastic_chain(product):
            return False
        return self._lx_get_chain_code_value(product) == PLASTIC_CHAIN_200_CODE


    def _want_chain_150(self, height_m=None):
        """
        Rule: height <= 2.70 → chain 150, else 200.
        """
        h = float(height_m if height_m is not None else (self.lx_height_m or 0.0))
        return h <= 2.70


    def _filter_plastic_chain_in_raw_vals(self, raw_vals_list, height_m=None):
        """
        During BoM explosion:
        Keep ONLY one plastic chain line according to height rule.
        If multiple chains exist → drop the wrong ones.
        """
        if not raw_vals_list:
            return raw_vals_list

        Product = self.env["product.product"]
        want_150 = self._want_chain_150(height_m)

        kept = []
        chain_candidates = []

        for vals in raw_vals_list:
            pid = vals.get("product_id")
            p = Product.browse(pid) if pid else False

            if p and self._is_plastic_chain(p):
                chain_candidates.append((vals, p))
            else:
                kept.append(vals)

        if not chain_candidates:
            return raw_vals_list

        for vals, p in chain_candidates:
            if want_150 and self._is_chain_150(p):
                kept.append(vals)
                break
            if (not want_150) and self._is_chain_200(p):
                kept.append(vals)
                break

        return kept


    def _enforce_plastic_chain_singleton(self):
        """
        On existing stock moves:
        Ensure ONLY one plastic chain move exists.
        Wrong one is deleted or qty forced to zero.
        """
        for mo in self:
            want_150 = mo._want_chain_150(mo.lx_height_m)

            chain_moves = mo.move_raw_ids.filtered(
                lambda m: mo._is_plastic_chain(m.product_id)
            )

            if len(chain_moves) <= 1:
                continue

            correct_move = False

            for mv in chain_moves:
                if want_150 and mo._is_chain_150(mv.product_id):
                    correct_move = mv
                    break
                if (not want_150) and mo._is_chain_200(mv.product_id):
                    correct_move = mv
                    break

            for mv in chain_moves:
                if mv == correct_move:
                    continue

                done_qty = getattr(mv, "quantity_done", 0.0)

                can_unlink = (
                    mv.state == "draft"
                    and not mv.move_lines
                    and not done_qty
                )

                if can_unlink:
                    mv.unlink()
                else:
                    mv.write({"product_uom_qty": 0.0})

    # ================================================================
    # WASTE / REMNANT ENGINE – ORIENTATION
    # ================================================================
    def _lx_is_day_night(self):
        """
        Check if the roller blind category is Day & Night.
        (Même règle que pour la hauteur max dans ton code original.)
        """
        self.ensure_one()
        cat = self.product_id.categ_id
        return bool(cat and "day & night" in (cat.name or "").lower())

    def _lx_is_screensun(self):
        """
        Heuristique pour détecter une catégorie 'sunscreen' (pour tester
        les deux sens et choisir la meilleure orientation).
        """
        self.ensure_one()
        cat = self.product_id.categ_id
        if not cat:
            return False
        name = (cat.name or '').replace(' ', '').lower()
        return 'sunscreen' in name


    def _lx_find_fabric_move(self):
        """
        Pick the first raw move whose template is fabric-like.
        """
        self.ensure_one()
        return self.move_raw_ids.filtered(
            lambda m: m.product_id
            and m.product_id.product_tmpl_id._lx_template_is_fabric_like()
        )[:1]

    def _lx_add_remnant_quant(self, fabric_move, qty_rem, treasure, lot=None):
        """
        Ajoute directement la quantité de remnant dans le stock Odoo
        SANS passer par un Purchase Order ni un picking.

        - Utilise stock.quant._update_available_quantity()
        - Location = WH/Treasure
        - Lot :
            * priorité au lot du fabric_move (restrict_lot_id ou move_line_ids)
            * sinon, pas de lot (lot_id=False)

        Cette quantité servira ensuite à être réservée/consommée par
        fabric_move._action_assign() quand on réutilise la chute.
        """
        self.ensure_one()
        Quant = self.env['stock.quant'].sudo()

        if not fabric_move or qty_rem <= 0.0 or not treasure:
            return False

        product = fabric_move.product_id

        # Si aucun lot explicitement passé, on essaie de reprendre celui du move tissu
        if not lot:
            lot = False
            # 1) restrict_lot_id si présent
            if hasattr(fabric_move, 'restrict_lot_id') and fabric_move.restrict_lot_id:
                lot = fabric_move.restrict_lot_id
            # 2) sinon lot sur les move_lines
            elif fabric_move.move_line_ids:
                lot = fabric_move.move_line_ids[:1].lot_id

        _logger.info(
            "[WASTE DEBUG] _lx_add_remnant_quant: adding qty=%.4f for product %s in location %s (lot=%s).",
            qty_rem,
            product.display_name,
            treasure.display_name if treasure else 'n/a',
            lot.name if lot else 'n/a',
        )

        # Injection directe dans les quants
        Quant._update_available_quantity(
            product,
            treasure,
            qty_rem,
            lot_id=lot or False,
        )

        return lot
   
    
    def _lx_get_or_create_treasure_location(self):
        """
        Treasure location where reusable remnants are stored.

        Strict rules:
        - If a location named 'Treasure' exists → return it AS-IS (no write)
        - If not found → create it once with:
            * name = 'Treasure'
            * usage = 'inventory'
            * is_lx_treasure = True
            * under warehouse view location (WH/Treasure)
        - Never auto-edit an existing location
        """
        self.ensure_one()
        Location = self.env['stock.location'].sudo()
        Warehouse = self.env['stock.warehouse'].sudo()

        # 1) STRICT SEARCH — do not touch existing record
        loc = Location.search(
            [('name', '=', 'Test-Treasure')],
            limit=1
        )
        if loc:
            return loc

        # 2) CREATE ONLY IF NOT FOUND
        wh = Warehouse.search([], limit=1)
        parent = wh.view_location_id if wh else False

        vals = {
            'name': 'Test-Treasure',
            'usage': 'inventory',      # excluded from Quantity On Hand
            'is_lx_treasure': True,
        }
        if parent:
            vals['location_id'] = parent.id

        loc = Location.create(vals)
        return loc
        
    # ================================================================
    # ORIENTATION / ROLL WIDTH ENGINE
    # ================================================================
    def _lx_get_fabric_template(self):
        """
        Retourne le template 'tissu' à utiliser pour les paramètres :
        - orientation
        - fabric_allowance
        - remenant_threshold
        - roller_width_ids / width_cm

        Priorité :
          1) product_id.product_tmpl_id.lx_fabric_ref_id (fabric lié)
          2) product_id.product_tmpl_id lui-même
        """
        self.ensure_one()
        tmpl = self.product_id.product_tmpl_id
        fabric = tmpl.lx_fabric_ref_id or tmpl
        return fabric

    def _lx_get_Q_factor(self):
        """
        Facteur Q :
          - 2 si catégorie 'Day & Night'
          - 1 sinon
        Utilisé pour calculer la longueur consommée en orientation widthwise.
        """
        self.ensure_one()
        cat = self.product_id.categ_id
        if cat and "day & night" in (cat.name or "").lower():
            return 2.0
        return 1.0

    def _lx_get_all_roll_widths(self):
        """
        Largeurs de rouleaux (en mètres) à partir du TEMPLATE tissu :
        - d'abord fabric.roller_width_ids.value_cm
        - sinon fabric.width_cm
        """
        self.ensure_one()
        fabric = self._lx_get_fabric_template()

        widths = []
        # 1) Tags roller_width_ids (cm → m)
        roller_tags = getattr(fabric, 'roller_width_ids', False)
        if roller_tags:
            for t in roller_tags:
                v_cm = float(getattr(t, 'value_cm', 0.0) or 0.0)
                if v_cm > 0:
                    widths.append(v_cm / 100.0)
        else:
            # 2) width_cm sur le tissu (cm → m)
            w_cm = float(getattr(fabric, 'width_cm', 0.0) or 0.0)
            if w_cm > 0:
                widths.append(w_cm / 100.0)
        return sorted(set(widths))

    def _lx_get_roll_widths_from_lots(self, fabric_product):
        """
        Largeurs de rouleaux (en mètres) réellement disponibles via les LOTS :
        - stock.lot.width_cm est en CENTIMÈTRES (cf. PurchaseOrderLine)
        - on ne fait qu'une projection en mètres, pas de création de lot ici.
        """
        self.ensure_one()
        Lot = self.env['stock.lot'].sudo()
        lots = Lot.search([
            ('product_id', '=', fabric_product.id),
            ('width_cm', '>', 0),
        ])

        # width_cm (int cm) -> m
        widths_m = sorted({float(l.width_cm) / 100.0 for l in lots if l.width_cm})
        _logger.info(
            "[WASTE DEBUG] _lx_get_roll_widths_from_lots: product=%s -> widths_m=%s",
            fabric_product.display_name, widths_m
        )
        return widths_m

    def _lx_get_fabric_allowance(self):
        """
        Fabric allowance en mètres, issu du TEMPLATE tissu :
        - fabric.fabric_allowance est stocké en CENTIMÈTRES
        - fallback sur param système si besoin
        """
        self.ensure_one()
        Param = self.env['ir.config_parameter'].sudo()
        fabric = self._lx_get_fabric_template()

        cm = float(getattr(fabric, 'fabric_allowance', 0.0) or 0.0)
        if not cm:
            cm = float(Param.get_param('luxtor.fabric_allowance_cm', '20') or 20.0)
        return cm / 100.0

    def _lx_get_orientation_candidates(self):
        """
        Orientation selection for cutting:

        On the fabric template (product.template.orientation) we have 2 options:
          - 'widthwise'        → test only widthwise
          - 'width_heightwise' → test widthwise AND heightwise

        No more special cases based on category (e.g. Sunscreen).
        """
        self.ensure_one()
        fabric = self._lx_get_fabric_template()

        # If for some reason we don't find the fabric, stay safe: widthwise only.
        if not fabric:
            return ['widthwise']

        tmpl_orientation = getattr(fabric, 'orientation', 'widthwise') or 'widthwise'
        if tmpl_orientation not in ('widthwise', 'width_heightwise'):
            tmpl_orientation = 'widthwise'

        if tmpl_orientation == 'widthwise':
            return ['widthwise']
        else:
            # 'width_heightwise' → test both
            return ['widthwise', 'heightwise']


    def _lx_get_roll_width(self):
        """
        Largeur de rouleau en m.
        Utilise en priorité lx_roll_width_best (choisie par le moteur).
        Sinon : max des largeurs théoriques du tissu.
        """
        self.ensure_one()
        if self.lx_roll_width_best:
            W_roll = float(self.lx_roll_width_best or 0.0)
        else:
            widths = self._lx_get_all_roll_widths()
            W_roll = max(widths) if widths else 0.0

        fabric = self._lx_get_fabric_template()
        width_cm = W_roll * 100.0 if W_roll else 0.0

        _logger.info(
            "[WASTE DEBUG] _lx_get_roll_width: fabric=%s, width_cm=%.2f → W_roll=%.3f",
            fabric.display_name,
            width_cm,
            W_roll,
        )
        return W_roll

    # ================================================================
    # ORIENTATION ENGINE (the RULES)
    # ================================================================
    def _lx_pick_orientation_and_roll(self):
        """
        Moteur d'ORIENTATION suivant les règles the simplifiées :

        Données :
        - W_store = lx_width_m
        - H_store = lx_height_m
        - A       = fabric_allowance (m)
        - Q       = 2 si Day & Night, sinon 1

        FORMULES WASTE :

        ORIENTATION = WIDTHWISE
            WASTE = roll_width - W_store - 0.03

        ORIENTATION = HEIGHTWISE
            WASTE = roll_width - 0.06 - H_store - A

        Pour chaque largeur de rouleau et orientation candidate :
        - on calcule WASTE,
        - on garde WASTE > 0 (rouleau assez large),
        - on choisit la combinaison avec WASTE minimal.

        Pour la chute, on reconstruit un rectangle :
        - W_rem = WASTE
        - H_rem :
            * widthwise  -> Q * H_store + A
            * heightwise -> W_store - 0.03

        Retour :
            (W_rem, H_rem, roll_width_best, orientation_best)
        ou False si aucune combinaison valide.
        """
        self.ensure_one()

        if not self.lx_width_m or not self.lx_height_m:
            return False

        W_store = float(self.lx_width_m)
        H_store = float(self.lx_height_m)

        # Produit tissu à partir du move (si déjà présent) sinon le produit de l'OF
        fabric_move = self._lx_find_fabric_move()
        fabric_product = fabric_move.product_id if fabric_move else self.product_id

        # 1) Largeurs issues des LOTS (stock réel)
        widths = self._lx_get_roll_widths_from_lots(fabric_product)
        # 2) Si rien en stock, on retombe sur les largeurs du template tissu
        if not widths:
            widths = self._lx_get_all_roll_widths()
        if not widths:
            return False

        A = self._lx_get_fabric_allowance()
        Q = self._lx_get_Q_factor()
        orientation_candidates = self._lx_get_orientation_candidates()

        best_waste = None
        best_data = None  # (W_rem, H_rem, roll_width, orientation)

        for roll_width in widths:
            roll_width = float(roll_width or 0.0)
            if roll_width <= 0.0:
                continue

            for orient in orientation_candidates:
                if orient == 'heightwise':
                    # WASTE = roll_width - 0.06 - H_store - A
                    waste_w = roll_width - 0.06 - H_store - A
                else:
                    # WIDTHWISE: WASTE = roll_width - W_store - 0.03
                    waste_w = roll_width - W_store - 0.03

                waste_w = float(waste_w)
                if waste_w <= 0.0:
                    continue  # rouleau trop petit ou pile 0

                # Reconstruction de la chute
                if orient == 'heightwise':
                    W_rem = waste_w
                    H_rem = max(W_store - 0.03, 0.0)
                else:  # widthwise
                    W_rem = waste_w
                    H_rem = max(Q * H_store + A, 0.0)

                if best_waste is None or waste_w < best_waste:
                    best_waste = waste_w
                    best_data = (W_rem, H_rem, roll_width, orient)

        if not best_data:
            return False

        W_rem, H_rem, roll_width_best, orient_best = best_data
        _logger.info(
            "[WASTE DEBUG] _lx_pick_orientation_and_roll: "
            "orient=%s, W_store=%.3f, H_store=%.3f, A=%.3f, Q=%.1f, roll=%.3f, "
            "waste_w=%.3f, W_rem=%.3f, H_rem=%.3f",
            orient_best, W_store, H_store, A, Q, roll_width_best,
            best_waste, W_rem, H_rem,
        )
        return best_data

    def _lx_compute_remnant_dims(self):
        """
        Calcule W_rem / H_rem avec le moteur d'orientation combiné aux données
        dynamiques du template (orientation, fabric_allowance, roller_width_ids).

        1) Tente _lx_pick_orientation_and_roll()
        2) Si aucun cas valide → fallback sur l'ancien calcul (max width, widthwise).
        """
        self.ensure_one()

        if not self.lx_width_m or not self.lx_height_m:
            return 0.0, 0.0

        chosen = self._lx_pick_orientation_and_roll()
        if chosen:
            W_rem, H_rem, roll_width_best, orient_best = chosen
            self.lx_roll_width_best = roll_width_best
            self.lx_orientation = orient_best

            _logger.info(
                "[WASTE DEBUG] _lx_compute_remnant_dims: orientation=%s, "
                "roll=%.3f, W_rem=%.3f, H_rem=%.3f",
                orient_best, roll_width_best, W_rem, H_rem,
            )
            return W_rem, H_rem

        # Fallback : ancien comportement
        widths = self._lx_get_all_roll_widths()
        if not widths:
            return 0.0, 0.0

        W_store = float(self.lx_width_m)
        H_store = float(self.lx_height_m)
        A = self._lx_get_fabric_allowance()
        Q = self._lx_get_Q_factor()

        H_bom_old = Q * H_store + A
        W_roll = max(widths)
        W_rem = max(W_roll - W_store - 0.03, 0.0)
        H_rem = max(H_bom_old, 0.0)

        self.lx_roll_width_best = W_roll
        self.lx_orientation = 'widthwise'

        _logger.info(
            "[WASTE DEBUG] _lx_compute_remnant_dims (fallback): "
            "orientation=widthwise, W_store=%.3f, H_store=%.3f, "
            "A=%.3f, Q=%.1f, roll=%.3f, W_rem=%.3f, H_rem=%.3f",
            W_store, H_store, A, Q, W_roll, W_rem, H_rem,
        )
        return W_rem, H_rem

    
    # ================================================================
    # REMNANT TOLERANCE TARGETS (W/H + permutation)
    # ================================================================
    def _lx_get_remnant_search_targets(self):
        """
        Retourne la liste des couples (width_target, height_target) à utiliser
        pour la recherche de chutes.

        - Cas 1 : orientation du tissu = 'widthwise'
            → on ne teste que (W_store, H_store).
        - Cas 2 : orientation du tissu = 'width_heightwise'
            → on teste (W_store, H_store) PUIS (H_store, W_store).
              (c'est exactement le cas 2 du document : WIDTHWISE & HEIGHTWISE,
               puis permutation W/H.)
        """
        self.ensure_one()

        W_store = float(self.lx_width_m or 0.0)
        H_store = float(self.lx_height_m or 0.0)
        if not W_store or not H_store:
            return []

        fabric = self._lx_get_fabric_template()
        tmpl_orientation = getattr(fabric, 'orientation', 'widthwise') or 'widthwise'
        if tmpl_orientation not in ('widthwise', 'width_heightwise'):
            tmpl_orientation = 'widthwise'

        # Cible principale
        targets = [(W_store, H_store)]

        # Si le tissu est défini en WIDTHWISE & HEIGHTWISE → ajouter permutation
        if tmpl_orientation == 'width_heightwise':
            targets.append((H_store, W_store))

        return targets


    # ================================================================
    # REMNANT TOLERANCE (USE remenant_threshold FROM TEMPLATE)
    # ================================================================

    def _lx_remnant_matches_tolerance(self, waste, width_target, height_target):
        """
        Vérifie si une chute 'waste' est réutilisable pour
        (width_target, height_target), en appliquant strictement les
        règles du document d'exceptions :

        1) Défaut max :
             w >= width_target  - 0.03  (3 cm)
             h >= height_target - 0.02  (2 cm)

        2) Excès max :
             w <= width_target  * 1.5   (150 %)
             h <= height_target * 1.5   (150 %)

        3) Seuil min remenant_threshold (cm → m) du template tissu.
        """
        self.ensure_one()

        if not waste:
            return False

        w = float(waste.width_m or 0.0)
        h = float(waste.height_m or 0.0)
        if w <= 0.0 or h <= 0.0:
            return False

        width_target = float(width_target or 0.0)
        height_target = float(height_target or 0.0)
        if width_target <= 0.0 or height_target <= 0.0:
            return False

        # 1) Bornes MIN/MAX issues du document (cm → m)
        width_min = max(width_target - 0.03, 0.0)      # W - 3 cm
        width_max = width_target * 1.5                 # 150 %
        height_min = max(height_target - 0.02, 0.0)    # H - 2 cm
        height_max = height_target * 1.5               # 150 %

        if w < width_min or w > width_max:
            return False
        if h < height_min or h > height_max:
            return False

        # 2) Seuil min remenant_threshold (template tissu)
        tmpl = self.product_id.product_tmpl_id
        fabric = tmpl.lx_fabric_ref_id or tmpl

        threshold_m = 0.0
        if hasattr(fabric, "_lx_get_remenant_threshold_m"):
            try:
                threshold_m = fabric._lx_get_remenant_threshold_m()
            except Exception:
                threshold_m = 0.0
        else:
            cm = float(getattr(fabric, 'remenant_threshold', 0.0) or 0.0)
            threshold_m = cm / 100.0

        if threshold_m > 0.0 and (w < threshold_m or h < threshold_m):
            return False

        return True

    def _lx_remnant_tolerance_score(self, waste, width_target, height_target):
        """
        Retourne un score de tolérance pour (waste, width_target, height_target)
        SI la chute respecte les bornes de tolérance, sinon None.

        Score simple :
          - somme des excès positifs sur W et H :
              max(w - width_target, 0) + max(h - height_target, 0)
          - Plus le score est petit, plus la chute est "ajustée".
        """
        if not self._lx_remnant_matches_tolerance(waste, width_target, height_target):
            return None

        w = float(waste.width_m or 0.0)
        h = float(waste.height_m or 0.0)

        dw = max(w - float(width_target or 0.0), 0.0)
        dh = max(h - float(height_target or 0.0), 0.0)
        return dw + dh


    def _lx_find_best_remnant(self, fabric_product):
        self.ensure_one()
        Waste = self.env['luxtor.waste'].sudo()
        treasure = self._lx_get_or_create_treasure_location()

        if not fabric_product:
            return False

        domain = [
            ('product_id', '=', fabric_product.id),
            ('location_id', '=', treasure.id),
            ('waste_type', 'in', ('remnant', 'roll_end')),
            ('is_consumed', '=', False),
            ('qty', '>', 0),
            ('lot_id', '!=', False),  # IMPORTANT
        ]
        candidates = Waste.search(domain)
        if not candidates:
            return False

        targets = self._lx_get_remnant_search_targets()
        if not targets:
            return False

        best_waste = None
        best_score = None
        best_area = None

        for waste in candidates:
            for (width_target, height_target) in targets:
                score = self._lx_remnant_tolerance_score(waste, width_target, height_target)
                if score is None:
                    continue

                area = float(waste.area_m2 or 0.0)

                if best_score is None or score < best_score or (score == best_score and area < (best_area or 0.0)):
                    best_waste = waste
                    best_score = score
                    best_area = area

        return best_waste or False
  

    # ================================================================
    # NEW ROLL PREPARATION (NO LOT CREATION HERE)
    # ================================================================
    def _lx_get_or_create_roll_lot(self, fabric_product, roll_width):
        """
        ⚠ Version modifiée : NE CRÉE PLUS DE LOT.

        On tente juste de retrouver un lot existant pour ce produit + largeur.
        La création de lot se fait côté PurchaseOrderLine.
        """
        self.ensure_one()
        Lot = self.env['stock.lot'].sudo()

        # roll_width est en m ; StockLot.width_cm est en cm
        width_cm = int(round(roll_width * 100))

        lot = Lot.search([
            ('product_id', '=', fabric_product.id),
            ('width_cm', '=', width_cm),
        ], limit=1)

        if lot:
            return lot

        _logger.info(
            "[WASTE DEBUG] _lx_get_or_create_roll_lot: NO lot found for product %s width %s cm; "
            "lot creation is handled on PurchaseOrderLine, so we skip.",
            fabric_product.display_name, width_cm
        )
        return False


    def _lx_prepare_new_roll_draft(self, fabric_move):
        """
        Draft: prepare using an existing NEW roll (lot created on PO receipt).

        What this method does:
        - set source location (MO source or warehouse stock)
        - choose roll width (engine best or fallback)
        - find the roll lot for (product + width) (do NOT create here if not found)
        - set lot on move + move lines
        - ALSO set candidate lot fields so UI shows the selected lot even when no remnant is used
        (lx_candidate_lot_id / lx_candidate_lot_ids)
        """
        self.ensure_one()
        if not fabric_move:
            return

        # 1) Source location = location_src_id of MO or main stock
        src_loc = self.location_src_id
        if not src_loc:
            Warehouse = self.env["stock.warehouse"].sudo()
            wh = Warehouse.search([], limit=1)
            src_loc = wh.lot_stock_id if wh else False

        if src_loc:
            fabric_move.location_id = src_loc.id

        # 2) Roll width chosen by engine
        roll_width = self.lx_roll_width_best or self._lx_get_roll_width()
        if not roll_width:
            _logger.info(
                "[WASTE DEBUG] _lx_prepare_new_roll_draft: no roll_width for MO %s.",
                self.name,
            )
            return

        # 3) Get existing lot for this product + width (no creation here if missing)
        lot = self._lx_get_or_create_roll_lot(fabric_move.product_id, roll_width)

        if not lot:
            _logger.info(
                "[WASTE DEBUG] _lx_prepare_new_roll_draft: no existing lot for product %s width %.2f m. "
                "Lot creation is done on purchase; we only set source location.",
                fabric_move.product_id.display_name, roll_width,
            )
            return

        _logger.info(
            "[WASTE DEBUG] _lx_prepare_new_roll_draft: MO %s -> src_loc=%s, roll_width=%.2f, lot=%s (id=%s)",
            self.name,
            src_loc.display_name if src_loc else "n/a",
            roll_width,
            lot.name,
            lot.id,
        )

        # 4) Assign lot on move (compat)
        vals_move = {}
        if hasattr(fabric_move, "restrict_lot_id"):
            vals_move["restrict_lot_id"] = lot.id
        if hasattr(fabric_move, "lot_ids"):
            vals_move["lot_ids"] = [(6, 0, [lot.id])]

        # 5) Make UI consistent: show which lot was selected even for "new roll" case
        if "lx_candidate_lot_id" in fabric_move._fields:
            vals_move["lx_candidate_lot_id"] = lot.id
        if "lx_candidate_lot_ids" in fabric_move._fields:
            vals_move["lx_candidate_lot_ids"] = [(6, 0, [lot.id])]

        if vals_move:
            fabric_move.write(vals_move)

        # 6) Update move lines (lot + source location)
        if fabric_move.move_line_ids:
            vals_ml = {"lot_id": lot.id}
            if src_loc:
                vals_ml["location_id"] = src_loc.id

            # Some versions/flows also like product_uom_id in ml, but keep it minimal here
            fabric_move.move_line_ids.write(vals_ml)

   
    # ================================================================
    # FIXED: DRAFT-STAGE PREP (lot display + chatter debug)
    # ================================================================
    def _lx_prepare_remnant_draft(self):
        for mo in self:
            if mo.state not in ("draft", "confirmed", "planned"):
                continue

            fabric_move = mo._lx_find_fabric_move()
            if not fabric_move:
                mo.lx_remnant_candidate_id = False
                mo.lx_remnant_candidate_lot_id = False
                _logger.info("[WASTE DEBUG] _lx_prepare_remnant_draft: no fabric_move for MO %s.", mo.name)
                continue

            treasure = mo._lx_get_or_create_treasure_location()

            # Build candidate lots (tags)
            cand_wastes = mo._lx_get_candidate_wastes(fabric_move.product_id, limit=12)
            cand_lot_ids = cand_wastes.mapped("lot_id").ids

            best = mo._lx_find_best_remnant(fabric_move.product_id)

            # --- NO CANDIDATE ---
            if not best:
                log = []
                log.append("[WASTE DEBUG] _lx_prepare_remnant_draft: NO suitable remnant found.")
                log.append(f"[WASTE DEBUG] MO={mo.name} move_id={fabric_move.id} product={fabric_move.product_id.display_name}")

                mo.remnant_reused_id = False
                mo.lx_remnant_candidate_id = False
                mo.lx_remnant_candidate_lot_id = False

                # Clear tags/selected lot on the move
                fabric_move.write({
                    "lx_candidate_lot_id": False,
                    "lx_candidate_lot_ids": [(6, 0, cand_lot_ids or [])],  # still useful to show options
                })

                # keep your original correction attempt
                try:
                    if fabric_move.location_id == treasure and mo.location_src_id:
                        fabric_move.location_id = mo.location_src_id.id
                except Exception:
                    pass

                mo._lx_prepare_new_roll_draft(fabric_move)
                mo.message_post(body="\n".join(log))
                continue

            # --- CANDIDATE FOUND ---
            lot = best.lot_id

            # Make sure selected lot is included in tags
            if lot and lot.id not in cand_lot_ids:
                cand_lot_ids = [lot.id] + cand_lot_ids

            log = []
            log.append("[WASTE DEBUG] _lx_prepare_remnant_draft: candidate remnant FOUND.")
            log.append(f"[WASTE DEBUG] MO={mo.name} state={mo.state}")
            log.append(f"[WASTE DEBUG] move_id={fabric_move.id} product={fabric_move.product_id.display_name}")
            log.append(
                "[WASTE DEBUG] candidate="
                f"{best.display_name} (id={best.id}) qty={float(best.qty or 0.0):.4f} "
                f"W={float(best.width_m or 0.0):.4f} H={float(best.height_m or 0.0):.4f} "
                f"lot={lot.name if lot else 'n/a'}"
            )

            # 1) redirect source location to Treasure
            fabric_move.location_id = treasure.id

            # 2) set lot consistently for correct UI display
            if lot:
                if hasattr(fabric_move, "restrict_lot_id"):
                    fabric_move.restrict_lot_id = lot
                if hasattr(fabric_move, "lot_ids"):
                    fabric_move.lot_ids = [(6, 0, [lot.id])]

            # 3) update move lines if they exist
            if fabric_move.move_line_ids:
                vals_ml = {"location_id": treasure.id}
                if lot:
                    vals_ml["lot_id"] = lot.id
                fabric_move.move_line_ids.write(vals_ml)

            # 4) store candidate fields on MO
            mo.remnant_reused_id = best
            mo.lx_remnant_candidate_id = best
            mo.lx_remnant_candidate_lot_id = lot

            # 5) store candidate lots + selected on the MOVE (your requested feature)
            fabric_move.write({
                "lx_candidate_lot_id": lot.id if lot else False,
                "lx_candidate_lot_ids": [(6, 0, cand_lot_ids or [])],
            })

            mo.message_post(body="\n".join(log))



    def _lx_get_candidate_wastes(self, fabric_product, limit=12):
        """
        Return candidate waste records from Treasure for the given fabric product.
        Used to populate stock.move candidate lot tags (lx_candidate_lot_ids).

        limit: keep it small to avoid UI clutter.
        """
        self.ensure_one()
        Waste = self.env["luxtor.waste"].sudo()
        treasure = self._lx_get_or_create_treasure_location()

        if not fabric_product:
            return Waste.browse()

        domain = [
            ("product_id", "=", fabric_product.id),
            ("location_id", "=", treasure.id),
            ("waste_type", "in", ("remnant", "roll_end")),
            ("is_consumed", "=", False),
            ("qty", ">", 0),
            ("lot_id", "!=", False),  # IMPORTANT for tags
        ]
        # You can refine ordering later (closest dims, newest, etc.)
        return Waste.search(domain, limit=limit)

    # ================================================================
    # FIXED: CONFIRM-STAGE ASSIGNMENT (lot assignment + chatter debug)
    # ================================================================
    def _lx_try_assign_remnant(self):
        for mo in self:
            fabric_move = mo._lx_find_fabric_move()
            if not fabric_move:
                _logger.info("[WASTE DEBUG] _lx_try_assign_remnant: no fabric_move found for MO %s.", mo.name)
                continue

            treasure = mo._lx_get_or_create_treasure_location()

            # ensure we have tags candidates
            cand_wastes = mo._lx_get_candidate_wastes(fabric_move.product_id, limit=12)
            cand_lot_ids = cand_wastes.mapped("lot_id").ids

            best = mo.remnant_reused_id or mo._lx_find_best_remnant(fabric_move.product_id)

            log = []
            log.append("[WASTE DEBUG] _lx_try_assign_remnant: confirm-stage started.")
            log.append(f"[WASTE DEBUG] MO={mo.name} state={mo.state} move_id={fabric_move.id} product={fabric_move.product_id.display_name}")

            if not best:
                # still write tags (optional but useful)
                fabric_move.write({
                    "lx_candidate_lot_id": False,
                    "lx_candidate_lot_ids": [(6, 0, cand_lot_ids or [])],
                })
                log.append("[WASTE DEBUG] NO usable remnant found => nothing to assign.")
                mo.message_post(body="\n".join(log))
                continue

            lot = best.lot_id
            if lot and lot.id not in cand_lot_ids:
                cand_lot_ids = [lot.id] + cand_lot_ids

            qty_needed = float(fabric_move.product_uom_qty or 0.0)
            qty_available = float(best.qty or 0.0)

            log.append(
                "[WASTE DEBUG] using remnant="
                f"{best.display_name} (id={best.id}) qty_avail={qty_available:.4f} "
                f"W={float(best.width_m or 0.0):.4f} H={float(best.height_m or 0.0):.4f} "
                f"lot={lot.name if lot else 'n/a'}"
            )
            log.append(f"[WASTE DEBUG] qty_needed(move.product_uom_qty)={qty_needed:.4f}")

            # 1) redirect to Treasure
            fabric_move.location_id = treasure.id

            # 2) set candidate tags + selected lot on move
            fabric_move.write({
                "lx_candidate_lot_id": lot.id if lot else False,
                "lx_candidate_lot_ids": [(6, 0, cand_lot_ids or [])],
            })

            # 3) force lot fields for correct reservation/visibility
            if lot:
                if hasattr(fabric_move, "restrict_lot_id"):
                    fabric_move.restrict_lot_id = lot
                if hasattr(fabric_move, "lot_ids"):
                    fabric_move.lot_ids = [(6, 0, [lot.id])]

            if fabric_move.move_line_ids:
                vals_ml = {"location_id": treasure.id}
                if lot:
                    vals_ml["lot_id"] = lot.id
                fabric_move.move_line_ids.write(vals_ml)

            # 4) reserve from Treasure
            try:
                fabric_move._action_assign()
                log.append("[WASTE DEBUG] _action_assign() executed successfully.")
            except Exception as e:
                _logger.exception("[WASTE DEBUG] _lx_try_assign_remnant: _action_assign error on move %s: %s", fabric_move.id, e)
                log.append(f"[WASTE DEBUG] _action_assign() ERROR: {e}")

            # 5) store on MO
            mo.remnant_reused_id = best
            mo.lx_remnant_candidate_id = best
            mo.lx_remnant_candidate_lot_id = lot

            # 6) mark waste consumed
            best.write({
                "qty": 0.0,
                "is_consumed": True,
                "consume_move_id": fabric_move.id,
            })
            log.append("[WASTE DEBUG] remnant marked as consumed (qty=0, is_consumed=True).")

            mo.message_post(body="\n".join(log))
    
    # ------------------------------------------------------------------
    # Waste generation (preview/final)
    # ------------------------------------------------------------------
    def action_generate_waste(self, preview=False):
        """
        Generate remnant data and (optionally) stock moves.

        preview=True:
        - Remove previous preview lines (waste_ids with no move_id),
        - If a dimension-matching reusable remnant already exists
          => no preview waste is generated,
        - Else: compute remnant W/H and qty, create luxtor.waste without move/lot.

        preview=False:
        - If waste_processed=True, skip,
        - If remnant_reused_id is set, skip (we used an old remnant,
          we do NOT create a new waste for this MO),
        - Remove any existing preview lines,
        - Compute remnant W/H and qty (avec moteur d'orientation),
        - Ensure a lot exists (reuse fabric lot or auto-create LOT-XXXXXN),
        - Create stock.move from MO dest location to Treasure,
        - Set qty_done / quantity_done,
        - Create luxtor.waste line linked to move + lot,
        - Set waste_processed=True.

        Quantity is stored in LINEAR METERS (not m²).
        """
        Waste = self.env['luxtor.waste']
        StockMove = self.env['stock.move']
        StockMoveLine = self.env['stock.move.line']
        Lot = self.env['stock.lot']

        for mo in self:
            debug = []
            debug.append(
                "[WASTE DEBUG] Start action_generate_waste (%s) for MO %s (width=%s, height=%s, orientation=%s)"
                % ("PREVIEW" if preview else "FINAL", mo.name or 'N/A', mo.lx_width_m, mo.lx_height_m, mo.lx_orientation)
            )

            # Si un remnant est déjà réutilisé, on ne génère pas de nouvelle chute.
            if preview and mo.remnant_reused_id:
                debug.append(
                    "[WASTE DEBUG] Preview requested but remnant_reused_id=%s (id=%s) is set "
                    "=> no preview waste for this MO."
                    % (mo.remnant_reused_id.display_name, mo.remnant_reused_id.id)
                )
                mo.message_post(body="\n".join(debug))
                continue

            # --- FINAL : éviter les doublons + respecter remnant_reused_id ---
            if not preview:
                if mo.waste_processed:
                    debug.append("[WASTE DEBUG] Already processed => skip FINAL generation.")
                    mo.message_post(body="\n".join(debug))
                    continue

                if mo.remnant_reused_id:
                    debug.append(
                        "[WASTE DEBUG] Remnant reused (%s, id=%s) for this MO "
                        "=> skip FINAL waste generation."
                        % (mo.remnant_reused_id.display_name, mo.remnant_reused_id.id)
                    )
                    mo.message_post(body="\n".join(debug))
                    continue

                preview_lines = mo.waste_ids.filtered(lambda w: not w.move_id)
                if preview_lines:
                    debug.append(
                        "[WASTE DEBUG] FINAL: removing %s preview waste lines before creating final one."
                        % len(preview_lines)
                    )
                    preview_lines.sudo().unlink()

            # --- PREVIEW : nettoyer les anciens previews ---
            if preview:
                preview_lines = mo.waste_ids.filtered(lambda w: not w.move_id)
                if preview_lines:
                    debug.append(
                        "[WASTE DEBUG] Removing %s existing preview waste lines." % len(preview_lines)
                    )
                    preview_lines.sudo().unlink()

            # 1) Find fabric move
            fabric_move = mo._lx_find_fabric_move()
            if not fabric_move:
                debug.append("[WASTE DEBUG] No fabric_move found => NO waste generated.")
                mo.message_post(body="\n".join(debug))
                continue

            debug.append(
                "[WASTE DEBUG] Found fabric_move: product=%s, qty=%s"
                % (
                    fabric_move.product_id.display_name,
                    fabric_move.product_uom_qty,
                )
            )

            # PREVIEW: check if a dimension-based reusable remnant already exists
            if preview:
                best = mo._lx_find_best_remnant(fabric_move.product_id)
                if best:
                    qty_needed = float(fabric_move.product_uom_qty or 0.0)
                    qty_available = float(best.qty or 0.0)
                    debug.append(
                        "[WASTE DEBUG] PREVIEW: existing reusable remnant found "
                        "(%s, id=%s, qty=%.4f, W=%.2f, H=%.2f) for required qty %.4f "
                        "=> no preview waste generated for this MO (dimension-based match)."
                        % (
                            best.display_name,
                            best.id,
                            qty_available,
                            best.width_m or 0.0,
                            best.height_m or 0.0,
                            qty_needed,
                        )
                    )
                    mo.message_post(body="\n".join(debug))
                    continue

            # 2) Compute remnant dims (utilise le moteur d'orientation)
            W_rem, H_rem = mo._lx_compute_remnant_dims()
            debug.append(
                "[WASTE DEBUG] Computed remnant dims: W_rem=%.4f m, H_rem=%.4f m (orientation=%s, roll=%.3f)"
                % (W_rem, H_rem, mo.lx_orientation, mo.lx_roll_width_best)
            )

            if not W_rem or not H_rem:
                debug.append(
                    "[WASTE DEBUG] W_rem or H_rem = 0 => NO waste generated."
                )
                mo.message_post(body="\n".join(debug))
                continue

            # 3) Compute remnant qty (linear metres)
            # Business rule (updated):
            #   - Quantity is ALWAYS the remnant HEIGHT in linear metres
            #   - No more area / roll_width, no more "sunscreen" exception.
            area = W_rem * H_rem
            qty_rem = H_rem
            debug.append(
                "[WASTE DEBUG] area=%.4f m², qty_rem (HEIGHT in lm)=%.4f"
                % (area, qty_rem)
            )

            if qty_rem <= 0.0:
                debug.append(
                    "[WASTE DEBUG] qty_rem <= 0 => NO waste generated."
                )
                mo.message_post(body="\n".join(debug))
                continue




            # 4) Treasure location
            treasure = mo._lx_get_or_create_treasure_location()
            debug.append(
                "[WASTE DEBUG] Using treasure location: %s (id=%s)"
                % (treasure.display_name, treasure.id)
            )

            # PREVIEW: just create luxtor.waste (no move, no lot)
            if preview:
                waste_rec = Waste.create({
                    "production_id": mo.id,
                    "product_id": fabric_move.product_id.id,
                    "lot_id": False,
                    "location_id": treasure.id,
                    "move_id": False,
                    "waste_type": "remnant",
                    "width_m": W_rem,
                    "height_m": H_rem,
                    "qty": qty_rem,
                })
                debug.append(
                    "[WASTE DEBUG] PREVIEW: Created luxtor.waste id=%s (name=%s)"
                    % (waste_rec.id, waste_rec.name)
                )
                mo.message_post(body="\n".join(debug))
                continue

            # FINAL : ajouter le remnant directement dans le stock via QUANT
            lot = False
            try:
                lot = mo._lx_add_remnant_quant(
                    fabric_move=fabric_move,
                    qty_rem=qty_rem,
                    treasure=treasure,
                    lot=None,   # on laisse la méthode récupérer le lot du move si possible
                )
                debug.append(
                    "[WASTE DEBUG] FINAL: Remnant quant added in WH/Treasure "
                    "(qty=%.4f, lot=%s)."
                    % (
                        qty_rem,
                        lot.name if lot else 'n/a',
                    )
                )
            except Exception as e:
                debug.append(
                    "[WASTE DEBUG] FINAL: ERROR while adding remnant quant in WH/Treasure: %s"
                    % e
                )

            # Create luxtor.waste record (sans move_id, on ne crée plus de move spécifique)
            waste_rec_vals = {
                "production_id": mo.id,
                "product_id": fabric_move.product_id.id,
                "lot_id": lot.id if lot else False,
                "location_id": treasure.id,
                "waste_type": "remnant",
                "width_m": W_rem,
                "height_m": H_rem,
                "qty": qty_rem,           # stored as HEIGHT in lm
            }

            waste_rec = Waste.create(waste_rec_vals)
            debug.append(
                "[WASTE DEBUG] FINAL: Created luxtor.waste id=%s (name=%s)"
                % (waste_rec.id, waste_rec.name)
            )

            mo.waste_processed = True
            debug.append("[WASTE DEBUG] FINAL: waste_processed set to True.")


            # Logs en texte simple dans le chatter (sans HTML)
            mo.message_post(body="\n".join(debug))

        return True

    def action_view_waste(self):
        """
        Smart button helper to open all waste records for this MO.
        """
        self.ensure_one()
        action = self.env.ref('luxtor_custom.action_luxtor_waste').read()[0]
        action['domain'] = [('production_id', '=', self.id)]
        action['context'] = {'default_production_id': self.id}
        return action

    # =======================================================================
    # PRE-CREATION PIPELINE (BOm → moves)
    # =======================================================================
    def _apply_absolute_rules_pre_snapshot(self, raw_vals_list, width_m=None):
        """
        Step 1: Work on product_uom_qty BEFORE mirroring:
          - Bracket qty:
              * product_uom_qty (to consume) = floor(((W-0.3)/0.95)+2), min 0
              * lx_bom_uom_qty (snapshot)   = floor(((1-0.3)/0.95)+2), min 0
          - If Headrail present => Adhesive qty = 2 (fixed)
        """
        if not raw_vals_list:
            return raw_vals_list

        Product = self.env['product.product']
        w = float(width_m or 0.0)

        for vals in raw_vals_list:
            prod = Product.browse(vals.get('product_id'))
            tmpl = prod.product_tmpl_id if prod else False

            if tmpl and getattr(tmpl, 'is_mounting_bracket', False):
                try:
                    qty_real = math.floor(((w - 0.3) / 0.95) + 2)
                except ZeroDivisionError:
                    qty_real = 2
                qty_real = max(qty_real, 0)
                vals['product_uom_qty'] = qty_real

                try:
                    qty_virtual = math.floor(((1.0 - 0.3) / 0.95) + 2)
                except ZeroDivisionError:
                    qty_virtual = 2
                vals['lx_bom_uom_qty'] = max(qty_virtual, 0)
                continue



        return raw_vals_list

    def _apply_dimension_scaling_from_snapshot(
        self,
        raw_vals_list,
        width_m=None,
        height_m=None,
    ):
        """
        Step 3: From snapshot (lx_bom_uom_qty) recompute product_uom_qty for most components.

        Pour les tissus (templates avec roller_width_ids, lx_qty_by_width et
        lx_qty_by_height), on applique la même logique que pour le moteur :

          - base = Q * H + A    si orientation = widthwise
          - base = W - 0.03     si orientation = heightwise

        et product_uom_qty = snapshot * base.

        Pour les autres composants, on garde ton comportement d'origine.
        """
        if not raw_vals_list:
            return raw_vals_list

        self.ensure_one()
        Product = self.env['product.product']
        Param = self.env['ir.config_parameter'].sudo()

        w = float(width_m or 0.0)
        h = float(height_m or 0.0)
        Q = self._lx_get_Q_factor()
        orientation = self.lx_orientation or 'widthwise'

        for vals in raw_vals_list:
            prod = Product.browse(vals.get('product_id'))
            tmpl = prod.product_tmpl_id if prod else False

            snap = vals.get('lx_bom_uom_qty')
            if snap is None:
                snap = vals.get('product_uom_qty', 0.0)
            snap = float(snap or 0.0)

            if tmpl and getattr(tmpl, 'is_mounting_bracket', False):
                # Les brackets sont déjà gérées dans _apply_absolute_rules_pre_snapshot
                continue

            if tmpl:
                has_w = bool(getattr(tmpl, 'lx_qty_by_width', False))
                has_h = bool(getattr(tmpl, 'lx_qty_by_height', False))
                is_fabric = bool(getattr(tmpl, 'roller_width_ids', False))

                if has_w and has_h and is_fabric:
                    # Tissu de store : on utilise la même logique que le moteur the
                    allowance_cm = float(getattr(tmpl, "fabric_allowance", 0.0) or 0.0)
                    if not allowance_cm:
                        allowance_cm = float(
                            Param.get_param('luxtor.fabric_allowance_cm', '20') or 20.0
                        )
                    allowance_m = allowance_cm / 100.0

                    if orientation == 'heightwise':
                        # L_h = New Fabric width = W - 0.03
                        base = max(w - 0.03, 0.0)
                    else:
                        # L_w = Height * Q + Fabric allowance
                        base = max(Q * h + allowance_m, 0.0)

                    # IMPORTANT : pour le tissu, on prend directement base comme to_consume
                    # (en mètres linéaires) et on NE multiplie PAS par le snapshot.
                    vals['product_uom_qty'] = base

                elif has_w and not is_fabric:
                    # Composant linéaire classique (guides, etc.)
                    vals['product_uom_qty'] = snap * w

                else:
                    vals['product_uom_qty'] = snap


        return raw_vals_list

    def _get_moves_raw_values(self):
        """
        Explosion BoM → valeurs de moves :
          1) on appelle super()
          2) on applique les règles absolues (brackets, headrail/adhésif)
          3) on prend un snapshot lx_bom_uom_qty
          4) on filtre les chaînes plastiques
          5) on applique le scaling dimensionnel (incl. logique tissu/orientation)
        """
        res = super()._get_moves_raw_values() or []

        # Calculer orientation + largeur de rouleau une fois pour assurer
        # la cohérence entre consommations et chutes.
        self._lx_compute_remnant_dims()

        res = self._apply_absolute_rules_pre_snapshot(res, width_m=self.lx_width_m)

        for vals in res:
            if 'lx_bom_uom_qty' not in vals:
                vals['lx_bom_uom_qty'] = float(vals.get('product_uom_qty') or 0.0)

        res = self._filter_plastic_chain_in_raw_vals(res, height_m=self.lx_height_m)

        return self._apply_dimension_scaling_from_snapshot(
            res, width_m=self.lx_width_m, height_m=self.lx_height_m
        )

    # =======================================================================
    # RECALCUL DES QUANTITÉS À CONSOMMER SUR LES MOVES EXISTANTS
    # =======================================================================
    def _recalc_to_consume_quantities(self, width_param=None, height_param=None):
        """
        Recalcule product_uom_qty sur les moves existants à partir du snapshot
        lx_bom_uom_qty, des dimensions et de l'orientation.

        Important : la logique tissu ici doit rester cohérente avec
        _apply_dimension_scaling_from_snapshot.
        """
        Param = self.env['ir.config_parameter'].sudo()

        for mo in self:
            w = float(mo.lx_width_m if width_param is None else width_param) or 0.0
            h = float(mo.lx_height_m if height_param is None else height_param) or 0.0
            Q = mo._lx_get_Q_factor()
            orientation = mo.lx_orientation or 'widthwise'

            for m in mo.move_raw_ids:
                tmpl = m.product_id.product_tmpl_id if m.product_id else False
                snap = float(m.lx_bom_uom_qty or m.product_uom_qty or 0.0)

                if tmpl and getattr(tmpl, 'is_mounting_bracket', False):
                    # Règle spécifique pour les supports
                    try:
                        m.product_uom_qty = max(math.floor(((w - 0.3) / 0.95) + 2), 0)
                    except ZeroDivisionError:
                        m.product_uom_qty = 2
                    continue

                if tmpl:
                    has_w = bool(getattr(tmpl, 'lx_qty_by_width', False))
                    has_h = bool(getattr(tmpl, 'lx_qty_by_height', False))
                    is_fabric = bool(getattr(tmpl, 'roller_width_ids', False))

                    if has_w and has_h and is_fabric:
                        # Tissu : même logique que dans _apply_dimension_scaling_from_snapshot
                        allowance_cm = float(getattr(tmpl, "fabric_allowance", 0.0) or 0.0)
                        if not allowance_cm:
                            allowance_cm = float(
                                Param.get_param('luxtor.fabric_allowance_cm', '20') or 20.0
                            )
                        allowance_m = allowance_cm / 100.0

                        if orientation == 'heightwise':
                            base = max(w - 0.03, 0.0)
                        else:
                            base = max(Q * h + allowance_m, 0.0)

                        # Ici aussi : base seul = quantité à consommer (en m linéaire)
                        m.product_uom_qty = base

                    elif has_w and not is_fabric:
                        m.product_uom_qty = snap * w

                    else:
                        m.product_uom_qty = snap


    # =======================================================================
    # ONCHANGE / WRITE / CREATE
    # =======================================================================
    @api.onchange('lx_width_m', 'lx_height_m')
    def _onchange_width_recalc(self):
        """
        Quand l'utilisateur change les dimensions depuis le formulaire OF :
          - recalcul des quantités
          - enforcement de la chaîne plastique
          - recalcul des montants
          - régénération de la prévisualisation de chute
        """
        # Recalcule aussi orientation + roll width
        self._lx_compute_remnant_dims()

        self._recalc_to_consume_quantities()
        self._enforce_plastic_chain_singleton()
        for mo in self:
            for m in mo.move_raw_ids:
                m._compute_lx_amount()
        self._compute_lx_totals()
        # preview waste will be refreshed in write()

    def write(self, vals):
        touching_dims = any(k in vals for k in ('lx_width_m', 'lx_height_m'))
        res = super().write(vals)
        if touching_dims and not self.env.context.get('lx_recalc_done'):
            # S'assurer que l'orientation est à jour
            self._lx_compute_remnant_dims()

            self.with_context(lx_recalc_done=True)._recalc_to_consume_quantities()
            self._enforce_plastic_chain_singleton()
            for mo in self:
                mo.move_raw_ids._compute_lx_amount()
            # Prepare remnant reuse at draft stage
            self._lx_prepare_remnant_draft()
            # Generate/refresh preview waste on dimension change
            self.action_generate_waste(preview=True)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        # Calculer orientation / roll width pour chaque OF créé
        for mo in recs:
            mo._lx_compute_remnant_dims()
        recs._recalc_to_consume_quantities()
        recs._enforce_plastic_chain_singleton()
        # Prepare remnant reuse on creation
        recs._lx_prepare_remnant_draft()
        # Generate preview waste right after MO creation (skipped if remnant_reused_id)
        recs.action_generate_waste(preview=True)
        return recs

    def _apply_headrail_adhesive_rule_on_moves(self):
        # Gardé pour compatibilité, tu peux y remettre de la logique plus tard.
        return

    # =======================================================================
    # WORKFLOW : CONFIRM / DONE / PLAN
    # =======================================================================
    def _lx_force_lot_on_move(self, move, lot, location_id=None):
        """Force lot on stock.move AND on all its move lines (reservation lines)."""
        if not move or not lot:
            return

        vals_move = {}
        if hasattr(move, "restrict_lot_id"):
            vals_move["restrict_lot_id"] = lot.id
        if hasattr(move, "lot_ids"):
            vals_move["lot_ids"] = [(6, 0, [lot.id])]
        if "lx_candidate_lot_id" in move._fields:
            vals_move["lx_candidate_lot_id"] = lot.id
        if "lx_candidate_lot_ids" in move._fields:
            # keep existing tags but ensure selected is present
            existing = set(move.lx_candidate_lot_ids.ids)
            existing.add(lot.id)
            vals_move["lx_candidate_lot_ids"] = [(6, 0, list(existing))]

        if vals_move:
            move.write(vals_move)

        # Ensure move lines carry the lot (this is what matters for consumption)
        mls = move.move_line_ids
        if mls:
            vals_ml = {"lot_id": lot.id}
            if location_id:
                vals_ml["location_id"] = location_id.id if hasattr(location_id, "id") else location_id
            # apply lot on any line missing it
            mls.filtered(lambda l: not l.lot_id).write(vals_ml)

    # def action_confirm(self):
    #     """
    #     Standard confirm + Luxtor dimension recalculation + plastic chain rules.

    #     - Preview waste is handled in create/write.
    #     - Remnant reuse is attempted here on the raw fabric move.
    #     - FINAL waste (stock move + luxtor.waste) is generated here.
    #     """
    #     res = super().action_confirm()

    #     for mo in self:
    #         _logger.info(
    #             "[WASTE DEBUG] action_confirm called for MO %s (width=%s, height=%s, orientation=%s).",
    #             mo.name, mo.lx_width_m, mo.lx_height_m, mo.lx_orientation,
    #         )
    #         mo.message_post(body=_(
    #             "[WASTE DEBUG] action_confirm: Luxtor recalculation + plastic chain rules "
    #             "(width=%(w)s, height=%(h)s, orientation=%(o)s). Preview waste is generated "
    #             "on create/write; final waste is generated now on Confirm."
    #         ) % {
    #             'w': mo.lx_width_m,
    #             'h': mo.lx_height_m,
    #             'o': mo.lx_orientation,
    #         })

    #     # Recompute to-consume quantities / chain rules on confirmed moves
    #     self._recalc_to_consume_quantities()
    #     self._enforce_plastic_chain_singleton()

    #     # Try to reuse a remnant from WH/Treasure instead of new fabric
    #     self._lx_try_assign_remnant()

    #     # Generate FINAL waste lines + stock moves (except if remnant_reused_id)
    #     self.action_generate_waste(preview=False)
    #     return res
    def action_confirm(self):
        """
        Standard confirm + Luxtor dimension recalculation + plastic chain rules.

        - Preview waste is handled in create/write.
        - Remnant reuse is attempted here on the raw fabric move.
        - FINAL waste (stock quant + luxtor.waste) is generated here.
        """
        res = super().action_confirm()

        # --- keep your existing logs exactly as-is ---
        for mo in self:
            _logger.info(
                "[WASTE DEBUG] action_confirm called for MO %s (width=%s, height=%s, orientation=%s).",
                mo.name, mo.lx_width_m, mo.lx_height_m, mo.lx_orientation,
            )
            mo.message_post(body=_(
                "[WASTE DEBUG] action_confirm: Luxtor recalculation + plastic chain rules "
                "(width=%(w)s, height=%(h)s, orientation=%(o)s). Preview waste is generated "
                "on create/write; final waste is generated now on Confirm."
            ) % {
                "w": mo.lx_width_m,
                "h": mo.lx_height_m,
                "o": mo.lx_orientation,
            })

        # 1) Recompute quantities / chain rules on confirmed moves
        #    (this may affect reservation, so do it before final lot enforcement)
        self._recalc_to_consume_quantities()
        self._enforce_plastic_chain_singleton()

        # 2) Try to reuse a remnant from WH/Treasure instead of new fabric
        #    (your method handles treasure redirection + candidate fields + remnant consume flag)
        self._lx_try_assign_remnant()

        # 3) FINAL LOT ENFORCEMENT (works for BOTH remnant and new roll)
        for mo in self:
            fabric_move = mo._lx_find_fabric_move()
            if not fabric_move:
                continue

            # Determine the intended lot:
            # - Remnant case: MO candidate lot is authoritative
            # - New roll case: move.lx_candidate_lot_id set by _lx_prepare_new_roll_draft
            # - Fallbacks: restrict_lot_id, existing move line lot
            lot = (
                mo.lx_remnant_candidate_lot_id
                or getattr(fabric_move, "lx_candidate_lot_id", False)
                or getattr(fabric_move, "restrict_lot_id", False)
                or (fabric_move.move_line_ids[:1].lot_id if fabric_move.move_line_ids else False)
            )

            if not lot:
                _logger.info(
                    "[WASTE DEBUG] action_confirm: no lot resolved for MO %s fabric_move=%s "
                    "(cand_mo=%s, cand_move=%s, restrict=%s, ml=%s).",
                    mo.name,
                    fabric_move.id,
                    mo.lx_remnant_candidate_lot_id.name if mo.lx_remnant_candidate_lot_id else "n/a",
                    getattr(fabric_move, "lx_candidate_lot_id", False) and fabric_move.lx_candidate_lot_id.name or "n/a",
                    getattr(fabric_move, "restrict_lot_id", False) and fabric_move.restrict_lot_id.name or "n/a",
                    (fabric_move.move_line_ids[:1].lot_id.name if fabric_move.move_line_ids and fabric_move.move_line_ids[:1].lot_id else "n/a"),
                )
                continue

            # Choose correct source location context
            # - Remnant: Treasure
            # - New roll: MO source / current move location
            location_ctx = False
            if mo.remnant_reused_id:
                location_ctx = mo._lx_get_or_create_treasure_location()
            else:
                location_ctx = mo.location_src_id or fabric_move.location_id

            try:
                # First enforce on move + existing lines (if any)
                mo._lx_force_lot_on_move(fabric_move, lot, location_id=location_ctx)

                # Reserve now (confirm can recreate lines; reservation may happen after our writes)
                fabric_move._action_assign()

                # Enforce AGAIN after assign (this is the key step)
                mo._lx_force_lot_on_move(fabric_move, lot, location_id=location_ctx)

                _logger.info(
                    "[WASTE DEBUG] action_confirm: lot enforced and reserved for MO %s: move=%s lot=%s lines=%s",
                    mo.name,
                    fabric_move.id,
                    lot.name,
                    len(fabric_move.move_line_ids),
                )
            except Exception as e:
                _logger.exception(
                    "[WASTE DEBUG] action_confirm: error while enforcing lot on fabric_move=%s for MO %s: %s",
                    fabric_move.id,
                    mo.name,
                    e,
                )

        # 4) Generate FINAL waste lines + stock quant (except if remnant_reused_id)
        self.action_generate_waste(preview=False)
        return res



    # def button_mark_done(self):
    #     """
    #     After MO is done, ensure FINAL waste/remnants exist.
    #     If they were already generated at confirm (waste_processed=True),
    #     action_generate_waste() will simply skip.
    #     """
    #     res = super().button_mark_done()
    #     self.action_generate_waste(preview=False)
    #     return res

    def button_mark_done(self):
        """
        After MO is done:
        - Ensure FINAL waste/remnants exist.
        - Enforce lot on fabric move lines one last time (safety net).
        """
        res = super().button_mark_done()

        # --- FINAL LOT SAFETY ENFORCEMENT ---
        for mo in self:
            fabric_move = mo._lx_find_fabric_move()
            if not fabric_move:
                continue

            # Same priority logic as confirm
            lot = mo.lx_remnant_candidate_lot_id or getattr(
                fabric_move, "lx_candidate_lot_id", False
            )
            if not lot:
                continue

            try:
                mo._lx_force_lot_on_move(
                    fabric_move,
                    lot,
                    location_id=fabric_move.location_id,
                )

                _logger.info(
                    "[WASTE DEBUG] button_mark_done: enforced lot=%s on fabric_move=%s for MO %s.",
                    lot.name if lot else "n/a",
                    fabric_move.id,
                    mo.name,
                )
            except Exception as e:
                _logger.exception(
                    "[WASTE DEBUG] button_mark_done: error enforcing lot on move %s for MO %s: %s",
                    fabric_move.id,
                    mo.name,
                    e,
                )

        # FINAL waste/remnants generation
        self.action_generate_waste(preview=False)
        return res


    def button_plan(self):
        """
        Planifie l'OF : on recalcule les quantités + chaînes plastiques, mais
        sans toucher au moteur de chutes.
        """
        res = super().button_plan()
        self._recalc_to_consume_quantities()
        self._enforce_plastic_chain_singleton()
        return res

    # =======================================================================
    # Virtual calculator (preview)
    # =======================================================================
    # def _lx_virtual_calculate(self, width_m=0.0, height_m=None):
    #     """
    #     Preview calculation:
    #       - Use pure explosion from super() as baseline.
    #       - Treat width=1 for brackets; if headrail present → Adhesive qty=2.
    #       - No rounding.
    #     """
    #     self.ensure_one()
    #     if not self.bom_id:
    #         return 0.0, 0.0

    #     v_width = 1.0
    #     total_cost = 0.0
    #     total_amount = 0.0
    #     Product = self.env['product.product']

    #     raw_vals_list = super(MrpProduction, self)._get_moves_raw_values() or []

    #     headrail_present = any(
    #         self._is_headrail_r_002_21(Product.browse(v.get('product_id')))
    #         for v in raw_vals_list
    #     )

    #     want_150 = self._want_chain_150(
    #         height_m if height_m is not None else self.lx_height_m
    #     )

    #     for vals in raw_vals_list:
    #         product = Product.browse(vals.get('product_id'))
    #         if not product:
    #             continue

    #         if self._is_chain_150(product) and not want_150:
    #             continue
    #         if self._is_chain_200(product) and want_150:
    #             continue

    #         tmpl = product.product_tmpl_id
    #         qty = float(vals.get('product_uom_qty') or 0.0)

    #         if getattr(tmpl, 'is_mounting_bracket', False):
    #             try:
    #                 qty = max(math.floor(((v_width - 0.3) / 0.95) + 2), 0)
    #             except ZeroDivisionError:
    #                 qty = 2



    #         unit = float(product.standard_price or 0.0)
    #         cost = unit * qty
    #         total_cost += cost

    #         waste_pct = max(float(getattr(tmpl, 'waste_rate', 0.0) or 0.0) / 100.0, 0.0)
    #         extra_pct = max(float(getattr(tmpl, 'added_margin', 0.0) or 0.0) / 100.0, 0.0)
    #         factor = waste_pct + extra_pct
    #         amount = cost * factor
    #         total_amount += amount

    #     return total_cost, total_amount

    def _has_manual_chain_control(self):
        """
        Check if variant attribute 'Control Type' == 'Manual, Chain Controlled'
        """
        self.ensure_one()
        ptavs = self.product_id.product_template_attribute_value_ids
        for ptav in ptavs:
            attr_name = ((ptav.attribute_id and ptav.attribute_id.name) or '').strip().lower()
            val_name = ((ptav.product_attribute_value_id and ptav.product_attribute_value_id.name) or '').strip().lower()
            if (
                attr_name == 'control type'
                and val_name == 'manual, chain controlled'
            ):
                return True
        return False

    # def _lx_virtual_calculate_manual_chain_control(self, width_m=0.0, height_m=None):
    #     """
    #     Preview calculation (only if Control Type == 'Manual, Chain controlled'):
    #       - Use pure explosion from super() as baseline.
    #       - Treat width=1 for brackets; if headrail present → Adhesive qty=2.
    #       - No rounding.
    #     """
    #     self.ensure_one()
    #     if not self.bom_id or not self._has_manual_chain_control():
    #         return 0.0, 0.0

    #     v_width = 1.0
    #     total_cost = 0.0
    #     total_amount = 0.0
    #     Product = self.env['product.product']

    #     raw_vals_list = super(MrpProduction, self)._get_moves_raw_values() or []

    #     headrail_present = any(
    #         self._is_headrail_r_002_21(Product.browse(v.get('product_id')))
    #         for v in raw_vals_list
    #     )

    #     want_150 = self._want_chain_150(
    #         height_m if height_m is not None else self.lx_height_m
    #     )

    #     for vals in raw_vals_list:
    #         product = Product.browse(vals.get('product_id'))
    #         if not product:
    #             continue

    #         if self._is_chain_150(product) and not want_150:
    #             continue
    #         if self._is_chain_200(product) and want_150:
    #             continue

    #         tmpl = product.product_tmpl_id
    #         qty = float(vals.get('product_uom_qty') or 0.0)

    #         if getattr(tmpl, 'is_mounting_bracket', False):
    #             try:
    #                 qty = max(math.floor(((v_width - 0.3) / 0.95) + 2), 0)
    #             except ZeroDivisionError:
    #                 qty = 2



    #         unit = float(product.standard_price or 0.0)
    #         cost = unit * qty
    #         total_cost += cost

    #         waste_pct = max(float(getattr(tmpl, 'waste_rate', 0.0) or 0.0) / 100.0, 0.0)
    #         extra_pct = max(float(getattr(tmpl, 'added_margin', 0.0) or 0.0) / 100.0, 0.0)
    #         factor = waste_pct + extra_pct
    #         amount = cost * factor
    #         total_amount += amount

    #     return total_cost, total_amount


    def _lx_get_scaled_component_qty(self, tmpl, snap, width_m=0.0, height_m=0.0):
        qty = float(snap or 0.0)
        width = max(float(width_m or 0.0), 0.0)
        height = max(float(height_m or 0.0), 0.0)

        if not tmpl:
            return qty

        if getattr(tmpl, 'is_mounting_bracket', False):
            try:
                return max(math.floor(((width - 0.3) / 0.95) + 2), 0)
            except ZeroDivisionError:
                return 2.0

        if getattr(tmpl, 'lx_qty_by_width', False):
            qty *= width
        if getattr(tmpl, 'lx_qty_by_height', False):
            qty *= height
        return qty

    def _apply_dimension_scaling_from_snapshot(
        self,
        raw_vals_list,
        width_m=None,
        height_m=None,
    ):
        if not raw_vals_list:
            return raw_vals_list

        self.ensure_one()
        Product = self.env['product.product']
        width = float(width_m or 0.0)
        height = float(height_m or 0.0)

        for vals in raw_vals_list:
            prod = Product.browse(vals.get('product_id'))
            tmpl = prod.product_tmpl_id if prod else False
            snap = vals.get('lx_bom_uom_qty')
            if snap is None:
                snap = vals.get('product_uom_qty', 0.0)
            vals['product_uom_qty'] = self._lx_get_scaled_component_qty(
                tmpl,
                snap,
                width_m=width,
                height_m=height,
            )
        return raw_vals_list

    def _recalc_to_consume_quantities(self, width_param=None, height_param=None):
        for mo in self:
            width = float(mo.lx_width_m if width_param is None else width_param) or 0.0
            height = float(mo.lx_height_m if height_param is None else height_param) or 0.0

            for move in mo.move_raw_ids:
                tmpl = move.product_id.product_tmpl_id if move.product_id else False
                snap = float(move.lx_bom_uom_qty or move.product_uom_qty or 0.0)
                move.product_uom_qty = mo._lx_get_scaled_component_qty(
                    tmpl,
                    snap,
                    width_m=width,
                    height_m=height,
                )

    # def _lx_virtual_calculate(self, width_m=0.0, height_m=None):
    #     self.ensure_one()
    #     if not self.bom_id:
    #         return 0.0, 0.0

    #     v_width = float(width_m or 1.0)
    #     v_height = float(height_m if height_m is not None else (self.lx_height_m or 1.0))
    #     total_cost = 0.0
    #     total_amount = 0.0
    #     Product = self.env['product.product']

    #     raw_vals_list = super(MrpProduction, self)._get_moves_raw_values() or []


    #     want_150 = self._want_chain_150(
    #         height_m if height_m is not None else self.lx_height_m
    #     )

    #     for vals in raw_vals_list:
    #         product = Product.browse(vals.get('product_id'))
    #         if not product:
    #             continue

    #         if self._is_chain_150(product) and not want_150:
    #             continue
    #         if self._is_chain_200(product) and want_150:
    #             continue

    #         tmpl = product.product_tmpl_id
    #         snap = float(vals.get('product_uom_qty') or 0.0)
    #         qty = self._lx_get_scaled_component_qty(
    #             tmpl, snap, width_m=v_width, height_m=v_height
    #         )



    #         unit = float(product.standard_price or 0.0)
    #         cost = unit * qty
    #         total_cost += cost

    #         waste_pct = max(float(getattr(tmpl, 'waste_rate', 0.0) or 0.0) / 100.0, 0.0)
    #         extra_pct = max(float(getattr(tmpl, 'added_margin', 0.0) or 0.0) / 100.0, 0.0)
    #         total_amount += cost * (1.0 + waste_pct + extra_pct)

    #     return total_cost, total_amount

    # def _lx_virtual_calculate_manual_chain_control(self, width_m=0.0, height_m=None):
    #     self.ensure_one()
    #     if not self.bom_id or not self._has_manual_chain_control():
    #         return 0.0, 0.0

    #     v_width = float(width_m or 1.0)
    #     v_height = float(height_m if height_m is not None else (self.lx_height_m or 1.0))
    #     total_cost = 0.0
    #     total_amount = 0.0
    #     Product = self.env['product.product']

    #     raw_vals_list = super(MrpProduction, self)._get_moves_raw_values() or []


    #     want_150 = self._want_chain_150(
    #         height_m if height_m is not None else self.lx_height_m
    #     )

    #     for vals in raw_vals_list:
    #         product = Product.browse(vals.get('product_id'))
    #         if not product:
    #             continue

    #         if self._is_chain_150(product) and not want_150:
    #             continue
    #         if self._is_chain_200(product) and want_150:
    #             continue

    #         tmpl = product.product_tmpl_id
    #         snap = float(vals.get('product_uom_qty') or 0.0)
    #         qty = self._lx_get_scaled_component_qty(
    #             tmpl, snap, width_m=v_width, height_m=v_height
    #         )


    #         unit = float(product.standard_price or 0.0)
    #         cost = unit * qty
    #         total_cost += cost

    #         waste_pct = max(float(getattr(tmpl, 'waste_rate', 0.0) or 0.0) / 100.0, 0.0)
    #         extra_pct = max(float(getattr(tmpl, 'added_margin', 0.0) or 0.0) / 100.0, 0.0)
    #         total_amount += cost * (1.0 + waste_pct + extra_pct)

    #     return total_cost, total_amount

    # ================================================================
    # FINAL VIRTUAL CALCULATOR (ORIENTATION SAFE)
    # ================================================================

    def _lx_virtual_calculate(self, width_m=0.0, height_m=None, idler_variant_id=None,
                               skip_tubular_motor=False):
        self.ensure_one()
        if not self.bom_id:
            return 0.0, 0.0

        v_width = 1.0
        total_cost = 0.0
        total_amount = 0.0
        Product = self.env['product.product']

        raw_vals_list = super(MrpProduction, self)._get_moves_raw_values() or []

        want_150 = self._want_chain_150(
            height_m if height_m is not None else self.lx_height_m
        )

        for vals in raw_vals_list:
            product = Product.browse(vals.get('product_id'))
            if not product:
                continue

            if self._is_chain_150(product) and not want_150:
                continue
            if self._is_chain_200(product) and want_150:
                continue

            tmpl = product.product_tmpl_id

            # Motor Only: skip tubular motor BOM components (they're SOL accessories)
            if skip_tubular_motor and getattr(tmpl, 'lx_is_tubular_motor', False):
                continue

            # Idler filtering: when idler_variant_id is given, include only the
            # matching idler variant and skip all others.
            # When idler_variant_id is None but skip_tubular_motor is set (Motor Only
            # context without motor selected yet), skip all idlers too.
            if getattr(tmpl, 'lx_is_idler', False):
                if not idler_variant_id or product.id != idler_variant_id:
                    if skip_tubular_motor:
                        continue

            qty = float(vals.get('product_uom_qty') or 0.0)

            if getattr(tmpl, 'is_mounting_bracket', False):
                try:
                    qty = max(math.floor(((v_width - 0.3) / 0.95) + 2), 0)
                except ZeroDivisionError:
                    qty = 2

            unit = float(product.standard_price or 0.0)
            cost = unit * qty
            total_cost += lx_truncate_2(cost)

            waste_pct = max(float(getattr(tmpl, 'waste_rate', 0.0) or 0.0) / 100.0, 0.0)
            extra_pct = max(float(getattr(tmpl, 'added_margin', 0.0) or 0.0) / 100.0, 0.0)
            raw_amount = cost * (1.0 + waste_pct + extra_pct)
            total_amount += lx_truncate_2(raw_amount)

        return lx_truncate_2(total_cost), lx_truncate_2(total_amount)


    def _lx_virtual_calculate_manual_chain_control(self, width_m=0.0, height_m=None):
        self.ensure_one()
        if not self.bom_id or not self._has_manual_chain_control():
            return 0.0, 0.0

        return self._lx_virtual_calculate(width_m=width_m, height_m=height_m)


# =======================================================================
# STOCK MOVE EXTENSION
# =======================================================================
class StockMove(models.Model):
    _inherit = 'stock.move'

    # mirror MO dims for line-level computations
    lx_mo_width_m = fields.Float(
        related='raw_material_production_id.lx_width_m',
        store=True,
        readonly=True
    )
    lx_mo_height_m = fields.Float(
        related='raw_material_production_id.lx_height_m',
        store=True,
        readonly=True
    )

    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        readonly=True
    )
    lx_unit_price = fields.Float(
        string='Unit Price',
        compute='_compute_lx_unit_price',
        store=True
    )
    lx_cost_price = fields.Monetary(
        string='Cost Price',
        compute='_compute_lx_cost_price',
        store=True,
        currency_field='currency_id'
    )
    lx_waste_rate = fields.Float(
        string='Waste Rate',
        compute='_compute_lx_rates',
        store=True
    )
    lx_added_margin = fields.Float(
        string='Added Margin',
        compute='_compute_lx_rates',
        store=True
    )
    lx_amount = fields.Monetary(
        string='Amount',
        compute='_compute_lx_amount',
        store=True,
        currency_field='currency_id'
    )

    # BoM snapshot qty at creation time
    lx_bom_uom_qty = fields.Float(
        string="Quantity",
        digits='Product Unit of Measure',
        help=(
            "Quantity from BoM explosion captured at creation time. "
            "Unaffected by later edits."
        ),
    )

    # Selected candidate lot (the one you picked)
    lx_candidate_lot_id = fields.Many2one(
        "stock.lot",
        string="Lot Number",
        readonly=True,
        copy=False,
    )

    # All candidate lots (tags)
    lx_candidate_lot_ids = fields.Many2many(
        "stock.lot",
        "lx_move_candidate_lot_rel",   # rel table
        "move_id",
        "lot_id",
        string="Candidate Lots",
        readonly=True,
        copy=False,
    )

    @api.model_create_multi
    def create(self, vals_list):
        # Persist snapshot at creation
        for vals in vals_list:
            if 'lx_bom_uom_qty' not in vals:
                vals['lx_bom_uom_qty'] = vals.get('product_uom_qty', 0.0)
        return super().create(vals_list)

    @api.depends('product_id')
    def _compute_lx_unit_price(self):
        for line in self:
            line.lx_unit_price = line.product_id.standard_price or 0.0



    @api.depends('lx_unit_price', 'product_uom_qty')
    def _compute_lx_cost_price(self):
        for line in self:
            unit = float(line.lx_unit_price or 0.0)
            qty = float(line.product_uom_qty or 0.0)

            raw = unit * qty

            line.lx_cost_price = lx_truncate_2(raw)

    # @api.depends('lx_cost_price', 'lx_waste_rate', 'lx_added_margin')
    # def _compute_lx_amount(self):
    #     for line in self:
    #         amount = float(line.lx_cost_price or 0.0)
    #         waste_pct = max(float(line.lx_waste_rate or 0.0) / 100.0, 0.0)
    #         extra_pct = max(float(line.lx_added_margin or 0.0) / 100.0, 0.0)
    #         line.lx_amount = amount * (1.0 + waste_pct + extra_pct)

    @api.depends('lx_cost_price', 'lx_waste_rate', 'lx_added_margin')
    def _compute_lx_amount(self):
        for line in self:
            base = float(line.lx_cost_price or 0.0)

            waste_pct = max(float(line.lx_waste_rate or 0.0) / 100.0, 0.0)
            margin_pct = max(float(line.lx_added_margin or 0.0) / 100.0, 0.0)

            raw = base * (1.0 + waste_pct + margin_pct)

            line.lx_amount = lx_truncate_2(raw)

    @api.depends('product_id')
    def _compute_lx_rates(self):
        for line in self:
            tmpl = line.product_id.product_tmpl_id
            line.lx_waste_rate = tmpl.waste_rate if tmpl else 0.0
            line.lx_added_margin = tmpl.added_margin if tmpl else 0.0

    # @api.depends(
    #     'lx_cost_price',
    #     'lx_mo_width_m', 'lx_mo_height_m',
    #     'product_id.product_tmpl_id.lx_qty_by_width',
    #     'product_id.product_tmpl_id.lx_qty_by_height',
    #     'product_id.product_tmpl_id.roller_width_ids',
    # )
    # def _compute_lx_amount(self):
    #     """
    #     Calcule le montant (Amount) en fonction du coût de base et
    #     des dimensions de l'OF. La logique d'origine est préservée.
    #     """
    #     for line in self:
    #         amount = float(line.lx_cost_price or 0.0)

    #         tmpl = line.product_id.product_tmpl_id
    #         w = float(line.lx_mo_width_m or 1.0)
    #         h = float(line.lx_mo_height_m or 1.0)

    #         if tmpl:
    #             if getattr(tmpl, 'is_mounting_bracket', False):
    #                 # Ajustement virtuel pour les supports
    #                 try:
    #                     q_virtual = math.floor(((1.0 - 0.3) / 0.95) + 2)
    #                 except ZeroDivisionError:
    #                     q_virtual = 2
    #                 q_virtual = max(q_virtual, 0)

    #                 try:
    #                     q_real = math.floor(((w - 0.3) / 0.95) + 2)
    #                 except ZeroDivisionError:
    #                     q_real = 2
    #                 q_real = max(q_real, 0)

    #                 ratio = (q_real / q_virtual) if q_virtual else 1.0
    #                 amount *= ratio
    #             else:
    #                 is_fabric = bool(getattr(tmpl, 'roller_width_ids', False))
    #                 if getattr(tmpl, 'lx_qty_by_width', False) or getattr(
    #                     tmpl, 'lx_qty_by_height', False
    #                 ):
    #                     amount *= (w * h) if is_fabric else w

    #         line.lx_amount = amount

    # @api.depends('lx_unit_price', 'lx_bom_uom_qty', 'lx_waste_rate', 'lx_added_margin')
    # def _compute_lx_cost_price(self):
    #     for line in self:
    #         unit = float(line.lx_unit_price or 0.0)
    #         base_qty = float(line.lx_bom_uom_qty or 0.0)
    #         base_cost = unit * base_qty

    #         waste_pct = max(float(line.lx_waste_rate or 0.0) / 100.0, 0.0)
    #         extra_pct = max(float(line.lx_added_margin or 0.0) / 100.0, 0.0)
    #         factor = waste_pct + extra_pct

    #         line.lx_cost_price = base_cost * factor

    # ------------------------------------------------------------------
    # Local utilities (attribute map / motorized / variant pick)
    # ------------------------------------------------------------------
    def _lx_attr_map(self, product):
        """Return {attr_name_lower: value_name_lower} from a product.product."""
        res = {}
        if not product:
            return res
        for pav in product.product_template_attribute_value_ids:
            attr = (pav.attribute_id.name or '').strip().lower()
            val = (pav.product_attribute_value_id.name or '').strip().lower()
            res[attr] = val
        return res

    def _lx_is_motorized(self, product):
        """Heuristic to detect motorized items."""
        if not product:
            return False

        amap = self._lx_attr_map(product)
        ct = amap.get('control type') or amap.get('control', '')
        if 'motor' in (ct or ''):
            return True

        cat_name = (product.categ_id.name or '').lower() if product.categ_id else ''
        if 'motor' in cat_name:
            return True

        code = (product.default_code or '').lower()
        if code.startswith('motor') or code.startswith('mtz'):
            return True

        return False

    def _lx_match_or_cheapest_variant(self, tmpl, parent_product):
        """Pick a variant for the component template."""
        Product = self.env['product.product']
        variants = tmpl.product_variant_ids
        if not variants:
            return Product

        parent_attrs = self._lx_attr_map(parent_product)
        want_headrail = parent_attrs.get('headrail')

        def has_headrail(p):
            amap = self._lx_attr_map(p)
            val = amap.get('headrail')
            if not want_headrail:
                return True
            return (val == want_headrail) or (want_headrail in (val or ''))

        candidates = variants.filtered(
            lambda p: has_headrail(p) and not self._lx_is_motorized(p)
        )
        if not candidates:
            candidates = variants.filtered(lambda p: not self._lx_is_motorized(p))
        if not candidates:
            candidates = variants

        cheapest = min(candidates, key=lambda p: p.lst_price or 0.0)
        return cheapest



