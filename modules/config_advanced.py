"""
Module de Configuration Avancee - Opti-Solar Maroc

Configuration centrale de l'application:
- Donnees geographiques TMY depuis fichiers CSV
- Parametres techniques PV, onduleur, batteries, cablage
- Parametres economiques, environnementaux et calcul
- References tarifaires ONEE de base
- References reglementaires indicatives

Important:
Ce module fournit des hypotheses de pre-dimensionnement.
Il ne remplace pas une etude d'execution, une validation ONEE/ANRE,
ni une verification par un bureau d'etudes.
"""

from dataclasses import dataclass, asdict, field
from typing import Dict, Any, List
import json


# ==============================================================================
# CHEMINS ET DONNEES TMY
# ==============================================================================

DATA_TMY_DIR = "data"

VILLES_MAROC = {
    "Benguerir": {
        "file_name": "data_TMY_Benguerir2050.csv.txt",
        "latitude": 32.2214,
        "longitude": -7.9282,
        "altitude": 474,
        "timezone": "UTC+01:00",
        "zone_climatique": "Zone 4 - Continental Semi-aride",
    },
    "Boucraa": {
        "file_name": "data_TMY_Boucraa.csv.txt",
        "latitude": 26.323527,
        "longitude": -12.852104,
        "altitude": 222,
        "timezone": "UTC+01:00",
        "zone_climatique": "Zone 5 - Saharien",
    },
    "Alargoub": {
        "file_name": "data_TMY_alargoub.csv.txt",
        "latitude": 23.6025,
        "longitude": -15.8571,
        "altitude": 26,
        "timezone": "UTC+01:00",
        "zone_climatique": "Zone 5 - Saharien littoral",
    },
    "Rabat": {
        "file_name": "data_TMY_rabat.csv.txt",
        "latitude": 33.9921,
        "longitude": -6.7086,
        "altitude": 138,
        "timezone": "UTC+01:00",
        "zone_climatique": "Zone 2 - Littoral Atlantique",
    },
    "Safi": {
        "file_name": "data_TMY_ocpsafi.csv.txt",
        "latitude": 32.232317,
        "longitude": -9.250319,
        "altitude": 26,
        "timezone": "UTC+01:00",
        "zone_climatique": "Zone 2 - Littoral Atlantique",
    },
}


# ==============================================================================
# TYPES DE CONTRAT
# ==============================================================================

TYPES_CONTRAT = {
    "bt_residentiel": {
        "label": "Basse Tension Residentiel",
        "description": "Tarification mensuelle par tranches ONEE",
        "calcul": "mensuel_tranches",
    },
    "mt_tertiaire": {
        "label": "Moyenne Tension Tertiaire",
        "description": "Tarification tri-horaire ONEE",
        "calcul": "horaire_tri_horaire",
    },
}


# ==============================================================================
# TARIFS ONEE - REFERENCES DE BASE
# ==============================================================================

# Tarifs BT residentiel indicatifs TTC selon grille ONEE.
# La logique progressive/selective doit etre implementee dans tarification_onee.py.
TARIFS_BT_RESIDENTIEL = {
    "unite": "MAD/kWh",
    "note": "Tarifs indicatifs. Verifier la grille ONEE applicable avant usage officiel.",
    "tranches": [
        {"tranche": 1, "min_kwh": 0, "max_kwh": 100, "prix_mad_kwh": 0.9010},
        {"tranche": 2, "min_kwh": 101, "max_kwh": 150, "prix_mad_kwh": 1.0732},
        {"tranche": 3, "min_kwh": 151, "max_kwh": 210, "prix_mad_kwh": 1.0732},
        {"tranche": 4, "min_kwh": 211, "max_kwh": 310, "prix_mad_kwh": 1.1676},
        {"tranche": 5, "min_kwh": 311, "max_kwh": 510, "prix_mad_kwh": 1.3817},
        {"tranche": 6, "min_kwh": 511, "max_kwh": float("inf"), "prix_mad_kwh": 1.5958},
    ],
}

