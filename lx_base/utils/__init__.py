# -*- coding: utf-8 -*-
"""
lx_base.utils
=============
Fonctions pures, constantes et helpers partagés entre tous les modules Luxtor.
Aucune dépendance Odoo — importable partout sans effets de bord.
"""
import math

# ── Limites dimensions ────────────────────────────────────────────────────────
LX_MIN_WIDTH_M = 0.60
LX_MIN_HEIGHT_M = 0.90
LX_CHAIN_HEIGHT_THRESHOLD_M = 2.70   # <= → chaîne 150, sinon 200

# ── Codes attribut chaîne plastique ──────────────────────────────────────────
PLASTIC_CHAIN_150_CODE = "BFPC-150"
PLASTIC_CHAIN_200_CODE = "BFPC-200"

# ── Clé paramètre système ─────────────────────────────────────────────────────
ICP_BROWSER_FACTOR = 'luxtor.lx_browser_factor_pct'


# ── Fonctions numériques ──────────────────────────────────────────────────────

def lx_truncate_2(value):
    """Troncature à 2 décimales (floor, pas round)."""
    return math.floor((value or 0.0) * 100.0) / 100.0


def lx_round_up_half(value):
    """Arrondi au 0.5 supérieur."""
    try:
        v = float(value or 0.0)
    except Exception:
        return 0.0
    return math.ceil(v * 2.0) / 2.0


def lx_ceil(value):
    """math.ceil avec protection None."""
    try:
        return math.ceil(float(value or 0.0))
    except Exception:
        return 0


# ── Normalisation valeurs ─────────────────────────────────────────────────────

def lx_norm(v, default=None):
    """Normalise une valeur en str propre (strip + virgule→point). Retourne default si vide."""
    if v in (None, '', False):
        return default
    try:
        return str(v).strip().replace(',', '.')
    except Exception:
        return default


def lx_float(v, default=0.0):
    """Convertit en float avec fallback."""
    try:
        return float(v if v not in (None, '') else default)
    except Exception:
        return default


# ── Conversion unités ─────────────────────────────────────────────────────────

def lx_to_meters(value, unit):
    """Convertit une valeur dans 'unit' en mètres."""
    try:
        v = float(value) if value is not None else 0.0
    except Exception:
        v = 0.0
    if unit == 'm':
        return v
    if unit == 'cm':
        return v / 100.0
    if unit == 'mm':
        return v / 1000.0
    return v


def lx_from_meters(value_m, unit):
    """Convertit des mètres vers 'unit'."""
    v = float(value_m or 0.0)
    if unit == 'm':
        return v
    if unit == 'cm':
        return v * 100.0
    if unit == 'mm':
        return v * 1000.0
    return v


def lx_fmt_unit(value_m, unit):
    """Formate une valeur en mètres vers 'unit' avec décimales adaptées."""
    v = lx_from_meters(value_m, unit)
    decimals = 2 if unit == 'm' else 0
    return f"{v:.{decimals}f} {unit}"


# ── Calculs géométrie ─────────────────────────────────────────────────────────

def lx_area(width_m, height_m, min_val=1.0):
    """Surface effective : max(w, min_val) × max(h, min_val)."""
    w = max(float(width_m or 0.0), min_val)
    h = max(float(height_m or 0.0), min_val)
    return w * h


def lx_bracket_qty(width_m):
    """Quantité de brackets muraux pour une largeur donnée."""
    v_w = max(float(width_m or 0.0), 0.0)
    try:
        return max(math.floor(((v_w - 0.3) / 0.95) + 2), 0)
    except ZeroDivisionError:
        return 2

