# -*- coding: utf-8 -*-
{
    'name': "LX MRP",
    'summary': "Explosion BoM dimensionnelle pour les stores enrouleurs",
    'description': (
        "Ajoute les champs dimensions (lx_width_m / lx_height_m) sur mrp.production, "
        "le scaling automatique des quantités à consommer (tissu, brackets, chaînes), "
        "le moteur d'orientation (widthwise / heightwise) et les champs de coût sur "
        "mrp.bom et mrp.bom.line."
    ),
    'author': "Luxtor",
    'category': 'Manufacturing',
    'version': '19.0.1.0.0',
    'depends': ['lx_base', 'sale_management', 'mrp', 'stock', 'mrp_bom_line_formula_quantity'],
    'data': [
        'security/ir.model.access.csv',
        'views/mrp_bom_views.xml',
        'views/mrp_production_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}

