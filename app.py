from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from modules.config_advanced import ConfigurationManager, TYPES_CONTRAT, VILLES_MAROC
from modules.tmy_advanced import TMYDataLoader
from modules.consommation_advanced import ConsommationManager
from modules.pv_calculator_advanced import PVCalculatorAdvanced
from modules.analyse_economique import AnalyseEconomiqueAvancee
from modules.recommandations_iso50001 import RecommandationsISO50001
from modules.rapport_pdf import generer_rapport_pdf
from modules.pv_design_advanced import (
    BatteryTech,
    CableDesignInput,
    InverterTech,
    PanelTech,
    calculate_pv_design,
    capex_from_rows,
    default_capex_rows,
    extract_power_candidates_from_file,
    parse_component_file,
)

st.set_page_config(page_title="Opti-Solar Maroc", page_icon="Solar", layout="wide")


# ==============================================================================
# HELPERS UI / DATA
# ==============================================================================


def save_uploaded_file(uploaded_file) -> Path:
    suffix = Path(uploaded_file.name).suffix
    temp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp.write(uploaded_file.getbuffer())
    temp.close()
    return Path(temp.name)


def money(x):
    try:
        return f"{float(x):,.0f} MAD".replace(",", " ")
    except Exception:
        return "N/A"


def kpi(label, value, help_text=None):
    st.metric(label, value, help=help_text)


def _pad_profile(df, value_col, n=8760):
    raw = df[value_col].to_numpy(float)
    if len(raw) >= n:
        return df.iloc[:n].reset_index(drop=True)
    n_missing = n - len(raw)
    last_dt = pd.to_datetime(df["DateTime"].iloc[-1])
    new_dts = pd.date_range(start=last_dt + pd.Timedelta(hours=1), periods=n_missing, freq="h")
    pad = pd.DataFrame({"DateTime": new_dts, value_col: 0.0})
    return pd.concat([df, pad], ignore_index=True)

