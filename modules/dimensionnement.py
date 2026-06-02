"""
Module de Dimensionnement - Opti-Solar Maroc

Objectif:
- Pre-dimensionner les composants PV:
  panneaux, onduleur, batteries, cables, protections, CAPEX.
- Fournir des ordres de grandeur coherents pour l'application.

Important:
Ce module ne remplace pas une note de calcul electrique d'execution.
Les sections, protections, parafoudres et raccordements doivent etre valides
par un bureau d'etudes/installateur qualifie selon le site reel.
"""

from __future__ import annotations

import math
from typing import Dict, Any, Optional, List


class ComponentSizerAdvanced:
    def __init__(
        self,
        config_settings: Dict[str, Any],
        puissance_crete_kwc: float,
        type_systeme: str,
        consommation_annuelle_kwh: Optional[float] = None,
        pic_consommation_kw: Optional[float] = None,
        temperature_min_site_c: float = -5.0,
    ):
        self.config = config_settings
        self.pc_kwc = float(puissance_crete_kwc)
        self.type_systeme = type_systeme
        self.conso_annuelle = consommation_annuelle_kwh
        self.pic_conso = pic_consommation_kw
        self.temperature_min_site_c = temperature_min_site_c

        if self.pc_kwc <= 0:
            raise ValueError("puissance_crete_kwc doit etre strictement positive.")

        if type_systeme not in ["on-grid", "off-grid", "hybride"]:
            raise ValueError("type_systeme doit etre: on-grid, off-grid ou hybride.")

    # --------------------------------------------------------------------------
    # PANNEAUX
    # --------------------------------------------------------------------------

    def dimensionner_panneaux(self) -> Dict[str, Any]:
        panel = self.config["panel"]

        p_module_w = panel["puissance_nominale_w"]
        p_module_kw = p_module_w / 1000.0

        nb_min = math.ceil(self.pc_kwc / p_module_kw)

        vmp = panel["v_mp"]
        voc = panel["v_oc"]
        imp = panel["i_mp"]
        isc = panel["i_sc"]

        voc_froid = self._calculer_voc_froid(voc, panel.get("coef_temp_voc", -0.0029))
        tension_max_onduleur = 1000.0
        tension_cible = 500.0

        panneaux_serie_cible = max(1, round(tension_cible / vmp))
        panneaux_serie_max = max(1, math.floor(tension_max_onduleur / voc_froid))
        panneaux_serie = min(panneaux_serie_cible, panneaux_serie_max)

        # Chercher une configuration proche de la puissance cible sans depassement excessif.
        config_candidates = []
        for serie in range(max(1, panneaux_serie - 4), panneaux_serie_max + 1):
            chaines = math.ceil(nb_min / serie)
            nb_total = serie * chaines
            pc_reelle = nb_total * p_module_kw
            ecart_pct = abs(pc_reelle - self.pc_kwc) / self.pc_kwc
            depassement_pct = max(0, pc_reelle - self.pc_kwc) / self.pc_kwc
            config_candidates.append((depassement_pct, ecart_pct, nb_total, serie, chaines, pc_reelle))

        config_candidates.sort(key=lambda x: (x[0] > 0.12, x[1]))
        _, _, nb_panneaux, panneaux_serie, nb_chaines, pc_reelle = config_candidates[0]

        surface_panneaux = nb_panneaux * panel["surface_m2"]
        surface_toiture = surface_panneaux * 1.15
        poids_total = nb_panneaux * panel.get("poids_kg", 28.0)

        tension_chaine_nominale = panneaux_serie * vmp
        tension_max_chaine = panneaux_serie * voc_froid
        courant_chaine_nominal = imp
        courant_total_nominal = nb_chaines * imp
        courant_total_isc = nb_chaines * isc

        cout_panneaux = nb_panneaux * panel.get("prix_unitaire_mad", 1200.0)

        return {
            "nombre_panneaux": nb_panneaux,
            "puissance_unitaire_w": p_module_w,
            "puissance_crete_reelle_kwc": round(pc_reelle, 3),
            "puissance_crete_cible_kwc": round(self.pc_kwc, 3),
            "ecart_puissance_pct": round((pc_reelle - self.pc_kwc) / self.pc_kwc * 100, 2),
            "surface_panneaux_m2": round(surface_panneaux, 2),
            "surface_toiture_necessaire_m2": round(surface_toiture, 2),
            "poids_total_kg": round(poids_total, 1),
            "configuration": {
                "panneaux_par_chaine": panneaux_serie,
                "nombre_chaines": nb_chaines,
                "connexion": f"{nb_chaines}P x {panneaux_serie}S",
            },
            "electrique": {
                "vmp_module_v": vmp,
                "voc_module_stc_v": voc,
                "voc_module_froid_v": round(voc_froid, 2),
                "tension_chaine_nominale_v": round(tension_chaine_nominale, 1),
                "tension_max_chaine_froid_v": round(tension_max_chaine, 1),
                "courant_chaine_nominal_a": round(courant_chaine_nominal, 2),
                "courant_total_nominal_a": round(courant_total_nominal, 2),
                "courant_total_isc_a": round(courant_total_isc, 2),
            },
            "cout": {
                "prix_unitaire_mad": panel.get("prix_unitaire_mad", 1200.0),
                "total_panneaux_mad": round(cout_panneaux, 0),
            },
            "note": "Configuration indicative a verifier avec les plages MPPT de l'onduleur choisi.",
        }

    def _calculer_voc_froid(self, voc_stc: float, coef_temp_voc: float) -> float:
        delta = 25.0 - self.temperature_min_site_c
        return voc_stc * (1 + abs(coef_temp_voc) * delta)

    # --------------------------------------------------------------------------
    # ONDULEUR
    # --------------------------------------------------------------------------

    def dimensionner_onduleur(self) -> Dict[str, Any]:
        specs = self.config["onduleur"]

        ratio = specs.get("ratio_surdimensionnement", 1.2)
        p_ac_cible = self.pc_kwc / ratio

        puissances_std = [3, 5, 6, 8, 10, 12, 15, 20, 25, 30, 36, 40, 50, 60, 80, 100, 125, 150, 200, 250, 300, 500]
        p_std = min([p for p in puissances_std if p >= p_ac_cible], default=puissances_std[-1])

        if p_std <= 10:
            tension_sortie = 230
            phases = 1
            niveau_tension = "BT monophase"
        else:
            tension_sortie = 400
            phases = 3
            niveau_tension = "BT triphase" if p_std <= 250 else "MT via poste de transformation"

        if self.type_systeme == "on-grid":
            type_onduleur = "Onduleur string raccorde reseau"
            batteries_compatible = False
        elif self.type_systeme == "off-grid":
            type_onduleur = "Onduleur-chargeur autonome"
            batteries_compatible = True
        else:
            type_onduleur = "Onduleur hybride bidirectionnel"
            batteries_compatible = True

        cout = p_std * specs.get("prix_par_kw_mad", 2500.0)

        return {
            "puissance_nominale_kw": p_std,
            "puissance_ac_cible_kw": round(p_ac_cible, 2),
            "type": type_onduleur,
            "niveau_tension": niveau_tension,
            "tension_sortie_v": tension_sortie,
            "phases": phases,
            "ratio_dc_ac": round(self.pc_kwc / p_std, 2),
            "batteries_compatible": batteries_compatible,
            "rendement": {
                "nominal": specs.get("rendement_nominal", 0.98),
                "europeen": specs.get("rendement_euro", 0.975),
            },
            "duree_vie_ans": specs.get("duree_vie_ans", 12),
            "garantie_ans": specs.get("garantie_ans", 10),
            "cout": {
                "prix_par_kw_mad": specs.get("prix_par_kw_mad", 2500.0),
                "total_onduleur_mad": round(cout, 0),
            },
            "note": "Selection indicative. Verifier nombre MPPT, tension min/max MPPT et courant admissible.",
        }

    # --------------------------------------------------------------------------
    # BATTERIES
    # --------------------------------------------------------------------------

    def dimensionner_batteries(self) -> Optional[Dict[str, Any]]:
        if self.type_systeme == "on-grid":
            return None

        specs = self.config["batterie"]

        if self.conso_annuelle:
            conso_journaliere = self.conso_annuelle / 365.0
        else:
            conso_journaliere = self.pc_kwc * 4.0

        jours_autonomie = specs.get("autonomie_jours", 2.0)
        dod = specs.get("dod_recommandee", 0.70)

        capacite_utile = conso_journaliere * jours_autonomie
        capacite_totale = capacite_utile / dod if dod > 0 else capacite_utile

        tension = specs.get("tension_nominale_v", 48.0)
        capacite_unitaire_ah = specs.get("capacite_unitaire_ah", 200.0)
        capacite_unitaire_kwh = tension * capacite_unitaire_ah / 1000.0

        nb_batteries = math.ceil(capacite_totale / capacite_unitaire_kwh)
        capacite_reelle = nb_batteries * capacite_unitaire_kwh
        capacite_utile_reelle = capacite_reelle * dod

        cycles = specs.get("cycles_vie_80dod", 8000)
        duree_vie_ans = cycles / 365.0

        cout_batteries = capacite_reelle * specs.get("prix_par_kwh_mad", 3500.0)
        cout_bms = specs.get("prix_bms_mad", 5000.0)
        cout_accessoires = nb_batteries * 500.0
        cout_total = cout_batteries + cout_bms + cout_accessoires

        return {
            "nombre_batteries": nb_batteries,
            "technologie": "Lithium LiFePO4",
            "capacite": {
                "unitaire_kwh": round(capacite_unitaire_kwh, 2),
                "totale_kwh": round(capacite_reelle, 2),
                "utile_kwh": round(capacite_utile_reelle, 2),
                "dod_recommande_pct": round(dod * 100, 1),
            },
            "electrique": {
                "tension_nominale_v": tension,
                "capacite_unitaire_ah": capacite_unitaire_ah,
            },
            "autonomie_jours": jours_autonomie,
            "duree_vie": {
                "cycles_vie": cycles,
                "annees_estimees": round(duree_vie_ans, 1),
                "annee_remplacement": math.ceil(duree_vie_ans),
            },
            "cout": {
                "prix_par_kwh_mad": specs.get("prix_par_kwh_mad", 3500.0),
                "batteries_mad": round(cout_batteries, 0),
                "bms_mad": round(cout_bms, 0),
                "accessoires_mad": round(cout_accessoires, 0),
                "total_batteries_mad": round(cout_total, 0),
            },
            "note": "Dimensionnement indicatif. Pour systemes tertiaires, verifier compatibilite batteries HV/onduleur.",
        }

    # --------------------------------------------------------------------------
    # CABLES
    # --------------------------------------------------------------------------

    def dimensionner_cables_precis(
        self,
        distance_panneaux_onduleur_m: float = 30.0,
        distance_onduleur_tableau_m: float = 20.0,
    ) -> Dict[str, Any]:
        panneaux = self.dimensionner_panneaux()
        onduleur = self.dimensionner_onduleur()
        cablage = self.config["cablage"]

        sections = cablage["sections_standard"]
        rho = cablage.get("resistivite_cuivre", 0.01724)

        # DC string: courant par chaine
        i_string = panneaux["electrique"]["courant_chaine_nominal_a"]
        v_string = panneaux["electrique"]["tension_chaine_nominale_v"]
        section_string_dc = self._section_dc(
            courant_a=i_string,
            tension_v=v_string,
            longueur_m=distance_panneaux_onduleur_m,
            chute_max_pct=cablage.get("chute_tension_max_dc", 0.03),
            rho=rho,
            sections=sections,
        )

        # DC principal: courant total apres regroupement
        i_total_dc = panneaux["electrique"]["courant_total_nominal_a"]
        section_principal_dc = self._section_dc(
            courant_a=i_total_dc,
            tension_v=v_string,
            longueur_m=distance_panneaux_onduleur_m,
            chute_max_pct=cablage.get("chute_tension_max_dc", 0.03),
            rho=rho,
            sections=sections,
        )

        # AC
        p_w = onduleur["puissance_nominale_kw"] * 1000
        u_v = onduleur["tension_sortie_v"]
        phases = onduleur["phases"]
        cos_phi = self.config["onduleur"].get("facteur_puissance", 0.99)

        if phases == 3:
            i_ac = p_w / (math.sqrt(3) * u_v * cos_phi)
            facteur_chute = math.sqrt(3)
            conducteurs_pertes = 3
        else:
            i_ac = p_w / (u_v * cos_phi)
            facteur_chute = 2
            conducteurs_pertes = 2

        section_ac = self._section_ac(
            courant_a=i_ac,
            tension_v=u_v,
            longueur_m=distance_onduleur_tableau_m,
            facteur_chute=facteur_chute,
            chute_max_pct=cablage.get("chute_tension_max_ac", 0.03),
            rho=rho,
            sections=sections,
        )

        resistance_string = rho * distance_panneaux_onduleur_m / section_string_dc
        pertes_string_w = 2 * resistance_string * i_string**2 * panneaux["configuration"]["nombre_chaines"]

        resistance_ac = rho * distance_onduleur_tableau_m / section_ac
        pertes_ac_w = conducteurs_pertes * resistance_ac * i_ac**2

        longueur_dc_total = distance_panneaux_onduleur_m * 2
        longueur_ac_total = distance_onduleur_tableau_m * conducteurs_pertes

        prix_dc_string = section_string_dc * cablage.get("prix_cable_dc_par_mm2", 0.5) + cablage.get("prix_base_dc", 10.0)
        prix_dc_principal = section_principal_dc * cablage.get("prix_cable_dc_par_mm2", 0.5) + cablage.get("prix_base_dc", 10.0)
        prix_ac = section_ac * cablage.get("prix_cable_ac_par_mm2", 0.4) + cablage.get("prix_base_ac", 8.0)

        cout_dc = longueur_dc_total * prix_dc_string + distance_panneaux_onduleur_m * prix_dc_principal
        cout_ac = longueur_ac_total * prix_ac

        section_terre = self._section_standard(max(16, section_ac / 2), sections)
        longueur_terre = (distance_panneaux_onduleur_m + distance_onduleur_tableau_m) * 1.5
        cout_terre = longueur_terre * 15.0

        return {
            "dc": {
                "string": {
                    "section_mm2": section_string_dc,
                    "courant_par_chaine_a": round(i_string, 2),
                    "longueur_aller_retour_m": round(longueur_dc_total, 1),
                    "type_cable": "Cable solaire H1Z2Z2-K",
                },
                "principal": {
                    "section_mm2": section_principal_dc,
                    "courant_total_a": round(i_total_dc, 2),
                    "tension_v": round(v_string, 1),
                    "type_cable": "Cable solaire principal DC",
                },
                "pertes_estimees_w": round(pertes_string_w, 1),
                "cout_mad": round(cout_dc, 0),
            },
            "ac": {
                "section_mm2": section_ac,
                "courant_a": round(i_ac, 2),
                "tension_v": u_v,
                "phases": phases,
                "longueur_conducteurs_m": round(longueur_ac_total, 1),
                "pertes_estimees_w": round(pertes_ac_w, 1),
                "type_cable": f"Cuivre U1000R2V {section_ac} mm2",
                "cout_mad": round(cout_ac, 0),
            },
            "terre": {
                "section_mm2": section_terre,
                "longueur_m": round(longueur_terre, 1),
                "cout_mad": round(cout_terre, 0),
            },
            "pertes_totales": {
                "dc_w": round(pertes_string_w, 1),
                "ac_w": round(pertes_ac_w, 1),
                "total_w": round(pertes_string_w + pertes_ac_w, 1),
                "pct_puissance_nominale": round((pertes_string_w + pertes_ac_w) / (self.pc_kwc * 1000) * 100, 2),
            },
            "cout_total_cablage_mad": round(cout_dc + cout_ac + cout_terre, 0),
            "note": "Sections indicatives a confirmer selon mode de pose, temperature, groupement et norme applicable.",
        }

    def _section_dc(self, courant_a, tension_v, longueur_m, chute_max_pct, rho, sections):
        delta_v = tension_v * chute_max_pct
        section_min = (2 * rho * longueur_m * courant_a) / delta_v if delta_v > 0 else 240
        section = self._section_standard(section_min, sections)

        # Verification simple intensite admissible indicative.
        if section * 5 < courant_a * 1.25:
            section = self._section_standard((courant_a * 1.25) / 5, sections)

        return section

    def _section_ac(self, courant_a, tension_v, longueur_m, facteur_chute, chute_max_pct, rho, sections):
        delta_v = tension_v * chute_max_pct
        section_min = (rho * facteur_chute * longueur_m * courant_a) / delta_v if delta_v > 0 else 240
        section = self._section_standard(section_min, sections)

        if section * 6 < courant_a * 1.25:
            section = self._section_standard((courant_a * 1.25) / 6, sections)

        return section

    def _section_standard(self, section_min: float, sections: List[float]) -> float:
        return min([s for s in sections if s >= section_min], default=sections[-1])

    # --------------------------------------------------------------------------
    # PROTECTIONS
    # --------------------------------------------------------------------------

    def dimensionner_protections(self) -> Dict[str, Any]:
        panneaux = self.dimensionner_panneaux()
        onduleur = self.dimensionner_onduleur()

        nb_chaines = panneaux["configuration"]["nombre_chaines"]
        isc_string = self.config["panel"]["i_sc"]
        courant_total = panneaux["electrique"]["courant_total_isc_a"]
        tension_max = panneaux["electrique"]["tension_max_chaine_froid_v"]

        phases = onduleur["phases"]
        p_w = onduleur["puissance_nominale_kw"] * 1000
        u_v = onduleur["tension_sortie_v"]
        cos_phi = self.config["onduleur"].get("facteur_puissance", 0.99)

        if phases == 3:
            i_ac = p_w / (math.sqrt(3) * u_v * cos_phi)
        else:
            i_ac = p_w / (u_v * cos_phi)

        cout_fusibles = nb_chaines * 150 if nb_chaines >= 3 else 0

        protections = {
            "cote_dc": {
                "fusibles_chaines": {
                    "nombre": nb_chaines if nb_chaines >= 3 else 0,
                    "calibre_a": math.ceil(isc_string * 1.5),
                    "tension_nominale_v": 1000,
                    "type": "Fusible gPV si necessaire selon retour de courant",
                    "cout_total_mad": cout_fusibles,
                    "note": "Pas toujours requis pour 1 ou 2 chaines; a valider selon modules/onduleur.",
                },
                "sectionneur_dc": {
                    "calibre_a": math.ceil(courant_total * 1.25),
                    "tension_nominale_v": 1000,
                    "type": "Sectionneur DC",
                    "cout_mad": 1200,
                },
                "parafoudre_dc": {
                    "type": "Parafoudre DC Type II",
                    "tension_max_v": round(tension_max, 1),
                    "cout_mad": 800,
                    "note": "A confirmer selon analyse de risque, longueur cables et presence paratonnerre.",
                },
                "boite_jonction": {
                    "nombre": max(1, math.ceil(nb_chaines / 4)),
                    "type": "Boite de jonction DC IP65",
                    "cout_unitaire_mad": 2500,
                    "cout_total_mad": max(1, math.ceil(nb_chaines / 4)) * 2500,
                },
            },
            "cote_ac": {
                "disjoncteur": {
                    "calibre_a": math.ceil(i_ac * 1.25),
                    "type": "Disjoncteur AC adapte au schema",
                    "cout_mad": 900,
                },
                "differentiel": {
                    "sensibilite_ma": 300,
                    "type": "Type A-Si ou Type B selon onduleur",
                    "cout_mad": 1500,
                    "note": "Type exact selon recommandations fabricant onduleur.",
                },
                "parafoudre_ac": {
                    "type": "Parafoudre AC Type II",
                    "cout_mad": 600,
                    "note": "A confirmer selon analyse de risque.",
                },
                "protection_decouplage": {
                    "type": "Protection de decouplage reseau si injection",
                    "requise_si_injection": self.type_systeme in ["on-grid", "hybride"],
                    "cout_mad": 2000 if self.type_systeme in ["on-grid", "hybride"] else 0,
                },
            },
            "mise_a_terre": {
                "piquets_terre": {
                    "nombre": 2,
                    "resistance_cible_ohm": 30,
                    "cout_total_mad": 500,
                },
                "barrette_coupure": {
                    "cout_mad": 150,
                },
            },
            "signalisation": {
                "etiquettes": {
                    "nombre": 10,
                    "cout_mad": 100,
                },
            },
        }

        protections["cout_total_protections_mad"] = round(self._somme_couts(protections), 0)
        protections["note"] = "Protections indicatives. Validation obligatoire par etude electrique d'execution."

        return protections

    def _somme_couts(self, obj: Any) -> float:
        total = 0.0
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ["cout_mad", "cout_total_mad"] and isinstance(v, (int, float)):
                    total += v
                else:
                    total += self._somme_couts(v)
        elif isinstance(obj, list):
            for item in obj:
                total += self._somme_couts(item)
        return total

    # --------------------------------------------------------------------------
    # CAPEX
    # --------------------------------------------------------------------------

    def calculer_capex_complet(self, prix_personnalises: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        panneaux = self.dimensionner_panneaux()
        onduleur = self.dimensionner_onduleur()
        batteries = self.dimensionner_batteries()
        cables = self.dimensionner_cables_precis()
        protections = self.dimensionner_protections()

        cout_panneaux = panneaux["cout"]["total_panneaux_mad"]
        cout_onduleur = onduleur["cout"]["total_onduleur_mad"]
        cout_batteries = batteries["cout"]["total_batteries_mad"] if batteries else 0
        cout_cables = cables["cout_total_cablage_mad"]
        cout_protections = protections["cout_total_protections_mad"]

        if prix_personnalises:
            cout_panneaux = prix_personnalises.get("panneaux", cout_panneaux)
            cout_onduleur = prix_personnalises.get("onduleur", cout_onduleur)
            cout_batteries = prix_personnalises.get("batteries", cout_batteries)
            cout_cables = prix_personnalises.get("cables", cout_cables)
            cout_protections = prix_personnalises.get("protections", cout_protections)

        materiel = cout_panneaux + cout_onduleur + cout_batteries + cout_cables + cout_protections

        eco = self.config["economie"]
        structure = materiel * eco.get("pct_structure_montage", 0.15)
        main_oeuvre = materiel * eco.get("pct_main_oeuvre", 0.20)
        etudes = materiel * eco.get("pct_etudes_ingenierie", 0.05)
        raccordement = eco.get("cout_raccordement_ongrid_mad", 8000) if self.type_systeme in ["on-grid", "hybride"] else eco.get("cout_raccordement_offgrid_mad", 3000)

        sous_total_ht = materiel + structure + main_oeuvre + etudes + raccordement
        contingence = sous_total_ht * eco.get("pct_contingence", 0.10)
        total_ht = sous_total_ht + contingence
        tva = total_ht * eco.get("tva", 0.20)
        total_ttc = total_ht + tva

        return {
            "materiel": {
                "panneaux_mad": round(cout_panneaux, 0),
                "onduleur_mad": round(cout_onduleur, 0),
                "batteries_mad": round(cout_batteries, 0),
                "cables_mad": round(cout_cables, 0),
                "protections_mad": round(cout_protections, 0),
                "sous_total_materiel_mad": round(materiel, 0),
            },
            "installation": {
                "structure_montage_mad": round(structure, 0),
                "main_oeuvre_mad": round(main_oeuvre, 0),
                "etudes_ingenierie_mad": round(etudes, 0),
                "raccordement_mad": round(raccordement, 0),
            },
            "totaux": {
                "sous_total_ht_mad": round(sous_total_ht, 0),
                "contingence_mad": round(contingence, 0),
                "total_ht_mad": round(total_ht, 0),
                "tva_mad": round(tva, 0),
                "total_ttc_mad": round(total_ttc, 0),
                "cout_par_kwc_mad": round(total_ttc / self.pc_kwc, 0),
            },
            "pourcentages": {
                "panneaux_pct": round(cout_panneaux / total_ttc * 100, 1),
                "onduleur_pct": round(cout_onduleur / total_ttc * 100, 1),
                "batteries_pct": round(cout_batteries / total_ttc * 100, 1) if cout_batteries else 0,
                "installation_pct": round((structure + main_oeuvre) / total_ttc * 100, 1),
            },
            "note": "CAPEX indicatif parametre. A remplacer par devis fournisseurs pour decision d'investissement.",
        }

    def dimensionner_systeme_complet(self) -> Dict[str, Any]:
        panneaux = self.dimensionner_panneaux()
        onduleur = self.dimensionner_onduleur()
        batteries = self.dimensionner_batteries()
        cables = self.dimensionner_cables_precis()
        protections = self.dimensionner_protections()
        capex = self.calculer_capex_complet()

        return {
            "panneaux": panneaux,
            "onduleur": onduleur,
            "batteries": batteries,
            "cables": cables,
            "protections": protections,
            "capex": capex,
        }
