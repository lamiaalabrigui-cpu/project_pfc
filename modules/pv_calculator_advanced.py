"""
Module PV Calculator Avance - Opti-Solar Maroc

Objectif:
- Calculer la production PV horaire a partir du TMY
- Utiliser une approche robuste de pre-dimensionnement
- Eviter le double comptage de l'irradiance
- Produire une colonne standard: Production_kWh
- Comparer plusieurs puissances PV pour optimiser autoconsommation

Remarque:
Ce module est volontairement plus robuste qu'un pseudo-modele DeSoto incomplet.
Pour une simulation physique avancee certifiable, integrer pvlib.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional, List
import numpy as np
import pandas as pd


# ==============================================================================
# MODELES SIMPLIFIES ROBUSTES
# ==============================================================================

@dataclass
class PVLosses:
    soiling: float = 0.05
    mismatch: float = 0.02
    cables_dc: float = 0.015
    iam: float = 0.02
    availability: float = 0.01


@dataclass
class ProductionSummary:
    puissance_crete_kwc: float
    production_annuelle_kwh: float
    productible_specifique_kwh_kwc: float
    irradiation_gpi_kwh_m2: float
    performance_ratio: float
    temperature_module_moy_c: float
    temperature_module_max_c: float
    energie_clipping_kwh: float
    taux_clipping_pct: float


class PVCalculatorAdvanced:
    """
    Calculateur PV horaire.
    """

    def __init__(
        self,
        donnees_tmy: pd.DataFrame,
        config_settings: Dict[str, Any],
        puissance_crete_kwc: float,
        inclinaison_source: str = "GPI",
    ):
        self.tmy = donnees_tmy.copy()
        self.config = config_settings
        self.pc_kwc = float(puissance_crete_kwc)
        self.pc_w = self.pc_kwc * 1000
        self.inclinaison_source = inclinaison_source

        if self.pc_kwc <= 0:
            raise ValueError("puissance_crete_kwc doit etre strictement positive.")

        self.production_horaire: Optional[pd.DataFrame] = None
        self.summary: Optional[ProductionSummary] = None

    def calculer_temperature_module(
        self,
        gpi_w_m2: np.ndarray,
        tamb_c: np.ndarray,
        vent_m_s: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """
        Calcule la temperature module.

        Modele Faiman simplifie:
            T_module = T_amb + G / (u0 + u1 * wind)

        Coefficients typiques:
            u0 = 25 W/m2/K
            u1 = 6.84 W/m2/K/(m/s)
        """
        if vent_m_s is None:
            vent_m_s = np.full_like(gpi_w_m2, 2.0, dtype=float)

        u0 = self.config.get("calcul", {}).get("faiman_u0", 25.0)
        u1 = self.config.get("calcul", {}).get("faiman_u1", 6.84)

        denom = u0 + u1 * np.clip(vent_m_s, 0, 20)
        return tamb_c + gpi_w_m2 / denom

    def calculer_production_annuelle(self) -> pd.DataFrame:
        """
        Calcule la production horaire PV.

        Returns:
            DataFrame avec:
            - DateTime
            - GPI_W_m2
            - T_Amb_C
            - T_Module_C
            - P_DC_W
            - P_AC_W
            - Production_kWh
        """
        self._valider_entrees()

        gpi_col = self._choisir_colonne_gpi()
        gpi = self.tmy[gpi_col].to_numpy(dtype=float)
        tamb = self.tmy["Tamb"].to_numpy(dtype=float)
        vent = self.tmy["WindVel"].to_numpy(dtype=float) if "WindVel" in self.tmy.columns else np.full(len(gpi), 2.0)

        panel = self.config["panel"]
        onduleur = self.config["onduleur"]
        environnement = self.config.get("environnement", {})

        coef_temp = panel.get("coef_temp_puissance", -0.0035)

        losses = PVLosses(
            soiling=environnement.get("soiling_loss_maroc", 0.05),
            mismatch=environnement.get("mismatch_loss", 0.02),
            cables_dc=environnement.get("cables_dc_loss", 0.015),
            iam=environnement.get("iam_loss", 0.02),
            availability=environnement.get("availability_loss", 0.01),
        )

        t_module = self.calculer_temperature_module(gpi, tamb, vent)

        # Puissance DC avant pertes systeme:
        # Pc_STC * irradiance ratio * correction temperature
        facteur_irradiance = np.clip(gpi / 1000.0, 0, None)
        facteur_temperature = 1 + coef_temp * (t_module - 25.0)
        facteur_temperature = np.clip(facteur_temperature, 0, 1.20)

        p_dc_brut = self.pc_w * facteur_irradiance * facteur_temperature

        # Pertes DC optiques et systeme, sans reappliquer l'irradiance.
        facteur_pertes_dc = (
            (1 - losses.iam)
            * (1 - losses.soiling)
            * (1 - losses.mismatch)
            * (1 - losses.cables_dc)
            * (1 - losses.availability)
        )
        p_dc_net = p_dc_brut * facteur_pertes_dc

        # Onduleur
        ratio_dc_ac = onduleur.get("ratio_surdimensionnement", 1.2)
        p_ac_nom_w = self.pc_w / ratio_dc_ac
        rendement_nominal = onduleur.get("rendement_nominal", 0.98)

        rendement_onduleur = self._rendement_onduleur_simple(p_dc_net, p_ac_nom_w, rendement_nominal)
        p_ac_avant_clip = p_dc_net * rendement_onduleur

        p_ac = np.minimum(p_ac_avant_clip, p_ac_nom_w)
        clipping_w = np.maximum(0, p_ac_avant_clip - p_ac)

        production = pd.DataFrame({
            "DateTime": self.tmy["DateTime"].values,
            "GPI_W_m2": gpi,
            "T_Amb_C": tamb,
            "WindVel_m_s": vent,
            "T_Module_C": t_module,
            "P_DC_W": p_dc_net,
            "Rendement_Onduleur": rendement_onduleur,
            "P_AC_W": p_ac,
            "Production_kWh": p_ac / 1000.0,
            "Clipping_kWh": clipping_w / 1000.0,
        })

        self.production_horaire = production
        self.summary = self._calculer_summary(production, gpi)

        return production

    def _rendement_onduleur_simple(
        self,
        p_dc_w: np.ndarray,
        p_ac_nom_w: float,
        rendement_nominal: float,
    ) -> np.ndarray:
        """
        Courbe de rendement simple selon charge.
        Evite les rendements irrealisables et garde le clipping separe.
        """
        charge = np.divide(
            p_dc_w,
            p_ac_nom_w,
            out=np.zeros_like(p_dc_w, dtype=float),
            where=p_ac_nom_w > 0,
        )

        eta = np.zeros_like(charge, dtype=float)

        masque = charge > 0.01
        eta[masque] = rendement_nominal * (
            0.94 + 0.06 * np.minimum(charge[masque] / 0.30, 1.0)
        )

        eta = np.clip(eta, 0, 0.99)
        return eta

    def _calculer_summary(self, production: pd.DataFrame, gpi: np.ndarray) -> ProductionSummary:
        prod_annuelle = float(production["Production_kWh"].sum())
        irradiation_gpi = float(np.sum(gpi) / 1000.0)
        prod_theorique = irradiation_gpi * self.pc_kwc
        pr = prod_annuelle / prod_theorique if prod_theorique > 0 else 0.0

        clipping = float(production["Clipping_kWh"].sum())
        prod_avant_clip = prod_annuelle + clipping
        taux_clipping = clipping / prod_avant_clip if prod_avant_clip > 0 else 0.0

        return ProductionSummary(
            puissance_crete_kwc=round(self.pc_kwc, 3),
            production_annuelle_kwh=round(prod_annuelle, 2),
            productible_specifique_kwh_kwc=round(prod_annuelle / self.pc_kwc, 2),
            irradiation_gpi_kwh_m2=round(irradiation_gpi, 2),
            performance_ratio=round(pr, 3),
            temperature_module_moy_c=round(float(production["T_Module_C"].mean()), 2),
            temperature_module_max_c=round(float(production["T_Module_C"].max()), 2),
            energie_clipping_kwh=round(clipping, 2),
            taux_clipping_pct=round(taux_clipping * 100, 2),
        )

    def get_production_annuelle_kwh(self) -> float:
        if self.production_horaire is None:
            self.calculer_production_annuelle()
        return float(self.production_horaire["Production_kWh"].sum())

    def get_productible_specifique(self) -> float:
        prod = self.get_production_annuelle_kwh()
        return prod / self.pc_kwc if self.pc_kwc > 0 else 0

    def get_performance_ratio(self) -> float:
        if self.summary is None:
            self.calculer_production_annuelle()
        return float(self.summary.performance_ratio)

    def get_summary(self) -> Dict[str, Any]:
        if self.summary is None:
            self.calculer_production_annuelle()
        return asdict(self.summary)

    def get_production_mensuelle(self) -> pd.DataFrame:
        if self.production_horaire is None:
            self.calculer_production_annuelle()

        df = self.production_horaire.copy()
        df["Mois"] = pd.to_datetime(df["DateTime"]).dt.month

        mensuel = df.groupby("Mois").agg({
            "Production_kWh": "sum",
            "GPI_W_m2": "sum",
            "T_Module_C": "mean",
            "Clipping_kWh": "sum",
        }).reset_index()

        mensuel["GPI_kWh_m2"] = mensuel["GPI_W_m2"] / 1000.0

        return mensuel

    def _choisir_colonne_gpi(self) -> str:
        if "GPI_Calcule" in self.tmy.columns:
            return "GPI_Calcule"
        if "GPI" in self.tmy.columns:
            return "GPI"
        raise ValueError("Aucune colonne GPI ou GPI_Calcule disponible dans TMY.")

    def _valider_entrees(self):
        required = ["DateTime", "Tamb"]
        for col in required:
            if col not in self.tmy.columns:
                raise ValueError(f"Colonne TMY manquante: {col}")

        self._choisir_colonne_gpi()

        if len(self.tmy) != 8760:
            raise ValueError(f"TMY doit contenir 8760 heures. Recu: {len(self.tmy)}")

        if "panel" not in self.config or "onduleur" not in self.config:
            raise ValueError("config_settings doit contenir 'panel' et 'onduleur'.")


# ==============================================================================
# OPTIMISATION MULTI-SCENARIOS
# ==============================================================================

class SystemOptimizerAdvanced:
    """
    Optimiseur de puissance PV par comparaison de scenarios.
    """

    def __init__(
        self,
        profil_consommation: pd.DataFrame,
        donnees_tmy: pd.DataFrame,
        config_settings: Dict[str, Any],
    ):
        self.conso = profil_consommation.copy()
        self.tmy = donnees_tmy.copy()
        self.config = config_settings

        if "Consommation_kWh" not in self.conso.columns:
            raise ValueError("profil_consommation doit contenir la colonne Consommation_kWh.")

        if len(self.conso) < 8760:
            raise ValueError("profil_consommation doit contenir au moins 8760 heures.")

    def optimiser_multi_scenarios(
        self,
        type_batiment: str = "tertiaire",
        type_systeme: str = "on-grid",
        puissances_kwc: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """
        Genere les scenarios:
        - roi_flash: retour simple minimal
        - optimal: meilleur score economique/autoconso/injection
        - independance: taux autoproduction maximal
        """
        if puissances_kwc is None:
            puissances_kwc = self._generer_plage_puissance(type_batiment)

        resultats = self._tester_puissances(puissances_kwc, type_systeme)

        if resultats.empty:
            raise ValueError("Aucun resultat d'optimisation genere.")

        scenario_roi = resultats.loc[resultats["Periode_retour_simple_ans"].idxmin()].to_dict()
        scenario_optimal = resultats.loc[resultats["Score_Optimal"].idxmax()].to_dict()
        scenario_independance = resultats.loc[resultats["Taux_autoproduction"].idxmax()].to_dict()

        return {
            "roi_flash": scenario_roi,
            "optimal": scenario_optimal,
            "independance": scenario_independance,
            "tous_resultats": resultats,
        }

    def _generer_plage_puissance(self, type_batiment: str) -> List[float]:
        conso_annuelle = float(self.conso["Consommation_kWh"].sum())

        if type_batiment == "residentiel":
            pc_min = 1.0
            pc_max = min(20.0, max(3.0, conso_annuelle / 1200.0 * 1.5))
            pas = 0.5
        else:
            pc_min = 5.0
            pc_max = min(300.0, max(20.0, conso_annuelle / 1400.0 * 1.5))
            pas = max(1.0, (pc_max - pc_min) / 40.0)

        return [round(float(x), 2) for x in np.arange(pc_min, pc_max + pas, pas)]

    def _tester_puissances(self, puissances_kwc: List[float], type_systeme: str) -> pd.DataFrame:
        rows = []

        for pc in puissances_kwc:
            calc = PVCalculatorAdvanced(self.tmy, self.config, pc)
            prod_df = calc.calculer_production_annuelle()
            summary = calc.get_summary()

            metrics = self._calculer_metriques_energie(prod_df, pc)
            metrics.update(summary)

            capex_estime = self._estimer_capex_simple(pc, type_systeme)
            economie_annuelle = self._estimer_economie_annuelle(metrics)
            periode_retour = capex_estime / economie_annuelle if economie_annuelle > 0 else 999

            metrics["CAPEX_estime_MAD"] = round(capex_estime, 0)
            metrics["Economie_annuelle_estimee_MAD"] = round(economie_annuelle, 0)
            metrics["Periode_retour_simple_ans"] = round(periode_retour, 2)
            metrics["Score_Optimal"] = self._score_optimal(metrics, periode_retour)

            rows.append(metrics)

        return pd.DataFrame(rows)

    def _calculer_metriques_energie(self, production_df: pd.DataFrame, pc_kwc: float) -> Dict[str, Any]:
        prod = production_df["Production_kWh"].to_numpy(dtype=float)[:8760]
        conso = self.conso["Consommation_kWh"].to_numpy(dtype=float)[:8760]

        autoconso = np.minimum(prod, conso)
        injection = np.maximum(0, prod - conso)
        achat_reseau = np.maximum(0, conso - prod)

        prod_annuelle = float(prod.sum())
        conso_annuelle = float(conso.sum())
        autoconso_totale = float(autoconso.sum())
        injection_totale = float(injection.sum())
        achat_total = float(achat_reseau.sum())

        taux_autoconso = autoconso_totale / prod_annuelle if prod_annuelle > 0 else 0
        taux_autoproduction = autoconso_totale / conso_annuelle if conso_annuelle > 0 else 0
        taux_injection = injection_totale / prod_annuelle if prod_annuelle > 0 else 0

        return {
            "Puissance_crete_kWc": round(pc_kwc, 2),
            "Production_annuelle_kWh": round(prod_annuelle, 2),
            "Consommation_annuelle_kWh": round(conso_annuelle, 2),
            "Autoconsommation_kWh": round(autoconso_totale, 2),
            "Injection_reseau_kWh": round(injection_totale, 2),
            "Achat_reseau_kWh": round(achat_total, 2),
            "Taux_autoconso": round(taux_autoconso, 4),
            "Taux_autoproduction": round(taux_autoproduction, 4),
            "Taux_injection": round(taux_injection, 4),
            "Limite_injection_20pct_respectee": taux_injection <= 0.20,
        }

    def _estimer_capex_simple(self, pc_kwc: float, type_systeme: str) -> float:
        """
        Estimation rapide pour comparaison.
        Le CAPEX detaille sera calcule dans le module dimensionnement.
        """
        if type_systeme == "off-grid":
            return pc_kwc * 14000
        if type_systeme == "hybride":
            return pc_kwc * 12000
        return pc_kwc * 8000

    def _estimer_economie_annuelle(self, metrics: Dict[str, Any]) -> float:
        """
        Estimation rapide avant le module tarifaire detaille.
        """
        prix_kwh_evite = self.config.get("economie", {}).get("prix_kwh_reseau_moyen", 1.1)
        tarif_injection = self.config.get("economie", {}).get("prix_injection_hors_pointe", 0.18)

        injection_remuneree = min(
            metrics["Injection_reseau_kWh"],
            metrics["Production_annuelle_kWh"] * 0.20,
        )

        return (
            metrics["Autoconsommation_kWh"] * prix_kwh_evite
            + injection_remuneree * tarif_injection
        )

    def _score_optimal(self, metrics: Dict[str, Any], periode_retour: float) -> float:
        """
        Score heuristique:
        - favorise autoconsommation et autoproduction
        - penalise injection >20%
        - penalise retour trop long
        """
        score = 0.0
        score += metrics["Taux_autoconso"] * 40
        score += metrics["Taux_autoproduction"] * 40
        score += max(0, 20 - periode_retour)

        if not metrics["Limite_injection_20pct_respectee"]:
            score -= 30

        return round(score, 3)


# ==============================================================================
# OUTILS RAPIDES
# ==============================================================================

def calculer_production_pv(
    donnees_tmy: pd.DataFrame,
    config_settings: Dict[str, Any],
    puissance_crete_kwc: float,
) -> pd.DataFrame:
    calc = PVCalculatorAdvanced(donnees_tmy, config_settings, puissance_crete_kwc)
    return calc.calculer_production_annuelle()