# Tarifs MT tertiaire tri-horaire.
# Attention: les postes horaires ONEE sont generalement exprimes en GMT.
TARIFS_MT_TERTIAIRE = {
    "unite": "MAD/kWh",
    "heures_pointe_hiver": {"debut": 18, "fin": 20, "tarif_mad_kwh": 1.4157},
    "heures_pointe_ete": {"debut": 19, "fin": 21, "tarif_mad_kwh": 1.4157},
    "heures_pleines_hiver": [
        {"debut": 7, "fin": 17, "tarif_mad_kwh": 1.0101},
        {"debut": 20, "fin": 22, "tarif_mad_kwh": 1.0101},
    ],
    "heures_pleines_ete": [
        {"debut": 7, "fin": 18, "tarif_mad_kwh": 1.0101},
        {"debut": 21, "fin": 23, "tarif_mad_kwh": 1.0101},
    ],
    "heures_creuses": {"tarif_mad_kwh": 0.7398},
    "prime_fixe_mad_kva_an": 512.62,
}

TARIFS_INJECTION_ANRE = {
    "periode": "2026-03-01 a 2027-02-28",
    "pointe_mad_kwh": 0.21,
    "hors_pointe_mad_kwh": 0.18,
    "limite_injection_annuelle": 0.20,
    "note": "Application selon regime, niveau de tension et conditions reglementaires.",
}

MOIS_HIVER = [1, 2, 3, 11, 12]
MOIS_ETE = [4, 5, 6, 7, 8, 9, 10]


# ==============================================================================
# PARAMETRES TECHNIQUES
# ==============================================================================

@dataclass
class PanelSpecs:
    puissance_nominale_w: float = 550.0
    v_oc: float = 49.5
    i_sc: float = 13.95
    v_mp: float = 41.8
    i_mp: float = 13.16

    # Fractions par degC. Exemple: -0.0035 = -0.35%/degC.
    coef_temp_puissance: float = -0.0035
    coef_temp_voc: float = -0.0029
    coef_temp_isc: float = 0.0005

    surface_m2: float = 2.61
    rendement_stc: float = 0.211
    garantie_ans: int = 25
    degradation_annuelle: float = 0.005
    prix_unitaire_mad: float = 1200.0
    noct_c: float = 45.0
    poids_kg: float = 28.0


@dataclass
class OnduleurSpecs:
    rendement_nominal: float = 0.98
    rendement_euro: float = 0.975
    c0: float = -0.0162
    c1: float = 0.0058
    c2: float = 0.0137
    ratio_surdimensionnement: float = 1.2
    facteur_puissance: float = 0.99
    prix_par_kw_mad: float = 2500.0
    duree_vie_ans: int = 12
    garantie_ans: int = 10


@dataclass
class BatterieSpecs:
    tension_nominale_v: float = 48.0
    capacite_unitaire_ah: float = 200.0
    rendement_charge: float = 0.95
    rendement_decharge: float = 0.95
    rendement_roundtrip: float = 0.90
    dod_max: float = 0.80
    dod_recommandee: float = 0.70
    cycles_vie_100dod: int = 6000
    cycles_vie_80dod: int = 8000
    autonomie_jours: float = 2.0
    prix_par_kwh_mad: float = 3500.0
    prix_bms_mad: float = 5000.0


@dataclass
class CablageSpecs:
    resistivite_cuivre: float = 0.01724
    chute_tension_max_dc: float = 0.03
    chute_tension_max_ac: float = 0.03
    temperature_fonctionnement_c: float = 70.0
    facteur_correction_temp: float = 1.2
    sections_standard: List[float] = field(default_factory=lambda: [
        1.5, 2.5, 4, 6, 10, 16, 25, 35, 50, 70, 95, 120, 150, 185, 240
    ])
    prix_cable_dc_par_mm2: float = 0.5
    prix_base_dc: float = 10.0
    prix_cable_ac_par_mm2: float = 0.4
    prix_base_ac: float = 8.0


