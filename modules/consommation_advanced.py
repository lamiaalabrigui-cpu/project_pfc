"""
Module Consommation Avance - Opti-Solar Maroc

Objectif:
- Importer des historiques de consommation CSV/Excel
- Reconnaitre compteur intelligent, analyseur reseau ou fichier simple
- Detecter les colonnes en francais/anglais
- Detecter le pas de temps
- Convertir tout vers une courbe horaire standard:
    DateTime, Consommation_kWh
- Generer un diagnostic qualite pour le rapport PDF

Conventions:
- Consommation_kWh = energie consommee pendant l'heure
- Si la source donne une puissance moyenne kW, conversion:
    Energie_kWh = P_kW * duree_pas_h
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import re
import unicodedata

import numpy as np
import pandas as pd


# ==============================================================================
# OUTILS DE NORMALISATION COLONNES
# ==============================================================================

def normaliser_nom_colonne(col: str) -> str:
    col = str(col).strip().lower()
    col = unicodedata.normalize("NFKD", col)
    col = "".join(c for c in col if not unicodedata.combining(c))
    col = re.sub(r"[^a-z0-9]+", " ", col)
    return col.strip()


COLUMN_ALIASES = {
    "datetime": [
        "datetime", "date time", "timestamp", "horodatage", "date heure",
        "date", "temps", "time", "date et heure", "date heure locale",
    ],
    "energy_import_kwh": [
        "energie import kwh", "energie importee kwh", "energie active importee",
        "energie active importee kwh", "energie active plus", "energie active",
        "active energy import", "import energy", "import kwh", "kwh import",
        "energie kwh", "consommation kwh", "conso kwh", "energie active kwh",
        "energie active plus kwh", "a plus", "e active plus",
    ],
    "index_import_kwh": [
        "index import kwh", "index import", "index energie", "index compteur",
        "index kwh", "compteur kwh", "meter index", "cumulative energy",
        "cumulative kwh", "index a plus", "index active energy",
    ],
    "power_kw": [
        "puissance kw", "puissance active", "puissance active totale",
        "p total kw", "p total", "p total kw", "p kw", "p total kw",
        "p total active", "kw", "active power", "total active power",
        "power kw", "puissance moyenne kw", "p_total_kw",
    ],
    "reactive_power_kvar": [
        "puissance reactive", "puissance reactive kvar", "q total",
        "q total kvar", "q kvar", "kvar", "reactive power",
        "reactive power kvar", "q_total_kvar",
    ],
    "apparent_power_kva": [
        "puissance apparente", "puissance apparente kva", "s total",
        "s total kva", "s kva", "kva", "apparent power",
        "apparent power kva", "s_total_kva",
    ],
    "power_factor": [
        "pf", "cos phi", "cosphi", "facteur puissance",
        "facteur de puissance", "power factor",
    ],
    "voltage": [
        "v", "voltage", "tension", "v l1", "v l2", "v l3",
        "v1", "v2", "v3", "u1", "u2", "u3",
    ],
    "current": [
        "i", "current", "courant", "i l1", "i l2", "i l3",
        "i1", "i2", "i3",
    ],
    "thd": [
        "thd", "thd v", "thd i", "thd voltage", "thd current",
        "distorsion harmonique",
    ],
}


def trouver_colonne(df: pd.DataFrame, alias_key: str) -> Optional[str]:
    noms_normalises = {col: normaliser_nom_colonne(col) for col in df.columns}
    aliases = [normaliser_nom_colonne(a) for a in COLUMN_ALIASES[alias_key]]

    for col, norm in noms_normalises.items():
        if norm in aliases:
            return col

    for col, norm in noms_normalises.items():
        for alias in aliases:
            if alias and alias in norm:
                return col

    return None


def detecter_colonnes_reseau(df: pd.DataFrame) -> Dict[str, List[str]]:
    colonnes_norm = {col: normaliser_nom_colonne(col) for col in df.columns}

    result = {
        "reactive_power": [],
        "apparent_power": [],
        "power_factor": [],
        "voltage": [],
        "current": [],
        "thd": [],
    }

    for col, norm in colonnes_norm.items():
        if any(a in norm for a in [normaliser_nom_colonne(x) for x in COLUMN_ALIASES["reactive_power_kvar"]]):
            result["reactive_power"].append(col)
        if any(a in norm for a in [normaliser_nom_colonne(x) for x in COLUMN_ALIASES["apparent_power_kva"]]):
            result["apparent_power"].append(col)
        if any(a in norm for a in [normaliser_nom_colonne(x) for x in COLUMN_ALIASES["power_factor"]]):
            result["power_factor"].append(col)
        if any(a in norm for a in [normaliser_nom_colonne(x) for x in COLUMN_ALIASES["voltage"]]):
            result["voltage"].append(col)
        if any(a in norm for a in [normaliser_nom_colonne(x) for x in COLUMN_ALIASES["current"]]):
            result["current"].append(col)
        if any(a in norm for a in [normaliser_nom_colonne(x) for x in COLUMN_ALIASES["thd"]]):
            result["thd"].append(col)

    return result


# ==============================================================================
# DIAGNOSTIC
# ==============================================================================

@dataclass
class DiagnosticConsommation:
    source_detectee: str
    mesure_detectee: str
    colonne_datetime: str
    colonne_principale: str
    pas_detecte: str
    pas_minutes: float
    nombre_lignes_original: int
    nombre_lignes_valides: int
    nombre_lignes_horaires: int
    date_debut: str
    date_fin: str
    doublons_datetime: int
    valeurs_manquantes: int
    valeurs_negatives: int
    trous_temporels_detectes: int
    consommation_totale_kwh: float
    puissance_max_kw_estimee: float
    facteur_charge: float
    qualite: str
    messages: List[str]
    colonnes_reseau: Dict[str, List[str]]


# ==============================================================================
# MANAGER
# ==============================================================================

class ConsommationManager:
    def __init__(self):
        self.profil_horaire: Optional[pd.DataFrame] = None
        self.diagnostic: Optional[DiagnosticConsommation] = None
        self.donnees_reseau_horaire: Optional[pd.DataFrame] = None

    # --------------------------------------------------------------------------
    # IMPORT HISTORIQUE
    # --------------------------------------------------------------------------

    def charger_historique(
        self,
        fichier: str | Path,
        source: str = "auto",
        type_mesure: str = "auto",
        colonne_datetime: Optional[str] = None,
        colonne_valeur: Optional[str] = None,
        dayfirst: bool = True,
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """
        Charge un historique CSV/Excel et retourne un profil horaire.

        Args:
            fichier: chemin CSV/XLSX
            source: auto, compteur_intelligent, analyseur_reseau, fichier_simple
            type_mesure: auto, energie_periode_kwh, index_cumule_kwh,
                         puissance_moyenne_kw, puissance_instantanee_kw
            colonne_datetime: optionnel si detection auto echoue
            colonne_valeur: optionnel si detection auto echoue
            dayfirst: format date JJ/MM/AAAA prioritaire

        Returns:
            (profil_horaire, diagnostic_dict)
        """
        fichier = Path(fichier)
        df_original = self._lire_fichier(fichier)
        nombre_lignes_original = len(df_original)

        df = df_original.copy()
        df.columns = [str(c).strip() for c in df.columns]

        dt_col = colonne_datetime or trouver_colonne(df, "datetime")
        if dt_col is None:
            raise ValueError("Colonne DateTime introuvable. Precisez colonne_datetime.")

        df["DateTime"] = pd.to_datetime(df[dt_col], dayfirst=dayfirst, errors="coerce")
        if df["DateTime"].isna().mean() > 0.1:
            df["DateTime"] = pd.to_datetime(df[dt_col], dayfirst=not dayfirst, errors="coerce")

        source_detectee = self._detecter_source(df, source)
        mesure_detectee, value_col = self._detecter_mesure(df, type_mesure, colonne_valeur)

        if value_col is None:
            raise ValueError("Colonne de consommation/puissance introuvable. Precisez colonne_valeur.")

        df["_valeur"] = pd.to_numeric(df[value_col], errors="coerce")

        valeurs_manquantes = int(df["DateTime"].isna().sum() + df["_valeur"].isna().sum())
        valeurs_negatives = int((df["_valeur"] < 0).sum())

        df = df.dropna(subset=["DateTime", "_valeur"]).copy()
        df = df.sort_values("DateTime")

        doublons = int(df["DateTime"].duplicated().sum())
        if doublons > 0:
            df = df.groupby("DateTime", as_index=False)["_valeur"].mean()

        pas_minutes = self._detecter_pas_minutes(df["DateTime"])
        pas_label = self._format_pas(pas_minutes)
        trous = self._compter_trous_temporels(df["DateTime"], pas_minutes)

        df_energie = self._convertir_en_energie_par_pas(df, mesure_detectee, pas_minutes)
        profil_horaire = self._agreger_horaire(df_energie)

        profil_horaire = profil_horaire.rename(columns={"Energie_kWh": "Consommation_kWh"})
        profil_horaire["Consommation_kWh"] = profil_horaire["Consommation_kWh"].clip(lower=0)

        puissance_max_kw = float(profil_horaire["Consommation_kWh"].max())
        conso_totale = float(profil_horaire["Consommation_kWh"].sum())
        puissance_moy_kw = float(profil_horaire["Consommation_kWh"].mean())
        facteur_charge = puissance_moy_kw / puissance_max_kw if puissance_max_kw > 0 else 0.0

        colonnes_reseau = detecter_colonnes_reseau(df_original)
        self.donnees_reseau_horaire = self._extraire_donnees_reseau_horaires(df_original, dt_col, dayfirst)

        messages = self._generer_messages_qualite(
            nombre_lignes_original=nombre_lignes_original,
            lignes_valides=len(df),
            lignes_horaires=len(profil_horaire),
            valeurs_manquantes=valeurs_manquantes,
            valeurs_negatives=valeurs_negatives,
            doublons=doublons,
            trous=trous,
            pas_minutes=pas_minutes,
        )
        qualite = self._evaluer_qualite(valeurs_manquantes, valeurs_negatives, doublons, trous, len(df))

        diagnostic = DiagnosticConsommation(
            source_detectee=source_detectee,
            mesure_detectee=mesure_detectee,
            colonne_datetime=dt_col,
            colonne_principale=value_col,
            pas_detecte=pas_label,
            pas_minutes=float(pas_minutes),
            nombre_lignes_original=nombre_lignes_original,
            nombre_lignes_valides=len(df),
            nombre_lignes_horaires=len(profil_horaire),
            date_debut=str(profil_horaire["DateTime"].min()),
            date_fin=str(profil_horaire["DateTime"].max()),
            doublons_datetime=doublons,
            valeurs_manquantes=valeurs_manquantes,
            valeurs_negatives=valeurs_negatives,
            trous_temporels_detectes=trous,
            consommation_totale_kwh=round(conso_totale, 2),
            puissance_max_kw_estimee=round(puissance_max_kw, 2),
            facteur_charge=round(facteur_charge, 3),
            qualite=qualite,
            messages=messages,
            colonnes_reseau=colonnes_reseau,
        )

        self.profil_horaire = profil_horaire
        self.diagnostic = diagnostic

        return profil_horaire, asdict(diagnostic)

    def _lire_fichier(self, fichier: Path) -> pd.DataFrame:
        if not fichier.exists():
            raise FileNotFoundError(f"Fichier introuvable: {fichier}")

        suffix = fichier.suffix.lower()

        if suffix in [".xlsx", ".xls"]:
            return pd.read_excel(fichier)

        if suffix in [".csv", ".txt"]:
            return pd.read_csv(fichier)

        raise ValueError("Format non supporte. Utiliser CSV, TXT, XLSX ou XLS.")

    def _detecter_source(self, df: pd.DataFrame, source: str) -> str:
        if source != "auto":
            return source

        colonnes_reseau = detecter_colonnes_reseau(df)
        nb_reseau = sum(len(v) for v in colonnes_reseau.values())

        if nb_reseau >= 3:
            return "analyseur_reseau"

        if trouver_colonne(df, "index_import_kwh") or trouver_colonne(df, "energy_import_kwh"):
            return "compteur_intelligent"

        return "fichier_simple"

    def _detecter_mesure(
        self,
        df: pd.DataFrame,
        type_mesure: str,
        colonne_valeur: Optional[str],
    ) -> Tuple[str, Optional[str]]:
        if colonne_valeur is not None:
            if type_mesure == "auto":
                norm = normaliser_nom_colonne(colonne_valeur)
                if "index" in norm:
                    return "index_cumule_kwh", colonne_valeur
                if "kw" in norm and "kwh" not in norm:
                    return "puissance_moyenne_kw", colonne_valeur
                return "energie_periode_kwh", colonne_valeur
            return type_mesure, colonne_valeur

        if type_mesure == "index_cumule_kwh":
            return type_mesure, trouver_colonne(df, "index_import_kwh")
        if type_mesure == "energie_periode_kwh":
            return type_mesure, trouver_colonne(df, "energy_import_kwh")
        if type_mesure in ["puissance_moyenne_kw", "puissance_instantanee_kw"]:
            return type_mesure, trouver_colonne(df, "power_kw")

        index_col = trouver_colonne(df, "index_import_kwh")
        energy_col = trouver_colonne(df, "energy_import_kwh")
        power_col = trouver_colonne(df, "power_kw")

        if energy_col is not None:
            return "energie_periode_kwh", energy_col
        if index_col is not None:
            return "index_cumule_kwh", index_col
        if power_col is not None:
            return "puissance_moyenne_kw", power_col

        return "inconnu", None

    def _detecter_pas_minutes(self, datetimes: pd.Series) -> float:
        deltas = datetimes.sort_values().diff().dropna()
        if deltas.empty:
            raise ValueError("Impossible de detecter le pas de temps: moins de 2 dates valides.")

        pas = deltas.median()
        return pas.total_seconds() / 60

    def _format_pas(self, pas_minutes: float) -> str:
        if abs(pas_minutes - 60) < 0.01:
            return "1H"
        if pas_minutes < 60:
            return f"{pas_minutes:g}min"
        return f"{pas_minutes / 60:g}H"

    def _compter_trous_temporels(self, datetimes: pd.Series, pas_minutes: float) -> int:
        deltas = datetimes.sort_values().diff().dropna()
        expected = pd.Timedelta(minutes=pas_minutes)
        return int((deltas > expected * 1.5).sum())

    def _convertir_en_energie_par_pas(
        self,
        df: pd.DataFrame,
        mesure_detectee: str,
        pas_minutes: float,
    ) -> pd.DataFrame:
        df = df[["DateTime", "_valeur"]].copy()
        duree_h = pas_minutes / 60

        if mesure_detectee == "energie_periode_kwh":
            df["Energie_kWh"] = df["_valeur"]

        elif mesure_detectee == "index_cumule_kwh":
            df["Energie_kWh"] = df["_valeur"].diff()
            df = df.dropna(subset=["Energie_kWh"])
            df["Energie_kWh"] = df["Energie_kWh"].clip(lower=0)

        elif mesure_detectee in ["puissance_moyenne_kw", "puissance_instantanee_kw"]:
            df["Energie_kWh"] = df["_valeur"] * duree_h

        else:
            raise ValueError(f"Type de mesure non reconnu: {mesure_detectee}")

        return df[["DateTime", "Energie_kWh"]]

    def _agreger_horaire(self, df_energie: pd.DataFrame) -> pd.DataFrame:
        df = df_energie.set_index("DateTime").sort_index()
        hourly = df["Energie_kWh"].resample("h").sum().reset_index()
        hourly = hourly.dropna(subset=["DateTime"])
        return hourly

    def _extraire_donnees_reseau_horaires(
        self,
        df_original: pd.DataFrame,
        dt_col: str,
        dayfirst: bool,
    ) -> Optional[pd.DataFrame]:
        colonnes_reseau = detecter_colonnes_reseau(df_original)
        cols = []

        for values in colonnes_reseau.values():
            cols.extend(values)

        # Supprimer les doublons et ne jamais reprendre la colonne DateTime
        cols = [c for c in dict.fromkeys(cols) if c != dt_col]

        if not cols:
            return None

        df = df_original[[dt_col] + cols].copy()
        df["DateTime"] = pd.to_datetime(df[dt_col], dayfirst=dayfirst, errors="coerce")
        df = df.dropna(subset=["DateTime"]).copy()

        for col in cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        hourly = df.set_index("DateTime")[cols].resample("h").mean().reset_index()
        return hourly


    def _generer_messages_qualite(
        self,
        nombre_lignes_original: int,
        lignes_valides: int,
        lignes_horaires: int,
        valeurs_manquantes: int,
        valeurs_negatives: int,
        doublons: int,
        trous: int,
        pas_minutes: float,
    ) -> List[str]:
        messages = [
            f"Pas de temps detecte: {self._format_pas(pas_minutes)}.",
            f"Conversion effectuee vers profil horaire: {lignes_horaires} heures.",
        ]

        if valeurs_manquantes:
            messages.append(f"{valeurs_manquantes} valeurs manquantes ou dates invalides ignorees.")
        if valeurs_negatives:
            messages.append(f"{valeurs_negatives} valeurs negatives detectees.")
        if doublons:
            messages.append(f"{doublons} doublons DateTime agreges par moyenne.")
        if trous:
            messages.append(f"{trous} trou(s) temporel(s) detecte(s).")

        if lignes_valides < nombre_lignes_original:
            messages.append(f"{nombre_lignes_original - lignes_valides} ligne(s) supprimee(s) lors du nettoyage.")

        return messages

    def _evaluer_qualite(
        self,
        valeurs_manquantes: int,
        valeurs_negatives: int,
        doublons: int,
        trous: int,
        lignes_valides: int,
    ) -> str:
        if lignes_valides == 0:
            return "invalide"

        score_penalite = 0
        score_penalite += min(40, valeurs_manquantes / max(lignes_valides, 1) * 100)
        score_penalite += min(20, valeurs_negatives / max(lignes_valides, 1) * 100)
        score_penalite += min(20, doublons / max(lignes_valides, 1) * 100)
        score_penalite += min(20, trous)

        if score_penalite < 5:
            return "bonne"
        if score_penalite < 20:
            return "moyenne"
        return "faible"

    # --------------------------------------------------------------------------
    # INVENTAIRE EQUIPEMENTS
    # --------------------------------------------------------------------------

    def creer_depuis_equipements(
        self,
        liste_equipements: List[Dict[str, Any]],
        annee: int = 2025,
    ) -> pd.DataFrame:
        """
        Cree un profil horaire a partir d'un inventaire d'equipements.

        Chaque equipement:
            nom: str
            puissance_w: float
            nombre: int
            plages_horaires: [(debut, fin), ...]
            jours_semaine: [0..6]
            facteur_usage: 0..1 optionnel
        """
        dates = pd.date_range(start=f"{annee}-01-01 00:00", end=f"{annee}-12-31 23:00", freq="h")
        if len(dates) == 8784:
            dates = dates[~((dates.month == 2) & (dates.day == 29))]

        df = pd.DataFrame({"DateTime": dates})
        df["Consommation_kWh"] = 0.0

        heures = df["DateTime"].dt.hour
        jours = df["DateTime"].dt.weekday

        for equip in liste_equipements:
            puissance_kw = (float(equip.get("puissance_w", 0)) * int(equip.get("nombre", 1))) / 1000
            facteur_usage = float(equip.get("facteur_usage", 1.0))
            plages = equip.get("plages_horaires", [(0, 24)])
            jours_actifs = equip.get("jours_semaine", list(range(7)))

            masque_jour = jours.isin(jours_actifs)
            masque_heure_total = pd.Series(False, index=df.index)

            for debut, fin in plages:
                debut = int(debut)
                fin = int(fin)

                if debut < fin:
                    masque_heure = (heures >= debut) & (heures < fin)
                else:
                    masque_heure = (heures >= debut) | (heures < fin)

                masque_heure_total = masque_heure_total | masque_heure

            masque = masque_jour & masque_heure_total
            df.loc[masque, "Consommation_kWh"] += puissance_kw * facteur_usage

        self.profil_horaire = df

        self.diagnostic = DiagnosticConsommation(
            source_detectee="inventaire_equipements",
            mesure_detectee="puissance_installee_convertie_horaire",
            colonne_datetime="DateTime",
            colonne_principale="inventaire",
            pas_detecte="1H",
            pas_minutes=60.0,
            nombre_lignes_original=len(df),
            nombre_lignes_valides=len(df),
            nombre_lignes_horaires=len(df),
            date_debut=str(df["DateTime"].min()),
            date_fin=str(df["DateTime"].max()),
            doublons_datetime=0,
            valeurs_manquantes=0,
            valeurs_negatives=0,
            trous_temporels_detectes=0,
            consommation_totale_kwh=round(float(df["Consommation_kWh"].sum()), 2),
            puissance_max_kw_estimee=round(float(df["Consommation_kWh"].max()), 2),
            facteur_charge=round(
                float(df["Consommation_kWh"].mean() / df["Consommation_kWh"].max())
                if df["Consommation_kWh"].max() > 0 else 0,
                3,
            ),
            qualite="bonne",
            messages=["Profil genere depuis inventaire d'equipements."],
            colonnes_reseau={},
        )

        return df

    # --------------------------------------------------------------------------
    # STATISTIQUES
    # --------------------------------------------------------------------------

    def get_statistiques(self) -> Dict[str, Any]:
        if self.profil_horaire is None:
            return {}

        conso = self.profil_horaire["Consommation_kWh"]

        stats = {
            "consommation_annuelle_kwh": round(float(conso.sum()), 2),
            "puissance_moyenne_kw": round(float(conso.mean()), 2),
            "puissance_max_kw": round(float(conso.max()), 2),
            "puissance_min_kw": round(float(conso.min()), 2),
            "facteur_charge": round(float(conso.mean() / conso.max()), 3) if conso.max() > 0 else 0,
        }

        if self.diagnostic:
            stats["diagnostic"] = asdict(self.diagnostic)

        return stats

    def get_profil_journalier_moyen(self) -> pd.DataFrame:
        if self.profil_horaire is None:
            return pd.DataFrame()

        df = self.profil_horaire.copy()
        df["Heure"] = df["DateTime"].dt.hour

        return df.groupby("Heure").agg({
            "Consommation_kWh": "mean",
        }).reset_index().rename(columns={"Consommation_kWh": "Consommation_Moyenne_kWh"})

    def get_consommation_mensuelle(self) -> pd.DataFrame:
        if self.profil_horaire is None:
            return pd.DataFrame()

        df = self.profil_horaire.copy()
        df["Mois"] = df["DateTime"].dt.month

        return df.groupby("Mois").agg({
            "Consommation_kWh": "sum",
        }).reset_index()

    def analyser_talon_consommation(self) -> Dict[str, Any]:
        if self.profil_horaire is None:
            return {}

        df = self.profil_horaire.copy()
        df["Heure"] = df["DateTime"].dt.hour

        conso_nuit = df[df["Heure"].between(0, 5)]["Consommation_kWh"].sum()
        conso_totale = df["Consommation_kWh"].sum()
        pct_nuit = conso_nuit / conso_totale * 100 if conso_totale > 0 else 0

        talon_moyen_kw = df[df["Heure"].between(0, 5)]["Consommation_kWh"].mean()
        moyenne_globale_kw = df["Consommation_kWh"].mean()
        ratio_talon_moyenne = talon_moyen_kw / moyenne_globale_kw if moyenne_globale_kw > 0 else 0

        return {
            "consommation_nuit_00_05_kwh": round(float(conso_nuit), 2),
            "pct_consommation_nuit": round(float(pct_nuit), 2),
            "talon_moyen_kw": round(float(talon_moyen_kw), 2),
            "moyenne_globale_kw": round(float(moyenne_globale_kw), 2),
            "ratio_talon_moyenne": round(float(ratio_talon_moyenne), 3),
            "alerte_talon": ratio_talon_moyenne > 0.20,
        }


# ==============================================================================
# EXEMPLES INVENTAIRE
# ==============================================================================

def exemple_equipements_residentiel() -> List[Dict[str, Any]]:
    return [
        {
            "nom": "Eclairage domestique",
            "puissance_w": 60,
            "nombre": 20,
            "plages_horaires": [(6, 8), (18, 23)],
            "jours_semaine": list(range(7)),
            "facteur_usage": 0.6,
        },
        {
            "nom": "Refrigerateur",
            "puissance_w": 180,
            "nombre": 1,
            "plages_horaires": [(0, 24)],
            "jours_semaine": list(range(7)),
            "facteur_usage": 0.35,
        },
        {
            "nom": "Climatisation",
            "puissance_w": 1200,
            "nombre": 3,
            "plages_horaires": [(14, 23)],
            "jours_semaine": list(range(7)),
            "facteur_usage": 0.45,
        },
        {
            "nom": "Chauffe-eau electrique",
            "puissance_w": 2000,
            "nombre": 1,
            "plages_horaires": [(5, 7), (20, 22)],
            "jours_semaine": list(range(7)),
            "facteur_usage": 0.7,
        },
    ]


def exemple_equipements_tertiaire() -> List[Dict[str, Any]]:
    return [
        {
            "nom": "Eclairage bureaux LED",
            "puissance_w": 80,
            "nombre": 120,
            "plages_horaires": [(8, 19)],
            "jours_semaine": [0, 1, 2, 3, 4],
            "facteur_usage": 0.8,
        },
        {
            "nom": "Ordinateurs et ecrans",
            "puissance_w": 150,
            "nombre": 100,
            "plages_horaires": [(8, 18)],
            "jours_semaine": [0, 1, 2, 3, 4],
            "facteur_usage": 0.75,
        },
        {
            "nom": "Climatisation bureaux",
            "puissance_w": 2500,
            "nombre": 8,
            "plages_horaires": [(9, 19)],
            "jours_semaine": [0, 1, 2, 3, 4],
            "facteur_usage": 0.55,
        },
        {
            "nom": "Serveurs informatiques",
            "puissance_w": 800,
            "nombre": 5,
            "plages_horaires": [(0, 24)],
            "jours_semaine": list(range(7)),
            "facteur_usage": 1.0,
        },
    ]
