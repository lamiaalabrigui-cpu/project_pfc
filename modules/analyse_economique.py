"""
Module Analyse Economique - Opti-Solar Maroc

Objectif:
- Calculer les economies avant/apres PV selon tarification ONEE
- Produire VAN, TRI, LCOE et flux 25 ans
- Integrer degradation PV, hausse tarifaire, OPEX et remplacements

Important:
Ce module produit une analyse de pre-faisabilite.
Les resultats doivent etre confirmes par devis, contrat ONEE/ANRE,
et validation fiscale/reglementaire.
"""

from __future__ import annotations

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd
import numpy_financial as npf

from modules.tarification_onee import TarificationONEE


@dataclass
class FluxAnnuel:
    annee: int
    production_kwh: float
    autoconsommation_kwh: float
    injection_kwh: float
    achat_reseau_kwh: float
    economie_autoconso_mad: float
    revenu_injection_mad: float
    economie_totale_mad: float
    opex_mad: float
    remplacement_mad: float
    flux_net_mad: float
    flux_actualise_mad: float
    cumul_actualise_mad: float


class AnalyseEconomiqueAvancee:
    def __init__(
        self,
        config_settings: Dict[str, Any],
        capex: float,
        type_contrat: str,
        profil_production: pd.DataFrame,
        profil_consommation: pd.DataFrame,
        puissance_souscrite_kva: Optional[float] = None,
        inclure_revenu_injection: bool = False,
        appliquer_limite_injection_20pct: bool = True,
    ):
        self.config = config_settings
        self.capex = float(capex)
        self.type_contrat = type_contrat
        self.production = profil_production.copy()
        self.consommation = profil_consommation.copy()
        self.puissance_souscrite_kva = puissance_souscrite_kva
        self.inclure_revenu_injection = inclure_revenu_injection
        self.appliquer_limite_injection_20pct = appliquer_limite_injection_20pct

        self.duree_projet = int(config_settings["economie"].get("duree_projet_ans", 25))
        self.taux_actualisation = float(config_settings["economie"].get("taux_actualisation", 0.06))
        self.augmentation_tarif = float(config_settings["economie"].get("augmentation_tarif_elec", 0.035))
        self.degradation_pv = float(config_settings["panel"].get("degradation_annuelle", 0.005))

        self.tarif_onee = TarificationONEE(type_contrat)

        self._valider_profils()
        self._calculer_flux_energetiques_an1()

    # --------------------------------------------------------------------------
    # VALIDATION
    # --------------------------------------------------------------------------

    def _valider_profils(self):
        if "DateTime" not in self.production.columns:
            raise ValueError("profil_production doit contenir DateTime.")
        if "Production_kWh" not in self.production.columns:
            raise ValueError("profil_production doit contenir Production_kWh.")

        if "DateTime" not in self.consommation.columns:
            raise ValueError("profil_consommation doit contenir DateTime.")
        if "Consommation_kWh" not in self.consommation.columns:
            raise ValueError("profil_consommation doit contenir Consommation_kWh.")

        self.production = self._pad_to_8760(self.production, "Production_kWh")
        self.consommation = self._pad_to_8760(self.consommation, "Consommation_kWh")

    @staticmethod
    def _pad_to_8760(df: pd.DataFrame, value_col: str) -> pd.DataFrame:
        raw = df[value_col].to_numpy(dtype=float)
        if len(raw) >= 8760:
            return df.iloc[:8760].reset_index(drop=True)
        repeats = int(np.ceil(8760 / len(raw)))
        repeated_vals = np.tile(raw, repeats)[:8760]
        start = pd.Timestamp(f"{pd.to_datetime(df['DateTime'].iloc[0]).year}-01-01 00:00:00")
        new_dts = pd.date_range(start=start, periods=8760, freq="h")
        return pd.DataFrame({"DateTime": new_dts, value_col: repeated_vals})

    def _calculer_flux_energetiques_an1(self):
        prod = self.production["Production_kWh"].to_numpy(dtype=float)
        conso = self.consommation["Consommation_kWh"].to_numpy(dtype=float)

        self.autoconso_horaire_an1 = np.minimum(prod, conso)
        self.injection_horaire_an1 = np.maximum(0, prod - conso)
        self.achat_reseau_horaire_an1 = np.maximum(0, conso - prod)

        self.production_annuelle_an1 = float(prod.sum())
        self.consommation_annuelle = float(conso.sum())
        self.autoconso_annuelle_an1 = float(self.autoconso_horaire_an1.sum())
        self.injection_annuelle_an1 = float(self.injection_horaire_an1.sum())
        self.achat_reseau_annuel_an1 = float(self.achat_reseau_horaire_an1.sum())

        self.taux_autoconso_an1 = (
            self.autoconso_annuelle_an1 / self.production_annuelle_an1
            if self.production_annuelle_an1 > 0 else 0
        )
        self.taux_autoproduction_an1 = (
            self.autoconso_annuelle_an1 / self.consommation_annuelle
            if self.consommation_annuelle > 0 else 0
        )

    # --------------------------------------------------------------------------
    # ECONOMIES ANNUELLES
    # --------------------------------------------------------------------------

    def calculer_economies_annuelles_detaillees(self, annee: int) -> Dict[str, Any]:
        if annee < 1:
            raise ValueError("annee doit etre >= 1.")

        facteur_degradation = (1 - self.degradation_pv) ** (annee - 1)
        facteur_tarif = (1 + self.augmentation_tarif) ** (annee - 1)

        prod = self.production["Production_kWh"].to_numpy(dtype=float) * facteur_degradation
        conso = self.consommation["Consommation_kWh"].to_numpy(dtype=float)

        autoconso = np.minimum(prod, conso)
        injection = np.maximum(0, prod - conso)
        achat_reseau = np.maximum(0, conso - prod)

        df_sans_pv = self.consommation[["DateTime", "Consommation_kWh"]].copy()

        df_avec_pv = self.consommation[["DateTime"]].copy()
        df_avec_pv["Consommation_kWh"] = achat_reseau

        economie_autoconso = self._calculer_economie_facture(
            df_sans_pv,
            df_avec_pv,
            facteur_tarif=facteur_tarif,
        )

        revenu_injection = 0.0
        if self.inclure_revenu_injection:
            df_injection = self.production[["DateTime"]].copy()
            df_injection["Injection_kWh"] = injection

            revenu = self.tarif_onee.calculer_revenu_injection(
                df_injection,
                appliquer_limite_20pct=self.appliquer_limite_injection_20pct,
                production_annuelle_kwh=float(prod.sum()),
            )
            revenu_injection = revenu["revenu_apres_limite_mad"] * facteur_tarif

        economie_totale = economie_autoconso + revenu_injection
        opex = self._calculer_opex_annuel(annee)
        remplacement = self._calculer_remplacements(annee)

        flux_net = economie_totale - opex - remplacement

        return {
            "annee": annee,
            "facteur_degradation": round(facteur_degradation, 5),
            "facteur_tarif": round(facteur_tarif, 5),
            "production_kwh": round(float(prod.sum()), 2),
            "autoconsommation_kwh": round(float(autoconso.sum()), 2),
            "injection_kwh": round(float(injection.sum()), 2),
            "achat_reseau_kwh": round(float(achat_reseau.sum()), 2),
            "economie_autoconso_mad": round(float(economie_autoconso), 2),
            "revenu_injection_mad": round(float(revenu_injection), 2),
            "economie_totale_mad": round(float(economie_totale), 2),
            "opex_mad": round(float(opex), 2),
            "remplacement_mad": round(float(remplacement), 2),
            "flux_net_mad": round(float(flux_net), 2),
        }

    def _calculer_economie_facture(
        self,
        df_sans_pv: pd.DataFrame,
        df_avec_pv: pd.DataFrame,
        facteur_tarif: float,
    ) -> float:
        if self.type_contrat.lower() in ["residentiel", "bt_residentiel", "bt"]:
            df1 = df_sans_pv.copy()
            df2 = df_avec_pv.copy()
            df1["Mois"] = pd.to_datetime(df1["DateTime"]).dt.month
            df2["Mois"] = pd.to_datetime(df2["DateTime"]).dt.month

            mensuel_avant = df1.groupby("Mois")["Consommation_kWh"].sum()
            mensuel_apres = df2.groupby("Mois")["Consommation_kWh"].sum()

            avant_12 = [float(mensuel_avant.get(m, 0.0)) for m in range(1, 13)]
            apres_12 = [float(mensuel_apres.get(m, 0.0)) for m in range(1, 13)]

            result = self.tarif_onee.calculer_economie_avec_pv_residentiel(
                avant_12,
                apres_12,
                facteur_tarif=facteur_tarif,
            )
            return float(result["economie_annuelle_mad"])

        result = self.tarif_onee.calculer_economie_avec_pv_tertiaire(
            df_sans_pv,
            df_avec_pv,
            puissance_souscrite_kva=self.puissance_souscrite_kva,
            facteur_tarif=facteur_tarif,
        )
        return float(result["economie_annuelle_mad"])

    def _calculer_opex_annuel(self, annee: int) -> float:
        eco = self.config["economie"]
        taux_inflation = eco.get("taux_inflation", 0.025)
        facteur_inflation = (1 + taux_inflation) ** (annee - 1)

        maintenance = self.capex * eco.get("cout_maintenance_pct_capex", 0.01)
        nettoyage = eco.get("cout_nettoyage_annuel_mad", 2000.0)
        inspection = eco.get("cout_inspection_annuel_mad", 1500.0)

        return (maintenance + nettoyage + inspection) * facteur_inflation

    def _calculer_remplacements(self, annee: int) -> float:
        cout = 0.0

        duree_onduleur = int(self.config["onduleur"].get("duree_vie_ans", 12))
        if annee == duree_onduleur:
            cout += self.capex * 0.10

        # Batteries seulement si le projet en contient.
        # Ici on reste indicatif car le detail CAPEX batteries est dans le module 5.
        if self.config.get("batterie") and self.type_contrat:
            duree_batt = self.config["batterie"].get("cycles_vie_80dod", 8000) / 365
            annee_batt = int(round(duree_batt))
            if annee == annee_batt:
                prix_kwh = self.config["batterie"].get("prix_par_kwh_mad", 3500.0)
                prix_bms = self.config["batterie"].get("prix_bms_mad", 5000.0)
                cout_batt_estime = self.capex * 0.15
                cout += max(cout_batt_estime, prix_bms)

        return cout

    # --------------------------------------------------------------------------
    # INDICATEURS FINANCIERS
    # --------------------------------------------------------------------------

    def generer_tableau_flux(self, duree: Optional[int] = None) -> pd.DataFrame:
        if duree is None:
            duree = self.duree_projet

        rows = []
        cumul_actualise = -self.capex

        rows.append({
            "Annee": 0,
            "Production_kWh": 0.0,
            "Autoconso_kWh": 0.0,
            "Injection_kWh": 0.0,
            "Achat_Reseau_kWh": 0.0,
            "Economie_MAD": 0.0,
            "OPEX_MAD": 0.0,
            "Remplacement_MAD": 0.0,
            "Flux_Net_MAD": -self.capex,
            "Flux_Actualise_MAD": -self.capex,
            "Cumul_Actualise_MAD": -self.capex,
        })

        for annee in range(1, duree + 1):
            e = self.calculer_economies_annuelles_detaillees(annee)
            flux = e["flux_net_mad"]
            flux_actualise = flux / ((1 + self.taux_actualisation) ** annee)
            cumul_actualise += flux_actualise

            rows.append({
                "Annee": annee,
                "Production_kWh": e["production_kwh"],
                "Autoconso_kWh": e["autoconsommation_kwh"],
                "Injection_kWh": e["injection_kwh"],
                "Achat_Reseau_kWh": e["achat_reseau_kwh"],
                "Economie_MAD": e["economie_totale_mad"],
                "OPEX_MAD": e["opex_mad"],
                "Remplacement_MAD": e["remplacement_mad"],
                "Flux_Net_MAD": e["flux_net_mad"],
                "Flux_Actualise_MAD": round(flux_actualise, 2),
                "Cumul_Actualise_MAD": round(cumul_actualise, 2),
            })

        return pd.DataFrame(rows)

    def calculer_van(self, duree: Optional[int] = None) -> float:
        flux = self.generer_tableau_flux(duree)
        return float(flux["Flux_Actualise_MAD"].sum())

    def calculer_tri(self, duree: Optional[int] = None) -> Optional[float]:
        flux = self.generer_tableau_flux(duree)["Flux_Net_MAD"].to_numpy(dtype=float)

        if np.all(flux <= 0):
            return None

        try:
            tri = npf.irr(flux)
            if tri is None or np.isnan(tri):
                return None
            return float(tri)
        except Exception:
            return self._tri_dichotomie(flux)

    def _tri_dichotomie(self, flux: np.ndarray) -> Optional[float]:
        def npv(rate):
            return sum(cf / ((1 + rate) ** i) for i, cf in enumerate(flux))

        low, high = -0.90, 1.00
        npv_low = npv(low)
        npv_high = npv(high)

        if npv_low * npv_high > 0:
            return None

        for _ in range(200):
            mid = (low + high) / 2
            val = npv(mid)

            if abs(val) < 1:
                return mid

            if npv_low * val < 0:
                high = mid
                npv_high = val
            else:
                low = mid
                npv_low = val

        return (low + high) / 2

    def calculer_lcoe(self, duree: Optional[int] = None) -> float:
        if duree is None:
            duree = self.duree_projet

        couts_actualises = self.capex
        production_actualisee = 0.0

        for annee in range(1, duree + 1):
            e = self.calculer_economies_annuelles_detaillees(annee)
            couts = e["opex_mad"] + e["remplacement_mad"]
            prod = e["production_kwh"]

            couts_actualises += couts / ((1 + self.taux_actualisation) ** annee)
            production_actualisee += prod / ((1 + self.taux_actualisation) ** annee)

        return couts_actualises / production_actualisee if production_actualisee > 0 else 0.0

    def calculer_periode_retour(self, duree: Optional[int] = None) -> Dict[str, Any]:
        if duree is None:
            duree = self.duree_projet

        cumul_simple = 0.0
        retour_simple = None

        cumul_actualise = 0.0
        retour_actualise = None

        for annee in range(1, duree + 1):
            e = self.calculer_economies_annuelles_detaillees(annee)
            flux = e["flux_net_mad"]

            cumul_prec = cumul_simple
            cumul_simple += flux

            if retour_simple is None and cumul_simple >= self.capex:
                reste = self.capex - cumul_prec
                fraction = reste / flux if flux > 0 else 0
                retour_simple = (annee - 1) + fraction

            flux_actualise = flux / ((1 + self.taux_actualisation) ** annee)
            cumul_actualise += flux_actualise

            if retour_actualise is None and cumul_actualise >= self.capex:
                retour_actualise = annee

        return {
            "periode_retour_simple_ans": round(retour_simple, 2) if retour_simple is not None else None,
            "periode_retour_actualisee_ans": retour_actualise,
        }

    def calculer_bilan_complet(self, duree: Optional[int] = None) -> Dict[str, Any]:
        if duree is None:
            duree = self.duree_projet

        flux = self.generer_tableau_flux(duree)
        van = self.calculer_van(duree)
        tri = self.calculer_tri(duree)
        lcoe = self.calculer_lcoe(duree)
        retour = self.calculer_periode_retour(duree)

        flux_sans_annee0 = flux[flux["Annee"] > 0]

        economies = float(flux_sans_annee0["Economie_MAD"].sum())
        opex = float(flux_sans_annee0["OPEX_MAD"].sum())
        remplacements = float(flux_sans_annee0["Remplacement_MAD"].sum())
        flux_nets = float(flux_sans_annee0["Flux_Net_MAD"].sum())
        benefice_net = flux_nets - self.capex

        taux_injection = (
            self.injection_annuelle_an1 / self.production_annuelle_an1
            if self.production_annuelle_an1 > 0 else 0
        )

        return {
            "duree_projet_ans": duree,
            "type_contrat": self.type_contrat,
            "investissement": {
                "capex_mad": round(self.capex, 0),
            },
            "production": {
                "annuelle_an1_kwh": round(self.production_annuelle_an1, 0),
                "totale_kwh": round(float(flux_sans_annee0["Production_kWh"].sum()), 0),
                "degradation_annuelle_pct": round(self.degradation_pv * 100, 2),
            },
            "performance": {
                "taux_autoconso_an1_pct": round(self.taux_autoconso_an1 * 100, 2),
                "taux_autoproduction_an1_pct": round(self.taux_autoproduction_an1 * 100, 2),
                "taux_injection_an1_pct": round(taux_injection * 100, 2),
                "limite_injection_20pct_respectee": taux_injection <= 0.20,
            },
            "economique": {
                "economies_brutes_mad": round(economies, 0),
                "opex_total_mad": round(opex, 0),
                "remplacements_total_mad": round(remplacements, 0),
                "flux_nets_totaux_mad": round(flux_nets, 0),
                "benefice_net_mad": round(benefice_net, 0),
            },
            "indicateurs_rentabilite": {
                "van_mad": round(van, 0),
                "tri_pct": round(tri * 100, 2) if tri is not None else None,
                "lcoe_mad_kwh": round(lcoe, 4),
                "periode_retour_simple_ans": retour["periode_retour_simple_ans"],
                "periode_retour_actualisee_ans": retour["periode_retour_actualisee_ans"],
                "rentable": van > 0,
            },
        }