@dataclass
class ParametresEconomiques:
    augmentation_tarif_elec: float = 0.035
    taux_actualisation: float = 0.06
    taux_inflation: float = 0.025
    duree_projet_ans: int = 25

    cout_maintenance_pct_capex: float = 0.01
    cout_nettoyage_annuel_mad: float = 2000.0
    cout_inspection_annuel_mad: float = 1500.0

    pct_structure_montage: float = 0.15
    pct_main_oeuvre: float = 0.20
    pct_etudes_ingenierie: float = 0.05
    cout_raccordement_ongrid_mad: float = 8000.0
    cout_raccordement_offgrid_mad: float = 3000.0
    pct_contingence: float = 0.10
    tva: float = 0.20


@dataclass
class ParametresEnvironnementaux:
    emission_co2_kwh: float = 0.721
    absorption_arbre_kg_co2_an: float = 50.0
    emission_voiture_kg_co2_an: float = 2300.0
    emission_fabrication_kg_co2_kwc: float = 500.0
    soiling_loss_maroc: float = 0.05
    frequence_nettoyage_jours: int = 15


@dataclass
class ParametresCalcul:
    heures_annee: int = 8760
    jours_annee: int = 365
    temperature_stc_c: float = 25.0
    irradiance_stc_w_m2: float = 1000.0
    facteur_pertes_base: float = 0.85
    taux_autoconso_min: float = 0.30
    inclinaison_optimale_deg: float = 30.0
    azimut_optimal_deg: float = 0.0


# ==============================================================================
# CONFIGURATION MANAGER
# ==============================================================================

class ConfigurationManager:
    def __init__(self):
        self.panel = PanelSpecs()
        self.onduleur = OnduleurSpecs()
        self.batterie = BatterieSpecs()
        self.cablage = CablageSpecs()
        self.economie = ParametresEconomiques()
        self.environnement = ParametresEnvironnementaux()
        self.calcul = ParametresCalcul()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "panel": asdict(self.panel),
            "onduleur": asdict(self.onduleur),
            "batterie": asdict(self.batterie),
            "cablage": asdict(self.cablage),
            "economie": asdict(self.economie),
            "environnement": asdict(self.environnement),
            "calcul": asdict(self.calcul),
        }

    def from_dict(self, config_dict: Dict[str, Any]):
        if "panel" in config_dict:
            self.panel = PanelSpecs(**config_dict["panel"])
        if "onduleur" in config_dict:
            self.onduleur = OnduleurSpecs(**config_dict["onduleur"])
        if "batterie" in config_dict:
            self.batterie = BatterieSpecs(**config_dict["batterie"])
        if "cablage" in config_dict:
            self.cablage = CablageSpecs(**config_dict["cablage"])
        if "economie" in config_dict:
            self.economie = ParametresEconomiques(**config_dict["economie"])
        if "environnement" in config_dict:
            self.environnement = ParametresEnvironnementaux(**config_dict["environnement"])
        if "calcul" in config_dict:
            self.calcul = ParametresCalcul(**config_dict["calcul"])

    def save_to_file(self, filepath: str):
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    def load_from_file(self, filepath: str):
        with open(filepath, "r", encoding="utf-8") as f:
            self.from_dict(json.load(f))


# ==============================================================================
# REFERENCES REGLEMENTAIRES INDICATIVES
# ==============================================================================

