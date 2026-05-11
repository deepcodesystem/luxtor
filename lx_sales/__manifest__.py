# -*- coding: utf-8 -*-
{
    'name': "LX Sales",
    'summary': "Dimensions sur les lignes de commande + prix simple (list_price × surface)",
    'description': (
        "Ajoute les champs lx_width_m / lx_height_m / size sur sale.order.line. "
        "Le prix est calculé via list_price × browser_factor × surface (W×H). "
        "Inclut le wizard de configuration des dimensions backend."
    ),
    'author': "Luxtor",
    'category': 'Sales',
    'version': '19.0.1.0.0',
    'depends': ['lx_base', 'sale_management'],
    'data': [
        'views/sale_order_line_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}

