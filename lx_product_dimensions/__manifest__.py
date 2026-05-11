# -*- coding: utf-8 -*-
{
    'name': "LX Product Dimensions",
    'summary': "Dimension-based pricing for Roller Blinds (width × height)",
    'description': (
        "Provides all dimension / roller-blind specific logic: "
        "roller.width tags, product auxiliary models, dimension fields on "
        "product.template and sale.order.line, the dimension configurator "
        "wizard and the /lx/dimensions/hints + /lx/configurator/info routes."
    ),
    'author': "Luxtor",
    'category': 'Sales',
    'version': '19.0.1.0.0',
    'depends': [
        'base',
        'product',
        'sale_management',
        'mrp',
        'website_sale',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/roller_width_views.xml',
        'views/product_auxiliary_views.xml',
        'views/product_template_dims_views.xml',
        'views/sale_order_line_dims_views.xml',
        'views/website_sale_dims_templates.xml',
        'wizards/wizard_dimension_configurator_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'lx_product_dimensions/static/src/js/lx_dim_validation.js',
            'lx_product_dimensions/static/src/js/lx_price_live.js',
            'lx_product_dimensions/static/src/css/lx_dim_inputs.css',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}

