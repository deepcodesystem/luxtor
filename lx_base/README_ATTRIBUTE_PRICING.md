# Gestion Automatique des Prix d'Attributs depuis les Composants

## Vue d'ensemble

Ce module permet d'associer des produits composants (variantes) aux valeurs d'attributs et de mettre à jour automatiquement leur `price_extra` en fonction du coût des composants.

## Architecture

### Modèles

1. **`product.attribute.component`** (nouveau)
   - Liaison entre une valeur d'attribut (`product.template.attribute.value`) et un composant (variante `product.product`)
   - Champs : `component_variant_id`, `quantity`, `component_standard_price`, `subtotal`

2. **`product.template.attribute.value`** (extension)
   - `lx_component_ids` : Liste des composants associés
   - `lx_price_mode` : Mode de calcul (`auto` ou `manual`)
   - `lx_computed_price` : Prix calculé automatiquement
   - `price_extra` : Synchronisé automatiquement en mode `auto`

3. **`product.product`** (extension)
   - Hook dans `write()` pour propager les changements de `standard_price` aux attributs concernés

4. **`product.template`** (extension)
   - Méthode `lx_sync_attribute_prices_from_components()` pour synchronisation manuelle

## Workflow utilisateur

### Configuration initiale

1. **Créer un produit avec attributs** (ex: Store enroulable avec variantes)

2. **Configurer les valeurs d'attributs**
   - Aller dans **Ventes → Configuration → Attributs → Valeurs d'attributs**
   - Ou depuis la fiche produit → **Variantes → Configurer**

3. **Pour chaque valeur d'attribut** :
   - Ouvrir la fiche de la valeur d'attribut
   - Définir **Price Mode** = `Automatic from Components`
   - Aller dans l'onglet **Components**
   - Ajouter les composants (variantes) avec leurs quantités :
     ```
     Composant                    | Quantité | Prix unitaire | Sous-total
     -----------------------------|----------|---------------|------------
     Tissu [Blanc] (Fabric)       | 1.5      | 25.00         | 37.50
     Tube Alu Ø28mm               | 1.0      | 12.00         | 12.00
     Mécanisme Standard           | 1.0      | 8.50          | 8.50
     -----------------------------|----------|---------------|------------
     Total composants             |          |               | 58.00
     ```

4. **Calcul automatique du prix**
   - Prix calculé = **Σ(prix_composant × quantité) × (1 + waste_rate/100) × (1 + added_margin/100)**
   - Exemple avec `waste_rate=5%` et `added_margin=20%` :
     ```
     Base = 58.00
     Avec waste (5%) = 58.00 × 1.05 = 60.90
     Avec marge (20%) = 60.90 × 1.20 = 73.08

     → price_extra = 73.08
     ```

### Synchronisation automatique

**Quand le `standard_price` d'un composant change** :
1. Le système détecte automatiquement tous les attributs qui utilisent ce composant
2. Recalcule leur `lx_computed_price`
3. Met à jour leur `price_extra` si en mode `auto`

**Exemple** :
- Le tissu blanc passe de 25.00 → 28.00
- Tous les attributs utilisant ce tissu sont automatiquement mis à jour
- Nouvelle valeur = (28.00 × 1.5 + 12.00 + 8.50) × 1.05 × 1.20 = **79.38**

### Synchronisation manuelle

Sur la fiche produit, cliquer sur le bouton **"Sync Attribute Prices"** :
- Recalcule tous les `price_extra` des attributs en mode `auto`
- Affiche une notification avec le nombre d'attributs synchronisés

### Mode manuel (override)

Pour forcer un prix spécifique :
1. Définir **Price Mode** = `Manual Entry`
2. Saisir directement le `price_extra` souhaité
3. Le prix ne sera plus recalculé automatiquement

## Formule de calcul

```python
base = Σ(component_standard_price × quantity)
waste_factor = 1 + (waste_rate / 100)
margin_factor = 1 + (added_margin / 100)

lx_computed_price = base × waste_factor × margin_factor
```

