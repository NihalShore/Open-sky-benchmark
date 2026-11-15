# SPHEREx TimeLens

**NASA Space Apps 2026 — Planet X & SPHEREx**

TimeLens is a science-first interface for exploring real SPHEREx infrared observations across sky position, observation time, and wavelength. The project aims to help users inspect changes and understand the evidence behind them. It does not claim to identify Planet X.

## Current build status

### Implemented on `feat/spherex-first-light`

- FastAPI health endpoint and validated ICRS coordinate search.
- IRSA SIA2 discovery through Astroquery for DR1 and QR3 spectral-image products.
- Separate DR1 All-Sky Cube discovery through the documented `spherex_dr1_cube` collection.
- Bounded FITS download from HTTPS URLs on the official IRSA host; redirects are not followed.
- FITS validation and extraction from `IMAGE`, `NHITS`, `FLAGS`, and `SPECTRAL_CHANNELS`.
- Coverage masking from `NHITS > 0`; channel wavelength metadata is read from the documented `WAVELENGTH`, `WL_MIN`, `WL_MAX`, `BANDWIDTH`, `R`, `DETECTOR`, and `SUBCHAN` columns.
- FITS-header blank-channel check using `BLANKCH`; no-data channels are not silently rendered.
- Display-only PNG preview with percentile stretch and explicit source/channel/coverage headers.
- Unit and API contract tests using generated FITS fixtures and mocked archive calls.

### Not implemented or not yet verified

- A successful live end-to-end download from IRSA in this development session.
- Spatial WCS rendering/reprojection onto a conventional sky grid.
- Scientific source extraction, photometry, or uncertainty propagation.
- Cross-epoch registration, blink comparison, or change-candidate scoring.
- Persistent caching, frontend integration, and deployed hosting.

A GitHub Actions workflow now runs `pytest -q` for backend changes. The connector has not yet returned a workflow run for this branch, so the suite remains **unverified** until a CI result is available. These items are not represented as completed features.

## Run the backend locally

Python 3.10 or newer is recommended.

```bash
cd backend
python -m venv .venv
```

Activate the virtual environment, then install dependencies:

```bash
# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
.venv\\Scripts\\Activate.ps1

pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open the interactive API documentation at:

- http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/api/v1/health

## Search for SPHEREx observations

Example request:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/search \\
  -H "Content-Type: application/json" \\
  -d '{
    "ra_deg": 127.69444,
    "dec_deg": -39.17760,
    "radius_arcsec": 36,
    "collections": ["spherex_dr1", "spherex_qr3"]
  }'
```

The endpoint returns SIA2 discovery metadata. An `access_url` identifies an archive product; it is not guaranteed to be a cutout exactly matching the requested search region.

## Explore the DR1 All-Sky Cube

Find cube tiles for a sky position:

```bash
curl "http://127.0.0.1:8000/api/v1/cube/search?ra_deg=127.69444&dec_deg=-39.17760"
```

Render one channel from the first matching real FITS tile:

```bash
curl -o channel-1.png "http://127.0.0.1:8000/api/v1/cube/preview?ra_deg=127.69444&dec_deg=-39.17760&channel_index=0"
```

The channel index is zero-based (0–101). The PNG is a display preview, not a calibrated photometry product. Response headers report the source, channel, wavelength when present, coverage fraction, and units. The FITS cube's `NHITS` layer is used to mask pixels without input coverage. The cube already has zodiacal light subtracted; TimeLens does not subtract it a second time.

IRSA documents the DR1 cube as 12,288 HEALPix order-5 NESTED tiles, each with 102 channels, and identifies the `IMAGE`, `NHITS`, `FLAGS`, `SPECTRAL_CHANNELS`, and `WCS-WAVE` extensions. The HiPS PNG tree is for visualization only; the FITS cube is used here. See the [official cube product description](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products/) and [DR1 cube DOI](https://doi.org/10.26131/IRSA679).

Run tests from the `backend` directory:

```bash
pytest -q
```

## Explore NEOWISE observations

Search the NEOWISE-R single-exposure source table around an ICRS position:

```bash
curl "http://127.0.0.1:8000/api/v1/neowise/search?ra_deg=127.69444&dec_deg=-39.17760&radius_arcsec=15"
```

The response is ordered by Modified Julian Date (MJD) and includes W1/W2 profile-fit magnitudes, uncertainties, signal-to-noise values, and archive quality fields. Results are source-table measurements, not image cutouts. Quality flags are preserved rather than silently filtered; the catalog includes artifacts and low-quality detections, so a returned row is not by itself evidence of a moving object. NEOWISE observed in W1 (3.4 μm) and W2 (4.6 μm).

## Scientific data rules

1. Preserve original FITS files; create derived products separately.
2. Inspect the FITS HDU list. SPHEREx spectral-image products are multi-extension FITS files; do not assume the primary HDU contains the science image.
3. The official IRSA tutorial identifies `IMAGE`, `FLAGS`, `VARIANCE`, `ZODI`, `EPSF`, and `WCS-WAVE` extensions in an example Level 2 product.
4. Respect the spatial WCS and the wavelength-dependent WCS. SPHEREx uses linear-variable filters, so wavelength can vary across detector pixels.
5. Compare like with like. Do not blindly subtract different instruments, spectral responses, or incompatible processing releases.
6. A difference image is a candidate-generation tool, not proof of motion or a Planet X detection.
7. An absent Gaia counterpart is not proof that a source is unusual.
8. Label synthetic fixtures explicitly and never present them as NASA observations.

## Official technical references

- [SPHEREx Data Access at IRSA](https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-access/)
- [SPHEREx Data Releases](https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-releases/)
- [IRSA tutorial: Introduction to SPHEREx Spectral Images](https://caltech-ipac.github.io/irsa-tutorials/spherex-intro/)
- [SPHEREx Cutout Tool](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/cutout_tool.html)

## Planned vertical slices

1. **First light:** Search IRSA and return genuine observation metadata. (Implemented.)
2. **Cube explorer:** Discover DR1 All-Sky Cube tiles, inspect FITS channels, mask missing coverage, and render a preview. (Implemented; live archive execution still needs verification.)
3. **Spatial rendering:** Apply the cube's spatial WCS and show coordinates correctly on the image.
4. **Temporal comparison:** Find compatible observations, reproject to a common grid, and display valid-coverage masks.
5. **Spectral exploration:** Build a wavelength profile from supported data and document its limitations.
6. **Evidence report:** Explain each flagged change with data provenance, uncertainty, and limitations.
