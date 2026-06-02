import math
import random
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

random.seed(42)
out = Path(r'C:\Users\Ce Pc\Documents\Codex\2026-05-06\mon-sujet-est-d-veloppement-d\data_examples')
out.mkdir(parents=True, exist_ok=True)

start = datetime(2025, 1, 1, 0, 0)
hours = [start + timedelta(hours=i) for i in range(8760)]

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

# Residential smart meter: hourly imported energy and cumulative index.
res_rows = []
index = 18420.0
for dt in hours:
    h = dt.hour
    doy = dt.timetuple().tm_yday
    weekend = dt.weekday() >= 5
    winter = dt.month in [1, 2, 12]
    summer = dt.month in [6, 7, 8, 9]

    base = 0.28
    morning = 0.75 * math.exp(-((h - 7.0) / 1.8) ** 2)
    evening = 1.25 * math.exp(-((h - 20.5) / 2.5) ** 2)
    daytime = 0.22 if 12 <= h <= 16 and weekend else 0.08 if 12 <= h <= 16 else 0
    hvac = 0.0
    if summer:
        hvac += 0.55 * max(0, math.sin((h - 12) / 12 * math.pi))
        hvac += 0.35 if h >= 21 or h <= 2 else 0
    if winter:
        hvac += 0.28 if h in [6, 7, 8, 19, 20, 21, 22] else 0
    seasonal = 1 + 0.08 * math.sin(2 * math.pi * (doy - 20) / 365)
    noise = random.gauss(0, 0.06)
    kwh = clamp((base + morning + evening + daytime + hvac) * seasonal + noise, 0.12, 4.5)
    index += kwh
    res_rows.append({
        'DateTime': dt.strftime('%d/%m/%Y %H:%M'),
        'Energie_import_kWh': round(kwh, 3),
        'Index_import_kWh': round(index, 3),
        'Source': 'Compteur intelligent',
        'Pas': '1H'
    })

res = pd.DataFrame(res_rows)

# Tertiary network analyzer: active/reactive/apparent power and electrical quality.
ter_rows = []
for dt in hours:
    h = dt.hour
    doy = dt.timetuple().tm_yday
    weekday = dt.weekday()
    working_day = weekday < 5
    summer = dt.month in [6, 7, 8, 9]
    winter = dt.month in [1, 2, 12]

    base = 18.0
    occupancy = 0.0
    if working_day:
        if 7 <= h < 9:
            occupancy = 22 * (h - 7) / 2
        elif 9 <= h < 12:
            occupancy = 42
        elif 12 <= h < 14:
            occupancy = 30
        elif 14 <= h < 18:
            occupancy = 48
        elif 18 <= h < 20:
            occupancy = 22 * (20 - h) / 2
    else:
        occupancy = 5 if 9 <= h < 18 else 0

    hvac = 0.0
    if summer and 8 <= h <= 19:
        hvac = 28 * max(0, math.sin((h - 8) / 11 * math.pi))
    if winter and 7 <= h <= 18:
        hvac = 12 * max(0, math.sin((h - 7) / 11 * math.pi))

    lunch_peak = 8 if working_day and h in [12, 13] else 0
    season_factor = 1 + 0.05 * math.sin(2 * math.pi * (doy - 170) / 365)
    p_kw = clamp((base + occupancy + hvac + lunch_peak) * season_factor + random.gauss(0, 2.0), 12, 135)

    pf = clamp(0.93 + random.gauss(0, 0.025) - (0.035 if hvac > 15 else 0), 0.82, 0.99)
    s_kva = p_kw / pf
    q_kvar = math.sqrt(max(s_kva * s_kva - p_kw * p_kw, 0))
    v1 = 230 + random.gauss(0, 2.5)
    v2 = 231 + random.gauss(0, 2.5)
    v3 = 229 + random.gauss(0, 2.5)
    # Approximate three-phase current per phase: S = sqrt(3)*Ull*I, with Ull around 400 V.
    i_phase = s_kva * 1000 / (math.sqrt(3) * 400)
    thd_v = clamp(2.0 + random.gauss(0, 0.4), 0.8, 4.5)
    thd_i = clamp(8.0 + (4.0 if p_kw > 90 else 0) + random.gauss(0, 1.2), 3.0, 18.0)
    energy_kwh = p_kw * 1.0

    ter_rows.append({
        'DateTime': dt.strftime('%d/%m/%Y %H:%M'),
        'P_total_kW': round(p_kw, 3),
        'Energie_active_kWh': round(energy_kwh, 3),
        'Q_total_kVAr': round(q_kvar, 3),
        'S_total_kVA': round(s_kva, 3),
        'PF': round(pf, 3),
        'V_L1_V': round(v1, 1),
        'V_L2_V': round(v2, 1),
        'V_L3_V': round(v3, 1),
        'I_L1_A': round(i_phase * random.uniform(0.96, 1.04), 1),
        'I_L2_A': round(i_phase * random.uniform(0.96, 1.04), 1),
        'I_L3_A': round(i_phase * random.uniform(0.96, 1.04), 1),
        'THD_V_pct': round(thd_v, 2),
        'THD_I_pct': round(thd_i, 2),
        'Frequence_Hz': round(50 + random.gauss(0, 0.03), 3),
        'Source': 'Analyseur de reseau',
        'Pas': '1H'
    })

ter = pd.DataFrame(ter_rows)

res_csv = out / 'exemple_residentiel_compteur_intelligent_2025_1h.csv'
res_xlsx = out / 'exemple_residentiel_compteur_intelligent_2025_1h.xlsx'
ter_csv = out / 'exemple_tertiaire_analyseur_reseau_2025_1h.csv'
ter_xlsx = out / 'exemple_tertiaire_analyseur_reseau_2025_1h.xlsx'

res.to_csv(res_csv, index=False, encoding='utf-8-sig')
ter.to_csv(ter_csv, index=False, encoding='utf-8-sig')

with pd.ExcelWriter(res_xlsx, engine='openpyxl') as writer:
    res.to_excel(writer, sheet_name='Historique_2025', index=False)
    ws = writer.book['Historique_2025']
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = ws.dimensions
    for col in ws.columns:
        width = min(max(len(str(col[0].value or '')) + 2, 12), 26)
        ws.column_dimensions[col[0].column_letter].width = width

with pd.ExcelWriter(ter_xlsx, engine='openpyxl') as writer:
    ter.to_excel(writer, sheet_name='Analyseur_2025', index=False)
    ws = writer.book['Analyseur_2025']
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = ws.dimensions
    for col in ws.columns:
        width = min(max(len(str(col[0].value or '')) + 2, 12), 26)
        ws.column_dimensions[col[0].column_letter].width = width

summary = {
    'residentiel_lignes': len(res),
    'residentiel_total_kwh': round(res['Energie_import_kWh'].sum(), 1),
    'residentiel_pic_kwh_h': round(res['Energie_import_kWh'].max(), 3),
    'tertiaire_lignes': len(ter),
    'tertiaire_total_kwh': round(ter['Energie_active_kWh'].sum(), 1),
    'tertiaire_pic_kw': round(ter['P_total_kW'].max(), 3),
    'files': [str(res_csv), str(res_xlsx), str(ter_csv), str(ter_xlsx)]
}
print(summary)
