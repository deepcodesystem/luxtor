#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de test pour vérifier que tous les imports Python sont corrects
avant l'installation du module lx_base.
"""

import sys
import os

# Ajouter le répertoire Odoo au path
sys.path.insert(0, '/opt/GetapERP/DeepOS-V19')
sys.path.insert(0, '/opt/GetapERP/DeepOS-V19/extra-addons/luxtor/lx_base')

print("=" * 70)
print("Test des imports Python - Module lx_base")
print("=" * 70)

try:
    print("\n1. Test du modèle product_attribute_component...")
    with open('models/product_attribute_component.py', 'r') as f:
        code = compile(f.read(), 'product_attribute_component.py', 'exec')
    print("   ✓ Syntaxe valide")

    print("\n2. Test du modèle product_template_attribute_value...")
    with open('models/product_template_attribute_value.py', 'r') as f:
        code = compile(f.read(), 'product_template_attribute_value.py', 'exec')
    print("   ✓ Syntaxe valide")

    print("\n3. Test du modèle product_product...")
    with open('models/product_product.py', 'r') as f:
        code = compile(f.read(), 'product_product.py', 'exec')
    print("   ✓ Syntaxe valide")

    print("\n4. Test de product_template (modifié)...")
    with open('models/product_template.py', 'r') as f:
        code = compile(f.read(), 'product_template.py', 'exec')
    print("   ✓ Syntaxe valide")

    print("\n5. Test du fichier __init__.py...")
    with open('models/__init__.py', 'r') as f:
        content = f.read()
        assert 'product_attribute_component' in content, "Import manquant: product_attribute_component"
        assert 'product_template_attribute_value' in content, "Import manquant: product_template_attribute_value"
        assert 'product_product' in content, "Import manquant: product_product"
    print("   ✓ Tous les imports présents")

    print("\n6. Test du __manifest__.py...")
    with open('__manifest__.py', 'r') as f:
        content = f.read()
        assert 'sale' in content, "Dépendance 'sale' manquante"
        assert 'product_attribute_component_views.xml' in content, "Vue manquante dans data"
    print("   ✓ Manifest correct")

    print("\n7. Test du fichier security/ir.model.access.csv...")
    with open('security/ir.model.access.csv', 'r') as f:
        content = f.read()
        assert 'product_attribute_component' in content, "Droits d'accès manquants"
        lines = [l for l in content.split('\n') if 'product_attribute_component' in l]
        assert len(lines) >= 3, f"Nombre de lignes de droits insuffisant: {len(lines)}"
    print("   ✓ Droits d'accès définis")

    print("\n" + "=" * 70)
    print("✅ TOUS LES TESTS SONT PASSÉS !")
    print("=" * 70)
    print("\nLe module est prêt à être installé.")
    print("\nCommande d'installation :")
    print("  ./odoo-bin -c /etc/odoo.conf -u lx_base -d votre_database --stop-after-init")

    sys.exit(0)

except AssertionError as e:
    print(f"\n❌ ERREUR : {e}")
    sys.exit(1)

except Exception as e:
    print(f"\n❌ ERREUR : {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
