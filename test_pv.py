from modules.config_advanced import ConfigurationManager
from modules.tmy_advanced import TMYDataLoader
from modules.pv_calculator_advanced import PVCalculatorAdvanced

config = ConfigurationManager().to_dict()

loader = TMYDataLoader(data_dir="data")
tmy = loader.charger_donnees_ville("Rabat")

calc = PVCalculatorAdvanced(tmy, config, puissance_crete_kwc=10)
prod = calc.calculer_production_annuelle()

print("Premieres lignes production:")
print(prod.head())

print("\nDimensions:")
print(prod.shape)

print("\nResume:")
print(calc.get_summary())

print("\nProduction mensuelle:")
print(calc.get_production_mensuelle())