NORMES_MAROC = {
    "loi_82_21": {
        "titre": "Loi n 82-21 sur l'autoproduction d'electricite",
        "limite_injection": 0.20,
        "seuils_puissance": {
            "declaration": {"min": 0, "max": 11, "unite": "kW", "delai_jours": 15},
            "accord_raccordement": {"min": 11, "max": 5000, "unite": "kW", "delai_jours": 30},
            "autorisation": {"min": 5000, "max": float("inf"), "unite": "kW", "delai_jours": 90},
        },
    },
    "decret_2_25_100": {
        "titre": "Decret n 2-25-100",
        "date_vigueur": "2026-06-09",
        "delai_regularisation_jours": 90,
    },
    "anre_04_26": {
        "titre": "Decision ANRE n 04/26",
        "periode": "2026-03-01 a 2027-02-28",
        "tarif_injection_pointe": 0.21,
        "tarif_injection_hors_pointe": 0.18,
    },
    "references_techniques": {
        "nfc_15_100": "Installations electriques basse tension",
        "nfc_15_712_1": "Installations photovoltaiques raccordees au reseau",
        "iec_62446": "Documentation, essais et inspection systemes PV",
        "iso_50001": "Systeme de management de l'energie",
        "rtcm": "Reglement thermique de construction au Maroc",
    },
}


# ==============================================================================
# FONCTIONS UTILITAIRES
# ==============================================================================

def est_hiver(mois: int) -> bool:
    return mois in MOIS_HIVER


def get_regime_legal(puissance_kwc: float) -> Dict[str, Any]:
    if puissance_kwc <= 0:
        raise ValueError("La puissance doit etre strictement positive.")

    seuils = NORMES_MAROC["loi_82_21"]["seuils_puissance"]

    if puissance_kwc <= seuils["declaration"]["max"]:
        return {
            "regime": "Declaration",
            "delai_jours": seuils["declaration"]["delai_jours"],
            "procedure": "Procedure simplifiee selon cas de raccordement",
        }

    if puissance_kwc <= seuils["accord_raccordement"]["max"]:
        return {
            "regime": "Accord de raccordement",
            "delai_jours": seuils["accord_raccordement"]["delai_jours"],
            "procedure": "Dossier technique et etude de raccordement",
        }

    return {
        "regime": "Autorisation",
        "delai_jours": seuils["autorisation"]["delai_jours"],
        "procedure": "Procedure complete avec etudes complementaires",
    }


def get_type_heure_onee_mt(heure: int, mois: int) -> str:
    if not 0 <= heure <= 23:
        raise ValueError("heure doit etre entre 0 et 23.")
    if not 1 <= mois <= 12:
        raise ValueError("mois doit etre entre 1 et 12.")

    if est_hiver(mois):
        if 18 <= heure < 20:
            return "Pointe"
        if 7 <= heure < 17 or 20 <= heure < 22:
            return "Pleine"
        return "Creuse"

    if 19 <= heure < 21:
        return "Pointe"
    if 7 <= heure < 18 or 21 <= heure < 23:
        return "Pleine"
    return "Creuse"


def calculer_tarif_horaire_onee_mt(heure: int, mois: int) -> float:
    type_heure = get_type_heure_onee_mt(heure, mois)

    if type_heure == "Pointe":
        if est_hiver(mois):
            return TARIFS_MT_TERTIAIRE["heures_pointe_hiver"]["tarif_mad_kwh"]
        return TARIFS_MT_TERTIAIRE["heures_pointe_ete"]["tarif_mad_kwh"]

    if type_heure == "Pleine":
        if est_hiver(mois):
            return TARIFS_MT_TERTIAIRE["heures_pleines_hiver"][0]["tarif_mad_kwh"]
        return TARIFS_MT_TERTIAIRE["heures_pleines_ete"][0]["tarif_mad_kwh"]

    return TARIFS_MT_TERTIAIRE["heures_creuses"]["tarif_mad_kwh"]


def get_tarif_injection(heure: int, mois: int) -> float:
    type_heure = get_type_heure_onee_mt(heure, mois)

    if type_heure == "Pointe":
        return TARIFS_INJECTION_ANRE["pointe_mad_kwh"]

    return TARIFS_INJECTION_ANRE["hors_pointe_mad_kwh"]


def get_ville_config(ville: str) -> Dict[str, Any]:
    if ville not in VILLES_MAROC:
        villes = ", ".join(VILLES_MAROC.keys())
        raise ValueError(f"Ville inconnue: {ville}. Villes disponibles: {villes}")

    return VILLES_MAROC[ville]
