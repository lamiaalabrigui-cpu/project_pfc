from modules.rapport_pdf import generer_rapport_pdf

resultats = {
    "nom_projet": "Test Opti-Solar Rabat",
    "ville": "Rabat",
    "type_batiment": "Residentiel",
    "type_contrat": "BT Residentiel",
    "type_systeme": "On-grid",
    "pc_kwc": 5,
    "capex_total_mad": 65000,
    "conclusion": "Projet indicatif a confirmer par une etude technique detaillee.",
    "kpis": {
        "pc_kwc": 5,
        "production_kwh": 8200,
        "taux_autoconso_pct": 72,
        "capex_mad": 65000,
        "van_mad": 18000,
        "retour_ans": 7.8,
    },
    "diagnostic_donnees": {
        "source_detectee": "compteur_intelligent",
        "mesure_detectee": "energie_periode_kwh",
        "colonne_datetime": "DateTime",
        "colonne_principale": "Energie_import_kWh",
        "pas_detecte": "1H",
        "nombre_lignes_original": 8760,
        "nombre_lignes_horaires": 8760,
        "date_debut": "2025-01-01",
        "date_fin": "2025-12-31",
        "qualite": "bonne",
        "messages": ["Pas horaire detecte.", "Conversion vers profil horaire effectuee."],
    },
    "stats_tmy": {
        "ville": "Rabat",
        "latitude": 33.9921,
        "longitude": -6.7086,
        "altitude": 138,
        "timezone": "UTC+01:00",
        "irradiation_annuelle_ghi_kwh_m2": 1972.5,
        "irradiation_annuelle_gpi_kwh_m2": 2146.3,
        "temperature_moyenne_c": 18.5,
        "temperature_max_c": 38.4,
        "temperature_min_c": 6.5,
    },
    "stats_conso": {
        "consommation_annuelle_kwh": 6400,
        "puissance_moyenne_kw": 0.73,
        "puissance_max_kw": 2.46,
        "facteur_charge": 0.29,
    },
    "recommandations": {
        "recommandations": [
            {
                "titre": "Talon de consommation maitrise",
                "niveau": "success",
                "message": "Le talon nocturne est acceptable.",
                "actions": ["Maintenir le suivi mensuel.", "Verifier les veilles."],
            }
        ]
    },
    "dimensionnement": {},
    "economie": {
        "indicateurs_rentabilite": {
            "van_mad": 18000,
            "tri_pct": 12.4,
            "lcoe_mad_kwh": 0.62,
            "periode_retour_simple_ans": 7.8,
            "periode_retour_actualisee_ans": 10,
            "rentable": True,
        },
        "economique": {
            "economies_brutes_mad": 180000,
            "opex_total_mad": 50000,
            "benefice_net_mad": 65000,
        },
        "production": {"annuelle_an1_kwh": 8200},
        "performance": {
            "taux_autoconso_an1_pct": 72,
            "taux_autoproduction_an1_pct": 58,
        },
    },
}

print(generer_rapport_pdf(resultats, "outputs/rapport_test.pdf"))
