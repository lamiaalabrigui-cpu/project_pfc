"""
Module TMY Avance - Opti-Solar Maroc

Chargement des donnees TMY depuis fichiers CSV par ville.
Format attendu:
- lignes metadata commencant par "#"
- ligne d'en-tete: Year,Month,Day,Hour,Minute,GHI,DHI,DNI,GPI,Tamb,WindVel,Press,RelHum
- ligne d'unites a supprimer
- 8760 lignes horaires utiles

Remarque:
Le GPI fourni dans les fichiers correspond a un plan incline de 30 deg.
Si l'utilisateur change inclinaison/azimut, le module peut recalculer un GPI simplifie.
Pour une transposition avancee Perez/HDKR, utiliser pvlib.
"""

from pathlib import Path
from typing import Dict, Any, Optional
import numpy as np
import pandas as pd

from modules.config_advanced import DATA_TMY_DIR, VILLES_MAROC


COLONNES_TMY = [
    "Annee", "Mois", "Jour", "Heure", "Minute",
    "GHI", "DHI", "DNI", "GPI", "Tamb",
    "WindVel", "Press", "RelHum",
]


class TMYDataLoader:
    """
    Chargeur de donnees TMY depuis fichiers CSV.
    """

    def __init__(self, data_dir: str = DATA_TMY_DIR):
        self.data_dir = Path(data_dir)
        self.data: Optional[pd.DataFrame] = None
        self.metadata: Dict[str, Any] = {}
        self.ville: Optional[str] = None
        self.latitude: Optional[float] = None
        self.longitude: Optional[float] = None
        self.altitude: Optional[float] = None
        self.timezone: Optional[str] = None

    def charger_donnees_ville(self, ville: str) -> pd.DataFrame:
        """
        Charge les donnees TMY d'une ville depuis le fichier CSV configure.

        Args:
            ville: Nom de la ville dans VILLES_MAROC.

        Returns:
            DataFrame horaire 8760 lignes avec DateTime.
        """
        if ville not in VILLES_MAROC:
            raise ValueError(f"Ville inconnue: {ville}. Villes disponibles: {list(VILLES_MAROC.keys())}")

        ville_cfg = VILLES_MAROC[ville]
        file_path = self.data_dir / ville_cfg["file_name"]

        df, metadata = self.charger_fichier_csv(file_path)

        self.data = df
        self.metadata = metadata
        self.ville = ville

        self.latitude = float(metadata.get("Latitude", ville_cfg["latitude"]))
        self.longitude = float(metadata.get("Longitude", ville_cfg["longitude"]))
        self.altitude = float(metadata.get("Altitude", ville_cfg["altitude"]))
        self.timezone = metadata.get("Time zone", ville_cfg.get("timezone", "UTC+01:00"))

        return df

    def charger_fichier_csv(self, file_path: str | Path) -> tuple[pd.DataFrame, Dict[str, Any]]:
        """
        Charge un fichier CSV TMY individuel.

        Args:
            file_path: Chemin du fichier .csv ou .csv.txt.

        Returns:
            (DataFrame nettoye, metadata)
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Fichier TMY introuvable: {file_path}")

        metadata = self._lire_metadata(file_path)

        df = pd.read_csv(file_path, comment="#")

        # Supprimer la ligne des unites: Year vide, GHI=W/m2, etc.
        df = df[pd.to_numeric(df["Year"], errors="coerce").notna()].copy()

        expected_cols = [
            "Year", "Month", "Day", "Hour", "Minute",
            "GHI", "DHI", "DNI", "GPI", "Tamb",
            "WindVel", "Press", "RelHum",
        ]

        missing = [col for col in expected_cols if col not in df.columns]
        if missing:
            raise ValueError(f"Colonnes TMY manquantes dans {file_path.name}: {missing}")

        df = df[expected_cols].copy()
        df.columns = COLONNES_TMY

        for col in COLONNES_TMY:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["Annee", "Mois", "Jour", "Heure", "Minute"])
        df[["Annee", "Mois", "Jour", "Heure", "Minute"]] = df[
            ["Annee", "Mois", "Jour", "Heure", "Minute"]
        ].astype(int)

        df["DateTime"] = pd.to_datetime({
            "year": df["Annee"],
            "month": df["Mois"],
            "day": df["Jour"],
            "hour": df["Heure"],
            "minute": df["Minute"],
        })

        df = df.sort_values("DateTime").reset_index(drop=True)

        self._valider_donnees(df, file_path.name)

        # Nettoyage physique simple.
        for col in ["GHI", "DHI", "DNI", "GPI"]:
            df[col] = df[col].clip(lower=0)

        df["Tamb"] = df["Tamb"].interpolate(limit_direction="both")
        df["WindVel"] = df["WindVel"].fillna(2.0).clip(lower=0)
        df["Press"] = df["Press"].interpolate(limit_direction="both")
        df["RelHum"] = df["RelHum"].interpolate(limit_direction="both").clip(lower=0, upper=100)

        return df, metadata

    def _lire_metadata(self, file_path: Path) -> Dict[str, Any]:
        """
        Lit les lignes metadata commencant par "#".
        Exemple: #Latitude,32.2214
        """
        metadata: Dict[str, Any] = {}

        with open(file_path, "r", encoding="utf-8-sig") as f:
            for line in f:
                if not line.startswith("#"):
                    break

                line = line[1:].strip()
                if "," in line:
                    key, value = line.split(",", 1)
                    metadata[key.strip()] = value.strip()
                else:
                    metadata[line.strip()] = True

        return metadata

    def _valider_donnees(self, df: pd.DataFrame, file_name: str):
        """
        Controle l'integrite du fichier TMY.
        """
        if len(df) != 8760:
            raise ValueError(f"{file_name}: nombre d'heures invalide ({len(df)} au lieu de 8760).")

        if df["DateTime"].duplicated().any():
            raise ValueError(f"{file_name}: doublons DateTime detectes.")

        deltas = df["DateTime"].diff().dropna()
        if not (deltas == pd.Timedelta(hours=1)).all():
            raise ValueError(f"{file_name}: pas horaire non regulier detecte.")

        if df[["GHI", "DHI", "DNI", "GPI"]].isna().any().any():
            raise ValueError(f"{file_name}: valeurs solaires manquantes detectees.")

    def calculer_gpi_dynamique(
        self,
        inclinaison_deg: float,
        azimut_deg: float = 0.0,
        albedo: float = 0.20,
        timezone_meridian_deg: float = 0.0,
    ) -> pd.Series:
        """
        Calcule un GPI simplifie pour une inclinaison/azimut donnes.

        Convention:
        - inclinaison_deg: 0 horizontal, 90 vertical
        - azimut_deg: 0 sud, -90 est, +90 ouest

        Attention:
        Ce modele est une transposition isotrope simplifiee:
        direct + diffuse isotrope + reflechie sol.
        Il ne doit pas etre annonce comme Perez/HDKR.
        """
        if self.data is None:
            raise ValueError("Aucune donnee TMY chargee.")

        if self.latitude is None or self.longitude is None:
            raise ValueError("Latitude/longitude indisponibles.")

        if not 0 <= inclinaison_deg <= 90:
            raise ValueError("inclinaison_deg doit etre entre 0 et 90 degres.")

        if not -180 <= azimut_deg <= 180:
            raise ValueError("azimut_deg doit etre entre -180 et 180 degres.")

        beta = np.radians(inclinaison_deg)
        gamma = np.radians(azimut_deg)
        phi = np.radians(self.latitude)

        ghi = self.data["GHI"].to_numpy(dtype=float)
        dhi = self.data["DHI"].to_numpy(dtype=float)
        dni = self.data["DNI"].to_numpy(dtype=float)

        gpi_calcule = np.zeros(len(self.data), dtype=float)

        for i, dt in enumerate(self.data["DateTime"]):
            n = dt.dayofyear
            heure_locale = dt.hour + dt.minute / 60

            delta = np.radians(23.45) * np.sin(2 * np.pi * (284 + n) / 365)

            b = 2 * np.pi * (n - 1) / 365
            equation_temps_min = 229.2 * (
                0.000075
                + 0.001868 * np.cos(b)
                - 0.032077 * np.sin(b)
                - 0.014615 * np.cos(2 * b)
                - 0.04089 * np.sin(2 * b)
            )

            correction_longitude_h = 4 * (self.longitude - timezone_meridian_deg) / 60
            heure_solaire = heure_locale + equation_temps_min / 60 + correction_longitude_h

            omega = np.radians(15 * (heure_solaire - 12))

            sin_alpha = (
                np.sin(phi) * np.sin(delta)
                + np.cos(phi) * np.cos(delta) * np.cos(omega)
            )
            sin_alpha = np.clip(sin_alpha, -1, 1)
            alpha = np.arcsin(sin_alpha)

            if alpha <= 0:
                gpi_calcule[i] = 0
                continue

            cos_theta = (
                np.sin(delta) * np.sin(phi) * np.cos(beta)
                - np.sin(delta) * np.cos(phi) * np.sin(beta) * np.cos(gamma)
                + np.cos(delta) * np.cos(phi) * np.cos(beta) * np.cos(omega)
                + np.cos(delta) * np.sin(phi) * np.sin(beta) * np.cos(gamma) * np.cos(omega)
                + np.cos(delta) * np.sin(beta) * np.sin(gamma) * np.sin(omega)
            )
            cos_theta = np.clip(cos_theta, 0, 1)

            # DNI est une irradiance normale directe: composante sur plan = DNI * cos(theta).
            i_beam = max(0.0, dni[i] * cos_theta)

            facteur_vue_ciel = (1 + np.cos(beta)) / 2
            i_diffuse = dhi[i] * facteur_vue_ciel

            facteur_vue_sol = (1 - np.cos(beta)) / 2
            i_reflechie = ghi[i] * albedo * facteur_vue_sol

            gpi_calcule[i] = max(0.0, i_beam + i_diffuse + i_reflechie)

        self.data["GPI_Calcule"] = gpi_calcule

        return self.data["GPI_Calcule"]

    def get_statistiques(self, utiliser_gpi_calcule: bool = False) -> Dict[str, Any]:
        if self.data is None:
            raise ValueError("Aucune donnee TMY chargee.")

        gpi_col = self._choisir_colonne_gpi(utiliser_gpi_calcule)

        return {
            "ville": self.ville,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "altitude": self.altitude,
            "timezone": self.timezone,
            "heures": len(self.data),
            "irradiation_annuelle_ghi_kwh_m2": float(round(self.data["GHI"].sum() / 1000, 2)),
            "irradiation_annuelle_gpi_kwh_m2": round(self.data[gpi_col].sum() / 1000, 2),
            "temperature_moyenne_c": round(self.data["Tamb"].mean(), 2),
            "temperature_max_c": round(self.data["Tamb"].max(), 2),
            "temperature_min_c": round(self.data["Tamb"].min(), 2),
            "vent_moyen_m_s": round(self.data["WindVel"].mean(), 2),
            "heures_ensoleillement": int((self.data["GHI"] > 100).sum()),
            "pic_irradiation_ghi_w_m2": round(self.data["GHI"].max(), 2),
            "pic_irradiation_gpi_w_m2": round(self.data[gpi_col].max(), 2),
        }

    def get_irradiation_mensuelle(self, utiliser_gpi_calcule: bool = False) -> pd.DataFrame:
        if self.data is None:
            raise ValueError("Aucune donnee TMY chargee.")

        gpi_col = self._choisir_colonne_gpi(utiliser_gpi_calcule)

        monthly = self.data.groupby("Mois").agg({
            "GHI": "sum",
            gpi_col: "sum",
            "Tamb": "mean",
            "WindVel": "mean",
        }).reset_index()

        monthly["GHI_kWh_m2"] = monthly["GHI"] / 1000
        monthly["GPI_kWh_m2"] = monthly[gpi_col] / 1000

        mois_noms = {
            1: "Jan", 2: "Fev", 3: "Mar", 4: "Avr",
            5: "Mai", 6: "Jun", 7: "Jul", 8: "Aou",
            9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
        }
        monthly["Mois_Nom"] = monthly["Mois"].map(mois_noms)

        return monthly

    def get_profil_journalier_moyen(self, utiliser_gpi_calcule: bool = False) -> pd.DataFrame:
        if self.data is None:
            raise ValueError("Aucune donnee TMY chargee.")

        gpi_col = self._choisir_colonne_gpi(utiliser_gpi_calcule)

        profil = self.data.groupby("Heure").agg({
            "GHI": "mean",
            gpi_col: "mean",
            "Tamb": "mean",
            "WindVel": "mean",
        }).reset_index()

        profil = profil.rename(columns={gpi_col: "GPI_Moyen"})

        return profil

    def _choisir_colonne_gpi(self, utiliser_gpi_calcule: bool) -> str:
        if utiliser_gpi_calcule and self.data is not None and "GPI_Calcule" in self.data.columns:
            return "GPI_Calcule"

        if self.data is not None and "GPI" in self.data.columns:
            return "GPI"

        raise ValueError("Aucune colonne GPI disponible.")


def calculer_angle_optimal_inclinaison(latitude: float) -> float:
    """
    Heuristique simple pour le Maroc.
    Pour une optimisation fine, tester plusieurs inclinaisons avec production/autoconsommation.
    """
    inclinaison = latitude - 5
    inclinaison = np.clip(inclinaison, 10, 40)
    return round(float(inclinaison), 1)


def verifier_fichier_tmy(file_path: str | Path) -> Dict[str, Any]:
    """
    Verifie rapidement un fichier TMY CSV.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        return {
            "existe": False,
            "erreur": f"Fichier introuvable: {file_path}",
        }

    try:
        loader = TMYDataLoader(data_dir=file_path.parent)
        df, metadata = loader.charger_fichier_csv(file_path)

        return {
            "existe": True,
            "fichier": file_path.name,
            "nombre_lignes": len(df),
            "colonnes": list(df.columns),
            "metadata": metadata,
            "date_debut": df["DateTime"].min(),
            "date_fin": df["DateTime"].max(),
            "irradiation_ghi_kwh_m2": round(df["GHI"].sum() / 1000, 2),
            "irradiation_gpi_kwh_m2": round(df["GPI"].sum() / 1000, 2),
        }

    except Exception as exc:
        return {
            "existe": True,
            "fichier": file_path.name,
            "erreur": str(exc),
        }


def verifier_dossier_tmy(data_dir: str | Path = DATA_TMY_DIR) -> Dict[str, Any]:
    """
    Verifie que tous les fichiers TMY configures dans VILLES_MAROC sont presents et valides.
    """
    data_dir = Path(data_dir)
    resultats = {}

    for ville, cfg in VILLES_MAROC.items():
        file_path = data_dir / cfg["file_name"]
        resultats[ville] = verifier_fichier_tmy(file_path)

    fichiers_ok = all(item.get("existe") and "erreur" not in item for item in resultats.values())

    return {
        "dossier": str(data_dir),
        "fichiers_ok": fichiers_ok,
        "resultats": resultats,
    }
