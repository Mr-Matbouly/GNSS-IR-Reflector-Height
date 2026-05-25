"""
GNSS-IR Reflector Height Estimation
-----------------------------------
Full pipeline for estimating reflector height using GNSS SNR data.
"""

# =========================
# 📦 Imports
# =========================
import numpy as np
import matplotlib.pyplot as plt
import georinex as gr
from pyproj import Transformer


# =========================
# 📌 Load Data
# =========================
obs = gr.load("p0411000.24o", use="G")   # RINEX Observation
nav = gr.load("COD0OPSFIN_20241000000_01D_05M_ORB.SP3")  # SP3 Orbits


# =========================
# 📍 Receiver Position
# =========================
rx_pos = obs.attrs["position"]

# Convert ECEF → Geodetic
transformer = Transformer.from_crs("epsg:4978", "epsg:4979", always_xy=True)
lon, lat, h = transformer.transform(rx_pos[0], rx_pos[1], rx_pos[2])

# Precompute trig terms
sin_lon, cos_lon = np.sin(np.deg2rad(lon)), np.cos(np.deg2rad(lon))
sin_lat, cos_lat = np.sin(np.deg2rad(lat)), np.cos(np.deg2rad(lat))

times = obs.time.values


# =========================
# 🛰️ STEP 1: Elevation Calculation + Satellite Selection
# =========================
elevations_dict = {}
valid_satellites = []

for sv in obs.sv.values:

    if sv not in nav.sv.values:
        continue

    nav_interp = nav.interp(time=obs.time).sel(sv=sv)

    elevations = []

    for t in range(len(times)):
        try:
            sat_pos = nav_interp.isel(time=t)

            # Satellite position (meters)
            xs = sat_pos["position"].sel(ECEF="x").values * 1000
            ys = sat_pos["position"].sel(ECEF="y").values * 1000
            zs = sat_pos["position"].sel(ECEF="z").values * 1000

            # Vector difference
            dx = xs - rx_pos[0]
            dy = ys - rx_pos[1]
            dz = zs - rx_pos[2]

            # ENU transformation
            east  = -sin_lon * dx + cos_lon * dy
            north = -sin_lat * cos_lon * dx - sin_lat * sin_lon * dy + cos_lat * dz
            up    =  cos_lat * cos_lon * dx + cos_lat * sin_lon * dy + sin_lat * dz

            # Elevation angle (degrees)
            elev = np.rad2deg(np.arctan2(up, np.sqrt(east**2 + north**2)))
            elevations.append(elev)

        except:
            elevations.append(np.nan)

    elevations = np.array(elevations)

    # Select satellites in GNSS-IR useful range
    mask = (elevations > 5) & (elevations < 25)

    if np.sum(mask) > 1000:   # High-quality satellites
        elevations_dict[sv] = elevations
        valid_satellites.append(sv)
        print(f"{sv} ✅ usable (points = {np.sum(mask)})")

print("\nSelected satellites:", valid_satellites)


# =========================
# 📡 STEP 2: Height Estimation (PER SATELLITE)
# =========================
lambda_L1 = 0.19029367  # GPS L1 wavelength (m)
heights = []

for sv in valid_satellites:

    print(f"\nProcessing {sv} ...")

    elevations = elevations_dict[sv]
    snr = obs["S1"].sel(sv=sv).values

    # Filter valid data (5-25°)
    mask = (~np.isnan(elevations)) & (~np.isnan(snr)) \
           & (elevations > 5) & (elevations < 25)

    elev_clean = elevations[mask]
    snr_clean = snr[mask]

    # Ensure enough data
    if len(snr_clean) < 100:
        continue

    # =========================
    # 🔧 Detrending
    # =========================
    t = np.arange(len(snr_clean))
    p = np.polyfit(t, snr_clean, 3)
    trend = np.polyval(p, t)
    snr_detrended = snr_clean - trend

    # =========================
    # 🔄 Convert to sin(elevation)
    # =========================
    sin_e = np.sin(np.deg2rad(elev_clean))

    # Sort data for FFT
    sort_idx = np.argsort(sin_e)
    sin_sorted = sin_e[sort_idx]
    snr_sorted = snr_detrended[sort_idx]

    # Remove DC component
    snr_signal = snr_sorted - np.mean(snr_sorted)

    # Sampling step
    delta = np.mean(np.diff(sin_sorted))

    # =========================
    # 📊 FFT
    # =========================
    fft_vals = np.fft.rfft(snr_signal)
    mag = np.abs(fft_vals)

    freq = np.fft.rfftfreq(len(snr_signal), d=delta)

    # Remove zero frequency
    freq, mag = freq[1:], mag[1:]

    # Select valid frequency range
    mask_valid = (freq > 10) & (freq < 150)

    freq_valid = freq[mask_valid]
    mag_valid = mag[mask_valid]

    # Peak detection
    f_peak = freq_valid[np.argmax(mag_valid)]

    # =========================
    # 📏 Height Calculation
    # =========================
    height = (f_peak * lambda_L1) / 2
    heights.append(height)

    print(f"{sv} → Height = {height:.2f} m")


# =========================
# 📊 STEP 3: Statistics
# =========================
mean_h = np.mean(heights)
std_h = np.std(heights)

print("\n✅ Average Height =", mean_h)
print("✅ Standard Deviation =", std_h)


# =========================
# 🔍 STEP 4: Remove Outliers
# =========================
filtered_heights = [h for h in heights if abs(h - mean_h) < 2 * std_h]

print("\n✅ After Outlier Removal:")
print("New Mean =", np.mean(filtered_heights))
print("New Std =", np.std(filtered_heights))


# =========================
# 📈 STEP 5: Visualization
# =========================

# Histogram
plt.figure(figsize=(8,4))
plt.hist(filtered_heights, bins=10, edgecolor='black')
plt.xlabel("Reflector Height (m)")
plt.ylabel("Number of Satellites")
plt.title("Histogram of GNSS-IR Heights")
plt.grid(True)
plt.tight_layout()
plt.savefig("histogram.png", dpi=300)
plt.show()

# Satellite plot
plt.figure(figsize=(8,4))
plt.plot(valid_satellites, heights, 'o-')
plt.xlabel("Satellites")
plt.ylabel("Height (m)")
plt.title("Height per Satellite")
plt.grid(True)
plt.tight_layout()
plt.savefig("satellite_plot.png", dpi=300)
plt.show()