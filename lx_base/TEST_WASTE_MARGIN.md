# Test waste_rate et added_margin

## 🧪 Procédure de test

### Étape 1 : Préparer un produit test

1. **Créer un produit template avec attributs**
   - Nom : `[TEST] Store Test`
   - Type : Store (`lx_is_store = True`)
   - Attribut : Couleur avec valeurs (Blanc, Gris)

2. **Configurer waste_rate et added_margin sur le template**
   - Onglet Luxtor
   - `waste_rate` = 5.0 (5%)
   - `added_margin` = 20.0 (20%)

### Étape 2 : Créer des composants

1. **Créer un composant "Tissu Blanc"**
   - Nom : `Tissu Blanc`
   - Type : `lx_is_component = True`
   - `standard_price` = 25.00 €

2. **Créer un composant "Support"**
   - Nom : `Support Fixation`
   - Type : `lx_is_component = True`
   - `standard_price` = 3.50 €

### Étape 3 : Configurer l'attribut en mode Auto

1. **Aller dans la valeur d'attribut "Blanc"**
   - Ventes → Configuration → Attributs → Valeurs d'attributs
   - Ou depuis produit → Variantes → Configurer → Ouvrir "Blanc"

2. **Définir le mode automatique**
   - `Price Mode` = **Automatic from Components**

3. **Ajouter les composants dans l'onglet "Components"**
   ```
   Composant           | Quantité | Prix unitaire | Sous-total
   --------------------|----------|---------------|------------
   Tissu Blanc         | 1.5      | 25.00         | 37.50
   Support Fixation    | 2.0      |  3.50         |  7.00
   --------------------|----------|---------------|------------
   Total                                          | 44.50
   ```

### Étape 4 : Vérifier le calcul

**Calcul attendu :**

```
Base (somme composants) = 44.50 €

Étape 1 - Application waste_rate (5%) :
  44.50 × (1 + 5/100) = 44.50 × 1.05 = 46.725 €

Étape 2 - Application added_margin (20%) :
  46.725 × (1 + 20/100) = 46.725 × 1.20 = 56.07 €

→ lx_computed_price = 56.07 €
→ price_extra = 56.07 € (synchronisé automatiquement)
```

**Vérification dans l'interface :**

1. **Dans le formulaire de la valeur d'attribut "Blanc"** :
   - Vérifier `lx_computed_price` = 56.07 €
   - Vérifier `price_extra` = 56.07 €

2. **Dans les logs Odoo (mode debug)** :
   ```
   Computing price for PTAV 'Blanc': base=44.50, waste_rate=5.00%, added_margin=20.00%
   Result: factor=1.2600, computed_price=56.07
   ```

### Étape 5 : Test de modification

1. **Changer waste_rate sur le template**
   - Passer `waste_rate` de 5% → 10%

2. **Déclencher recalcul**
   - Cliquer sur "Sync Attribute Prices" OU
   - Modifier un composant (déclenche auto)

3. **Vérifier nouveau calcul**
   ```
   Base = 44.50 €
   Avec waste (10%) = 44.50 × 1.10 = 48.95 €
   Avec margin (20%) = 48.95 × 1.20 = 58.74 €

   → Nouveau lx_computed_price = 58.74 €
   ```

### Étape 6 : Test sans waste_rate ni added_margin

1. **Mettre waste_rate = 0 et added_margin = 0**

2. **Vérifier calcul**
   ```
   Base = 44.50 €
   Factor = (1 + 0/100) × (1 + 0/100) = 1.0 × 1.0 = 1.0

   → lx_computed_price = 44.50 € (exactement la somme des composants)
   ```

## 🔍 Debugging

### Activer les logs détaillés

1. **Via ligne de commande** :
   ```bash
   ./odoo-bin -c /etc/odoo.conf --log-handler=odoo.addons.lx_base.models.product_template_attribute_value:DEBUG
   ```

2. **Chercher dans les logs** :
   ```
   DEBUG ... Computing price for PTAV 'Blanc': base=44.50, waste_rate=5.00%, added_margin=20.00%
   DEBUG ... Result: factor=1.2600, computed_price=56.07
   ```

### Vérifications manuelles

1. **SQL directe** (en dernier recours) :
   ```sql
   SELECT
       ptav.id,
       ptav.name,
       pt.waste_rate,
       pt.added_margin,
       ptav.lx_computed_price,
       ptav.price_extra
   FROM product_template_attribute_value ptav
   JOIN product_template_attribute_line ptal ON ptal.id = ptav.attribute_line_id
   JOIN product_template pt ON pt.id = ptal.product_tmpl_id
   WHERE pt.name LIKE '%TEST%';
   ```

2. **Via Python shell Odoo** :
   ```python
   ptav = env['product.template.attribute.value'].search([('name', '=', 'Blanc')], limit=1)
   print(f"Base: {sum(ptav.lx_component_ids.mapped('subtotal'))}")
   print(f"Waste: {ptav.product_tmpl_id.waste_rate}%")
   print(f"Margin: {ptav.product_tmpl_id.added_margin}%")
   print(f"Computed: {ptav.lx_computed_price}")
   print(f"Price Extra: {ptav.price_extra}")
   ```

## ❌ Problèmes possibles

### Problème 1 : lx_computed_price = base (pas de facteur)

**Cause** : `product_tmpl_id` est vide ou `waste_rate`/`added_margin` non définis

**Solution** :
- Vérifier que l'attribut est bien lié au template
- Vérifier que `waste_rate` et `added_margin` sont bien saisis sur le **template** (pas la variante)

### Problème 2 : Les logs ne s'affichent pas

**Cause** : Niveau de log trop élevé

**Solution** :
- Relancer avec `--log-level=debug`
- Ou modifier `/etc/odoo.conf` :
  ```ini
  [options]
  log_level = debug
  log_handler = odoo.addons.lx_base:DEBUG
  ```

### Problème 3 : price_extra pas synchronisé

**Cause** : Mode manual au lieu de auto

**Solution** :
- Vérifier `lx_price_mode` = 'auto'
- Cliquer sur "Sync Attribute Prices"

## ✅ Résultat attendu

Avec la configuration test ci-dessus :

| Champ | Valeur attendue | Formule |
|-------|-----------------|---------|
| Base (composants) | 44.50 € | 37.50 + 7.00 |
| waste_rate | 5% | Défini sur template |
| added_margin | 20% | Défini sur template |
| Factor | 1.26 | (1 + 0.05) × (1 + 0.20) |
| lx_computed_price | 56.07 € | 44.50 × 1.26 |
| price_extra | 56.07 € | Sync auto en mode 'auto' |

---

**Testé avec** : Odoo 19.0, module lx_base v19.0.1.0.0
**Date** : 2026-05-19
