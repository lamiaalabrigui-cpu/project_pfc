from modules.config_advanced import ConfigurationManager
from modules.tmy_advanced import TMYDataLoader
from modules.pv_calculator_advanced import PVCalculatorAdvanced
from modules.consommation_advanced import ConsommationManager
from modules.recommandations_iso50001 import RecommandationsISO50001

config = ConfigurationManager().to_dict()

loader = TMYDataLoader(data_dir="data")
tmy = loader.charger_donnees_ville("Rabat")

pv = PVCalculatorAdvanced(tmy, config, 5)
production = pv.calculer_production_annuelle()

conso_manager = ConsommationManager()
consommation, diagnostic = conso_manager.charger_historique(
    "data_examples/exemple_tertiaire_analyseur_reseau_2025_1h.csv"
)

reco = RecommandationsISO50001(
    profil_consommation=consommation,
    donnees_tmy=tmy,
    profil_production=production,
    donnees_reseau=conso_manager.donnees_reseau_horaire,
    diagnostic_donnees=diagnostic,
    type_batiment="tertiaire",
)

resultats = reco.generer_recommandations()

for r in resultats["recommandations"]:
    print("\n---", r["titre"])
    print(r["niveau"])
    print(r["message"])
    for action in r["actions"]:
        print("-", action)
