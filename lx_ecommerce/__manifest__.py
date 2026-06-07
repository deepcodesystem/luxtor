# -*- coding: utf-8 -*-
{
    'name': "LX eCommerce - Services Associés",
    'summary': "Ajoute la fonctionnalité Services Associés pour les ventes incitatives & croisées",
    'description': """
        LX eCommerce - Services Associés
        =================================

        Ce module ajoute une nouvelle fonctionnalité "Services Associés" dans
        la section "Ventes incitatives & croisées" des produits.

        Fonctionnalités:
        ----------------
        * Nouveau champ "Services Associés" sur le formulaire produit
        * Permet de sélectionner un ou plusieurs services à proposer au client
        * Positionné après "Produits Accessoires" dans l'onglet Ventes
        * Fonctionne comme les produits accessoires pour l'eCommerce
    """,
    'author': "Luxtor",
    'category': 'Sales/eCommerce',
    'version': '19.0.1.0.0',
    'depends': [
        'lx_base',
        'sale',
        'website_sale',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/product_template_views.xml',
        'views/templates/cart_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'lx_ecommerce/static/src/js/lx_variant_mixin.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
