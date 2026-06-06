# ✅ CORRECTION MAJEURE : waste_rate et added_margin PAR COMPOSANT

## 🎯 Changement important

**AVANT** (incorrect) : Les marges du template du store étaient appliquées globalement
**MAINTENANT** (correct) : Les marges de **chaque composant** sont appliquées individuellement

## 🔧 Logique corrigée

### Principe
Chaque composant a ses propres `waste_rate` et `added_margin` définis sur son template.
Le calcul final est la **somme des montants avec marges de chaque composant**.

### Formule

Pour chaque composant :
```
subtotal = standard_price × quantity
amount_with_margins = subtotal × (1 + waste_rate/100) × (1 + added_margin/100)
```

Prix total de l'attribut :
```
lx_computed_price = Σ(amount_with_margins de chaque composant)
```

## 📊 Exemple concret

### Configuration

**Composant 1 : Tissu Blanc**
- `standard_price` = 25.00 €
- `waste_rate` = 5%
- `added_margin` = 20%
- Quantité utilisée = 1.5

**Composant 2 : Support Fixation**
- `standard_price` = 3.50 €
- `waste_rate` = 10%
- `added_margin` = 30%
- Quantité utilisée = 2.0

### Calcul détaillé

**Composant 1 (Tissu) :**
```
subtotal = 25.00 × 1.5 = 37.50 €
factor = (1 + 0.05) × (1 + 0.20) = 1.05 × 1.20 = 1.26
amount_with_margins = 37.50 × 1.26 = 47.25 €
```

**Composant 2 (Support) :**
```
subtotal = 3.50 × 2.0 = 7.00 €
factor = (1 + 0.10) × (1 + 0.30) = 1.10 × 1.30 = 1.43
amount_with_margins = 7.00 × 1.43 = 10.01 €
```

**Total attribut :**
```
lx_computed_price = 47.25 + 10.01 = 57.26 €
price_extra = 57.26 € (si mode auto)
```

## 🆚 Comparaison avec l'ancienne méthode

### ❌ Ancienne méthode (incorrecte)
```
Base = 37.50 + 7.00 = 44.50 €
Marges du store (ex: 5% + 20%) = 44.50 × 1.26 = 56.07 €
```
→ **Ne tient pas compte des marges différentes de chaque composant**

### ✅ Nouvelle méthode (correcte)
```
Tissu avec ses marges (5% + 20%) = 47.25 €
Support avec ses marges (10% + 30%) = 10.01 €
Total = 57.26 €
```
→ **Chaque composant a ses propres marges**

## 🔍 Nouveaux champs

### Sur `product.attribute.component`

| Champ | Type | Description |
|-------|------|-------------|
| `component_waste_rate` | Float (related, stored) | waste_rate du template du composant |
| `component_added_margin` | Float (related, stored) | added_margin du template du composant |
| `subtotal` | Float (computed, stored) | Prix × Quantité (sans marges) |
| `amount_with_margins` | Float (computed, stored) | Subtotal avec marges appliquées |

### Vues mises à jour

**Liste des composants** :
- Colonnes `component_waste_rate` et `component_added_margin` (optionnelles, cachées par défaut)
- Colonne `subtotal` (optionnelle, cachée)
- Colonne `amount_with_margins` (visible, avec total)

## 🧪 Test après correction

### Étape 1 : Préparer les composants

1. **Créer "Tissu Blanc" (composant)**
   - `lx_is_component` = True
   - `standard_price` = 25.00 €
   - `waste_rate` = 5.0
   - `added_margin` = 20.0

2. **Créer "Support Fixation" (composant)**
   - `lx_is_component` = True
   - `standard_price` = 3.50 €
   - `waste_rate` = 10.0
   - `added_margin` = 30.0

### Étape 2 : Configurer l'attribut

1. Créer produit avec attribut "Couleur → Blanc"
2. Mode = `Automatic from Components`
3. Ajouter composants :
   - Tissu Blanc : qty = 1.5
   - Support : qty = 2.0

### Étape 3 : Vérifier le calcul

**Dans la vue liste des composants :**

| Composant | Qty | Prix | Waste | Margin | Subtotal | Amount w/ Margins |
|-----------|-----|------|-------|--------|----------|-------------------|
| Tissu Blanc | 1.5 | 25.00 | 5% | 20% | 37.50 | **47.25** |
| Support | 2.0 | 3.50 | 10% | 30% | 7.00 | **10.01** |
| **TOTAL** | | | | | | **57.26** |

**Dans le formulaire attribut :**
- `lx_computed_price` = **57.26 €**
- `price_extra` = **57.26 €** (en mode auto)

### Étape 4 : Vérifier les logs (DEBUG)

```
Computing price for PTAV 'Blanc': 2 component(s), total=57.26
  - Tissu Blanc: qty=1.50, price=25.00, waste=5.0%, margin=20.0%, amount=47.25
  - Support Fixation: qty=2.00, price=3.50, waste=10.0%, margin=30.0%, amount=10.01
```

## 📝 Impact sur la migration

### Données existantes

Les attributs existants continueront de fonctionner :
- Mode `manual` : pas de changement
- Mode `auto` sans composants : `lx_computed_price` = 0

### Nouveaux attributs

Lors de l'ajout de composants :
1. Les champs `component_waste_rate` et `component_added_margin` sont récupérés automatiquement
2. Le calcul `amount_with_margins` se fait automatiquement
3. Le total est recalculé

## 🎓 Bonnes pratiques

1. **Définir waste_rate et added_margin sur les templates de composants**
   - Aller sur chaque composant (Tissu, Support, etc.)
   - Onglet Luxtor → Définir les marges

2. **Vérifier les marges dans la liste**
   - Activer les colonnes optionnelles `component_waste_rate` et `component_added_margin`
   - Vérifier que les valeurs sont correctes

3. **Utiliser les logs pour débugger**
   - Mode DEBUG affiche les calculs détaillés de chaque composant

## 🚀 Mise à jour nécessaire

```bash
# Mise à jour du module
./odoo-bin -c /etc/odoo.conf -u lx_base -d votre_database --stop-after-init

# Redémarrage Odoo
sudo systemctl restart odoo
```

## ✅ Checklist après mise à jour

- [ ] Les colonnes `component_waste_rate` et `component_added_margin` apparaissent dans les vues
- [ ] Le champ `amount_with_margins` affiche le bon calcul
- [ ] Le total `lx_computed_price` correspond à la somme des `amount_with_margins`
- [ ] Les logs DEBUG montrent le détail par composant
- [ ] La colonne `amount_with_margins` a un total en bas de liste

---

**Correction appliquée** : 2026-05-19
**Version** : lx_base 19.0.1.0.0
**Impact** : Majeur - Changement de logique de calcul
