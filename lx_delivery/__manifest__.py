# -*- coding: utf-8 -*-
{
    'name': "LX Delivery",
    'summary': "Livraison custom Luxtor : Standard (ville) + Express (poids) + free shipping",
    'description': (
        "Gestion de la livraison Luxtor : mode Standard (tarif par ville/ZIP via shipping.rate), "
        "mode Express (tarification par tranches de poids), logique free-shipping configurable, "
        "wizard backend et preview frontend via /lx/shipping/preview_prices."
    ),
    'author': "Luxtor",
    'category': 'Inventory/Delivery',
    'version': '19.0.1.0.0',
    'depends': ['lx_base', 'lx_sales', 'sale_management', 'delivery', 'website_sale'],
    'data': [
        'security/ir.model.access.csv',
        'data/delivery_products.xml',
        'data/delivery_brackets_data.xml',
        'views/delivery_carrier_lx_views.xml',
        'views/shipping_rate_views.xml',
        'views/sale_order_views.xml',
        'views/lx_website_delivery.xml',
        'views/lx_delivery_payment.xml',
        'wizards/lx_wizard_shipping.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'lx_delivery/static/src/css/lx_delivery.css',
            'lx_delivery/static/src/js/lx_delivery_preview.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}

