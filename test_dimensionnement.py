from modules.config_advanced import ConfigurationManager
from modules.dimensionnement import ComponentSizerAdvanced

config = ConfigurationManager().to_dict()

sizer = ComponentSizerAdvanced(
    config_settings=config,
    puissance_crete_kwc=10,
    type_systeme="on-grid",
    consommation_annuelle_kwh=15000,
    pic_consommation_kw=8,
)

print("PANNEAUX")
print(sizer.dimensionner_panneaux())

print("\nONDULEUR")
print(sizer.dimensionner_onduleur())

print("\nCABLES")
print(sizer.dimensionner_cables_precis())

print("\nPROTECTIONS")
print(sizer.dimensionner_protections())

print("\nCAPEX")
print(sizer.calculer_capex_complet())
