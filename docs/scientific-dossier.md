# SPHEREx TimeLens — Scientific Research Dossier & Integration Architecture

> **Scope:** NASA Space Apps Challenge 2026 — *Planet X and SPHEREx* (`NihalShore/Open-sky-benchmark`).  
> **Core Epistemic Rule:** SPHEREx's **102 channels are spectral wavelength bins ($\lambda_1 \dots \lambda_{102}$), never 102 simultaneous observation dates**, and **TimeLens is an exploratory benchmark/research prototype — never claim Planet X detection from a single platform without multi-epoch Keplerian/parallactic linking and independent optical/IR confirmation.**

---

## 1. Epistemic Hygiene: Verified In-Repo Behavior vs. Unverified External Notes

Because this repository is developed and tested with synthetic FITS fixtures and mocked IRSA responses (and the development environment cannot fetch external hosts such as `irsa.ipac.caltech.edu` or `arxiv.org` directly), this dossier separates:

1. **Verified in code and physical equations (`backend/app/services/*`, `backend/tests/*`):**
   - `MJy/sr` $\to$ $\mu\text{Jy}$ pixel conversion at pixel solid angle $\Omega_{\text{pix}} = (\theta_x \theta_y) / (206264.806247)^2\ \text{sr}$ ($888.981\ \mu\text{Jy}/(\text{MJy/sr}\cdot\text{pix})$ at $6.15'' \times 6.15''$), AB magnitude zero point $3631\ \text{Jy}$ ($m_{\text{AB}} = -2.5\log_{10}(F_{\mu\text{Jy}} / 3.631\times 10^9)$).
   - 6-month Earth-orbit parallax angle across baseline $\Delta r \approx 2\ \text{AU}$: $\Delta\theta_{\text{par}} = 2 \arctan(\Delta r / (2 d_{\text{AU}})) \approx 1031''$ ($17.2'$, $\approx 168$ pixels at $6.15''/\text{px}$) at $d = 400\ \text{AU}$.
   - FITS alternate WCS `'A'` (`CRPIX1A` / `CRPIX2A` / `CRVAL1A` / `CRVAL2A`), Astropy `SkyCoord` frame transforms across Galactic/ICRS and swapped axes, and `hdu.section[...]` single-plane slicing on FITS cubes (`memmap=False` for `BZERO`-scaled `uint16` `NHITS`/`FLAGS`).
2. **External mission specifications & literature summaries requiring live IRSA validation:**
   - Exact post-launch release contents (`spherex_dr1`, `spherex_qr3`, `SSDC-DP-017`, `SPLICES v8.6`), HDU naming/oversampling variants (e.g., `EPSF` vs `PSF`, $33\times 33$ $5\times$-oversampled cutouts vs $101\times 101$ $10\times$ average PSF; mosaic footprint $3.5^\circ \times 11.3^\circ$ across two $1\times 3$ focal planes vs narrower single-array bounds), specific bit definitions in `FLAGS`, and cited recent papers (`Crill et al. 2025/2026`, `Korngut et al. 2026`, `Lisse et al. 2025/2026`, `Phan et al. 2025`) should be checked directly against official NASA/IPAC IRSA documentation and FITS headers before making scientific claims on real survey data.

---

## 2. What Scientific Information SPHEREx Provides

SPHEREx (Spectro-Photometer for the History of the Universe, Epoch of Reionization, and Ices Explorer) performs **all-sky slitless near-infrared spectrophotometry** using six Hawaii-2RG ($2040 \times 2040$, $6.15''/\text{px}$) HgCdTe detectors mounted behind **Linear Variable Filters (LVFs)** split across two focal planes (SWIR $0.75$–$2.41\ \mu\text{m}$ and MWIR $2.42$–$5.00\ \mu\text{m}$).

- Because each LVF transmits a wavelength that varies continuously along one detector axis, a single pointing captures a sky source at only one SWIR wavelength and one MWIR wavelength simultaneously.
- Stepping the spacecraft pointing across successive exposures samples a source across **6 bands $\times$ 17 channels = 102 spectral channels**:

| Band | Wavelength ($\mu\text{m}$) | Nominal $R = \lambda/\Delta\lambda$ | Channels | Primary Spectral Diagnostics |
|---|---:|---:|---:|---|
| 1 | 0.75 – 1.09 | 39 | 1 – 17 | Continuum, silicates, He I ($1.083\ \mu\text{m}$ foreground) |
| 2 | 1.10 – 1.62 | 41 | 18 – 34 | $\text{H}_2\text{O}$ ice ($1.5\ \mu\text{m}$), $\text{CH}_4$ overtones |
| 3 | 1.63 – 2.41 | 41 | 35 – 51 | $\text{H}_2\text{O}$ ice ($2.0\ \mu\text{m}$), $\text{CH}_4$ ($2.2\ \mu\text{m}$), $\text{NH}_3$ |
| 4 | 2.42 – 3.82 | 35 | 52 – 68 | $\text{H}_2\text{O}$ ($3.0\ \mu\text{m}$), $\text{CH}_4$ ($3.3\ \mu\text{m}$), organics |
| 5 | 3.83 – 4.41 | 112 | 69 – 85 | $\text{CO}_2$ ($4.26\ \mu\text{m}$), $\text{SO}_2$ |
| 6 | 4.42 – 5.00 | 128 | 86 – 102 | $\text{CO}$ ($4.67\ \mu\text{m}$), $\text{OCN}^-$, thermal tail |

**Critical architectural rule:** Because each channel for a sky position is recorded on a different pointing step, each channel has its own exposure timestamp (`MJD-OBS`). Channels 51 and 52 sit at the $2.42\ \mu\text{m}$ dichroic boundary and are marked blank (`BLANKCH`) in DR1 All-Sky Cubes.

---

## 3. How Repeated Observations Can Be Used

1. **Six-Month Annual Parallax Baseline ($\Delta r \approx 2\ \text{AU}$):** Wide Survey passes revisit fields roughly every 6 months from opposite sides of Earth's orbit, creating large parallactic offsets for Solar System bodies ($\sim 1031''$ at $400\ \text{AU}$, $\sim 825''$ at $500\ \text{AU}$) against stationary background stars.
2. **Intra-Pass Motion Tracking:** Within one survey pass, exposures across the 102 spectral steps span minutes to days; Solar System objects move across pixels between wavelengths and must be extracted along their ephemeris rather than stacked statically.
3. **Cometary Activity & Rotational Variations:** Comparing repeated visits isolates rotational lightcurves and transient $\text{H}_2\text{O}$ / $\text{CO}_2$ / $\text{CO}$ outgassing.
4. **Cosmic-Ray & Artifact Rejection:** Single-exposure glints, radiation hits, and detector latch-ups fail multi-exposure spatial/parallactic consistency.

---

## 4. Suitable IRSA Data Products (`backend/app/services/`)

| Product / Collection | Implementation Status in TimeLens | Role & Limitations |
|---|---|---|
| `spherex_dr1`, `spherex_qr3` (Spectral Image MEFs) | Metadata discovery via `irsa.py`; cutout ingestion, ZODI/FLAGS/VARIANCE calibration & photometry in `spherex_mef.py` | **Primary moving-object data product.** Preserves single-exposure `MJD-OBS`, `ZODI`, `FLAGS`, `VARIANCE`, and `EPSF`/`PSF` extensions. Supports IRSA `?center=...&size=...` cutouts paired with `CRPIX1A`/`CRPIX2A` full-detector lookup into `CWAVE`/`CBAND`. |
| `spherex_dr1_cube` (DR1 All-Sky Cubes) | Discovery & single-channel inspection in `spherex_cube.py` (`/api/v1/cube/search`, `/api/v1/cube/preview`) | **Static sky context only.** Co-added across epochs onto a coarser grid; smears or flags moving targets. |
| `neowiser_p1bs_psd` (NEOWISE-R) | Time-ordered TAP queries in `neowise.py` (`/api/v1/neowise/search`) | Independent dated $W1$ ($3.4\ \mu\text{m}$) / $W2$ ($4.6\ \mu\text{m}$) catalog baseline with quality flags (`ph_qual`, `qual_frame`, `cc_flags`) retained. |

---

## 5. Quantitative Limitations for Planet X Investigations

- **Verified sensitivity vs. Planet X hypothesis:** Nominal SPHEREx Wide Survey $5\sigma$ point-source depth is roughly $18.5$–$19.0\ \text{AB mag}$ per channel ($19.7\ \text{AB mag}$ over four combined passes). Under standard Batygin & Brown dynamical hypotheses ($5$–$10\ M_\oplus$, $a \approx 380$–$800\ \text{AU}$, $T_{\text{eq}} \approx 35$–$50\ \text{K}$), predicted optical/NIR reflected brightness scales as $r_h^{-4}$ ($V \approx 21.5$–$25\ \text{AB mag}$), suppressed further in Bands 2–4 by $\text{CH}_4$ / $\text{H}_2$ absorption.
- **Thermal Wien cutoff:** At $T_{\text{eq}} \approx 40$–$50\ \text{K}$, blackbody emission peaks around $60$–$75\ \mu\text{m}$ (far-IR), leaving $\lambda < 5\ \mu\text{m}$ deep on the Wien tail unless internal heat produces strong $4$–$5\ \mu\text{m}$ flux.
- **Co-addition smearing & $6.15''$ confusion:** Static multi-pass stacks reject or smear objects with $>10'$ 6-month parallax shifts, while $6.15''$ pixels blend sources near the Galactic plane.

---

## 6. Complementary Datasets & Validation Benchmarks

- **Complementary archives:** Gaia DR3/DR4 (sub-mas stationary star subtraction), WISE/NEOWISE (14+ year $W1$/$W2$ proper-motion baseline, already queried via `/api/v1/neowise/search`), Pan-STARRS / DECam (high-resolution optical deblending), Vera C. Rubin Observatory / LSST (deep moving-object discovery), and IRAS/AKARI (far-IR checks).
- **Validation targets (`backend/configs/benchmark_targets.json`, `GET /api/v1/benchmarks/targets`):**
  1. **Interstellar Comet 3I/ATLAS** (moving-target LVF tracking + $\text{H}_2\text{O}$ / $\text{CO}_2$ / $\text{CO}$ bands).
  2. **Bright TNOs / Dwarf Planets:** `136472 Makemake`, `136108 Haumea`, `136199 Eris`, `134340 Pluto` ($\text{CH}_4$ and crystalline $\text{H}_2\text{O}$ ices; Eris near single-pass $5\sigma$).
  3. **Cold Brown Dwarfs:** `WISE J085510.83-071442.5` ($T_{\text{eff}} \approx 250\ \text{K}$, large proper motion, $W2 \approx 13.9$).
  4. **Synthetic ePSF injection-recovery (`parallax_benchmark.evaluate_injection_recovery`):** Quantifies recovery completeness across AB magnitudes in real background variance while explicitly marking outputs `synthetic: True`.

---

## 7. Scientific Mistakes Prevented by TimeLens Design

1. Never plot the 102 spectral channels as a time series; always carry `mjd_obs` per MEF exposure.
2. Never search `spherex_dr1_cube` for moving targets; use single-epoch MEFs (`spherex_mef.py`).
3. Always subtract `ZODI` (`IMAGE - ZODI`), mask `FLAGS` and non-positive `VARIANCE`, and transform cutout coordinates via FITS alternate WCS `'A'` (`CRPIX1A`/`CRPIX2A`) before reading calibrated `CWAVE`/`CBAND`.
4. Never hide uncalibrated aperture losses (`aperture_correction` / `use_epsf` explicit in output) or dichroic edge impacts (`dichroic_impacted`).
5. Never report synthetic injections (`synthetic: True`) or unlinked residual candidates as Planet X detections.

---

## 8. Implemented TimeLens Workflow & Module Map

```
[1. SIA2 Discovery]       backend/app/services/irsa.py (search_spherex, trusted URL checks)
         │
         ▼
[2. MEF Cutout & Cal]     backend/app/services/spherex_mef.py
                          • build_cutout_url / download_mef_cutout_file (bounded HTTPS streaming)
                          • calibrate_mef (IMAGE - ZODI, FLAGS, VARIANCE, WCS 'A' -> CWAVE/CBAND)
         │
         ▼
[3. Forced Photometry]    extract_forced_photometry (aperture or inverse-variance ePSF fit -> uJy, AB mag)
         │
         ▼
[4. Registration & Diff]  reprojection.py + difference.py + image_pipeline.py
                          • SkyCoord WCS registration, common coverage masking, float64 MAD residuals
         │
         ▼
[5. Benchmark & Parallax] backend/app/services/parallax_benchmark.py + GET /api/v1/benchmarks/targets
                          • 6-month parallax estimator, documented validation targets, ePSF injection tests
```

---

## 9. Reference Documentation & Citations

- NASA/IPAC IRSA SPHEREx Archive & Tutorials: <https://irsa.ipac.caltech.edu/Missions/spherex.html>, <https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-access/>, <https://caltech-ipac.github.io/irsa-tutorials/spherex-intro/>
- NEOWISE at IRSA: <https://irsa.ipac.caltech.edu/Missions/wise.html>
- Mission, Solar System & Planet Nine literature cited in project research notes (verify bibliographic metadata directly against ADS/arXiv when online): Doré et al. (2014, arXiv:1412.4872); Batygin & Brown (2016, AJ 151, 22); Fortney et al. (2016, ApJL 824, L25); Cowan et al. (2016, ApJL 822, L2); Batygin et al. (2019, Phys. Rep. 805, 1); Brown & Batygin (2021, AJ 162, 219); Ivezić et al. (2022, Icarus 371, 114696); Ashby et al. (2023, ApJ 949, 105); Phan et al. (2025, arXiv:2504.17288); Crill et al. (2025, arXiv:2511.02985); Lisse et al. (2025/2026, arXiv:2512.07318); Korngut et al. (2026, arXiv:2602.09139).
