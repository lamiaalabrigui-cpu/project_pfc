from modules.consommation_advanced import ConsommationManager

manager = ConsommationManager()

profil, diagnostic = manager.charger_historique(
    "data_examples/exemple_residentiel_compteur_intelligent_2025_1h.csv"
)

print(profil.head())
print(profil.shape)
print(diagnostic)
print(manager.get_statistiques())
print(manager.get_consommation_mensuelle())
