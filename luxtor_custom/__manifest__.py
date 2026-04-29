# -*- coding: utf-8 -*-
{
    'name': "Curtain & Blinds",

    'summary': "Luxtor Custom Enhancements",

    'description': "Custom features for Luxtor Odoo 18 instance",

    'author': "Abdessamad O.",

    # Categories can be used to filter modules in modules listing
    # for the full list
    'category': 'sales',
    'version': '0.2',
    'post_init_hook': 'post_init_hook',

    # always loaded
    'depends': [
        'sale_management',
        'base',
        'website_sale',
        'sale_loyalty',
        'website_sale_loyalty',
        'project_mrp_sale',
        'helpdesk',
        'website_helpdesk',
        ],
    'data': [
        'security/ir.model.access.csv',
        # 'wizards/wizard_validate_code.xml',

        'data/service_products.xml',
        'data/ir_sequence.xml',
        'data/mail_template.xml',
        'data/welcome_loyalty_program.xml',
        'data/electric_data.xml',
        'data/delivery_brackets_data.xml',
        'data/lx_dynamic_snippet_filters.xml',
        'data/lx_checkout_steps.xml',
        'data/website_menu.xml',
        'views/luxtor_res_partner.xml',
        'views/luxtor_sale_order.xml',
        'views/luxtor_product.xml',
        'views/luxtor_mrp_bom.xml',
        'views/luxtor_mo.xml',
        'views/luxtor_shipping_rate.xml',
        'views/header_cart_link.xml',

        'views/website_sale_templates.xml',
        'views/website_checkout.xml',
        'views/suivi_de_commande_templates.xml',
        'views/luxtor_helpdesk.xml',
        'views/luxtor_website_helpdesk_team_inherit.xml',
        'views/checkout_services.xml',
        'views/cart_products_fragment.xml',
        'views/cart_lines_inherit.xml',         # child filter + child block + dims + data-attrs
        'views/luxtor_website_sale_total.xml',
        'views/lx_homepage.xml',
        'views/portal_coupon.xml',
        'views/lx_website_delivery.xml',
        'views/luxtor_delivery_payment.xml',
        'views/inspiration_page.xml',
        'views/res_config_settings_views.xml',
        'wizards/luxtor_wizard_shipping.xml',
        # 'wizards/wizard_dimension_configurator_views.xml',
        'views/purchase_order_view.xml',
        'views/lx_delivery_carrier_form.xml',
        #     #'views/delivery_carrier_views.xml',
        'views/luxtor_waste_views.xml',
        'views/lx_affiliate_click_views.xml',
        'views/production_monitor_views.xml',
        # 'views/luxtor_delivery_website.xml',
        # 'views/website_sale_product.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'luxtor_custom/static/src/js/sale_lx_product_configurator_patch.js',
            'luxtor_custom/static/src/js/sale_lx_configurator_payload_patch.js',
            'luxtor_custom/static/src/xml/sale_lx_product_configurator.xml',
            'luxtor_custom/static/src/css/lx_electric_lines.css',
        ],
          
        'web.assets_frontend': [
            # ---------- CSS ----------
            'luxtor_custom/static/src/css/lx_product_variants.css',
            'luxtor_custom/static/src/css/lx_gallery.css',
            'luxtor_custom/static/src/css/lx_cart.css',
            'luxtor_custom/static/src/css/lx_navbar.css',
            'luxtor_custom/static/src/css/lx_checkout_ui.css',
            'luxtor_custom/static/src/css/lx_debug.css',
            'luxtor_custom/static/src/css/lx_delivery.css',
            'luxtor_custom/static/src/css/lx_payment.css',
            'luxtor_custom/static/src/css/lx_order_limit.css',

            # ---------- JS — dimensions / price ----------
            'luxtor_custom/static/src/js/lx_dimensions_hints.js',
            'luxtor_custom/static/src/js/lx_price_live.js',
            'luxtor_custom/static/src/js/lx_dim_validation.js',
            'luxtor_custom/static/src/js/lx_update_card.js',

            # ---------- JS — cart/checkout patches ----------
            'luxtor_custom/static/src/js/install.js',
            'luxtor_custom/static/src/js/lx_website_product_configurator_patch.js',
            'luxtor_custom/static/src/js/checkout.js',

            # ---------- JS — frontend widgets ----------
            'luxtor_custom/static/src/js/custom_title.js',
            'luxtor_custom/static/src/js/lx_product_page.js',
            'luxtor_custom/static/src/js/lx_cart_tooltips.js',
            'luxtor_custom/static/src/js/lx_service_qty_resync.js',
            'luxtor_custom/static/src/js/lx_install_toggle.js',
            'luxtor_custom/static/src/js/lx_priority_toggle.js',
            'luxtor_custom/static/src/js/lx_freeze_check.js',
            'luxtor_custom/static/src/js/lx_delivery_preview.js',
            'luxtor_custom/static/src/js/lx_payment_terms.js',
            'luxtor_custom/static/src/js/lx_order_limit_cart.js',
            'luxtor_custom/static/src/js/lx_helpdesk_prefill.js',
            'luxtor_custom/static/src/js/lx_inspiration.js',
            'luxtor_custom/static/src/js/lx_motor_only_picker.js',
            'luxtor_custom/static/src/js/lx_variant_ui.js',
        ],
},

}

