# -*- coding: utf-8 -*-
{
    'name': "LX Base",
    'summary': "Socle commun Luxtor : champs produit, utilitaires, modèles auxiliaires",
    'description': (
        "Fournit tous les éléments partagés entre les modules Luxtor : "
        "flags et propriétés sur product.template, modèle roller.width, "
        "modèles auxiliaires produit, fonctions utilitaires pures et "
        "paramètre lx_browser_factor_pct."
    ),
    'author': "Luxtor",
    'category': 'Hidden',
    'version': '19.0.1.0.0',
    'depends': ['base', 'product', 'sale'],
    'data': [
        'security/ir.model.access.csv',
        'data/product_attributes.xml',
        'views/product_auxiliary_views.xml',
        'views/roller_width_views.xml',
        'views/product_attribute_component_views.xml',
        'views/product_template_base_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}

