# Installation - Module lx_base avec gestion des prix d'attributs

## 📋 Fichiers créés

### Modèles Python
- ✅ `models/product_attribute_component.py` - Liaison attribut ↔ composant
- ✅ `models/product_template_attribute_value.py` - Extension valeurs d'attributs
- ✅ `models/product_product.py` - Hook pour synchronisation automatique

### Vues XML
- ✅ `views/product_attribute_component_views.xml` - Interface graphique

### Documentation
- ✅ `README_ATTRIBUTE_PRICING.md` - Guide complet d'utilisation

## 📝 Fichiers modifiés

- ✅ `models/product_template.py` - Ajout méthode `lx_sync_attribute_prices_from_components()`
- ✅ `models/__init__.py` - Imports des nouveaux modèles
- ✅ `views/product_template_base_views.xml` - Ajout bouton "Sync Attribute Prices"
- ✅ `security/ir.model.access.csv` - Droits d'accès
- ✅ `__manifest__.py` - Dépendances et vues

## 🚀 Installation

### Étape 1 : Vérification
```bash
cd /opt/GetapERP/DeepOS-V19

# Vérifier la syntaxe Python
python3 -m py_compile extra-addons/luxtor/lx_base/models/product_attribute_component.py
python3 -m py_compile extra-addons/luxtor/lx_base/models/product_template_attribute_value.py
python3 -m py_compile extra-addons/luxtor/lx_base/models/product_product.py

# Vérifier la syntaxe XML
xmllint --noout extra-addons/luxtor/lx_base/views/product_attribute_component_views.xml
xmllint --noout extra-addons/luxtor/lx_base/views/product_template_base_views.xml

echo "✓ Vérifications OK"
```

### Étape 2 : Mise à jour du module
```bash
# Option 1 : Avec votre commande habituelle
./odoo-bin -c /etc/odoo.conf -u lx_base -d votre_database --stop-after-init

# Option 2 : Via l'interface (recommandé pour debugger)
# 1. Activer le mode développeur
# 2. Apps → lx_base → Mettre à jour
```

### Étape 3 : Vérification post-installation

#### Dans l'interface Odoo :

1. **Vérifier le nouveau modèle**
   - Menu Technique → Modèles → Rechercher "product.attribute.component"
   - Devrait exister avec les champs : ptav_id, component_variant_id, quantity, subtotal

2. **Vérifier les vues**
   - Créer/éditer un produit avec attributs
   - Ventes → Produits → Produits
   - Choisir un produit avec variantes
   - Vérifier présence du bouton "Sync Attribute Prices"

3. **Tester la fonctionnalité**
   - Aller dans les valeurs d'attributs (Variantes → Configurer)
   - Ouvrir une valeur d'attribut
   - Vérifier présence des champs :
     - Price Mode (radio buttons)
     - Auto Computed Price
     - Onglet "Components"

## 🔍 En cas d'erreur

### Erreur : "Field 'sequence' does not exist"
✅ **Résolu** - Les widgets "handle" ont été retirés des vues embedded

### Erreur : "Model 'product.attribute.component' not found"
→ Vérifier que `models/__init__.py` importe bien le nouveau fichier :
```python
from . import product_attribute_component
```

### Erreur : "View not found"
→ Vérifier que `__manifest__.py` contient :
```python
'data': [
    'security/ir.model.access.csv',
    'views/product_auxiliary_views.xml',
    'views/roller_width_views.xml',
    'views/product_attribute_component_views.xml',  # ← IMPORTANT
    'views/product_template_base_views.xml',
],
```

### Erreur : "Access denied"
→ Vérifier `security/ir.model.access.csv` :
```csv
access_product_attribute_component_user,product.attribute.component user,model_product_attribute_component,base.group_user,1,0,0,0
access_product_attribute_component_salesman,product.attribute.component salesman,model_product_attribute_component,sales_team.group_sale_salesman,1,1,1,0
access_product_attribute_component_manager,product.attribute.component manager,model_product_attribute_component,sales_team.group_sale_manager,1,1,1,1
```

### Logs détaillés
```bash
# Relancer avec plus de détails
./odoo-bin -c /etc/odoo.conf -u lx_base -d votre_database --log-level=debug --stop-after-init
```

## ✅ Checklist post-installation

- [ ] Module lx_base mis à jour sans erreur
- [ ] Modèle `product.attribute.component` créé
- [ ] Bouton "Sync Attribute Prices" visible sur fiche produit
- [ ] Onglet "Components" visible dans formulaire valeur d'attribut
- [ ] Champs `lx_price_mode` et `lx_computed_price` présents
- [ ] Droits d'accès fonctionnels

## 📚 Documentation

Voir `README_ATTRIBUTE_PRICING.md` pour :
- Guide complet d'utilisation
- Exemples de configuration
- Formules de calcul
- Cas d'usage détaillés

## 🎯 Prochaines étapes

1. **Configurer un produit test**
   - Créer un produit avec 2-3 variantes
   - Marquer des composants avec `lx_is_component = True`
   - Associer les composants aux valeurs d'attributs

2. **Tester la synchronisation automatique**
   - Changer le `standard_price` d'un composant
   - Vérifier que le `price_extra` de l'attribut se met à jour

3. **Tester la synchronisation manuelle**
   - Cliquer sur "Sync Attribute Prices"
   - Vérifier la notification avec le nombre d'attributs mis à jour

## 🐛 Support

En cas de problème :
1. Consulter les logs Odoo
2. Vérifier les fichiers listés ci-dessus
3. Vérifier que `luxtor_custom` n'est PAS installé (conflit potentiel)
4. Relire `README_ATTRIBUTE_PRICING.md`

---

**Version** : 19.0.1.0.0
**Date** : 2026-05-19
**Module** : lx_base
**Auteur** : Luxtor