def ensure_state():
    defaults = {
        "show_tool": False,
        "show_process": False,
        "project_name": "Projet PV",
        "ville": "Rabat",
        "type_batiment": "residentiel",
        "type_contrat": "bt_residentiel",
        "type_systeme": "on-grid",
        "consommation": None,
        "diagnostic": {},
        "donnees_reseau": None,
        "tmy": None,
        "stats_tmy": {},
        "production": None,
        "pv_summary": {},
        "design": {},
        "capex_rows": None,
        "capex_total": 0.0,
        "bilan_eco": {},
        "recommandations": {},
        "panel_specs": {
            "wc": 550.0, "prix_unitaire": 0.0, "impp": 13.16, "umpp": 41.8,
            "icc": 13.95, "uco": 49.5, "irm": 25.0, "degradation_annuelle": 0.005,
            "surface_m2": 2.61,
        },
        "inverter_specs": {
            "puissance_nominale_kw": 10.0, "prix_unitaire": 0.0, "imax": 30.0,
            "umppt_max": 850.0, "umppt_min": 200.0, "tension_ac_v": 400.0,
            "uw": 1000.0, "phases": 3,
        },
        "battery_specs": {
            "capacite_ah": 200.0, "tension_v": 48.0, "dod_max": 0.80,
            "prix_unitaire": 0.0,
        },
        "last_panel_file": None,
        "last_inverter_file": None,
        "last_battery_file": None,
        "last_panel_target": None,
        "last_inverter_target": None,
        "panel_parse_empty": False,
        "inverter_parse_empty": False,
        "battery_parse_empty": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = deepcopy(value)
        elif isinstance(value, dict) and isinstance(st.session_state[key], dict):
            for sub_key, sub_value in value.items():
                st.session_state[key].setdefault(sub_key, sub_value)


def build_inventory(type_batiment: str):
    st.info("Remplissez les equipements principaux. Les plages qui traversent minuit sont acceptees, ex: 22 -> 6.")
    n = st.number_input("Nombre d'equipements", min_value=1, max_value=40, value=6 if type_batiment == "residentiel" else 10, step=1)
    jours_map = {"Lun": 0, "Mar": 1, "Mer": 2, "Jeu": 3, "Ven": 4, "Sam": 5, "Dim": 6}
    default_days = list(jours_map.keys()) if type_batiment == "residentiel" else ["Lun", "Mar", "Mer", "Jeu", "Ven"]
    rows = []
    for i in range(int(n)):
        with st.expander(f"Equipement {i + 1}", expanded=i < 3):
            c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
            name = c1.text_input("Nom", f"Equipement {i + 1}", key=f"inv_name_{i}")
            p = c2.number_input("Puissance W", 0.0, 100000.0, 500.0, 10.0, key=f"inv_p_{i}")
            nb = c3.number_input("Nombre", 1, 1000, 1, 1, key=f"inv_nb_{i}")
            factor = c4.slider("Usage", 0.0, 1.0, 1.0, 0.05, key=f"inv_factor_{i}")
            h1, h2, days_col = st.columns([1, 1, 2])
            start = h1.number_input("Debut", 0, 23, 8, 1, key=f"inv_start_{i}")
            end = h2.number_input("Fin", 0, 24, 18, 1, key=f"inv_end_{i}")
            days = days_col.multiselect("Jours", list(jours_map.keys()), default_days, key=f"inv_days_{i}")
            rows.append({
                "nom": name,
                "puissance_w": p,
                "nombre": int(nb),
                "plages_horaires": [(int(start), int(end))],
                "jours_semaine": [jours_map[d] for d in days],
                "facteur_usage": factor,
            })
    return rows


def optimize_power(tmy, config, conso, type_contrat, type_systeme, pc_min, pc_max, n_tests):
    n_hours = 8760
    raw = conso["Consommation_kWh"].to_numpy(float)
    if len(raw) < n_hours:
        raw = np.pad(raw, (0, n_hours - len(raw)), constant_values=0)
    conso_values = raw[:n_hours]
    conso_total = float(conso_values.sum())
    rows = []
    for pc in np.linspace(pc_min, pc_max, int(n_tests)):
        calc = PVCalculatorAdvanced(tmy, config, float(pc))
        prod_df = calc.calculer_production_annuelle()
        prod = prod_df["Production_kWh"].to_numpy(float)[:8760]
        autoconso = np.minimum(prod, conso_values)
        surplus = np.maximum(0, prod - conso_values)
        prod_total = float(prod.sum())
        auto_total = float(autoconso.sum())
        surplus_total = float(surplus.sum())
        taux_auto = auto_total / prod_total if prod_total else 0
        taux_autoprod = auto_total / conso_total if conso_total else 0
        taux_surplus = surplus_total / prod_total if prod_total else 0
        bt_or_offgrid = type_contrat == "bt_residentiel" or type_systeme == "off-grid"
        injection_rem = 0 if bt_or_offgrid else min(surplus_total, 0.20 * prod_total)
        economie = auto_total * 1.10 + injection_rem * 0.18
        capex = pc * (14000 if type_systeme == "off-grid" else 12000 if type_systeme == "hybride" else 8000)
        payback = capex / economie if economie > 0 else 999
        penalty = taux_surplus * (100 if bt_or_offgrid else 60 if taux_surplus > 0.20 else 10)
        score = 45 * taux_autoprod + 35 * taux_auto + max(0, 20 - payback) - penalty
        rows.append({
            "Puissance_kWc": round(float(pc), 2),
            "Production_kWh": round(prod_total, 0),
            "Autoconso_kWh": round(auto_total, 0),
            "Surplus_kWh": round(surplus_total, 0),
            "Taux_autoconso_%": round(taux_auto * 100, 1),
            "Taux_autoproduction_%": round(taux_autoprod * 100, 1),
            "Taux_surplus_%": round(taux_surplus * 100, 1),
            "Payback_simple_estime": round(payback, 1),
            "Score": round(score, 3),
        })
    df = pd.DataFrame(rows)
    best = df.loc[df["Score"].idxmax()].to_dict()
    return best, df


def apply_financial_inputs(config, panel_degradation):
    cfg = deepcopy(config)
    st.subheader("Parametres financiers")
    c1, c2, c3 = st.columns(3)
    cfg["economie"]["taux_actualisation"] = c1.number_input("Taux d'actualisation", 0.0, 0.30, 0.08, 0.005)
    cfg["economie"]["augmentation_tarif_elec"] = c2.number_input("Hausse tarif electricite", 0.0, 0.30, 0.035, 0.005)
    cfg["economie"]["cout_maintenance_pct_capex"] = c3.number_input("Maintenance annuelle (% CAPEX)", 0.0, 0.20, 0.01, 0.005)
    c4, c5, c6 = st.columns(3)
    cfg["economie"]["tva"] = c4.number_input("TVA CAPEX", 0.0, 0.30, 0.20, 0.01)
    cfg["economie"]["duree_projet_ans"] = int(c5.number_input("Duree projet (ans)", 1, 40, 25, 1))
    cfg["economie"]["taux_inflation"] = c6.number_input("Croissance O&M", 0.0, 0.20, 0.0002, 0.0001, format="%.4f")
    cfg["panel"]["degradation_annuelle"] = panel_degradation
    return cfg


def spec_inputs(prefix: str, parsed: dict, defaults):
    data = as_dict(defaults)
    data.update({k: v for k, v in parsed.items() if k in data})
    return data


def as_dict(obj):
    if hasattr(obj, "__dataclass_fields__"):
        return obj.__dict__.copy()
    return dict(obj)


def bounded_default(parsed: dict, key: str, default: float, min_value: float, max_value: float) -> float:
    try:
        value = float(parsed.get(key, default))
    except Exception:
        value = default
    if not np.isfinite(value):
        value = default
    return float(min(max(value, min_value), max_value))


def sync_widget_values(specs: dict, parsed: dict, mapping: dict):
    """Injecte les valeurs extraites dans les widgets avant leur creation."""
    for data_key, item in mapping.items():
        widget_key, default, min_value, max_value = item
        if data_key not in parsed:
            continue
        specs[data_key] = parsed[data_key]
        st.session_state[widget_key] = bounded_default(specs, data_key, default, min_value, max_value)


def dict_to_table(title, data):
    st.markdown(f"**{title}**")
    rows = [{"Parametre": key, "Valeur": value} for key, value in data.items()]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ==============================================================================
# APP HEADER
# ==============================================================================

ensure_state()

h1, h2, h3 = st.columns([1, 3, 1])
with h1:
    st.markdown("### OPTI\n### SOLAR")
with h2:
    st.title("Opti-Solar Maroc")
    st.write("Plateforme interactive d'analyse de consommation, dimensionnement PV, audit ISO 50001, CAPEX, rentabilite et rapport PDF.")
with h3:
    if st.button("Lancer l'outil", use_container_width=True):
        st.session_state.show_tool = True
    if st.button("Afficher le processus d'analyse", use_container_width=True):
        st.session_state.show_process = not st.session_state.show_process

if st.session_state.show_process:
    st.graphviz_chart('''
    digraph G {
      rankdir=LR;
      Projet -> TMY -> Consommation -> AnalyseConso -> OptimisationPV -> Dimensionnement -> CAPEX -> Economie -> Recommandations -> RapportPDF;
      Consommation -> QualiteDonnees;
      AnalyseConso -> Recommandations;
      Dimensionnement -> Protections;
    }
    ''')

if not st.session_state.show_tool:
    st.info("Cliquez sur 'Lancer l'outil' pour commencer la configuration du projet.")
    st.stop()

base_config = ConfigurationManager().to_dict()

st.markdown("---")
st.subheader("Donnees initiales du projet")
p1, p2, p3, p4, p5 = st.columns([2, 1, 1, 1, 1])
project_name = p1.text_input("Nom du projet", st.session_state.project_name)
ville = p2.selectbox("Ville", list(VILLES_MAROC.keys()), index=list(VILLES_MAROC.keys()).index(st.session_state.ville) if st.session_state.ville in VILLES_MAROC else 0)
type_batiment = p3.selectbox("Batiment", ["residentiel", "tertiaire"], index=0 if st.session_state.type_batiment == "residentiel" else 1)
type_contrat = p4.selectbox("Contrat", list(TYPES_CONTRAT.keys()), format_func=lambda x: TYPES_CONTRAT[x]["label"])
type_systeme = p5.selectbox("Systeme", ["on-grid", "off-grid", "hybride"])

# ==============================================================================
# TABS
# ==============================================================================

tabs = st.tabs([
    "🏠 Vue generale",
    "☀ Donnees solaires TMY",
    "📥 Donnees de consommation",
    "📊 Analyse consommation",
    "⚡ Production PV & Bilan",
    "🧰 Dimensionnement PV",
    "💰 Analyse economique",
    "💡 Recommandations",
    "📄 Rapport PDF",
])

# ------------------------------------------------------------------------------
# 1 OVERVIEW
# ------------------------------------------------------------------------------
with tabs[0]:
    st.subheader("Vue generale")
    st.write("Avancement recommande: chargez les donnees TMY, importez ou saisissez la consommation, optimisez la puissance PV, dimensionnez les composants, puis genereez le rapport.")
    st.info("Les fichiers d'exemple ne sont pas inclus dans l'interface. Utilisez-les seulement via l'import CSV/Excel pour tester l'application.")

# ------------------------------------------------------------------------------
# 2 TMY
# ------------------------------------------------------------------------------
with tabs[1]:
    st.subheader("Donnees solaires TMY")
    try:
        loader = TMYDataLoader(data_dir="data")
        tmy = loader.charger_donnees_ville(ville)
        stats_tmy = loader.get_statistiques()
        st.session_state.tmy = tmy
        st.session_state.stats_tmy = stats_tmy
        c1, c2, c3, c4 = st.columns(4)
        kpi("GHI annuel", f"{stats_tmy['irradiation_annuelle_ghi_kwh_m2']:.0f} kWh/m2")
        c2.metric("GPI annuel", f"{stats_tmy['irradiation_annuelle_gpi_kwh_m2']:.0f} kWh/m2")
        c3.metric("Temperature moyenne", f"{stats_tmy['temperature_moyenne_c']:.1f} C")
        c4.metric("Heures", stats_tmy["heures"])
        mensuel_tmy = loader.get_irradiation_mensuelle()
        st.plotly_chart(px.bar(mensuel_tmy, x="Mois_Nom", y=["GHI_kWh_m2", "GPI_kWh_m2"], barmode="group"), use_container_width=True)
    except Exception as exc:
        st.error(f"Erreur TMY: {exc}")

# ------------------------------------------------------------------------------
# 3 CONSUMPTION INPUT
# ------------------------------------------------------------------------------
with tabs[2]:
    st.subheader("Donnees de consommation")
    manager = ConsommationManager()
    mode = st.radio("Mode de saisie", ["Importer historique CSV/Excel", "Remplir tableau d'inventaire"], horizontal=True)
    try:
        if mode == "Importer historique CSV/Excel":
            file = st.file_uploader("Historique compteur intelligent ou analyseur reseau", type=["csv", "txt", "xlsx", "xls"])
            if file:
                path = save_uploaded_file(file)
                conso, diag = manager.charger_historique(path)
                st.session_state.consommation = _pad_profile(conso, "Consommation_kWh")
                st.session_state.diagnostic = diag
                st.session_state.donnees_reseau = manager.donnees_reseau_horaire
                st.success("Historique charge et converti en profil horaire.")
        else:
            equipements = build_inventory(type_batiment)
            if st.button("Calculer la consommation depuis l'inventaire"):
                conso = manager.creer_depuis_equipements(equipements, annee=2025)
                st.session_state.consommation = _pad_profile(conso, "Consommation_kWh")
                st.session_state.diagnostic = manager.get_statistiques().get("diagnostic", {})
                st.session_state.donnees_reseau = None
                st.success("Profil horaire genere depuis l'inventaire.")

        if st.session_state.consommation is not None:
            stats = manager.get_statistiques() if manager.profil_horaire is not None else {
                "consommation_annuelle_kwh": float(st.session_state.consommation["Consommation_kWh"].sum()),
                "puissance_moyenne_kw": float(st.session_state.consommation["Consommation_kWh"].mean()),
                "puissance_max_kw": float(st.session_state.consommation["Consommation_kWh"].max()),
                "facteur_charge": float(st.session_state.consommation["Consommation_kWh"].mean() / max(st.session_state.consommation["Consommation_kWh"].max(), 0.001)),
            }
            st.session_state.stats_conso = stats
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Consommation annuelle", f"{stats['consommation_annuelle_kwh']:.0f} kWh")
            c2.metric("Puissance moyenne", f"{stats['puissance_moyenne_kw']:.2f} kW")
            c3.metric("Puissance max", f"{stats['puissance_max_kw']:.2f} kW")
            c4.metric("Facteur charge", f"{stats['facteur_charge']*100:.1f}%")
            with st.expander("Diagnostic qualite"):
                st.json(st.session_state.diagnostic)
    except Exception as exc:
        st.error(f"Erreur consommation: {exc}")

# ------------------------------------------------------------------------------
# 4 DETAILED CONSUMPTION
# ------------------------------------------------------------------------------
with tabs[3]:
    st.subheader("Analyse detaillee de la consommation")
    conso = st.session_state.consommation
    if conso is None:
        st.warning("Veuillez d'abord charger ou creer un profil de consommation.")
    else:
        df = conso.copy()
        df["Heure"] = pd.to_datetime(df["DateTime"]).dt.hour
        df["Mois"] = pd.to_datetime(df["DateTime"]).dt.month
        hourly = df.groupby("Heure")["Consommation_kWh"].mean().reset_index()
        monthly = df.groupby("Mois")["Consommation_kWh"].sum().reset_index()
        st.plotly_chart(px.line(hourly, x="Heure", y="Consommation_kWh", title="Profil horaire moyen"), use_container_width=True)
        st.plotly_chart(px.bar(monthly, x="Mois", y="Consommation_kWh", title="Consommation mensuelle"), use_container_width=True)
        nuit = df[df["Heure"].between(0, 5)]["Consommation_kWh"].mean()
        moy = df["Consommation_kWh"].mean()
        st.metric("Ratio talon 00h-05h / moyenne", f"{(nuit / max(moy, 0.001))*100:.1f}%")

# ------------------------------------------------------------------------------
# 5 PV PRODUCTION AND BALANCE
# ------------------------------------------------------------------------------
with tabs[4]:
    st.subheader("Production PV, puissance optimale et bilan energie")
    tmy = st.session_state.tmy
    conso = st.session_state.consommation
    if tmy is None or conso is None:
        st.warning("Chargez les donnees solaires et la consommation.")
    else:
        conso_total = float(conso["Consommation_kWh"].sum())
        c1, c2, c3 = st.columns(3)
        pc_min = c1.number_input("Puissance min kWc", 0.5, 1000.0, 1.0 if type_batiment == "residentiel" else 5.0, 0.5)
        pc_max_default = max(pc_min + 1, min(500.0, max(20.0, conso_total / 900)))
        pc_max = c2.number_input("Puissance max kWc", pc_min, 1000.0, float(pc_max_default), 0.5)
        nb_tests = c3.number_input("Nombre tests", 5, 80, 25, 1)
        best, opt_df = optimize_power(tmy, base_config, conso, type_contrat, type_systeme, pc_min, pc_max, nb_tests)
        st.success(f"Puissance optimale estimee: {best['Puissance_kWc']:.2f} kWc")
        st.dataframe(opt_df, use_container_width=True)
        selected_pc = st.number_input("Puissance retenue kWc", 0.5, 1000.0, float(best["Puissance_kWc"]), 0.5)
        calc = PVCalculatorAdvanced(tmy, base_config, selected_pc)
        production = calc.calculer_production_annuelle()
        st.session_state.production = production
        st.session_state.pv_summary = calc.get_summary()
        n_hours = 8760
        prod = production["Production_kWh"].to_numpy(float)[:n_hours]
        raw_load = conso["Consommation_kWh"].to_numpy(float)
        if len(raw_load) < n_hours:
            raw_load = np.pad(raw_load, (0, n_hours - len(raw_load)), constant_values=0)
        load = raw_load[:n_hours]
        autoconso = np.minimum(prod, load)
        surplus = np.maximum(0, prod - load)
        injection_allowed = type_contrat != "bt_residentiel" and type_systeme != "off-grid"
        injection = surplus if injection_allowed else np.zeros_like(surplus)
        st.session_state.selected_pc = selected_pc
        st.session_state.energy_balance = {
            "production_kwh": float(prod.sum()),
            "autoconso_kwh": float(autoconso.sum()),
            "surplus_kwh": float(surplus.sum()),
            "injection_kwh": float(injection.sum()),
            "taux_autoconso": float(autoconso.sum() / max(prod.sum(), 0.001)),
            "taux_autoproduction": float(autoconso.sum() / max(load.sum(), 0.001)),
            "taux_injection": float(injection.sum() / max(prod.sum(), 0.001)),
        }
        b = st.session_state.energy_balance
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Production", f"{b['production_kwh']:.0f} kWh")
        k2.metric("Autoconsommation", f"{b['autoconso_kwh']:.0f} kWh")
        k3.metric("Taux autoconso", f"{b['taux_autoconso']*100:.1f}%")
        k4.metric("Injection", f"{b['taux_injection']*100:.1f}%")
        if not injection_allowed:
            st.warning("Injection non valorisee: BT residentiel ou systeme off-grid.")

# ------------------------------------------------------------------------------
# 6 DIMENSIONING
# ------------------------------------------------------------------------------
with tabs[5]:
    st.subheader("Dimensionnement photovoltaique avance")
    selected_pc = st.session_state.get("selected_pc", None)
    conso = st.session_state.consommation
    if selected_pc is None or conso is None:
        st.warning("Calculez d'abord la puissance optimale dans l'onglet Production PV.")
    else:
        st.write("Importez une fiche technique si disponible, puis corrigez les champs manuellement.")
        up1, up2, up3 = st.columns(3)
        panel_file = up1.file_uploader("Fiche panneau PDF/PAN", type=["pdf", "pan", "txt"], key="panel_file")
        inv_file = up2.file_uploader("Fiche onduleur PDF/OND", type=["pdf", "ond", "txt"], key="inv_file")
        batt_file = up3.file_uploader("Fiche batterie PDF/BATT", type=["pdf", "batt", "txt"], key="batt_file")

        panel_mapping = {
            "wc": ("panel_wc", 550.0, 1.0, 1000.0),
            "impp": ("panel_impp", 13.16, 0.1, 100.0),
            "umpp": ("panel_umpp", 41.8, 1.0, 200.0),
            "icc": ("panel_icc", 13.95, 0.1, 100.0),
            "uco": ("panel_uco", 49.5, 1.0, 250.0),
            "irm": ("panel_irm", 25.0, 0.1, 100.0),
            "degradation_annuelle": ("panel_deg", 0.005, 0.0, 0.05),
            "surface_m2": ("panel_surface", 2.61, 0.1, 10.0),
        }
        inverter_mapping = {
            "puissance_nominale_kw": ("inv_pnom", max(float(selected_pc) / 1.2, 0.1), 0.1, 1000.0),
            "imax": ("inv_imax", 30.0, 0.1, 1000.0),
            "umppt_max": ("inv_umax", 850.0, 1.0, 2000.0),
            "umppt_min": ("inv_umin", 200.0, 1.0, 2000.0),
            "tension_ac_v": ("inv_vac", 400.0, 120.0, 1000.0),
            "uw": ("inv_uw", 1000.0, 100.0, 2000.0),
        }
        battery_mapping = {
            "capacite_ah": ("batt_cap", 200.0, 1.0, 10000.0),
            "tension_v": ("batt_u", 48.0, 1.0, 1000.0),
            "dod_max": ("batt_dod", 0.80, 0.1, 0.95),
        }

        p_parsed, i_parsed, b_parsed = {}, {}, {}
        if panel_file is not None and st.session_state.last_panel_file != panel_file.name:
            p_parsed = parse_component_file(panel_file, "panel")
            p_empty = not bool(p_parsed)
            if p_empty:
                p_parsed = {"wc": 450.0, "impp": 10.8, "umpp": 41.7, "icc": 11.5, "uco": 49.5, "irm": 20.0, "degradation_annuelle": 0.005, "surface_m2": 2.1}
            st.session_state.panel_specs.update(p_parsed)
            sync_widget_values(st.session_state.panel_specs, p_parsed, panel_mapping)
            st.session_state.last_panel_file = panel_file.name
            st.session_state.last_panel_target = None
            st.session_state.panel_parse_empty = p_empty
        if inv_file is not None and st.session_state.last_inverter_file != inv_file.name:
            i_parsed = parse_component_file(inv_file, "inverter")
            i_empty = not bool(i_parsed)
            if i_empty:
                i_parsed = {"puissance_nominale_kw": 10.0, "imax": 30.0, "umppt_max": 850.0, "umppt_min": 200.0, "tension_ac_v": 400.0, "uw": 1000.0}
            st.session_state.inverter_specs.update(i_parsed)
            sync_widget_values(st.session_state.inverter_specs, i_parsed, inverter_mapping)
            st.session_state.last_inverter_file = inv_file.name
            st.session_state.last_inverter_target = None
            st.session_state.inverter_parse_empty = i_empty
        if batt_file is not None and st.session_state.last_battery_file != batt_file.name:
            b_parsed = parse_component_file(batt_file, "battery")
            b_empty = not bool(b_parsed)
            if b_empty:
                b_parsed = {"capacite_ah": 100.0, "tension_v": 48.0, "dod_max": 0.80}
            st.session_state.battery_specs.update(b_parsed)
            sync_widget_values(st.session_state.battery_specs, b_parsed, battery_mapping)
            st.session_state.last_battery_file = batt_file.name
            st.session_state.battery_parse_empty = b_empty

        p_specs = st.session_state.panel_specs
        i_specs = st.session_state.inverter_specs
        b_specs = st.session_state.battery_specs

        if panel_file is not None and st.session_state.panel_parse_empty:
            st.info("Si la fiche panneau est un PDF scanne ou un format graphique, verifiez les champs manuellement. Valeurs marche par defaut conservees.")
        if inv_file is not None and st.session_state.inverter_parse_empty:
            st.info("Si la fiche onduleur est un PDF scanne ou un format graphique, verifiez les champs manuellement. Valeurs marche par defaut conservees.")
        if batt_file is not None and st.session_state.battery_parse_empty:
            st.info("Si la fiche batterie est un PDF scanne ou un format graphique, verifiez les champs manuellement. Valeurs marche par defaut conservees.")

        power_candidates = extract_power_candidates_from_file(panel_file, "panel")
        selected_panel_power = None
        if power_candidates:
            selected_panel_power = st.selectbox(
                "Puissance panneau detectee dans la fiche (verifier si plusieurs puissances fabricant)",
                power_candidates,
                index=0,
            )
            if st.session_state.last_panel_target != selected_panel_power:
                targeted = parse_component_file(panel_file, "panel", target_value=selected_panel_power)
                targeted["wc"] = selected_panel_power
                st.session_state.panel_specs.update(targeted)
                sync_widget_values(st.session_state.panel_specs, targeted, panel_mapping)
                st.session_state.last_panel_target = selected_panel_power
        else:
            selected_panel_power = bounded_default(p_specs, "wc", 550.0, 1.0, 1000.0)

        with st.expander("Valeurs extraites automatiquement des fiches techniques"):
            st.write("Ces valeurs servent uniquement de pre-remplissage. Verifiez toujours les valeurs finales avant de continuer.")
            c1, c2, c3 = st.columns(3)
            c1.write("Panneau")
            c1.json(st.session_state.panel_specs)
            c2.write("Onduleur")
            c2.json(st.session_state.inverter_specs)
            c3.write("Batterie")
            c3.json(st.session_state.battery_specs)

        st.markdown("#### Panneau PV")
        c = st.columns(4)
        p_specs["wc"] = c[0].number_input("Puissance panneau a utiliser Wc", 1.0, 1000.0, float(selected_panel_power), key="panel_wc")
        p_specs["prix_unitaire"] = c[1].number_input("Prix panneau HT a saisir", 0.0, 100000.0, bounded_default(p_specs, "prix_unitaire", 0.0, 0.0, 100000.0), key="panel_price")
        p_specs["impp"] = c[2].number_input("Impp", 0.1, 100.0, bounded_default(p_specs, "impp", 13.16, 0.1, 100.0), key="panel_impp")
        p_specs["umpp"] = c[3].number_input("Umpp", 1.0, 200.0, bounded_default(p_specs, "umpp", 41.8, 1.0, 200.0), key="panel_umpp")
        p_specs["icc"] = st.number_input("Icc", 0.1, 100.0, bounded_default(p_specs, "icc", 13.95, 0.1, 100.0), key="panel_icc")
        p_specs["uco"] = st.number_input("Uco", 1.0, 250.0, bounded_default(p_specs, "uco", 49.5, 1.0, 250.0), key="panel_uco")
        p_specs["irm"] = st.number_input("IRM", 0.1, 100.0, bounded_default(p_specs, "irm", 25.0, 0.1, 100.0), key="panel_irm")
        p_specs["degradation_annuelle"] = st.number_input("Taux degradation annuel", 0.0, 0.05, bounded_default(p_specs, "degradation_annuelle", 0.005, 0.0, 0.05), 0.001, key="panel_deg")
        p_specs["surface_m2"] = st.number_input("Surface unitaire m2", 0.1, 10.0, bounded_default(p_specs, "surface_m2", 2.61, 0.1, 10.0), 0.01, key="panel_surface")
        panel = PanelTech(**p_specs)

        st.markdown("#### Onduleur")
        inverter_candidates = extract_power_candidates_from_file(inv_file, "inverter")
        if inverter_candidates:
            selected_inverter_power = st.selectbox(
                "Puissance onduleur detectee dans la fiche (kW, verifier le modele exact)",
                inverter_candidates,
                index=0,
            )
            if st.session_state.last_inverter_target != selected_inverter_power:
                targeted = parse_component_file(inv_file, "inverter", target_value=selected_inverter_power)
                targeted["puissance_nominale_kw"] = selected_inverter_power
                st.session_state.inverter_specs.update(targeted)
                sync_widget_values(st.session_state.inverter_specs, targeted, inverter_mapping)
                st.session_state.last_inverter_target = selected_inverter_power
        c = st.columns(4)
        i_specs["puissance_nominale_kw"] = c[0].number_input("Puissance nominale onduleur kW a verifier", 0.1, 1000.0, bounded_default(i_specs, "puissance_nominale_kw", selected_pc / 1.2, 0.1, 1000.0), key="inv_pnom")
        i_specs["prix_unitaire"] = c[1].number_input("Prix onduleur HT a saisir", 0.0, 1000000.0, bounded_default(i_specs, "prix_unitaire", 0.0, 0.0, 1000000.0), key="inv_price")
        i_specs["imax"] = c[2].number_input("Imax", 0.1, 1000.0, bounded_default(i_specs, "imax", 30.0, 0.1, 1000.0), key="inv_imax")
        i_specs["umppt_max"] = c[3].number_input("Umppt max", 1.0, 2000.0, bounded_default(i_specs, "umppt_max", 850.0, 1.0, 2000.0), key="inv_umax")
        i_specs["umppt_min"] = st.number_input("Umppt min", 1.0, 2000.0, bounded_default(i_specs, "umppt_min", 200.0, 1.0, 2000.0), key="inv_umin")
        i_specs["tension_ac_v"] = st.number_input("Tension AC V", 120.0, 1000.0, bounded_default(i_specs, "tension_ac_v", 400.0, 120.0, 1000.0), key="inv_vac")
        i_specs["uw"] = st.number_input("Uw tension max supportee", 100.0, 2000.0, bounded_default(i_specs, "uw", 1000.0, 100.0, 2000.0), key="inv_uw")
        i_specs["phases"] = st.selectbox("Phases AC", [1, 3], index=0 if int(i_specs.get("phases", 3)) == 1 else 1, key="inv_phases")
        inverter = InverterTech(**i_specs)

        battery = None
        autonomie = 1.0
        if type_systeme in ["hybride", "off-grid"]:
            st.markdown("#### Batterie")
            st.caption("La fiche batterie pre-remplit les parametres techniques. L'utilisateur doit renseigner l'autonomie souhaitee et le prix.")
            autonomie = st.number_input("Nombre de jours d'autonomie N a saisir", 0.5, 10.0, 2.0, 0.5)
            b_specs["capacite_ah"] = st.number_input("C_batt Ah", 1.0, 10000.0, bounded_default(b_specs, "capacite_ah", 200.0, 1.0, 10000.0), key="batt_cap")
            b_specs["tension_v"] = st.number_input("U_batt V", 1.0, 1000.0, bounded_default(b_specs, "tension_v", 48.0, 1.0, 1000.0), key="batt_u")
            b_specs["dod_max"] = st.number_input("D DoD max", 0.1, 0.95, bounded_default(b_specs, "dod_max", 0.80, 0.1, 0.95), 0.05, key="batt_dod")
            b_specs["prix_unitaire"] = st.number_input("Prix batterie HT a saisir", 0.0, 100000.0, bounded_default(b_specs, "prix_unitaire", 0.0, 0.0, 100000.0), key="batt_price")
            battery = BatteryTech(**b_specs)

        st.markdown("#### Cables et protections")
        c = st.columns(5)
        cable = CableDesignInput(
            conducteur=c[0].selectbox("Conducteur", ["Cuivre", "Aluminium"]),
            longueur_dc_m=c[1].number_input("Longueur DC aller l (m)", 0.1, 1000.0, 30.0),
            longueur_ac_m=c[2].number_input("Longueur AC aller l (m)", 0.1, 1000.0, 20.0),
            chute_dc=c[3].number_input("epsilon DC", 0.001, 0.10, 0.03, 0.001, format="%.3f"),
            chute_ac=c[4].number_input("epsilon AC", 0.001, 0.10, 0.03, 0.001, format="%.3f"),
        )
        spd_up = st.number_input("Parafoudre DC Up (V)", 10.0, 2000.0, 600.0)
        conso_annuelle = float(conso["Consommation_kWh"].sum())
        design = calculate_pv_design(selected_pc, conso_annuelle, type_systeme, panel, inverter, battery, autonomie, cable, spd_up)
        st.session_state.design = design
        st.session_state.panel_tech = panel
        st.session_state.inverter_tech = inverter
        st.session_state.battery_tech = battery
        st.markdown("### Resultats du dimensionnement")
        g = design["general"]
        comp = design["compatibilite_onduleur"]
        cab = design["cables"]
        prot = design["protections"]

        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Modules PV", g["nombre_modules"])
        r2.metric("Puissance reelle", f"{g['puissance_reelle_kwc']} kWc")
        r3.metric("Surface panneaux", f"{g['surface_panneaux_m2']} m2")
        r4.metric("U_sys recommande", f"{g['u_sys_recommande_v']} V")

        status = "Compatible" if comp["compatible_global"] else "A verifier"
        if comp["compatible_global"]:
            st.success(f"Compatibilite onduleur: {status}")
        else:
            st.warning(f"Compatibilite onduleur: {status}")

        dict_to_table("Compatibilite onduleur", comp)
        if design.get("batteries"):
            dict_to_table("Stockage batteries", design["batteries"])
        dict_to_table("Dimensionnement cables", cab)

        st.markdown("**Dispositifs de protection calcules**")
        protection_rows = [
            {"Protection": "Fusible DC", "Calibrage": f"In choisi {prot['fusible_dc']['in_choisi_a']} A", "Tension": f"Un >= {prot['fusible_dc']['un_min_v']} V", "Etat": "OK" if prot["fusible_dc"]["ok"] else "A verifier / IRM insuffisant"},
            {"Protection": "Sectionneur DC", "Calibrage": f"In >= {prot['sectionneur_dc']['in_min_a']} A, choisi {prot['sectionneur_dc']['in_choisi_a']} A", "Tension": f"Un >= {prot['sectionneur_dc']['un_min_v']} V", "Etat": "Calcul indicatif"},
            {"Protection": "Parafoudre DC", "Calibrage": f"Up = {prot['parafoudre_dc']['up_v']} V", "Tension": "Up < 0.8*Uco et Up < 0.8*Uw", "Etat": "OK" if prot["parafoudre_dc"]["critere_modules_up_lt_0_8_uco"] and prot["parafoudre_dc"]["critere_onduleur_up_lt_0_8_uw"] else "A verifier"},
            {"Protection": "Disjoncteur AC", "Calibrage": f"In choisi {prot['protection_ac']['disjoncteur_ac_choisi_a']} A", "Tension": f"Iac = {prot['protection_ac']['courant_ac_a']} A", "Etat": "Calcul indicatif"},
        ]
        st.dataframe(pd.DataFrame(protection_rows), use_container_width=True, hide_index=True)
        st.info("Les calibrages sont calcules pour aider le choix du materiel. L'utilisateur renseigne ensuite les prix dans le CAPEX.")

# ------------------------------------------------------------------------------
# 7 ECONOMY
# ------------------------------------------------------------------------------
with tabs[6]:
    st.subheader("Analyse economique et CAPEX")
    design = st.session_state.design
    conso = st.session_state.consommation
    production = st.session_state.production
    if not design or conso is None or production is None:
        st.warning("Completez d'abord consommation, production et dimensionnement.")
    else:
        panel = st.session_state.panel_tech
        inverter = st.session_state.inverter_tech
        battery = st.session_state.battery_tech
        structure_type = st.selectbox("Type structure", ["Toiture residentielle inclinee", "Toiture industrielle bac acier", "Sol ground-mounted", "Ombriere parking"])
        labour_pct = st.number_input("Main d'oeuvre automatique (% CAPEX hors MO)", 0.0, 0.50, 0.15, 0.01)
        econ_config = apply_financial_inputs(base_config, panel.degradation_annuelle)
        default_rows = default_capex_rows(design, panel, inverter, battery, type_systeme, structure_type, labour_pct)
        edited = st.data_editor(default_rows, num_rows="dynamic", use_container_width=True, key="capex_editor")
        capex_summary = capex_from_rows(edited, econ_config["economie"]["tva"])
        st.session_state.capex_rows = edited
        st.session_state.capex_total = capex_summary["total_ttc"]
        c1, c2, c3 = st.columns(3)
        c1.metric("Total HT", f"{capex_summary['total_ht']:,.0f} MAD")
        c2.metric("TVA", f"{capex_summary['tva']:,.0f} MAD")
        c3.metric("Total TTC", f"{capex_summary['total_ttc']:,.0f} MAD")
        try:
            eco = AnalyseEconomiqueAvancee(econ_config, capex_summary["total_ttc"], type_contrat, production, conso, inclure_revenu_injection=(type_contrat != "bt_residentiel" and type_systeme != "off-grid"))
            bilan = eco.calculer_bilan_complet()
            st.session_state.bilan_eco = bilan
            i = bilan["indicateurs_rentabilite"]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("LCOE", f"{i['lcoe_mad_kwh']:.3f} MAD/kWh")
            c2.metric("VAN", f"{i['van_mad']:,.0f} MAD")
            c3.metric("TRI", f"{i['tri_pct']} %")
            c4.metric("Payback", f"{i['periode_retour_simple_ans']} ans")
        except Exception as exc:
            st.error(f"Erreur economie: {exc}")

# ------------------------------------------------------------------------------
# 8 RECOMMENDATIONS
# ------------------------------------------------------------------------------
with tabs[7]:
    st.subheader("Recommandations efficacite energetique et optimisation PV")
    if st.session_state.consommation is None:
        st.warning("Chargez la consommation.")
    else:
        reco_engine = RecommandationsISO50001(st.session_state.consommation, st.session_state.tmy, st.session_state.production, st.session_state.donnees_reseau, st.session_state.diagnostic, type_batiment)
        reco = reco_engine.generer_recommandations()
        st.session_state.recommandations = reco
        for item in reco["recommandations"]:
            msg = f"**{item['titre']}**\n\n{item['message']}"
            if item["niveau"] == "danger": st.error(msg)
            elif item["niveau"] == "warning": st.warning(msg)
            elif item["niveau"] == "success": st.success(msg)
            else: st.info(msg)
            with st.expander("Actions"):
                for a in item.get("actions", []): st.write(f"- {a}")
        st.markdown("#### Idees innovantes a integrer ensuite")
        st.write("- Pilotage automatique des charges flexibles selon prevision PV du lendemain.")
        st.write("- Score de qualite energetique du batiment avant/apres PV.")
        st.write("- Simulation batterie virtuelle: surplus transforme en usages decales.")
        st.write("- Detection d'anomalies par comparaison jours ouvrables/week-ends.")

# ------------------------------------------------------------------------------
# 9 PDF
# ------------------------------------------------------------------------------
with tabs[8]:
    st.subheader("Rapport PDF")
    if st.session_state.production is None or not st.session_state.bilan_eco:
        st.warning("Completez d'abord les calculs.")
    else:
        balance = st.session_state.get("energy_balance", {})
        resultats_pdf = {
            "nom_projet": project_name,
            "ville": ville,
            "type_batiment": type_batiment,
            "type_contrat": TYPES_CONTRAT[type_contrat]["label"],
            "type_systeme": type_systeme,
            "pc_kwc": st.session_state.get("selected_pc", 0),
            "capex_total_mad": st.session_state.capex_total,
            "conclusion": "Rapport de pre-faisabilite a confirmer par etude technique detaillee.",
            "kpis": {
                "pc_kwc": st.session_state.get("selected_pc", 0),
                "production_kwh": balance.get("production_kwh", 0),
                "taux_autoconso_pct": balance.get("taux_autoconso", 0) * 100,
                "capex_mad": st.session_state.capex_total,
                "van_mad": st.session_state.bilan_eco.get("indicateurs_rentabilite", {}).get("van_mad", 0),
                "retour_ans": st.session_state.bilan_eco.get("indicateurs_rentabilite", {}).get("periode_retour_simple_ans", "N/A"),
            },
            "diagnostic_donnees": st.session_state.diagnostic,
            "stats_tmy": st.session_state.stats_tmy,
            "stats_conso": st.session_state.get("stats_conso", {}),
            "recommandations": st.session_state.recommandations,
            "dimensionnement": st.session_state.design,
            "economie": st.session_state.bilan_eco,
        }
        if st.button("Generer le rapport PDF"):
            path = generer_rapport_pdf(resultats_pdf, "outputs/rapport_opti_solar.pdf")
            st.success(f"Rapport genere: {path}")
            with open(path, "rb") as f:
                st.download_button("Telecharger", f, file_name="rapport_opti_solar.pdf", mime="application/pdf")
