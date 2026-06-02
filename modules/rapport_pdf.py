"""
Module Rapport PDF - Opti-Solar Maroc

Objectif:
Generer un rapport PDF de pre-faisabilite technico-economique.

Important:
Ce rapport ne doit pas etre presente comme une certification, une etude
d'execution ou une validation bancaire. Il s'agit d'une aide a la decision.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from fpdf import FPDF


class RapportPDF(FPDF):
    def __init__(self, titre_projet: str = "Projet Photovoltaique", type_contrat: str = "N/A"):
        super().__init__()
        self.titre_projet = titre_projet
        self.type_contrat = type_contrat
        self.set_auto_page_break(auto=True, margin=15)

        self.color_primary = (255, 107, 53)
        self.color_blue = (52, 100, 160)
        self.color_green = (46, 140, 90)
        self.color_yellow = (230, 170, 40)
        self.color_red = (190, 60, 60)
        self.color_gray = (245, 245, 245)

    # ----------------------------------------------------------------------
    # BASE
    # ----------------------------------------------------------------------

    def header(self):
        self.set_fill_color(*self.color_primary)
        self.rect(10, 10, 18, 8, "F")

        self.set_font("Helvetica", "B", 16)
        self.set_text_color(*self.color_primary)
        self.set_xy(33, 8)
        self.cell(0, 8, "OPTI-SOLAR MAROC", 0, 1, "L")

        self.set_font("Helvetica", "", 8)
        self.set_text_color(90, 90, 90)
        self.set_x(33)
        self.cell(0, 5, "Rapport de pre-faisabilite technico-economique photovoltaique", 0, 1, "L")

        self.set_draw_color(*self.color_primary)
        self.set_line_width(0.4)
        self.line(10, 23, 200, 23)
        self.ln(8)

    def footer(self):
        self.set_y(-14)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, f"Page {self.page_no()}/{{nb}}", 0, 0, "C")
        self.set_x(10)
        self.cell(0, 8, f"Genere le {datetime.now().strftime('%d/%m/%Y')}", 0, 0, "L")
        self.set_x(-65)
        self.cell(55, 8, "Document indicatif", 0, 0, "R")

    def titre_chapitre(self, numero: int, titre: str):
        self.set_font("Helvetica", "B", 14)
        self.set_fill_color(*self.color_primary)
        self.set_text_color(255, 255, 255)
        self.cell(0, 9, f" {numero}. {titre}", 0, 1, "L", True)
        self.ln(3)

    def sous_titre(self, titre: str):
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*self.color_blue)
        self.cell(0, 7, titre, 0, 1, "L")

    def texte(self, texte: str):
        self.set_font("Helvetica", "", 9)
        self.set_text_color(0, 0, 0)
        self.set_x(self.l_margin)
        self.multi_cell(0, 5, self._safe(texte), 0, "L")
        self.ln(1)

    def _safe(self, value: Any) -> str:
        text = str(value)
        replacements = {
            "é": "e", "è": "e", "ê": "e", "ë": "e",
            "à": "a", "â": "a",
            "î": "i", "ï": "i",
            "ô": "o",
            "ù": "u", "û": "u",
            "ç": "c",
            "É": "E", "È": "E", "À": "A", "Ç": "C",
            "°": " deg", "²": "2", "³": "3",
            "–": "-", "—": "-", "’": "'", "“": '"', "”": '"',
            "φ": "phi", "≥": ">=", "≤": "<=",
        }
        for k, v in replacements.items():
            text = text.replace(k, v)
        return text

    def alerte(self, titre: str, message: str, niveau: str = "info"):
        colors = {
            "success": self.color_green,
            "warning": self.color_yellow,
            "danger": self.color_red,
            "info": self.color_blue,
        }
        color = colors.get(niveau, self.color_blue)

        x = self.get_x()
        y = self.get_y()
        width = 190

        self.set_draw_color(*color)
        self.set_fill_color(250, 250, 250)
        self.rect(x, y, width, 18, "DF")

        self.set_xy(x + 3, y + 2)
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*color)
        self.cell(width - 6, 5, self._safe(titre), 0, 1)

        self.set_x(x + 3)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(0, 0, 0)
        self.set_x(x + 3)
        self.multi_cell(width - 6, 4, self._safe(message), 0, "L")

        self.set_y(y + 20)

    def tableau_2col(self, data: Dict[str, Any], col1: int = 85):
        self.set_font("Helvetica", "", 8)

        for i, (key, value) in enumerate(data.items()):
            fill = i % 2 == 0
            self.set_fill_color(248, 248, 248) if fill else self.set_fill_color(255, 255, 255)

            self.set_text_color(70, 70, 70)
            self.cell(col1, 6, self._safe(key), 1, 0, "L", True)

            self.set_text_color(0, 0, 0)
            self.set_font("Helvetica", "B", 8)
            self.cell(0, 6, self._safe(value), 1, 1, "R", True)
            self.set_font("Helvetica", "", 8)

        self.ln(2)

    def kpi_row(self, kpis: List[Dict[str, Any]]):
        width = 190 / max(1, len(kpis))
        y = self.get_y()

        for kpi in kpis:
            x = self.get_x()
            self.set_fill_color(*self.color_gray)
            self.rect(x, y, width - 2, 20, "F")

            self.set_xy(x + 2, y + 2)
            self.set_font("Helvetica", "", 8)
            self.set_text_color(80, 80, 80)
            self.cell(width - 6, 5, self._safe(kpi.get("label", "")), 0, 1, "C")

            self.set_x(x + 2)
            self.set_font("Helvetica", "B", 12)
            self.set_text_color(*self.color_primary)
            self.cell(width - 6, 8, self._safe(kpi.get("value", "")), 0, 1, "C")

            self.set_xy(x + width, y)

        self.set_y(y + 23)

    # ----------------------------------------------------------------------
    # SECTIONS
    # ----------------------------------------------------------------------

    def page_garde(self, resultats: Dict[str, Any]):
        self.add_page()
        self.ln(35)

        self.set_font("Helvetica", "B", 24)
        self.set_text_color(*self.color_primary)
        self.set_x(self.l_margin)
        self.multi_cell(0, 12, "RAPPORT DE PRE-FAISABILITE", 0, "C")

        self.set_font("Helvetica", "B", 18)
        self.set_text_color(0, 0, 0)
        self.set_x(self.l_margin)
        self.multi_cell(0, 10, "SYSTEME PHOTOVOLTAIQUE", 0, "C")

        self.ln(10)

        self.set_font("Helvetica", "", 12)
        self.set_text_color(*self.color_blue)
        self.cell(0, 8, self._safe(self.titre_projet), 0, 1, "C")

        self.ln(15)

        self.set_fill_color(248, 248, 248)
        self.rect(30, self.get_y(), 150, 58, "F")
        self.set_y(self.get_y() + 5)

        infos = {
            "Ville": resultats.get("ville", "N/A"),
            "Type batiment": resultats.get("type_batiment", "N/A"),
            "Type contrat": resultats.get("type_contrat", self.type_contrat),
            "Type systeme": resultats.get("type_systeme", "N/A"),
            "Puissance PV": f"{resultats.get('pc_kwc', 0):,.2f} kWc",
            "CAPEX estime": f"{resultats.get('capex_total_mad', 0):,.0f} MAD",
        }

        self.set_x(40)
        self.tableau_2col(infos, col1=60)

        self.ln(15)
        self.alerte(
            "Limites du rapport",
            "Ce rapport est une estimation de pre-dimensionnement. Il ne remplace pas une etude electrique "
            "d'execution, une etude de raccordement, un devis fournisseur, ni une validation administrative.",
            "warning",
        )

    def section_resume_executif(self, resultats: Dict[str, Any]):
        self.add_page()
        self.titre_chapitre(1, "Resume executif")

        kpis = resultats.get("kpis", {})
        self.kpi_row([
            {"label": "Puissance", "value": f"{kpis.get('pc_kwc', 0):.1f} kWc"},
            {"label": "Production", "value": f"{kpis.get('production_kwh', 0)/1000:.1f} MWh/an"},
            {"label": "Autoconso", "value": f"{kpis.get('taux_autoconso_pct', 0):.1f}%"},
        ])
        self.kpi_row([
            {"label": "CAPEX", "value": f"{kpis.get('capex_mad', 0)/1000:.0f} kMAD"},
            {"label": "VAN", "value": f"{kpis.get('van_mad', 0)/1000:.0f} kMAD"},
            {"label": "Retour", "value": f"{kpis.get('retour_ans', 0)} ans"},
        ])

        conclusion = resultats.get("conclusion", "Le projet doit etre confirme par une etude detaillee.")
        self.texte(conclusion)

    def section_qualite_donnees(self, diagnostic: Dict[str, Any]):
        self.titre_chapitre(2, "Qualite des donnees importees")

        if not diagnostic:
            self.alerte("Donnees non documentees", "Aucun diagnostic de donnees n'a ete fourni.", "warning")
            return

        self.tableau_2col({
            "Source detectee": diagnostic.get("source_detectee", "N/A"),
            "Mesure detectee": diagnostic.get("mesure_detectee", "N/A"),
            "Colonne DateTime": diagnostic.get("colonne_datetime", "N/A"),
            "Colonne principale": diagnostic.get("colonne_principale", "N/A"),
            "Pas detecte": diagnostic.get("pas_detecte", "N/A"),
            "Lignes originales": diagnostic.get("nombre_lignes_original", "N/A"),
            "Lignes horaires": diagnostic.get("nombre_lignes_horaires", "N/A"),
            "Periode": f"{diagnostic.get('date_debut', 'N/A')} -> {diagnostic.get('date_fin', 'N/A')}",
            "Qualite": diagnostic.get("qualite", "N/A"),
        })

        for msg in diagnostic.get("messages", []):
            self.texte(f"- {msg}")

    def section_localisation_solaire(self, stats_tmy: Dict[str, Any]):
        self.add_page()
        self.titre_chapitre(3, "Localisation et donnees solaires")

        self.tableau_2col({
            "Ville": stats_tmy.get("ville", "N/A"),
            "Latitude": stats_tmy.get("latitude", "N/A"),
            "Longitude": stats_tmy.get("longitude", "N/A"),
            "Altitude": f"{stats_tmy.get('altitude', 0)} m",
            "Timezone": stats_tmy.get("timezone", "N/A"),
            "GHI annuel": f"{stats_tmy.get('irradiation_annuelle_ghi_kwh_m2', 0):,.1f} kWh/m2/an",
            "GPI annuel": f"{stats_tmy.get('irradiation_annuelle_gpi_kwh_m2', 0):,.1f} kWh/m2/an",
            "Temperature moyenne": f"{stats_tmy.get('temperature_moyenne_c', 0):.1f} degC",
            "Temperature max": f"{stats_tmy.get('temperature_max_c', 0):.1f} degC",
            "Temperature min": f"{stats_tmy.get('temperature_min_c', 0):.1f} degC",
        })

    def section_consommation(self, stats_conso: Dict[str, Any]):
        self.titre_chapitre(4, "Analyse de consommation")

        self.tableau_2col({
            "Consommation annuelle": f"{stats_conso.get('consommation_annuelle_kwh', 0):,.0f} kWh",
            "Puissance moyenne": f"{stats_conso.get('puissance_moyenne_kw', 0):.2f} kW",
            "Puissance maximale": f"{stats_conso.get('puissance_max_kw', 0):.2f} kW",
            "Facteur de charge": f"{stats_conso.get('facteur_charge', 0)*100:.1f}%",
        })

    def section_recommandations(self, recommandations: Dict[str, Any]):
        self.add_page()
        self.titre_chapitre(5, "Recommandations ISO 50001 et efficacite energetique")

        self.texte(
            "Les recommandations suivantes sont generees a partir du profil de charge, des donnees meteo "
            "et des mesures reseau disponibles. Elles constituent une aide au diagnostic energetique."
        )

        for reco in recommandations.get("recommandations", []):
            self.alerte(
                reco.get("titre", "Recommandation"),
                reco.get("message", ""),
                reco.get("niveau", "info"),
            )
            actions = reco.get("actions", [])
            for action in actions:
                self.texte(f"- {action}")

    def section_dimensionnement(self, dimensionnement: Dict[str, Any]):
        self.add_page()
        self.titre_chapitre(6, "Dimensionnement technique indicatif")

        general = dimensionnement.get("general", {})
        self.sous_titre("Champ photovoltaique")
        self.tableau_2col({
            "Nombre panneaux": general.get("nombre_modules", "N/A"),
            "Puissance reelle": f"{general.get('puissance_reelle_kwc', 0)} kWc",
            "Surface panneaux": f"{general.get('surface_panneaux_m2', 0)} m2",
            "U_sys recommande": f"{general.get('u_sys_recommande_v', 0)} V",
        })

        compat = dimensionnement.get("compatibilite_onduleur", {})
        self.sous_titre("Onduleur")
        self.tableau_2col({
            "Puissance OK 80-110%": "Oui" if compat.get("puissance_ok_80_110") else "Non",
            "Chaines requises": compat.get("chaines_requises", "N/A"),
            "Ns min/max": f"{compat.get('ns_min', '?')} / {compat.get('ns_max', '?')}",
            "Compatible global": "Oui" if compat.get("compatible_global") else "Non",
        })

        batteries = dimensionnement.get("batteries")
        if batteries:
            self.sous_titre("Stockage")
            self.tableau_2col({
                "Autonomie": f"{batteries.get('autonomie_jours', 0)} jours",
                "Capacite installee": f"{batteries.get('capacite_installee_kwh', 0)} kWh",
                "Capacite requise": f"{batteries.get('capacite_requise_ah', 0)} Ah",
                "Nombre total": batteries.get("nombre_total_batteries", 0),
            })

        self.alerte(
            "Validation requise",
            "Les sections de cables, protections, mise a la terre et parafoudres doivent etre valides "
            "par une etude electrique d'execution selon le site reel.",
            "warning",
        )

    def section_economie(self, economie: Dict[str, Any]):
        self.add_page()
        self.titre_chapitre(7, "Analyse economique")

        indicateurs = economie.get("indicateurs_rentabilite", {})
        eco = economie.get("economique", {})
        prod = economie.get("production", {})
        perf = economie.get("performance", {})

        self.sous_titre("Indicateurs financiers")
        self.tableau_2col({
            "VAN": f"{indicateurs.get('van_mad', 0):,.0f} MAD",
            "TRI": f"{indicateurs.get('tri_pct', 'N/A')} %",
            "LCOE": f"{indicateurs.get('lcoe_mad_kwh', 0)} MAD/kWh",
            "Retour simple": f"{indicateurs.get('periode_retour_simple_ans', 'N/A')} ans",
            "Retour actualise": f"{indicateurs.get('periode_retour_actualisee_ans', 'N/A')} ans",
            "Rentable": "Oui" if indicateurs.get("rentable") else "Non",
        })

        self.sous_titre("Bilan energie/economie")
        self.tableau_2col({
            "Production an 1": f"{prod.get('annuelle_an1_kwh', 0):,.0f} kWh",
            "Taux autoconso": f"{perf.get('taux_autoconso_an1_pct', 0)}%",
            "Taux autoproduction": f"{perf.get('taux_autoproduction_an1_pct', 0)}%",
            "Economies brutes": f"{eco.get('economies_brutes_mad', 0):,.0f} MAD",
            "OPEX total": f"{eco.get('opex_total_mad', 0):,.0f} MAD",
            "Benefice net": f"{eco.get('benefice_net_mad', 0):,.0f} MAD",
        })

    def section_reglementaire_maintenance(self, resultats: Dict[str, Any]):
        self.add_page()
        self.titre_chapitre(8, "Cadre reglementaire et maintenance")

        self.sous_titre("References prises en compte")
        self.texte("- Loi 82-21 sur l'autoproduction d'electricite.")
        self.texte("- Decret 2-25-100 et textes d'application selon cas.")
        self.texte("- Decision ANRE 04/26 pour l'excedent si applicable.")
        self.texte("- NF C 15-100, NF C 15-712-1, IEC 62446 comme references techniques.")

        self.alerte(
            "Conformite a confirmer",
            "Le simulateur estime le regime et les contraintes. La conformite finale depend de l'etude "
            "technique, du gestionnaire de reseau, du contrat et de la validation administrative.",
            "warning",
        )

        self.sous_titre("Plan de maintenance indicatif")
        maintenance = {
            "Nettoyage panneaux": "Mensuel a bimensuel selon poussiere/site",
            "Inspection visuelle": "Trimestrielle",
            "Suivi production": "Mensuel",
            "Verification connexions/cables": "Annuelle",
            "Verification mise a la terre": "Annuelle",
            "Thermographie": "Recommandee selon taille/risque",
            "Onduleur": "Remplacement possible vers annee 10-15",
        }
        self.tableau_2col(maintenance)


# ==============================================================================
# FONCTION PRINCIPALE
# ==============================================================================

def generer_rapport_pdf(resultats: Dict[str, Any], fichier_sortie: str = "rapport_opti_solar.pdf") -> str:
    """
    Genere le rapport PDF.

    Structure attendue dans resultats:
    - nom_projet
    - type_contrat
    - kpis
    - diagnostic_donnees
    - stats_tmy
    - stats_conso
    - recommandations
    - dimensionnement
    - economie
    """
    output = Path(fichier_sortie)
    output.parent.mkdir(parents=True, exist_ok=True)

    pdf = RapportPDF(
        titre_projet=resultats.get("nom_projet", "Projet photovoltaique"),
        type_contrat=resultats.get("type_contrat", "N/A"),
    )
    pdf.alias_nb_pages()

    pdf.page_garde(resultats)
    pdf.section_resume_executif(resultats)
    pdf.section_qualite_donnees(resultats.get("diagnostic_donnees", {}))
    pdf.section_localisation_solaire(resultats.get("stats_tmy", {}))
    pdf.section_consommation(resultats.get("stats_conso", {}))
    pdf.section_recommandations(resultats.get("recommandations", {}))
    pdf.section_dimensionnement(resultats.get("dimensionnement", {}))
    pdf.section_economie(resultats.get("economie", {}))
    pdf.section_reglementaire_maintenance(resultats)

    pdf.output(str(output))
    return str(output)
