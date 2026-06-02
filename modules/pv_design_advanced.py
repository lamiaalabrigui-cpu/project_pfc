"""
Calculs avances de dimensionnement PV - Opti-Solar Maroc.

Ce module contient uniquement des fonctions de calcul et de preparation de tableaux.
Les fonctions d'affichage restent dans app.py.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from math import ceil, floor, sqrt
from pathlib import Path
from typing import Any, Dict, List, Optional
import re

import numpy as np
import pandas as pd


SAFETY_MPPT_HIGH = 1.15
SAFETY_MPPT_LOW = 0.85
SAFETY_DC_VOLTAGE = 1.04
RHO_VALUES = {"Cuivre": 0.0175, "Aluminium": 0.028}
STANDARD_SECTIONS = [1.5, 2.5, 4, 6, 10, 16, 25, 35, 50, 70, 95, 120, 150, 185, 240]
STANDARD_BREAKERS = [2, 4, 6, 10, 16, 20, 25, 32, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630]
NUMBER_RE = re.compile(r"[-+]?\d+(?:[\.,]\d+)?")


PHYSICAL_RANGES = {
    "panel": {
        "wc": (100.0, 900.0),
        "uco": (30.0, 80.0),
        "icc": (1.0, 30.0),
        "umpp": (20.0, 70.0),
        "impp": (1.0, 30.0),
        "irm": (5.0, 60.0),
        "degradation_annuelle": (0.0, 0.05),
        "surface_m2": (0.5, 5.0),
    },
    "inverter": {
        "puissance_nominale_kw": (0.3, 2000.0),
        "imax": (1.0, 2000.0),
        "umppt_min": (20.0, 1000.0),
        "umppt_max": (50.0, 2000.0),
        "tension_ac_v": (100.0, 1000.0),
        "uw": (100.0, 2000.0),
    },
    "battery": {
        "capacite_ah": (1.0, 20000.0),
        "tension_v": (1.0, 1000.0),
        "dod_max": (0.05, 0.98),
    },
}


SYNONYMS = {
    "panel": {
        "wc": [r"\bpmax\b", r"maximum\s+power", r"puissance\s+max(?:imale)?", r"rated\s+power", r"nominal\s+power", r"\bpnom\b"],
        "uco": [r"\bvoc\b", r"open\s+circuit\s+voltage", r"tension\s+en\s+circuit\s+ouvert", r"\buco\b"],
        "icc": [r"\bisc\b", r"short\s+circuit\s+current", r"courant\s+de\s+court[-\s]?circuit", r"\bicc\b"],
        "umpp": [r"\bvmp\b", r"\bvmpp\b", r"\bumpp\b", r"maximum\s+power\s+voltage", r"rated\s+voltage", r"tension\s+nominale", r"tension\s+(?:a|à)\s+puissance\s+max"],
        "impp": [r"\bimp\b", r"\bimpp\b", r"maximum\s+power\s+current", r"rated\s+current", r"courant\s+nominal", r"courant\s+(?:a|à)\s+puissance\s+max"],
        "irm": [r"\birm\b", r"max(?:imum)?\s+series\s+fuse", r"maximum\s+fuse", r"courant\s+inverse\s+max"],
        "surface_m2": [r"\barea\b", r"\bsurface\b", r"module\s+area"],
    },
    "inverter": {
        "puissance_nominale_kw": [r"\bp[_\s-]?nom\b", r"\bpnom\b", r"\bpacnom\b", r"rated\s+ac\s+power", r"nominal\s+ac\s+power", r"puissance\s+nominale"],
        "uw": [r"max\.?\s+input\s+voltage", r"max\.?\s+dc\s+voltage", r"tension\s+d'?entree\s+max", r"tension\s+d'entrée\s+max", r"\bvmax\b", r"\buw\b"],
        "umppt_min": [r"mppt\s+voltage\s+range", r"operating\s+voltage\s+range", r"plage\s+de\s+tension\s+mppt", r"\bvmppt?min\b", r"\bvmin\b"],
        "umppt_max": [r"mppt\s+voltage\s+range", r"operating\s+voltage\s+range", r"plage\s+de\s+tension\s+mppt", r"\bvmppt?max\b"],
        "imax": [r"max\.?\s+input\s+current", r"max\.?\s+current\s+per\s+mppt", r"courant\s+d'?entree\s+max", r"courant\s+d'entrée\s+max", r"\bimax\b", r"\bidcmax\b"],
        "tension_ac_v": [r"\bvac\b", r"ac\s+voltage", r"tension\s+ac", r"nominal\s+output\s+voltage"],
    },
    "battery": {
        "capacite_ah": [r"nominal\s+capacity", r"capacite\s+nominale", r"capacité\s+nominale", r"\bah\b", r"\bcapacity\b", r"\bcapac\b", r"\bc[_\s-]?nom\b"],
        "tension_v": [r"nominal\s+voltage", r"tension\s+nominale", r"\bunom\b", r"\bvolt\b"],
        "dod_max": [r"depth\s+of\s+discharge", r"\bdod\b", r"profondeur\s+de\s+decharge", r"profondeur\s+de\s+décharge"],
    },
}


@dataclass
class PanelTech:
    wc: float = 550.0
    prix_unitaire: float = 1200.0
    impp: float = 13.16
    umpp: float = 41.8
    icc: float = 13.95
    uco: float = 49.5
    irm: float = 25.0
    degradation_annuelle: float = 0.005
    surface_m2: float = 2.61


@dataclass
class InverterTech:
    puissance_nominale_kw: float = 10.0
    prix_unitaire: float = 25000.0
    imax: float = 30.0
    umppt_max: float = 850.0
    umppt_min: float = 200.0
    tension_ac_v: float = 400.0
    uw: float = 1000.0
    phases: int = 3


@dataclass
class BatteryTech:
    capacite_ah: float = 200.0
    tension_v: float = 48.0
    dod_max: float = 0.80
    prix_unitaire: float = 3500.0


@dataclass
class CableDesignInput:
    conducteur: str = "Cuivre"
    longueur_dc_m: float = 30.0
    longueur_ac_m: float = 20.0
    chute_dc: float = 0.03
    chute_ac: float = 0.03


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return default
        return float(value)
    except Exception:
        return default


def next_standard(value: float, standards: Optional[List[float]] = None) -> float:
    standards = standards or STANDARD_SECTIONS
    value = safe_float(value, 0.0)
    for item in standards:
        if item >= value:
            return item
    return standards[-1]


def clean_numeric(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip()
    text = text.replace(",", ".")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except Exception:
        return None


def read_uploaded_text(uploaded_file) -> str:
    if uploaded_file is None:
        return ""

    raw = uploaded_file.getvalue()
    name = getattr(uploaded_file, "name", "").lower()

    if name.endswith(".pdf"):
        # Prefer pdfplumber, fallback to pypdf. Both are optional so the app
        # keeps working even when PDF extraction is unavailable.
        try:
            import pdfplumber  # type: ignore
            import io
            with pdfplumber.open(io.BytesIO(raw)) as pdf:
                return "\n".join((page.extract_text() or "") for page in pdf.pages)
        except Exception:
            pass
        try:
            from pypdf import PdfReader  # type: ignore
            import io
            reader = PdfReader(io.BytesIO(raw))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception:
            return ""

    try:
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        try:
            return raw.decode("latin-1", errors="ignore")
        except Exception:
            return ""


def normalize_spec_text(text: str) -> List[str]:
    """Nettoie un texte de fiche technique en conservant les lignes utiles."""
    text = text.replace("\xa0", " ")
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    text = text.replace("：", ":")
    lines = []
    for line in text.splitlines():
        clean = re.sub(r"[ \t]+", " ", line).strip()
        if clean:
            lines.append(clean)
    return lines


def extract_numbers(text: str) -> List[float]:
    text = re.sub(r"(?<=\d)\s*-\s*(?=\d)", " ", text)
    values = []
    for raw in NUMBER_RE.findall(text):
        try:
            values.append(float(raw.replace(",", ".")))
        except Exception:
            continue
    return values


def is_valid_physical(component_type: str, key: str, value: float) -> bool:
    if value is None or not np.isfinite(value):
        return False
    low_high = PHYSICAL_RANGES.get(component_type, {}).get(key)
    if not low_high:
        return True
    low, high = low_high
    return low <= float(value) <= high


def normalize_extracted_value(component_type: str, key: str, value: float) -> Optional[float]:
    value = safe_float(value, np.nan)
    if not np.isfinite(value):
        return None

    if component_type == "inverter" and key == "puissance_nominale_kw" and value > 1000:
        value = value / 1000
    if component_type == "battery" and key == "dod_max" and value > 1:
        value = value / 100
    if component_type == "panel" and key == "degradation_annuelle" and value > 0.2:
        value = value / 100

    if not is_valid_physical(component_type, key, value):
        return None
    return float(value)


def sanitize_extracted(result: Dict[str, float], component_type: str) -> Dict[str, float]:
    clean: Dict[str, float] = {}
    for key, value in result.items():
        normalized = normalize_extracted_value(component_type, key, value)
        if normalized is not None:
            clean[key] = normalized
    if component_type == "inverter":
        if clean.get("umppt_min") and clean.get("umppt_max") and clean["umppt_min"] > clean["umppt_max"]:
            clean["umppt_min"], clean["umppt_max"] = clean["umppt_max"], clean["umppt_min"]
    return clean


def line_matches(line: str, patterns: List[str]) -> bool:
    return any(re.search(pattern, line, re.IGNORECASE) for pattern in patterns)


def choose_number_for_key(
    numbers: List[float],
    component_type: str,
    key: str,
    target_index: Optional[int] = None,
    target_value: Optional[float] = None,
) -> Optional[float]:
    if not numbers:
        return None

    candidates: List[float] = []
    if target_index is not None and 0 <= target_index < len(numbers):
        candidates = [numbers[target_index]]
    candidates.extend(numbers)

    normalized_candidates = []
    for value in candidates:
        normalized = normalize_extracted_value(component_type, key, value)
        if normalized is not None:
            normalized_candidates.append(normalized)

    if not normalized_candidates:
        return None

    if target_value is not None and key in ["wc", "puissance_nominale_kw"]:
        target = target_value
        if component_type == "inverter" and target > 1000:
            target = target / 1000
        return min(normalized_candidates, key=lambda x: abs(x - target))

    return normalized_candidates[0]


def find_target_column_index(lines: List[str], component_type: str, target_value: Optional[float]) -> Optional[int]:
    """
    Repere la colonne correspondant a la puissance cible dans les tableaux
    multi-modeles, par exemple 530/535/540/545/550 W.
    """
    if target_value is None:
        return None
    target = safe_float(target_value, np.nan)
    if not np.isfinite(target):
        return None
    if component_type == "inverter" and target > 1000:
        target = target / 1000

    if component_type == "panel":
        line_patterns = SYNONYMS["panel"]["wc"] + [r"\bmodel\b", r"\btype\b", r"\bmodule\b"]
        key = "wc"
    elif component_type == "inverter":
        line_patterns = SYNONYMS["inverter"]["puissance_nominale_kw"] + [r"\bmodel\b", r"\btype\b", r"\bktl\b"]
        key = "puissance_nominale_kw"
    else:
        return None

    best_index = None
    best_distance = float("inf")
    for line in lines:
        if not line_matches(line, line_patterns):
            continue
        raw_numbers = extract_numbers(line)
        normalized = []
        original_positions = []
        for idx, value in enumerate(raw_numbers):
            converted = normalize_extracted_value(component_type, key, value)
            if converted is not None:
                normalized.append(converted)
                original_positions.append(idx)
        if len(normalized) < 2:
            continue
        distances = [abs(value - target) for value in normalized]
        local_idx = int(np.argmin(distances))
        if distances[local_idx] < best_distance:
            best_distance = distances[local_idx]
            best_index = local_idx
    return best_index


def parse_by_proximity(text: str, component_type: str, target_value: Optional[float] = None) -> Dict[str, float]:
    """
    Parseur adaptatif: trouve les lignes par synonymes FR/EN, extrait les nombres,
    puis choisit la colonne cible si la fiche contient plusieurs modeles.
    """
    lines = normalize_spec_text(text)
    result: Dict[str, float] = {}
    target_index = find_target_column_index(lines, component_type, target_value)
    synonyms = SYNONYMS.get(component_type, {})

    for key, patterns in synonyms.items():
        for i, line in enumerate(lines):
            if not line_matches(line, patterns):
                continue
            numbers = extract_numbers(line)
            if not numbers and i + 1 < len(lines):
                numbers = extract_numbers(lines[i + 1])

            # MPPT range is commonly written as "200-850 V". Use both values.
            if component_type == "inverter" and key in ["umppt_min", "umppt_max"]:
                valid = [normalize_extracted_value(component_type, key, n) for n in numbers]
                valid = [v for v in valid if v is not None]
                if len(valid) >= 2:
                    result["umppt_min"] = min(valid)
                    result["umppt_max"] = max(valid)
                    continue

            value = choose_number_for_key(numbers, component_type, key, target_index, target_value)
            if value is not None:
                result[key] = value
                break

    return sanitize_extracted(result, component_type)


def extract_power_candidates_from_file(uploaded_file, component_type: str = "panel") -> List[float]:
    text = read_uploaded_text(uploaded_file)
    if not text:
        return []
    lines = normalize_spec_text(text)
    if component_type == "inverter":
        key = "puissance_nominale_kw"
        patterns = SYNONYMS["inverter"][key] + [r"\bktl\b", r"\bkw\b"]
    else:
        key = "wc"
        patterns = SYNONYMS["panel"][key] + [r"\bwc\b", r"\bw\b"]

    candidates = set()
    for line in lines:
        if not line_matches(line, patterns):
            continue
        for value in extract_numbers(line):
            normalized = normalize_extracted_value(component_type, key, value)
            if normalized is not None:
                candidates.add(float(normalized))
    return sorted(candidates)


def parse_pvsyst_key_values(text: str, component_type: str) -> Dict[str, float]:
    """
    Parse les fichiers PVSyst .PAN/.OND/.BATT en lignes cle=valeur.
    Les cles PVSyst sont mappees vers les noms internes.
    """
    key_map = {
        "panel": {
            "pnom": "wc", "pmax": "wc",
            "voc": "uco", "uco": "uco",
            "isc": "icc", "icc": "icc",
            "vmpp": "umpp", "umpp": "umpp", "vmp": "umpp",
            "impp": "impp", "imp": "impp",
            "irm": "irm",
            "area": "surface_m2", "surface": "surface_m2",
        },
        "inverter": {
            "p_nom": "puissance_nominale_kw", "pnom": "puissance_nominale_kw", "pacnom": "puissance_nominale_kw",
            "vmin": "umppt_min", "vmppmin": "umppt_min", "vmpptmin": "umppt_min",
            "vmax": "umppt_max", "vmppmax": "umppt_max", "vmpptmax": "umppt_max",
            "imax": "imax", "idcmax": "imax",
            "vac": "tension_ac_v", "uw": "uw", "vmaxdc": "uw",
        },
        "battery": {
            "capac": "capacite_ah", "ah": "capacite_ah", "c_nom": "capacite_ah", "cnom": "capacite_ah",
            "volt": "tension_v", "unom": "tension_v", "u_nom": "tension_v",
            "dod": "dod_max",
        },
    }
    aliases = key_map.get(component_type, {})
    result: Dict[str, float] = {}

    for raw_line in text.splitlines():
        if "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        clean_key = re.sub(r"[^a-z0-9_]+", "", key.strip().lower())
        if clean_key not in aliases:
            continue
        num = clean_numeric(value)
        if num is not None:
            internal = aliases[clean_key]
            result[internal] = num

    # PVSyst inverter powers are often W. Convert likely W to kW.
    return sanitize_extracted(result, component_type)


def parse_pdf_regex(text: str, component_type: str) -> Dict[str, float]:
    """
    Extraction par regex bilingue FR/EN depuis texte brut de PDF.
    """
    normalized = text.replace(",", ".")
    flags = re.IGNORECASE | re.MULTILINE
    patterns = {
        "panel": {
            "wc": r"(?:pmax|maximum\s+power|puissance\s+maximale|puissance\s+max|rated\s+power|nominal\s+power)[\s:]+(\d+(?:\.\d+)?)\s*(?:w|wc)?",
            "uco": r"(?:voc|open\s+circuit\s+voltage|tension\s+en\s+circuit\s+ouvert|uco)[\s:]+(\d+(?:\.\d+)?)\s*v",
            "icc": r"(?:isc|short\s+circuit\s+current|courant\s+de\s+court[-\s]?circuit|icc)[\s:]+(\d+(?:\.\d+)?)\s*a",
            "umpp": r"(?:vmpp|vmp|umpp|rated\s+voltage|maximum\s+power\s+voltage|tension\s+nominale|tension\s+mpp)[\s:]+(\d+(?:\.\d+)?)\s*v",
            "impp": r"(?:impp|imp|rated\s+current|maximum\s+power\s+current|courant\s+nominal|courant\s+mpp)[\s:]+(\d+(?:\.\d+)?)\s*a",
            "irm": r"(?:irm|max(?:imum)?\s+series\s+fuse|maximum\s+fuse|courant\s+inverse\s+max)[\s:]+(\d+(?:\.\d+)?)\s*a",
            "surface_m2": r"(?:surface|area|module\s+area)[\s:]+(\d+(?:\.\d+)?)\s*(?:m2|m²|sqm)?",
        },
        "inverter": {
            "puissance_nominale_kw": r"(?:p[_\s-]?nom|pnom|pacnom|rated\s+ac\s+power|nominal\s+ac\s+power|puissance\s+nominale)[\s:]+(\d+(?:\.\d+)?)\s*(?:kw|w)?",
            "umppt_min": r"(?:vmin|vmppmin|vmpptmin|mppt\s+voltage\s+range|u\s*mppt\s*min|tension\s+mppt\s+min)[^0-9]{0,20}(\d+(?:\.\d+)?)\s*v",
            "umppt_max": r"(?:vmax|vmppmax|vmpptmax|u\s*mppt\s*max|tension\s+mppt\s+max)[^0-9]{0,20}(\d+(?:\.\d+)?)\s*v",
            "imax": r"(?:imax|idcmax|max(?:imum)?\s+input\s+current|courant\s+max)[\s:]+(\d+(?:\.\d+)?)\s*a",
            "tension_ac_v": r"(?:vac|ac\s+voltage|tension\s+ac|tension\s+nominale\s+ac)[\s:]+(\d+(?:\.\d+)?)\s*v",
            "uw": r"(?:uw|max(?:imum)?\s+dc\s+voltage|tension\s+max(?:imale)?\s+dc)[\s:]+(\d+(?:\.\d+)?)\s*v",
        },
        "battery": {
            "capacite_ah": r"(?:capac|ah|c[_\s-]?nom|capacity|capacite|capacité)[\s:]+(\d+(?:\.\d+)?)\s*(?:ah)?",
            "tension_v": r"(?:volt|unom|u[_\s-]?nom|nominal\s+voltage|tension\s+nominale)[\s:]+(\d+(?:\.\d+)?)\s*v",
            "dod_max": r"(?:dod|depth\s+of\s+discharge|profondeur\s+de\s+decharge)[\s:]+(\d+(?:\.\d+)?)\s*%?",
        },
    }
    result: Dict[str, float] = {}
    for key, pattern in patterns.get(component_type, {}).items():
        match = re.search(pattern, normalized, flags)
        if not match:
            continue
        num = clean_numeric(match.group(1))
        if num is not None:
            result[key] = num
    return sanitize_extracted(result, component_type)


def parse_component_file(uploaded_file, component_type: str, target_value: Optional[float] = None) -> Dict[str, float]:
    text = read_uploaded_text(uploaded_file)
    if not text:
        return {}
    name = getattr(uploaded_file, "name", "").lower()
    result: Dict[str, float] = {}
    if Path(name).suffix.lower() in [".pan", ".ond", ".batt", ".txt"]:
        result.update(parse_pvsyst_key_values(text, component_type))
    # Always run regex fallback too; PDF extraction and text fiches often use labels.
    regex_result = parse_pdf_regex(text, component_type)
    result.update({k: v for k, v in regex_result.items() if v is not None})
    proximity_result = parse_by_proximity(text, component_type, target_value)
    result.update({k: v for k, v in proximity_result.items() if v is not None})
    return sanitize_extracted(result, component_type)


def parse_key_value_spec(uploaded_file) -> Dict[str, float]:
    """
    Backward-compatible parser. Prefer parse_component_file(..., component_type)
    from the Streamlit app.
    """
    text = read_uploaded_text(uploaded_file)
    if not text:
        return {}

    aliases = {
        "wc": ["wc", "pmax", "puissance", "puissance crete", "pmpp"],
        "prix_unitaire": ["prix", "price", "prix_unitaire"],
        "impp": ["impp", "imp", "i_mpp", "courant mpp"],
        "umpp": ["umpp", "vmp", "u_mpp", "tension mpp"],
        "icc": ["icc", "isc", "i_sc", "courant court circuit"],
        "uco": ["uco", "voc", "v_oc", "tension circuit ouvert"],
        "irm": ["irm", "max series fuse", "courant inverse max"],
        "degradation_annuelle": ["degradation", "degradation_annuelle"],
        "surface_m2": ["surface", "area"],
        "puissance_nominale_kw": ["pnom", "pac", "puissance nominale", "rated power"],
        "imax": ["imax", "courant max", "max input current"],
        "umppt_max": ["umppt max", "mppt max", "vmppt max"],
        "umppt_min": ["umppt min", "mppt min", "vmppt min"],
        "tension_ac_v": ["tension ac", "vac", "ac voltage"],
        "uw": ["uw", "tension max", "max dc voltage"],
        "capacite_ah": ["capacite", "capacity", "ah"],
        "tension_v": ["u batt", "battery voltage", "tension batterie"],
        "dod_max": ["dod", "depth of discharge"],
    }

    found: Dict[str, float] = {}
    lines = text.replace(";", "\n").splitlines()
    for line in lines:
        clean = line.strip().lower()
        if not clean:
            continue
        nums = re.findall(r"[-+]?\d+[\.,]?\d*", clean)
        if not nums:
            continue
        value = float(nums[-1].replace(",", "."))
        for key, words in aliases.items():
            if any(w in clean for w in words):
                found[key] = value
    return found


def recommended_system_voltage(power_kwc: float, system_type: str) -> float:
    if system_type == "on-grid":
        return 600.0 if power_kwc > 30 else 400.0
    if power_kwc <= 5:
        return 48.0
    if power_kwc <= 15:
        return 96.0
    return 400.0


def calculate_pv_design(
    puissance_optimale_kwc: float,
    conso_annuelle_kwh: float,
    system_type: str,
    panel: PanelTech,
    inverter: InverterTech,
    battery: Optional[BatteryTech],
    autonomie_jours: float,
    cable: CableDesignInput,
    spd_up_v: float = 600.0,
) -> Dict[str, Any]:
    pc_kwc = max(safe_float(puissance_optimale_kwc, 0.0), 0.001)
    wc = max(panel.wc, 1.0)
    nb_modules = ceil(pc_kwc * 1000 / wc)
    pc_reelle_kwc = nb_modules * wc / 1000
    surface = nb_modules * panel.surface_m2
    u_sys = recommended_system_voltage(pc_reelle_kwc, system_type)

    power_ok = 0.80 * pc_reelle_kwc <= inverter.puissance_nominale_kw <= 1.10 * pc_reelle_kwc
    np_max = max(1, floor(inverter.imax / max(panel.impp, 0.001)))
    ns_max = max(1, ceil(inverter.umppt_max / max(panel.umpp * SAFETY_MPPT_HIGH, 0.001)))
    ns_min = max(1, floor(inverter.umppt_min / max(panel.umpp * SAFETY_MPPT_LOW, 0.001)))
    ns_ok = ns_min <= ns_max

    target_ns = int(np.clip(round(u_sys / max(panel.umpp, 0.001)), ns_min, ns_max)) if ns_ok else max(1, ns_min)
    strings_needed = ceil(nb_modules / max(target_ns, 1))
    parallel_ok = strings_needed <= np_max

    battery_result = None
    if system_type in ["hybride", "off-grid"] and battery is not None:
        e_daily_wh = conso_annuelle_kwh / 365 * 1000
        c_required_ah = (e_daily_wh * autonomie_jours) / max(battery.dod_max * u_sys, 0.001)
        nb_p = ceil(c_required_ah / max(battery.capacite_ah, 0.001))
        nb_s = ceil(u_sys / max(battery.tension_v, 0.001))
        battery_result = {
            "energie_journaliere_wh": round(e_daily_wh, 2),
            "autonomie_jours": autonomie_jours,
            "u_sys_v": u_sys,
            "capacite_requise_ah": round(c_required_ah, 2),
            "batteries_parallele": nb_p,
            "batteries_serie": nb_s,
            "nombre_total_batteries": nb_p * nb_s,
            "capacite_installee_kwh": round(nb_p * nb_s * battery.capacite_ah * battery.tension_v / 1000, 2),
        }

    rho = RHO_VALUES.get(cable.conducteur, RHO_VALUES["Cuivre"])
    idc = panel.impp * strings_needed
    vdc = panel.umpp * target_ns
    s_dc = (2 * cable.longueur_dc_m * rho * idc) / max(vdc * cable.chute_dc, 0.001)
    section_dc = next_standard(s_dc)

    pac_w = inverter.puissance_nominale_kw * 1000
    if inverter.phases == 3:
        iac = pac_w / max(sqrt(3) * inverter.tension_ac_v, 0.001)
        s_ac = (sqrt(3) * cable.longueur_ac_m * rho * iac) / max(inverter.tension_ac_v * cable.chute_ac, 0.001)
    else:
        iac = pac_w / max(inverter.tension_ac_v, 0.001)
        s_ac = (2 * cable.longueur_ac_m * rho * iac) / max(inverter.tension_ac_v * cable.chute_ac, 0.001)
    section_ac = next_standard(s_ac)

    fuse_low = 1.1 * 1.25 * panel.icc
    fuse_high = min(2 * panel.icc, panel.irm)
    fuse_in = next_standard(fuse_low, STANDARD_BREAKERS)
    fuse_ok = fuse_low <= fuse_high and fuse_in <= fuse_high
    un_dc_required = panel.uco * target_ns * SAFETY_DC_VOLTAGE
    breaker_dc_in = next_standard(1.25 * panel.icc, STANDARD_BREAKERS)
    spd_module_ok = spd_up_v < 0.8 * panel.uco
    spd_inverter_ok = spd_up_v < 0.8 * inverter.uw
    ac_breaker = next_standard(1.25 * iac, STANDARD_BREAKERS)

    return {
        "general": {
            "puissance_optimale_kwc": round(pc_kwc, 3),
            "nombre_modules": nb_modules,
            "puissance_reelle_kwc": round(pc_reelle_kwc, 3),
            "surface_panneaux_m2": round(surface, 2),
            "u_sys_recommande_v": round(u_sys, 1),
        },
        "compatibilite_onduleur": {
            "puissance_ok_80_110": bool(power_ok),
            "np_max": int(np_max),
            "ns_min": int(ns_min),
            "ns_max": int(ns_max),
            "ns_recommande": int(target_ns),
            "chaines_requises": int(strings_needed),
            "parallel_ok": bool(parallel_ok),
            "compatible_global": bool(power_ok and ns_ok and parallel_ok),
        },
        "batteries": battery_result,
        "cables": {
            "conducteur": cable.conducteur,
            "rho": rho,
            "courant_dc_a": round(idc, 2),
            "tension_dc_v": round(vdc, 2),
            "section_dc_calculee_mm2": round(s_dc, 2),
            "section_dc_standard_mm2": section_dc,
            "courant_ac_a": round(iac, 2),
            "section_ac_calculee_mm2": round(s_ac, 2),
            "section_ac_standard_mm2": section_ac,
        },
        "protections": {
            "fusible_dc": {
                "in_min_a": round(fuse_low, 2),
                "in_max_a": round(fuse_high, 2),
                "in_choisi_a": fuse_in,
                "ok": bool(fuse_ok),
                "un_min_v": round(un_dc_required, 2),
            },
            "sectionneur_dc": {
                "in_min_a": round(1.25 * panel.icc, 2),
                "in_choisi_a": breaker_dc_in,
                "un_min_v": round(un_dc_required, 2),
            },
            "parafoudre_dc": {
                "up_v": spd_up_v,
                "critere_modules_up_lt_0_8_uco": bool(spd_module_ok),
                "critere_onduleur_up_lt_0_8_uw": bool(spd_inverter_ok),
            },
            "protection_ac": {
                "courant_ac_a": round(iac, 2),
                "disjoncteur_ac_min_a": round(1.25 * iac, 2),
                "disjoncteur_ac_choisi_a": ac_breaker,
            },
        },
    }


def default_capex_rows(design: Dict[str, Any], panel: PanelTech, inverter: InverterTech, battery: Optional[BatteryTech], system_type: str, structure_type: str, labour_pct: float) -> pd.DataFrame:
    g = design["general"]
    c = design["cables"]
    p = design["protections"]
    pc_w = g["puissance_reelle_kwc"] * 1000
    structure_prices = {
        "Toiture residentielle inclinee": 0.20,
        "Toiture industrielle bac acier": 0.30,
        "Sol ground-mounted": 0.45,
        "Ombriere parking": 0.90,
    }
    rows = [
        ["Modules PV", "u", g["nombre_modules"], panel.prix_unitaire],
        ["Onduleur", "u", 1, inverter.prix_unitaire],
        [f"Cable solaire DC {c['section_dc_standard_mm2']} mm2", "m", 60, {4:14, 6:18, 10:30, 16:40}.get(c["section_dc_standard_mm2"], 35)],
        [f"Cable AC {c['section_ac_standard_mm2']} mm2", "m", 40, {4:14, 6:18, 10:30, 16:40}.get(c["section_ac_standard_mm2"], 35)],
        ["Fusibles DC gPV", "u", max(1, design["compatibilite_onduleur"]["chaines_requises"]), 150],
        ["Sectionneur DC", "u", 1, 1200],
        ["Parafoudre DC", "u", 1, 800],
        ["Disjoncteur AC", "u", 1, 900],
        ["Structure de fixation", "Wc", pc_w, structure_prices.get(structure_type, 0.30)],
    ]
    if system_type in ["hybride", "off-grid"] and design.get("batteries") and battery is not None:
        rows.append(["Batteries", "u", design["batteries"]["nombre_total_batteries"], battery.prix_unitaire])

    df = pd.DataFrame(rows, columns=["Designation", "Unite", "Quantite", "Prix unitaire HT"])
    df["Prix total HT"] = df["Quantite"].astype(float) * df["Prix unitaire HT"].astype(float)
    labour_base = float(df["Prix total HT"].sum())
    labour = labour_base * labour_pct
    df.loc[len(df)] = ["Main d'oeuvre", "forfait", 1, labour, labour]
    df["Prix total HT"] = df["Quantite"].astype(float) * df["Prix unitaire HT"].astype(float)
    return df


def capex_from_rows(rows: pd.DataFrame, tva: float) -> Dict[str, float]:
    df = rows.copy()
    for col in ["Quantite", "Prix unitaire HT"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df["Prix total HT"] = df["Quantite"] * df["Prix unitaire HT"]
    total_ht = float(df["Prix total HT"].sum())
    tva_amount = total_ht * tva
    return {"total_ht": total_ht, "tva": tva_amount, "total_ttc": total_ht + tva_amount}
