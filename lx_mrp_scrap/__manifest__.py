# -*- coding: utf-8 -*-
{
    'name': "LX MRP Scrap",
    'summary': "Gestion des chutes de tissu réutilisables en production",
    'description': (
        "Enregistre les chutes de tissu générées lors de la production de stores. "
        "Chaque chute est liée à un rouleau (lot) source et peut être réutilisée "
        "ou rebutée."
    ),
    'author': "Luxtor",
    'category': 'Manufacturing',
    'version': '19.0.1.0.0',
    'depends': ['mrp', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/removal_strategy.xml',
        'views/stock_lot_views.xml',
        'views/mrp_production_views.xml',
        'views/lx_scrap_views.xml',
        'views/stock_move_line_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
