from modules.tarification_onee import TarificationONEE

tarif = TarificationONEE("bt_residentiel")

print("Residentiel 120 kWh")
print(tarif.calculer_facture_mensuelle_residentiel(120, mois=1))

print("\nResidentiel 250 kWh")
print(tarif.calculer_facture_mensuelle_residentiel(250, mois=1))

print("\nEconomie residentiel")
avant = [250] * 12
apres = [160] * 12
print(tarif.calculer_economie_avec_pv_residentiel(avant, apres))
