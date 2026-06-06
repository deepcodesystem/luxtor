# Changelog - Gestion des Prix d'Attributs depuis Composants

## Version 1.0.0 - 2026-05-19

### ✨ Nouvelles fonctionnalités

#### 1. Modèle `product.attribute.component`
- Nouveau modèle pour lier les valeurs d'attributs aux composants (variantes)
- Champs :
  - `ptav_id` : Lien vers la valeur d'attribut
  - `component_variant_id` : Lien vers la variante du composant
  - `quantity` : Quantité utilisée
  - `component_standard_price` : Prix unitaire (stocké pour trigger auto)
  - `subtotal` : Calcul automatique (prix × quantité)

#### 2. Extension `product.template.attribute.value`
- `lx_component_ids` : Liste des composants associés (One2many)
- `lx_price_mode` : Sélection Auto/Manual
  - **Auto** : Prix calculé depuis les composants
  - **Manual** : Saisie manuelle classique
- `lx_computed_price` : Prix calculé avec formule :
  ```
  Σ(component_price × qty) × (1 + waste_rate/100) × (1 + margin/100)
  ```
- Synchronisation automatique du `price_extra` en mode Auto

#### 3. Extension `product.product`
- Hook dans `write()` pour détecter changements de `standard_price`
- Propagation automatique aux attributs concernés
- Context `lx_skip_auto_price_sync` pour éviter boucles infinies

#### 4. Extension `product.template`
- Méthode `lx_sync_attribute_prices_from_components()`
- Bouton "Sync Attribute Prices" dans l'interface
- Notification avec nombre d'attributs synchronisés

#### 5. Vues et interface
- Vue liste `product.attribute.component`
- Vue formulaire enrichie pour valeurs d'attributs
- Onglet "Components" pour gérer les liaisons
- Colonnes `lx_price_mode` et `lx_computed_price` dans liste

### 🔧 Corrections techniques

#### Fix #1 : Erreur validation "sequence"
- **Problème** : Widget "handle" dans vue embedded causait erreur validation
- **Solution** : Retrait des `<field name="sequence" widget="handle"/>`
- **Commit** : Simplifié les vues tree embedded

#### Fix #2 : Erreur validation "component_variant_id"
- **Problème** : Odoo validait les champs One2many inline dans contexte parent
- **Solution** : Utilisation de `context="{'tree_view_ref': '...'}"` au lieu de définition inline
- **Commit** : Référencement vue existante au lieu d'embed

#### Fix #3 : AttributeError sur product.product
- **Problème** : Méthode `lx_sync_attribute_prices_from_components` uniquement sur template
- **Cause** : Bouton cliqué depuis formulaire variante (product.product)
- **Solution** : Ajout de la méthode sur product.product avec délégation au template
- **Commit** : Méthode déléguée template ↔ variante

### 📚 Documentation

- `README_ATTRIBUTE_PRICING.md` : Guide complet d'utilisation
- `INSTALLATION.md` : Instructions d'installation et debugging
- `test_imports.py` : Script de validation pré-installation
- `CHANGELOG_ATTRIBUTE_PRICING.md` : Ce fichier

### 🔒 Sécurité

Droits d'accès pour `product.attribute.component` :
- **Utilisateur** : Lecture seule
- **Commercial** : Lecture, écriture, création
- **Responsable commercial** : Tous droits (incluant suppression)

### ⚙️ Configuration

#### Dépendances ajoutées
- `sale` (pour accès à `product.template.attribute.value`)

#### Vues ajoutées
- `views/product_attribute_component_views.xml`

#### Fichiers modifiés
- `models/__init__.py` : +3 imports
- `__manifest__.py` : +1 dépendance, +1 vue
- `security/ir.model.access.csv` : +3 lignes
- `models/product_template.py` : +1 méthode
- `views/product_template_base_views.xml` : +1 bouton

### 🧪 Tests

Tous les tests de validation passent :
```bash
cd extra-addons/luxtor/lx_base
python3 test_imports.py
# ✅ TOUS LES TESTS SONT PASSÉS !
```

### 📊 Impact

#### Modèles créés : 1
- `product.attribute.component`

#### Modèles étendus : 3
- `product.template.attribute.value`
- `product.product`
- `product.template`

#### Vues créées : 2
- Vue liste composants
- Vue formulaire valeurs d'attributs enrichie

#### Vues modifiées : 1
- Vue formulaire produit template (bouton)

### 🚀 Migration

#### Depuis version précédente (manuelle)
Aucune migration nécessaire - nouveaux champs avec valeurs par défaut :
- `lx_price_mode` : défaut = 'manual' (comportement existant préservé)
- `lx_computed_price` : défaut = 0.0
- `lx_component_ids` : défaut = vide

Les valeurs d'attributs existantes restent en mode "manual" et conservent leur `price_extra` actuel.

### 📝 Notes de version

#### Compatibilité
- **Odoo** : 19.0
- **Module lx_base** : 19.0.1.0.0
- **Python** : 3.11+

#### Limitations connues
- Le widget "handle" pour réordonner les composants n'est pas disponible (problème validation Odoo)
- Ordre des composants défini par `sequence` mais pas modifiable via drag & drop

#### Améliorations futures possibles
1. Ajouter historique des changements de prix
2. Rapport comparatif prix manuel vs auto
3. Import/export en masse des configurations
4. API pour calcul de prix en temps réel
5. Support multi-devises avec conversion

### 🐛 Problèmes résolus

| # | Description | Status |
|---|-------------|--------|
| 1 | Erreur "sequence does not exist" | ✅ Résolu |
| 2 | Erreur "component_variant_id does not exist" | ✅ Résolu |
| 3 | Validation XML embedded views | ✅ Résolu |
| 4 | AttributeError sur product.product | ✅ Résolu |

### 👥 Auteur

**Luxtor Team**
- Date : 2026-05-19
- Module : lx_base
- Version : 19.0.1.0.0

### 📞 Support

En cas de problème :
1. Consulter `INSTALLATION.md` pour debugging
2. Consulter `README_ATTRIBUTE_PRICING.md` pour utilisation
3. Vérifier logs Odoo avec `--log-level=debug`
4. Exécuter `python3 test_imports.py` pour validation

---

**Prochaine étape** : Installation via
```bash
./odoo-bin -c /etc/odoo.conf -u lx_base -d votre_database --stop-after-init
```
