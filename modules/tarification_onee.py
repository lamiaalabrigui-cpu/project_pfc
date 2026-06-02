"""
Module Tarification ONEE - Opti-Solar Maroc

Objectif:
- Calculer les factures selon le type de contrat:
  1. BT Residentiel: facture mensuelle par tranches
  2. MT Tertiaire: tri-horaire Pointe/Pleine/Creuse

Important:
Les tarifs doivent rester configurables et verifies avant usage officiel.
Ce module est destine au pre-dimensionnement et a la comparaison avant/apres PV.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Tuple, Optional

import numpy as np
import pandas as pd

from modules.config_advanced import (
    TARIFS_BT_RESIDENTIEL,
    TARIFS_MT_TERTIAIRE,
    TARIFS_INJECTION_ANRE,
    MOIS_HIVER,
)


# ==============================================================================
# OUTILS
# ==============================================================================

def _verifier_mois(mois: int):
    if not 1 <= mois <= 12:
        raise ValueError("mois doit etre entre 1 et 12.")


def _verifier_heure(heure: int):
    if not 0 <= heure <= 23:
        raise ValueError("heure doit etre entre 0 et 23.")


def _est_hiver(mois: int) -> bool:
    return mois in MOIS_HIVER


def _dans_plage(heure: int, debut: int, fin: int) -> bool:
    if debut < fin:
        return debut <= heure < fin
    return heure >= debut or heure < fin


# ==============================================================================
# RESULTATS
# ==============================================================================

@dataclass
class FactureMensuelleResidentiel:
    mois: int
    consommation_kwh: float
    tranche_atteinte: int
    mode_facturation: str
    cout_energie_mad: float
    total_mad: float
    detail_tranches: List[Dict[str, Any]]


@dataclass
class FactureMensuelleTertiaire:
    mois: int
    saison: str
    consommation_pointe_kwh: float
    consommation_pleine_kwh: float
    consommation_creuse_kwh: float
    cout_pointe_mad: float
    cout_pleine_mad: float
    cout_creuse_mad: float
    cout_energie_mad: float
    prime_puissance_mad: float
    total_mad: float


# ==============================================================================
# CLASSE PRINCIPALE
# ==============================================================================

class TarificationONEE:
    """
    Gestionnaire de tarification ONEE.
    """

    def __init__(
        self,
        type_contrat: str,
        appliquer_taxes: bool = False,
        timezone_data: str = "UTC+01:00",
        postes_onee_gmt: bool = True,
    ):
        """
        Args:
            type_contrat:
                - bt_residentiel / residentiel
                - mt_tertiaire / tertiaire
            appliquer_taxes:
                False par defaut car les tarifs config sont souvent TTC.
            timezone_data:
                Timezone des donnees de consommation.
            postes_onee_gmt:
                Si True, decale les heures UTC+01 vers GMT pour classer les postes MT.
        """
        type_contrat = type_contrat.lower().strip()

        aliases = {
            "residentiel": "bt_residentiel",
            "bt": "bt_residentiel",
            "bt_residentiel": "bt_residentiel",
            "basse tension residentiel": "bt_residentiel",
            "tertiaire": "mt_tertiaire",
            "mt": "mt_tertiaire",
            "mt_tertiaire": "mt_tertiaire",
            "moyenne tension tertiaire": "mt_tertiaire",
        }

        if type_contrat not in aliases:
            raise ValueError("type_contrat doit etre residentiel/bt_residentiel ou tertiaire/mt_tertiaire.")

        self.type_contrat = aliases[type_contrat]
        self.appliquer_taxes = appliquer_taxes
        self.timezone_data = timezone_data
        self.postes_onee_gmt = postes_onee_gmt

    # --------------------------------------------------------------------------
    # BT RESIDENTIEL
    # --------------------------------------------------------------------------

    def calculer_facture_mensuelle_residentiel(
        self,
        consommation_kwh: float,
        mois: int = 1,
        facteur_tarif: float = 1.0,
    ) -> Dict[str, Any]:
        """
        Calcule facture residentielle mensuelle.

        Logique retenue:
        - 0 a 100 kWh: tranche 1
        - 101 a 150 kWh: progressif T1 + T2
        - >150 kWh: mode selectif, toute la consommation est facturee
          au prix de la tranche atteinte.
        """
        _verifier_mois(mois)

        conso = max(0.0, float(consommation_kwh))
        tranches = TARIFS_BT_RESIDENTIEL["tranches"]

        if conso <= 100:
            t = tranches[0]
            cout = conso * t["prix_mad_kwh"] * facteur_tarif
            detail = [{
                "tranche": 1,
                "kwh": round(conso, 3),
                "prix_mad_kwh": round(t["prix_mad_kwh"] * facteur_tarif, 4),
                "cout_mad": round(cout, 2),
            }]
            tranche_atteinte = 1
            mode = "progressif"

        elif conso <= 150:
            t1 = tranches[0]
            t2 = tranches[1]
            kwh_t1 = 100
            kwh_t2 = conso - 100
            cout_t1 = kwh_t1 * t1["prix_mad_kwh"] * facteur_tarif
            cout_t2 = kwh_t2 * t2["prix_mad_kwh"] * facteur_tarif
            cout = cout_t1 + cout_t2
            detail = [
                {
                    "tranche": 1,
                    "kwh": round(kwh_t1, 3),
                    "prix_mad_kwh": round(t1["prix_mad_kwh"] * facteur_tarif, 4),
                    "cout_mad": round(cout_t1, 2),
                },
                {
                    "tranche": 2,
                    "kwh": round(kwh_t2, 3),
                    "prix_mad_kwh": round(t2["prix_mad_kwh"] * facteur_tarif, 4),
                    "cout_mad": round(cout_t2, 2),
                },
            ]
            tranche_atteinte = 2
            mode = "progressif"

        else:
            tranche = self._tranche_selective_residentiel(conso)
            prix = tranche["prix_mad_kwh"] * facteur_tarif
            cout = conso * prix
            detail = [{
                "tranche": tranche["tranche"],
                "kwh": round(conso, 3),
                "prix_mad_kwh": round(prix, 4),
                "cout_mad": round(cout, 2),
            }]
            tranche_atteinte = tranche["tranche"]
            mode = "selectif"

        total = cout
        if self.appliquer_taxes:
            # A utiliser seulement si les prix config sont HT.
            taxe_communale = cout * 0.10
            tva = (cout + taxe_communale) * 0.14
            total = cout + taxe_communale + tva

        result = FactureMensuelleResidentiel(
            mois=mois,
            consommation_kwh=round(conso, 2),
            tranche_atteinte=tranche_atteinte,
            mode_facturation=mode,
            cout_energie_mad=round(cout, 2),
            total_mad=round(total, 2),
            detail_tranches=detail,
        )

        return asdict(result)

    def _tranche_selective_residentiel(self, conso_kwh: float) -> Dict[str, Any]:
        for tranche in TARIFS_BT_RESIDENTIEL["tranches"]:
            if tranche["min_kwh"] <= conso_kwh <= tranche["max_kwh"]:
                return tranche

        return TARIFS_BT_RESIDENTIEL["tranches"][-1]

    def calculer_facture_annuelle_residentiel(
        self,
        consommations_mensuelles_kwh: List[float],
        facteur_tarif: float = 1.0,
    ) -> Dict[str, Any]:
        if len(consommations_mensuelles_kwh) != 12:
            raise ValueError("consommations_mensuelles_kwh doit contenir 12 valeurs.")

        factures = []
        total = 0.0
        conso_totale = 0.0

        for mois, conso in enumerate(consommations_mensuelles_kwh, start=1):
            f = self.calculer_facture_mensuelle_residentiel(conso, mois, facteur_tarif)
            factures.append(f)
            total += f["total_mad"]
            conso_totale += f["consommation_kwh"]

        return {
            "type_contrat": "BT Residentiel",
            "factures_mensuelles": factures,
            "consommation_totale_kwh": round(conso_totale, 2),
            "total_annuel_mad": round(total, 2),
            "tarif_moyen_mad_kwh": round(total / conso_totale, 4) if conso_totale > 0 else 0,
        }

    def calculer_economie_avec_pv_residentiel(
        self,
        conso_mensuelle_sans_pv: List[float],
        conso_mensuelle_avec_pv: List[float],
        facteur_tarif: float = 1.0,
    ) -> Dict[str, Any]:
        facture_avant = self.calculer_facture_annuelle_residentiel(
            conso_mensuelle_sans_pv,
            facteur_tarif=facteur_tarif,
        )
        facture_apres = self.calculer_facture_annuelle_residentiel(
            conso_mensuelle_avec_pv,
            facteur_tarif=facteur_tarif,
        )

        economie = facture_avant["total_annuel_mad"] - facture_apres["total_annuel_mad"]

        detail = []
        for avant, apres in zip(facture_avant["factures_mensuelles"], facture_apres["factures_mensuelles"]):
            detail.append({
                "mois": avant["mois"],
                "conso_avant_kwh": avant["consommation_kwh"],
                "conso_apres_kwh": apres["consommation_kwh"],
                "tranche_avant": avant["tranche_atteinte"],
                "tranche_apres": apres["tranche_atteinte"],
                "facture_avant_mad": avant["total_mad"],
                "facture_apres_mad": apres["total_mad"],
                "economie_mad": round(avant["total_mad"] - apres["total_mad"], 2),
            })

        return {
            "type_contrat": "BT Residentiel",
            "facture_avant_mad": facture_avant["total_annuel_mad"],
            "facture_apres_mad": facture_apres["total_annuel_mad"],
            "economie_annuelle_mad": round(economie, 2),
            "economie_pct": round(economie / facture_avant["total_annuel_mad"] * 100, 2)
            if facture_avant["total_annuel_mad"] > 0 else 0,
            "detail_mensuel": detail,
        }

    # --------------------------------------------------------------------------
    # MT TERTIAIRE
    # --------------------------------------------------------------------------

    def get_type_heure_mt(self, dt: pd.Timestamp) -> Tuple[str, float]:
        """
        Retourne (type_heure, tarif_mad_kwh) pour MT tertiaire.
        """
        dt = pd.Timestamp(dt)
        heure = int(dt.hour)
        mois = int(dt.month)

        if self.postes_onee_gmt and self.timezone_data.upper() in ["UTC+01:00", "GMT+1", "UTC+1"]:
            heure = (heure - 1) % 24

        _verifier_heure(heure)
        _verifier_mois(mois)

        saison = "hiver" if _est_hiver(mois) else "ete"
        tarifs_saison = {
            "hiver": {
                "pointe": [TARIFS_MT_TERTIAIRE["heures_pointe_hiver"]],
                "pleine": TARIFS_MT_TERTIAIRE["heures_pleines_hiver"],
            },
            "ete": {
                "pointe": [TARIFS_MT_TERTIAIRE["heures_pointe_ete"]],
                "pleine": TARIFS_MT_TERTIAIRE["heures_pleines_ete"],
            },
        }[saison]

        for plage in tarifs_saison["pointe"]:
            if _dans_plage(heure, plage["debut"], plage["fin"]):
                return "Pointe", plage["tarif_mad_kwh"]

        for plage in tarifs_saison["pleine"]:
            if _dans_plage(heure, plage["debut"], plage["fin"]):
                return "Pleine", plage["tarif_mad_kwh"]

        return "Creuse", TARIFS_MT_TERTIAIRE["heures_creuses"]["tarif_mad_kwh"]

    def ajouter_tarif_horaire_mt(
        self,
        profil_horaire: pd.DataFrame,
        facteur_tarif: float = 1.0,
    ) -> pd.DataFrame:
        df = profil_horaire.copy()

        if "DateTime" not in df.columns:
            raise ValueError("profil_horaire doit contenir DateTime.")

        types = []
        tarifs = []

        for dt in df["DateTime"]:
            type_heure, tarif = self.get_type_heure_mt(pd.Timestamp(dt))
            types.append(type_heure)
            tarifs.append(tarif * facteur_tarif)

        df["Type_Heure"] = types
        df["Tarif_MAD_kWh"] = tarifs

        return df

    def calculer_facture_mensuelle_tertiaire(
        self,
        profil_mois: pd.DataFrame,
        puissance_souscrite_kva: Optional[float] = None,
        facteur_tarif: float = 1.0,
    ) -> Dict[str, Any]:
        if "Consommation_kWh" not in profil_mois.columns:
            raise ValueError("profil_mois doit contenir Consommation_kWh.")

        if profil_mois.empty:
            raise ValueError("profil_mois est vide.")

        df = self.ajouter_tarif_horaire_mt(profil_mois, facteur_tarif=facteur_tarif)
        df["Cout_Energie_MAD"] = df["Consommation_kWh"] * df["Tarif_MAD_kWh"]

        mois = int(pd.Timestamp(df["DateTime"].iloc[0]).month)
        saison = "hiver" if _est_hiver(mois) else "ete"

        conso_pointe = float(df.loc[df["Type_Heure"] == "Pointe", "Consommation_kWh"].sum())
        conso_pleine = float(df.loc[df["Type_Heure"] == "Pleine", "Consommation_kWh"].sum())
        conso_creuse = float(df.loc[df["Type_Heure"] == "Creuse", "Consommation_kWh"].sum())

        cout_pointe = float(df.loc[df["Type_Heure"] == "Pointe", "Cout_Energie_MAD"].sum())
        cout_pleine = float(df.loc[df["Type_Heure"] == "Pleine", "Cout_Energie_MAD"].sum())
        cout_creuse = float(df.loc[df["Type_Heure"] == "Creuse", "Cout_Energie_MAD"].sum())

        cout_energie = cout_pointe + cout_pleine + cout_creuse

        if puissance_souscrite_kva is None:
            puissance_souscrite_kva = float(df["Consommation_kWh"].max() * 1.2)

        prime_kw_an = TARIFS_MT_TERTIAIRE.get("prime_fixe_mad_kva_an", 512.62)
        prime_puissance = puissance_souscrite_kva * prime_kw_an / 12.0

        total = cout_energie + prime_puissance

        result = FactureMensuelleTertiaire(
            mois=mois,
            saison=saison,
            consommation_pointe_kwh=round(conso_pointe, 2),
            consommation_pleine_kwh=round(conso_pleine, 2),
            consommation_creuse_kwh=round(conso_creuse, 2),
            cout_pointe_mad=round(cout_pointe, 2),
            cout_pleine_mad=round(cout_pleine, 2),
            cout_creuse_mad=round(cout_creuse, 2),
            cout_energie_mad=round(cout_energie, 2),
            prime_puissance_mad=round(prime_puissance, 2),
            total_mad=round(total, 2),
        )

        return asdict(result)

    def calculer_facture_annuelle_tertiaire(
        self,
        profil_horaire: pd.DataFrame,
        puissance_souscrite_kva: Optional[float] = None,
        facteur_tarif: float = 1.0,
    ) -> Dict[str, Any]:
        if "DateTime" not in profil_horaire.columns:
            raise ValueError("profil_horaire doit contenir DateTime.")
        if "Consommation_kWh" not in profil_horaire.columns:
            raise ValueError("profil_horaire doit contenir Consommation_kWh.")

        df = profil_horaire.copy()
        df["Mois"] = pd.to_datetime(df["DateTime"]).dt.month

        factures = []
        total = 0.0

        for mois in range(1, 13):
            df_mois = df[df["Mois"] == mois]
            if df_mois.empty:
                continue

            f = self.calculer_facture_mensuelle_tertiaire(
                df_mois,
                puissance_souscrite_kva=puissance_souscrite_kva,
                facteur_tarif=facteur_tarif,
            )
            factures.append(f)
            total += f["total_mad"]

        return {
            "type_contrat": "MT Tertiaire",
            "factures_mensuelles": factures,
            "total_annuel_mad": round(total, 2),
            "puissance_souscrite_kva": puissance_souscrite_kva,
        }

    def calculer_economie_avec_pv_tertiaire(
        self,
        profil_sans_pv: pd.DataFrame,
        profil_avec_pv: pd.DataFrame,
        puissance_souscrite_kva: Optional[float] = None,
        facteur_tarif: float = 1.0,
    ) -> Dict[str, Any]:
        facture_avant = self.calculer_facture_annuelle_tertiaire(
            profil_sans_pv,
            puissance_souscrite_kva=puissance_souscrite_kva,
            facteur_tarif=facteur_tarif,
        )
        facture_apres = self.calculer_facture_annuelle_tertiaire(
            profil_avec_pv,
            puissance_souscrite_kva=puissance_souscrite_kva,
            facteur_tarif=facteur_tarif,
        )

        economie = facture_avant["total_annuel_mad"] - facture_apres["total_annuel_mad"]

        return {
            "type_contrat": "MT Tertiaire",
            "facture_avant_mad": facture_avant["total_annuel_mad"],
            "facture_apres_mad": facture_apres["total_annuel_mad"],
            "economie_annuelle_mad": round(economie, 2),
            "economie_pct": round(economie / facture_avant["total_annuel_mad"] * 100, 2)
            if facture_avant["total_annuel_mad"] > 0 else 0,
            "facture_avant": facture_avant,
            "facture_apres": facture_apres,
        }

    # --------------------------------------------------------------------------
    # INJECTION
    # --------------------------------------------------------------------------

    def calculer_revenu_injection(
        self,
        profil_injection: pd.DataFrame,
        appliquer_limite_20pct: bool = True,
        production_annuelle_kwh: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Calcule le revenu d'injection.
        Attention: application selon regime/niveau tension a confirmer.
        """
        if "DateTime" not in profil_injection.columns:
            raise ValueError("profil_injection doit contenir DateTime.")
        if "Injection_kWh" not in profil_injection.columns:
            raise ValueError("profil_injection doit contenir Injection_kWh.")

        df = profil_injection.copy()

        revenus = []
        types = []

        for _, row in df.iterrows():
            type_heure, _ = self.get_type_heure_mt(pd.Timestamp(row["DateTime"]))
            types.append(type_heure)

            if type_heure == "Pointe":
                tarif = TARIFS_INJECTION_ANRE["pointe_mad_kwh"]
            else:
                tarif = TARIFS_INJECTION_ANRE["hors_pointe_mad_kwh"]

            revenus.append(row["Injection_kWh"] * tarif)

        df["Type_Heure"] = types
        df["Revenu_MAD"] = revenus

        injection_totale = float(df["Injection_kWh"].sum())
        revenu_brut = float(df["Revenu_MAD"].sum())

        injection_remuneree = injection_totale
        facteur_limite = 1.0

        if appliquer_limite_20pct and production_annuelle_kwh is not None and production_annuelle_kwh > 0:
            plafond = production_annuelle_kwh * TARIFS_INJECTION_ANRE["limite_injection_annuelle"]
            injection_remuneree = min(injection_totale, plafond)
            facteur_limite = injection_remuneree / injection_totale if injection_totale > 0 else 1.0

        revenu_limite = revenu_brut * facteur_limite

        return {
            "injection_totale_kwh": round(injection_totale, 2),
            "injection_remuneree_kwh": round(injection_remuneree, 2),
            "revenu_brut_mad": round(revenu_brut, 2),
            "revenu_apres_limite_mad": round(revenu_limite, 2),
            "limite_20pct_appliquee": appliquer_limite_20pct,
            "note": "Revenu indicatif. Eligibilite et conditions d'achat a confirmer selon contrat et reglementation.",
        }

    # --------------------------------------------------------------------------
    # FACTURE COMPLETE AUTO
    # --------------------------------------------------------------------------

    def calculer_facture_complete(
        self,
        profil_horaire: pd.DataFrame,
        puissance_souscrite_kva: Optional[float] = None,
        facteur_tarif: float = 1.0,
    ) -> Dict[str, Any]:
        if self.type_contrat == "bt_residentiel":
            df = profil_horaire.copy()
            if "DateTime" not in df.columns:
                raise ValueError("profil_horaire doit contenir DateTime.")
            if "Consommation_kWh" not in df.columns:
                raise ValueError("profil_horaire doit contenir Consommation_kWh.")

            df["Mois"] = pd.to_datetime(df["DateTime"]).dt.month
            mensuel = df.groupby("Mois")["Consommation_kWh"].sum()

            conso_12 = [float(mensuel.get(m, 0.0)) for m in range(1, 13)]
            return self.calculer_facture_annuelle_residentiel(conso_12, facteur_tarif=facteur_tarif)

        return self.calculer_facture_annuelle_tertiaire(
            profil_horaire,
            puissance_souscrite_kva=puissance_souscrite_kva,
            facteur_tarif=facteur_tarif,
        )


# ==============================================================================
# OUTIL DE CHOIX INDICATIF
# ==============================================================================

def determiner_type_contrat_indicatif(
    consommation_annuelle_kwh: float,
    puissance_max_kw: float,
) -> str:
    """
    Choix indicatif pour l'interface.
    L'utilisateur doit pouvoir le modifier.
    """
    if puissance_max_kw > 36 or consommation_annuelle_kwh > 50000:
        return "mt_tertiaire"
    return "bt_residentiel"
