"""
Module Recommandations ISO 50001 - Opti-Solar Maroc

Objectif:
Generer des recommandations personnalisees pour le rapport PDF final,
a partir de:
- profil de consommation horaire
- donnees TMY / temperature exterieure
- production PV
- donnees analyseur reseau si disponibles
- diagnostic qualite des donnees

Important:
Ces recommandations constituent une aide au diagnostic energetique.
Elles ne remplacent pas un audit energetique terrain certifie.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional

import numpy as np
import pandas as pd


@dataclass
class Recommandation:
    categorie: str
    niveau: str
    titre: str
    message: str
    actions: List[str]
    indicateurs: Dict[str, Any]


class RecommandationsISO50001:
    def __init__(
        self,
        profil_consommation: pd.DataFrame,
        donnees_tmy: Optional[pd.DataFrame] = None,
        profil_production: Optional[pd.DataFrame] = None,
        donnees_reseau: Optional[pd.DataFrame] = None,
        diagnostic_donnees: Optional[Dict[str, Any]] = None,
        type_batiment: str = "tertiaire",
    ):
        self.conso = profil_consommation.copy()
        self.tmy = donnees_tmy.copy() if donnees_tmy is not None else None
        self.production = profil_production.copy() if profil_production is not None else None
        self.reseau = donnees_reseau.copy() if donnees_reseau is not None else None
        self.diagnostic_donnees = diagnostic_donnees or {}
        self.type_batiment = type_batiment

        self._valider()

    def _valider(self):
        if "DateTime" not in self.conso.columns:
            raise ValueError("profil_consommation doit contenir DateTime.")
        if "Consommation_kWh" not in self.conso.columns:
            raise ValueError("profil_consommation doit contenir Consommation_kWh.")

    # --------------------------------------------------------------------------
    # GENERATION COMPLETE
    # --------------------------------------------------------------------------

    def generer_recommandations(self) -> Dict[str, Any]:
        recommandations = []

        recommandations.append(self.analyser_talon_consommation())

        thermique = self.analyser_signature_thermique()
        if thermique is not None:
            recommandations.append(thermique)

        solaire = self.analyser_optimisation_solaire()
        if solaire is not None:
            recommandations.append(solaire)

        reactive = self.analyser_compensation_reactive()
        if reactive is not None:
            recommandations.append(reactive)

        recommandations.append(self.analyser_pics_et_load_shifting())

        qualite = self.analyser_qualite_donnees()
        if qualite is not None:
            recommandations.append(qualite)

        return {
            "nombre_recommandations": len(recommandations),
            "recommandations": [asdict(r) for r in recommandations],
            "synthese": self._synthese(recommandations),
        }

    def _synthese(self, recommandations: List[Recommandation]) -> Dict[str, Any]:
        niveaux = [r.niveau for r in recommandations]

        return {
            "alertes_critiques": niveaux.count("danger"),
            "alertes_attention": niveaux.count("warning"),
            "informations": niveaux.count("info"),
            "points_favorables": niveaux.count("success"),
        }

    # --------------------------------------------------------------------------
    # 1. TALON DE CONSOMMATION
    # --------------------------------------------------------------------------

    def analyser_talon_consommation(self) -> Recommandation:
        df = self.conso.copy()
        df["Heure"] = pd.to_datetime(df["DateTime"]).dt.hour

        conso_globale_moy = float(df["Consommation_kWh"].mean())
        conso_nuit_moy = float(df[df["Heure"].between(0, 5)]["Consommation_kWh"].mean())
        ratio = conso_nuit_moy / conso_globale_moy if conso_globale_moy > 0 else 0

        conso_nuit_totale = float(df[df["Heure"].between(0, 5)]["Consommation_kWh"].sum())
        conso_totale = float(df["Consommation_kWh"].sum())
        pct_nuit = conso_nuit_totale / conso_totale * 100 if conso_totale > 0 else 0

        if ratio > 0.20:
            niveau = "warning"
            titre = "Talon de consommation nocturne eleve"
            message = (
                f"La consommation moyenne entre 00h et 05h represente {ratio*100:.1f}% "
                "de la moyenne globale. Cela peut indiquer des veilles, eclairages ou "
                "equipements permanents non optimises."
            )
            actions = [
                "Identifier les charges permanentes: veilles, serveurs, pompes, eclairage exterieur.",
                "Installer horloges programmables, contacteurs ou detecteurs de presence.",
                "Separer les charges critiques des charges non critiques.",
                "Verifier les fuites de consommation pendant les periodes d'inoccupation.",
            ]
        else:
            niveau = "success"
            titre = "Talon de consommation maitrise"
            message = (
                f"Le ratio talon nocturne/moyenne globale est de {ratio*100:.1f}%. "
                "Le niveau de consommation de nuit semble acceptable pour une premiere analyse."
            )
            actions = [
                "Maintenir le suivi mensuel du talon de consommation.",
                "Verifier ponctuellement les consommations de nuit apres ajout de nouveaux equipements.",
            ]

        return Recommandation(
            categorie="talon_consommation",
            niveau=niveau,
            titre=titre,
            message=message,
            actions=actions,
            indicateurs={
                "moyenne_globale_kwh_h": round(conso_globale_moy, 3),
                "moyenne_nuit_00_05_kwh_h": round(conso_nuit_moy, 3),
                "ratio_talon_moyenne_pct": round(ratio * 100, 2),
                "part_energie_nuit_pct": round(pct_nuit, 2),
            },
        )

    # --------------------------------------------------------------------------
    # 2. SIGNATURE THERMIQUE
    # --------------------------------------------------------------------------

    def analyser_signature_thermique(self) -> Optional[Recommandation]:
        if self.tmy is None or "Tamb" not in self.tmy.columns:
            return None

        n = min(len(self.conso), len(self.tmy))
        conso = self.conso["Consommation_kWh"].iloc[:n].astype(float).reset_index(drop=True)
        temp = self.tmy["Tamb"].iloc[:n].astype(float).reset_index(drop=True)

        if conso.std() == 0 or temp.std() == 0:
            return None

        corr = float(conso.corr(temp))

        if corr >= 0.50:
            niveau = "warning"
            titre = "Signature thermique forte - sensibilite a la chaleur"
            message = (
                f"La correlation consommation/temperature est elevee ({corr:.2f}). "
                "La charge semble fortement influencee par la climatisation ou les apports thermiques."
            )
            actions = [
                "Regler les climatiseurs a 24 degC comme seuil de sobriete recommande.",
                "Nettoyer les filtres et verifier le rendement des unites de climatisation.",
                "Ameliorer l'isolation de toiture et limiter les apports solaires directs.",
                "Installer stores, films solaires ou brise-soleil sur facades exposees.",
                "Programmer la climatisation pendant les heures solaires pour augmenter l'autoconsommation PV.",
            ]
            interpretation = "chaleur_climatisation"

        elif corr <= -0.50:
            niveau = "warning"
            titre = "Signature thermique forte - sensibilite au froid"
            message = (
                f"La correlation consommation/temperature est negative et forte ({corr:.2f}). "
                "La consommation augmente probablement lorsque la temperature baisse."
            )
            actions = [
                "Verifier les usages de chauffage electrique.",
                "Ameliorer l'isolation de l'enveloppe et l'etancheite a l'air.",
                "Programmer les charges thermiques hors heures de pointe si possible.",
            ]
            interpretation = "froid_chauffage"

        else:
            niveau = "info"
            titre = "Signature thermique moderee"
            message = (
                f"La correlation consommation/temperature est de {corr:.2f}. "
                "La temperature exterieure n'explique pas seule le profil de charge."
            )
            actions = [
                "Completer l'analyse par usage: eclairage, process, bureautique, pompage, CVC.",
                "Comparer les jours ouvrables et week-ends pour identifier les usages dominants.",
            ]
            interpretation = "moderee"

        return Recommandation(
            categorie="signature_thermique",
            niveau=niveau,
            titre=titre,
            message=message,
            actions=actions,
            indicateurs={
                "correlation_consommation_temperature": round(corr, 3),
                "interpretation": interpretation,
            },
        )

    # --------------------------------------------------------------------------
    # 3. OPTIMISATION SOLAIRE / AUTOCONSOMMATION
    # --------------------------------------------------------------------------

    def analyser_optimisation_solaire(self) -> Optional[Recommandation]:
        if self.production is None or "Production_kWh" not in self.production.columns:
            return None

        n = min(len(self.conso), len(self.production))
        conso = self.conso["Consommation_kWh"].iloc[:n].to_numpy(dtype=float)
        prod = self.production["Production_kWh"].iloc[:n].to_numpy(dtype=float)

        autoconso = np.minimum(conso, prod)
        injection = np.maximum(0, prod - conso)

        prod_tot = float(prod.sum())
        conso_tot = float(conso.sum())
        autoconso_tot = float(autoconso.sum())
        injection_tot = float(injection.sum())

        taux_autoconso = autoconso_tot / prod_tot if prod_tot > 0 else 0
        taux_autoproduction = autoconso_tot / conso_tot if conso_tot > 0 else 0
        taux_injection = injection_tot / prod_tot if prod_tot > 0 else 0

        if taux_injection > 0.20:
            niveau = "warning"
            titre = "Injection solaire elevee"
            message = (
                f"Le taux d'injection estime est de {taux_injection*100:.1f}%, "
                "superieur au seuil de reference de 20%. Le systeme pourrait etre surdimensionne "
                "par rapport a la charge de jour."
            )
            actions = [
                "Reduire la puissance crete ou tester un scenario intermediaire.",
                "Deplacer des charges vers les heures solaires: pompage, chauffe-eau, climatisation, recharge VE.",
                "Etudier un stockage si l'objectif est l'autonomie ou la reduction d'injection.",
                "Verifier les conditions reglementaires d'injection applicables au contrat.",
            ]

        elif taux_autoconso >= 0.75:
            niveau = "success"
            titre = "Bonne adequation production solaire / consommation"
            message = (
                f"Le taux d'autoconsommation estime est de {taux_autoconso*100:.1f}%. "
                "La puissance PV semble bien adaptee au profil de charge."
            )
            actions = [
                "Maintenir ce scenario comme reference.",
                "Optimiser les usages de jour pour augmenter encore l'autoproduction.",
                "Verifier la contrainte toiture et le budget CAPEX.",
            ]

        else:
            niveau = "info"
            titre = "Autoconsommation ameliorable"
            message = (
                f"Le taux d'autoconsommation estime est de {taux_autoconso*100:.1f}%. "
                "Une optimisation des usages peut ameliorer la rentabilite."
            )
            actions = [
                "Programmer les usages flexibles entre 10h et 16h.",
                "Comparer plusieurs puissances cretes pour identifier le meilleur compromis.",
                "Analyser les profils week-end et jours ouvrables.",
            ]

        return Recommandation(
            categorie="optimisation_solaire",
            niveau=niveau,
            titre=titre,
            message=message,
            actions=actions,
            indicateurs={
                "production_kwh": round(prod_tot, 2),
                "consommation_kwh": round(conso_tot, 2),
                "autoconsommation_kwh": round(autoconso_tot, 2),
                "injection_kwh": round(injection_tot, 2),
                "taux_autoconso_pct": round(taux_autoconso * 100, 2),
                "taux_autoproduction_pct": round(taux_autoproduction * 100, 2),
                "taux_injection_pct": round(taux_injection * 100, 2),
            },
        )

    # --------------------------------------------------------------------------
    # 4. COMPENSATION REACTIVE
    # --------------------------------------------------------------------------

    def analyser_compensation_reactive(self) -> Optional[Recommandation]:
        pf_col = self._trouver_colonne_pf()
        if pf_col is None:
            return Recommandation(
                categorie="compensation_reactive",
                niveau="info",
                titre="Facteur de puissance non disponible",
                message=(
                    "Aucune colonne de facteur de puissance n'a ete detectee. "
                    "Le diagnostic des penalites d'energie reactive ne peut pas etre etabli."
                ),
                actions=[
                    "Importer un fichier analyseur reseau contenant PF, cos phi, Q ou S.",
                    "Mesurer le facteur de puissance en periode de charge representative.",
                ],
                indicateurs={"pf_disponible": False},
            )

        pf = pd.to_numeric(self.reseau[pf_col], errors="coerce").dropna()
        if pf.empty:
            return None

        pf_moy = float(pf.mean())
        pf_min = float(pf.min())

        if pf_moy < 0.90:
            niveau = "danger"
            titre = "Facteur de puissance faible"
            message = (
                f"Le facteur de puissance moyen est de {pf_moy:.2f}, inferieur au seuil 0.90. "
                "Cela peut entrainer des penalites ou une mauvaise utilisation de la puissance souscrite."
            )
            actions = [
                "Realiser une etude de compensation reactive.",
                "Installer une batterie de condensateurs automatique adaptee au profil de charge.",
                "Verifier moteurs, compresseurs, pompes et charges inductives.",
                "Surveiller le cos phi par poste horaire et par saison.",
            ]
        else:
            niveau = "success"
            titre = "Facteur de puissance acceptable"
            message = (
                f"Le facteur de puissance moyen est de {pf_moy:.2f}. "
                "Aucune alerte majeure de compensation reactive n'est detectee."
            )
            actions = [
                "Continuer le suivi du facteur de puissance.",
                "Verifier le cos phi apres ajout de nouveaux moteurs ou onduleurs.",
            ]

        return Recommandation(
            categorie="compensation_reactive",
            niveau=niveau,
            titre=titre,
            message=message,
            actions=actions,
            indicateurs={
                "pf_disponible": True,
                "pf_moyen": round(pf_moy, 3),
                "pf_min": round(pf_min, 3),
            },
        )

    def _trouver_colonne_pf(self) -> Optional[str]:
        if self.reseau is None:
            return None

        for col in self.reseau.columns:
            c = str(col).strip().lower()
            if c in ["pf", "cos_phi", "cos phi", "cosφ", "facteur_puissance", "power_factor"]:
                return col

        for col in self.reseau.columns:
            c = str(col).lower()
            if "pf" in c or "cos" in c or "power factor" in c or "facteur" in c:
                return col

        return None

    # --------------------------------------------------------------------------
    # 5. PICS ET LOAD SHIFTING
    # --------------------------------------------------------------------------

    def analyser_pics_et_load_shifting(self) -> Recommandation:
        df = self.conso.copy()
        df["DateTime"] = pd.to_datetime(df["DateTime"])
        df["Heure"] = df["DateTime"].dt.hour

        conso = df["Consommation_kWh"]
        seuil_pic = float(conso.quantile(0.95))
        nb_pics = int((conso >= seuil_pic).sum())

        # Pointe indicative soir Maroc; la tarification precise est dans module ONEE.
        pics_soir = df[(conso >= seuil_pic) & (df["Heure"].between(18, 21))]
        pct_pics_soir = len(pics_soir) / nb_pics * 100 if nb_pics > 0 else 0

        if pct_pics_soir > 30:
            niveau = "warning"
            titre = "Pics significatifs en periode du soir"
            message = (
                f"{pct_pics_soir:.1f}% des pics de charge apparaissent entre 18h et 21h. "
                "Un deplacement de certaines charges peut reduire la facture et lisser la puissance appelee."
            )
            actions = [
                "Eviter le demarrage simultane des gros equipements.",
                "Decaler les usages flexibles vers les heures solaires ou creuses.",
                "Installer un systeme de delestage ou de pilotage energetique.",
                "Pour le tertiaire, analyser la puissance souscrite et les appels de puissance.",
            ]
        else:
            niveau = "info"
            titre = "Pics de charge a surveiller"
            message = (
                f"Le seuil des 5% plus fortes charges est de {seuil_pic:.2f} kWh/h. "
                "Les pics ne sont pas majoritairement concentres le soir."
            )
            actions = [
                "Identifier les equipements responsables des pics.",
                "Suivre l'evolution de la puissance maximale mensuelle.",
            ]

        return Recommandation(
            categorie="pics_load_shifting",
            niveau=niveau,
            titre=titre,
            message=message,
            actions=actions,
            indicateurs={
                "seuil_pic_95pct_kwh_h": round(seuil_pic, 2),
                "nombre_heures_pic": nb_pics,
                "part_pics_18_21_pct": round(pct_pics_soir, 2),
            },
        )

    # --------------------------------------------------------------------------
    # 6. QUALITE DES DONNEES
    # --------------------------------------------------------------------------

    def analyser_qualite_donnees(self) -> Optional[Recommandation]:
        if not self.diagnostic_donnees:
            return None

        qualite = self.diagnostic_donnees.get("qualite", "inconnue")
        messages_diag = self.diagnostic_donnees.get("messages", [])

        if qualite == "bonne":
            niveau = "success"
            titre = "Qualite des donnees satisfaisante"
            message = "L'historique importe est suffisamment propre pour une analyse de pre-faisabilite."
            actions = [
                "Conserver le fichier source comme annexe du rapport.",
                "Mettre a jour l'analyse avec des donnees plus recentes si disponibles.",
            ]
        elif qualite == "moyenne":
            niveau = "warning"
            titre = "Qualite des donnees moyenne"
            message = (
                "Certaines anomalies ont ete detectees dans l'historique. "
                "Les resultats restent exploitables mais doivent etre interpretes avec prudence."
            )
            actions = [
                "Verifier les periodes manquantes ou les doublons.",
                "Comparer avec les factures ONEE ou l'export compteur original.",
                "Relancer l'analyse avec un historique plus complet si possible.",
            ]
        else:
            niveau = "danger"
            titre = "Qualite des donnees faible"
            message = (
                "Les donnees importees presentent des anomalies importantes. "
                "Le dimensionnement PV peut etre fortement influence par ces erreurs."
            )
            actions = [
                "Corriger le fichier source avant decision.",
                "Verifier l'unite de mesure: kWh, index kWh, puissance kW.",
                "Importer un historique plus fiable ou plus long.",
            ]

        return Recommandation(
            categorie="qualite_donnees",
            niveau=niveau,
            titre=titre,
            message=message,
            actions=actions,
            indicateurs={
                "qualite": qualite,
                "messages": messages_diag,
                "pas_detecte": self.diagnostic_donnees.get("pas_detecte"),
                "source_detectee": self.diagnostic_donnees.get("source_detectee"),
            },
        )
