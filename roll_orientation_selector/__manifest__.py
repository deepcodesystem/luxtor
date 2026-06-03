{
    "name": "Roll & Orientation Selector",
    "summary": "Select the best roll width and cutting orientation when no remnant is available.",
    "version": "19.0.1.0.0",
    "category": "Manufacturing/Manufacturing",
    "author": "Custom",
    "license": "LGPL-3",
    "depends": ["mrp", "stock", "remnant_fetching"],
    "data": [
        "security/ir.model.access.csv",
        "data/roll_stock_test_data.xml",
        "views/stock_lot_views.xml",
        "views/fabric_pick_option_views.xml",
        "views/mrp_production_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "application": False,
}
