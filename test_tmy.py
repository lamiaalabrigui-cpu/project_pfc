from modules.tmy_advanced import TMYDataLoader

loader = TMYDataLoader(data_dir="data")
df_tmy = loader.charger_donnees_ville("Rabat")

print(df_tmy.head())
print(df_tmy.shape)

stats = loader.get_statistiques()
print(stats)

mensuel = loader.get_irradiation_mensuelle()
print(mensuel)
