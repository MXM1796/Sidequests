"""
ESP32 Sensor-Rauschanalyse
===========================
Schritt 1: Rauschboden bestimmen (Standardabweichung bei konstanten Bedingungen)
Schritt 2: Allan-Deviation berechnen (trennt Rauschen von Drift)

Datenquelle: InfluxDB 3.x / Cloud, Abfrage per SQL über den offiziellen
influxdb3-python Client (Arrow Flight SQL), letzte 12h.

Installation:
    pip install influxdb3-python pandas numpy matplotlib allantools
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import allantools
from influxdb_client_3 import InfluxDBClient3
from config_private import INFLUX_HOST, INFLUX_TOKEN, INFLUX_DATABASE

# ---------------------------------------------------------------------------
# 1. Daten aus InfluxDB 3.x laden
# ---------------------------------------------------------------------------
# Werte anpassen: Host-URL und Token findest du im InfluxDB Cloud UI unter
# "Load Data > API Tokens"; database = der Bucket-/Datenbankname.
INFLUX_DATABASE = "Temperaturdaten"
MEASUREMENT = "klima"  # Name deines Measurements, z.B. "dht22"
VALUE_COLUMN = "feuchtigkeit"  # Feldname, z.B. "humidity" oder "temperature"
LOOKBACK = "24 hours"

client = InfluxDBClient3(
    host=INFLUX_HOST,
    token=INFLUX_TOKEN,
    database=INFLUX_DATABASE,
)

query = f"""
SELECT time, {VALUE_COLUMN}
FROM "{MEASUREMENT}"
WHERE time >= now() - interval '{LOOKBACK}'
ORDER BY time
"""

table = client.query(query=query, language="sql")
df = table.to_pandas()
df = df.rename(columns={VALUE_COLUMN: "value"})
df["time"] = pd.to_datetime(df["time"])
df = df.sort_values("time").reset_index(drop=True)

print(f"{len(df)} Messwerte aus den letzten {LOOKBACK} geladen "
      f"({df['time'].min()} bis {df['time'].max()})")

# Abtastintervall in Sekunden bestimmen (muss für Allan-Deviation ~konstant sein)
dt = df["time"].diff().dt.total_seconds().median()
print(f"Median-Abtastintervall: {dt:.2f} s")

values = df["value"].to_numpy()

# ---------------------------------------------------------------------------
# Schritt 1: Rauschboden bestimmen
# ---------------------------------------------------------------------------
# Wichtig: Dieser Datensatz sollte aus einer Phase mit möglichst konstanten
# äußeren Bedingungen stammen (z.B. eine ruhige Nacht), sonst mischt sich
# echte Signaländerung mit Rauschen.

mean_val = np.mean(values)
std_val = np.std(values, ddof=1)  # Stichproben-Standardabweichung
n = len(values)
sem = std_val / np.sqrt(n)  # Standardfehler des Mittelwerts (nur gültig bei Unabhängigkeit!)

print("\n--- Schritt 1: Rauschboden ---")
print(f"Mittelwert:              {mean_val:.3f}")
print(f"Standardabweichung (σ):  {std_val:.4f}")
print(f"Naiver Standardfehler:   {sem:.4f}  (Achtung: unterschätzt bei Autokorrelation!)")
print(f"Anzahl Messwerte:        {n}")
print("--> Vergleiche std_val mit der Genauigkeitsangabe im Sensor-Datenblatt.")

# Autokorrelation der ersten Lags prüfen (sollte bei reinem Rauschen ~0 sein)
autocorr_lag1 = pd.Series(values).autocorr(lag=1)
print(f"Autokorrelation (Lag 1): {autocorr_lag1:.3f}")
if abs(autocorr_lag1) > 0.3:
    print("--> Deutliche Autokorrelation: der naive Standardfehler ist zu optimistisch.")

# ---------------------------------------------------------------------------
# Schritt 2: Allan-Deviation berechnen
# ---------------------------------------------------------------------------
# allantools erwartet eine Rate (Messungen pro Sekunde) statt dt direkt.
rate = 1.0 / dt

taus, adevs, errors, ns = allantools.oadev(
    values, rate=rate, data_type="freq", taus="octave"
)

print("\n--- Schritt 2: Allan-Deviation ---")
for tau, adev in zip(taus, adevs):
    print(f"τ = {tau:8.1f} s   ADEV = {adev:.4f}")

plt.figure(figsize=(7, 5))
plt.loglog(taus, adevs, marker="o")
plt.xlabel("Mittelungszeit τ [s]")
plt.ylabel("Allan-Deviation")
plt.title(f"Allan-Deviation: {MEASUREMENT}/{VALUE_COLUMN}")
plt.grid(True, which="both", ls="--", alpha=0.5)
plt.tight_layout()
plt.savefig("allan_deviation.png", dpi=150)
plt.show()

print("\nInterpretation:")
print("- Fallender Teil (meist τ^-1/2): dominiert von weißem Rauschen,")
print("  Mittelung über längere Zeit verbessert die Präzision.")
print("- Minimum: optimale Mittelungszeit für diesen Sensor.")
print("- Ansteigender Teil danach: Drift dominiert, längeres Mitteln hilft")
print("  ab hier nicht mehr bzw. verschlechtert die Genauigkeit wieder.")
