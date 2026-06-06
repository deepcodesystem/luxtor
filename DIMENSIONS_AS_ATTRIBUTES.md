# Migration des Dimensions vers Attributs Odoo

## Vue d'ensemble

Cette migration transforme les dimensions (largeur/hauteur) des produits sur mesure Luxtor d'une implémentation basée sur des champs personnalisés vers une solution utilisant les **attributs natifs d'Odoo** avec valeurs custom.

## Avantages

✅ **Fiabilité** : Utilise le système natif d'Odoo pour les attributs
✅ **Maintenance réduite** : Plus de patches JS personnalisés à maintenir
✅ **UX native** : Interface utilisateur standard d'Odoo
✅ **Traçabilité** : Les dimensions apparaissent dans la description de la variante
✅ **Compatibilité** : Garde les champs `lx_width_m` et `lx_height_m` pour les calculs existants

## Architecture

### 1. Attributs créés (lx_base)

Deux attributs avec valeurs custom sont créés automatiquement :

- **Largeur (m)** : `lx_base.product_attribute_width_m`
- **Hauteur (m)** : `lx_base.product_attribute_height_m`

Ces attributs utilisent `is_custom=True` pour permettre la saisie libre de valeurs numériques.

### 2. Synchronisation bidirectionnelle (lx_sales)

Les dimensions sont synchronisées automatiquement entre :
- Les **champs custom** : `lx_width_m` et `lx_height_m` sur `sale.order.line`
- Les **attributs custom** : valeurs dans `product.attribute.custom.value`

**Flux de synchronisation :**

```
Configurateur Odoo (attributs custom)
         ↕ (sync automatique)
sale.order.line (lx_width_m, lx_height_m)
         ↓
Calculs (surface, prix, validation)
```

### 3. Configurateur natif

Plus besoin de patches JS ! Le configurateur Odoo standard :
- Affiche automatiquement les champs dimension pour les attributs custom
- Valide les saisies
- Stocke les valeurs dans les tables standard

## Configuration d'un produit dimensionnel

### Étape 1 : Marquer comme produit dimensionnel

Dans la fiche produit (`product.template`) :
1. Cocher **"Dimension Product"**
2. Les attributs Width/Height seront ajoutés automatiquement lors de la migration

### Étape 2 : Vérifier les attributs

Onglet **Variants** :
- **Largeur (m)** : Valeur "Sur mesure" (custom)
- **Hauteur (m)** : Valeur "Sur mesure" (custom)

### Étape 3 : Utilisation dans les ventes

Lors de l'ajout du produit à une commande :
1. Le configurateur s'ouvre automatiquement
2. L'utilisateur saisit la largeur et hauteur
3. Les valeurs sont synchronisées vers `lx_width_m` et `lx_height_m`
4. Les calculs de surface et prix s'exécutent normalement

## Migration des données existantes

Un script de migration (`lx_base/migrations/19.0.1.1.0/post-migrate.py`) :
1. Identifie tous les produits avec `is_dimension_product=True`
2. Ajoute automatiquement les attributs Largeur et Hauteur
3. Crée les lignes d'attributs et PTAVs correspondants

**Exécution :**
```bash
# Lors de la mise à jour du module
odoo-bin -u lx_base -d votre_base
```

## Compatibilité et rétrocompatibilité

### Champs conservés

Les champs `lx_width_m` et `lx_height_m` sur `sale.order.line` sont **conservés** pour :
- Compatibilité avec le code existant de calcul (surface, prix)
- Validation des contraintes (min/max width/height)
- Intégration avec `lx_mrp` (génération BOM)

### Suppression des patches JS

Les fichiers suivants ont été supprimés car devenus obsolètes :
- `lx_sales/static/src/js/product_configurator_dialog.js`
- `lx_sales/static/src/xml/product_configurator_dialog.xml`

Le configurateur natif d'Odoo gère maintenant les dimensions.

## Méthodes de synchronisation

### `_sync_dimensions_from_attributes()`

Lit les valeurs custom des attributs et met à jour `lx_width_m` et `lx_height_m`.

**Appelée lors de :**
- `_get_sale_order_line_configurator_values()` (chargement du configurateur)

### `_sync_dimensions_to_attributes()`

Écrit `lx_width_m` et `lx_height_m` dans les valeurs custom des attributs.

**Appelée lors de :**
- `_update_from_configurator_values()` (confirmation du configurateur)

## Tests recommandés

### Test 1 : Création d'une nouvelle commande
1. Créer une commande
2. Ajouter un produit dimensionnel
3. Vérifier que le configurateur affiche les champs Width/Height
4. Saisir des dimensions (ex: 2.5 m × 1.8 m)
5. Confirmer et vérifier que `lx_width_m` et `lx_height_m` sont corrects

### Test 2 : Édition d'une ligne existante
1. Ouvrir une ligne de commande avec dimensions
2. Cliquer "Edit Configuration"
3. Modifier les dimensions
4. Vérifier la synchronisation

### Test 3 : Migration de données
1. Créer des produits dimensionnels avant migration
2. Exécuter la migration
3. Vérifier que les attributs Width/Height sont ajoutés automatiquement

### Test 4 : Validation des contraintes
1. Tester les contraintes min/max width/height
2. Vérifier que les erreurs sont bien affichées
3. Tester avec des valeurs invalides (zéro, négatif)

## Dépannage

### Les attributs dimension n'apparaissent pas

**Solution :**
1. Vérifier que `is_dimension_product=True` sur le produit
2. Relancer la migration si nécessaire
3. Vérifier manuellement les lignes d'attributs

### Dimensions non synchronisées

**Solution :**
1. Vérifier les logs pour les erreurs de synchronisation
2. S'assurer que les PTAVs custom existent sur le template
3. Vérifier les références XML `lx_base.product_attribute_width_m`

### Erreurs dans le configurateur

**Solution :**
1. Vider le cache navigateur
2. Régénérer les assets : `odoo-bin --dev=all`
3. Vérifier que les anciens fichiers JS ont bien été supprimés

## Fichiers modifiés

### lx_base
- `data/product_attributes.xml` (nouveau)
- `models/product_template.py` (ajout champs attribut)
- `migrations/19.0.1.1.0/post-migrate.py` (nouveau)
- `__manifest__.py` (version 19.0.1.1.0)

### lx_sales
- `models/sale_order_line.py` (ajout méthodes sync)
- `static/src/js/product_configurator_dialog.js` (supprimé)
- `static/src/xml/product_configurator_dialog.xml` (supprimé)
- `__manifest__.py` (suppression assets)

## Support

Pour toute question ou problème, vérifier :
1. Les logs Odoo pour les erreurs de synchronisation
2. La documentation officielle Odoo sur les attributs custom
3. Ce document pour les scénarios de dépannage

---

**Version:** 19.0.1.1.0
**Date:** 2026-05-20
**Auteur:** Luxtor Development Team