Les paramètres `waste_rate` et `added_margin` sont définis sur le **template du produit** (onglet Luxtor).

## Vues et interfaces

### Vue formulaire valeur d'attribut
- Champ **Price Mode** : Auto / Manual
- Champ **Auto Computed Price** (visible en mode auto uniquement)
- Onglet **Components** : liste éditable des composants

### Vue liste valeurs d'attributs
- Colonne **Price Mode** (optionnelle)
- Colonne **Computed Price** (cachée par défaut)

### Fiche produit
- Bouton **"Sync Attribute Prices"** dans la zone boutons (visible si le produit a des attributs)

## Droits d'accès

| Groupe                    | Lecture | Écriture | Création | Suppression |
|---------------------------|---------|----------|----------|-------------|
| Utilisateur               | ✓       | ✗        | ✗        | ✗           |
| Commercial                | ✓       | ✓        | ✓        | ✗           |
| Responsable commercial    | ✓       | ✓        | ✓        | ✓           |

## Cas d'usage

### Exemple : Store enroulable avec tissus

**Produit** : `[CODE] Roller Blind`
**Attributs** :
- Tissu : Blanc, Beige, Gris
- Mécanisme : Manuel, Motorisé

**Configuration pour "Tissu : Blanc"** :
```
Composants :
- Fabric [Blanc] : 1.5m² @ 25.00€ = 37.50€
- Support fixation : 2 unités @ 3.50€ = 7.00€

Sous-total composants = 44.50€
Avec waste_rate (5%) = 46.73€
Avec added_margin (20%) = 56.08€

→ price_extra = 56.08€
```

**Configuration pour "Mécanisme : Motorisé"** :
```
Composants :
- Moteur tubulaire 30Nm : 1 unité @ 45.00€ = 45.00€
- Télécommande : 1 unité @ 15.00€ = 15.00€

Sous-total composants = 60.00€
Avec waste_rate (0%) = 60.00€
Avec added_margin (15%) = 69.00€

→ price_extra = 69.00€
```

**Prix final de la variante** :
```
Prix de base = 100.00€
+ Tissu Blanc = 56.08€
+ Mécanisme Motorisé = 69.00€
────────────────────────
Prix de vente = 225.08€
```

## Maintenance

### Mise à jour des prix composants
1. Modifier le `standard_price` du composant
2. La synchronisation est **automatique** pour tous les attributs concernés
3. Vérifier les notifications dans l'interface

### Traçabilité
- Le champ `component_standard_price` est stocké pour suivre l'historique
- Le champ `lx_computed_price` garde la trace du dernier calcul

### Déboggage
- Vérifier que le composant a bien `lx_is_component = True`
- Vérifier que l'attribut est en mode `lx_price_mode = 'auto'`
- Vérifier que `waste_rate` et `added_margin` sont bien définis sur le template

## Intégration avec les BOM

Cette fonctionnalité est complémentaire aux BOM (Bill of Materials) :
- Les **attributs** définissent les extras de prix pour chaque option
- Les **BOM** définissent la fabrication complète du produit final

Les composants référencés dans les attributs peuvent être les mêmes que ceux utilisés dans les BOM, assurant une cohérence entre le prix de vente et le coût de fabrication.

## Notes techniques

### Éviter les boucles infinies
- Utilisation du contexte `lx_skip_auto_price_sync=True` lors des écritures
- Tolérance de 0.01 pour les comparaisons de prix

### Performance
- Le champ `component_standard_price` est stocké (`store=True`) pour déclencher automatiquement les recalculs
- Les calculs sont déclenchés uniquement quand nécessaire (changement de `standard_price`)

### Extensibilité
- La formule de calcul peut être personnalisée en surchargeant `_compute_lx_computed_price()`
- D'autres facteurs peuvent être ajoutés facilement (ex: taxes, remises)
