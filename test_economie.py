from modules.config_advanced import ConfigurationManager
from modules.tmy_advanced import TMYDataLoader
from modules.pv_calculator_advanced import PVCalculatorAdvanced
from modules.consommation_advanced import ConsommationManager
from modules.dimensionnement import ComponentSizerAdvanced
from modules.analyse_economique import AnalyseEconomiqueAvancee

config = ConfigurationManager().to_dict()

loader = TMYDataLoader(data_dir="data")
tmy = loader.charger_donnees_ville("Rabat")

pv = PVCalculatorAdvanced(tmy, config, 5)
production = pv.calculer_production_annuelle()

conso_manager = ConsommationManager()
consommation, diag = conso_manager.charger_historique(
    "data_examples/exemple_residentiel_compteur_intelligent_2025_1h.csv"
)

sizer = ComponentSizerAdvanced(config, 5, "on-grid")
capex = sizer.calculer_capex_complet()["totaux"]["total_ttc_mad"]

eco = AnalyseEconomiqueAvancee(
    config_settings=config,
    capex=capex,
    type_contrat="bt_residentiel",
    profil_production=production,
    profil_consommation=consommation,
    inclure_revenu_injection=False,
)

print(eco.calculer_economies_annuelles_detaillees(1))
print(eco.calculer_bilan_complet())
print(eco.generer_tableau_flux().head())
