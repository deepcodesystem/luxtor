from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestRemnantPicking(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env.ref("remnant_fetching.product_sp_test")
        cls.rule = cls.env.ref("remnant_fetching.rule_sunscreen")
        cls.location = cls.env.ref("remnant_fetching.location_wh_remnants")

    def _make_request(self, width, height):
        return self.env["remnant.fetch.request"].create(
            {
                "product_id": self.product.id,
                "category_rule_id": self.rule.id,
                "required_width_m": width,
                "required_height_m": height,
                "tolerance": 1.5,
                "required_layer_count": 1,
                "orientation": "widthwise",
                "company_id": self.env.company.id,
            }
        )

    def test_small_sunscreen_order_picks_smallest_valid_remnant(self):
        request = self._make_request(0.68, 1.25)
        self.assertEqual(request.best_remnant_id.name, "R-SU-12-020")
        self.assertEqual(request.selected_orientation, "widthwise")

    def test_low_width_remnant_is_not_selected(self):
        request = self._make_request(1.00, 1.40)
        self.assertNotEqual(request.best_remnant_id.name, "R-SU-12-012")
        self.assertEqual(request.best_remnant_id.name, "R-SU-12-007")

    def test_height_uses_excel_min_max_range(self):
        request = self._make_request(0.60, 1.20)
        remnant = self.env.ref("remnant_fetching.remnant_su_003")
        fit = request._get_best_fit_for_remnant(remnant)
        self.assertFalse(fit)

    def test_r_su_005_is_rejected_for_small_order(self):
        request = self._make_request(0.50, 1.30)
        remnant = self.env.ref("remnant_fetching.remnant_su_005")
        fit = request._get_best_fit_for_remnant(remnant)
        self.assertFalse(fit)

    def test_heightwise_r_su_013_is_rejected_by_height_max(self):
        request = self._make_request(0.80, 1.50)
        remnant = self.env.ref("remnant_fetching.remnant_su_013")
        fit = request._get_best_fit_for_remnant(remnant)
        self.assertFalse(fit)

    def test_heightwise_r_su_004_is_rejected_by_height_max(self):
        request = self._make_request(0.55, 1.40)
        remnant = self.env.ref("remnant_fetching.remnant_su_004")
        fit = request._get_best_fit_for_remnant(remnant)
        self.assertFalse(fit)

    def test_heightwise_r_su_001_is_rejected_by_height_max(self):
        request = self._make_request(0.60, 1.50)
        remnant = self.env.ref("remnant_fetching.remnant_su_001")
        fit = request._get_best_fit_for_remnant(remnant)
        self.assertFalse(fit)

    def test_batch_auto_names_do_not_collide(self):
        remnants = self.env["remnant.stock"].create(
            [
                {
                    "product_id": self.product.id,
                    "category_rule_id": self.rule.id,
                    "usable_layer_count": 1,
                    "width_m": 0.40,
                    "height_m": 0.70,
                    "location_id": self.location.id,
                    "company_id": self.env.company.id,
                },
                {
                    "product_id": self.product.id,
                    "category_rule_id": self.rule.id,
                    "usable_layer_count": 1,
                    "width_m": 0.42,
                    "height_m": 0.72,
                    "location_id": self.location.id,
                    "company_id": self.env.company.id,
                },
            ]
        )
        self.assertEqual(len(set(remnants.mapped("name"))), 2)
        self.assertEqual(remnants[0].remnant_code, "023")
        self.assertEqual(remnants[1].remnant_code, "024")
        self.assertEqual(remnants[0].name, "R-SU-12-023")
        self.assertEqual(remnants[1].name, "R-SU-12-024")
