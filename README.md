# SPHEREx TimeLens

NASA Space Apps 2026 — Planet X & SPHEREx

Open Sky Benchmark is a public exploration workspace for SPHEREx and NEOWISE archive data. TimeLens helps inspect infrared observations across sky position, wavelength, and time. It does not claim to detect or confirm Planet X.

## Current components

### Web application

The Next.js application in `web/` provides:

- Coordinate-first SPHEREx SIA2 discovery and normalized archive metadata
- A synthetic 102-channel viewer and blink demonstration, always labelled synthetic
- A live archive-tools panel for DR1 All-Sky Cube tile discovery and real FITS channel previews
- NEOWISE-R single-exposure queries with W1/W2 errors and quality flags
- JSON evidence export with query parameters, observation metadata, preview provenance, returned measurements, and limitations

The web app has no database requirement. Its short-lived metadata cache and search diagnostics are limited to a warm server process.

### Python API

The FastAPI service in `backend/` provides:

- SPHEREx SIA2 observation discovery
- DR1 All-Sky Cube tile discovery, bounded FITS validation, channel extraction, and coverage-masked PNG preview
- NEOWISE-R single-exposure source lookup ordered by MJD
- WCS reprojection and coverage-aware difference primitives
- Optional variance-map propagation through squared bilinear interpolation weights

## What is not implemented

- PSF matching, photometric scaling, and background matching
- Automatic selection and registration of paired archive FITS products in the public blink viewer
- Covariance propagation for correlated pixels or resampling
- Source extraction, astrometric association, or moving-object classification

Inputs to WCS comparison must already have compatible units and photometric calibration. Synthetic blink frames and differences are interface demonstrations, not observations or candidate detections. Evidence exports are reproducible records of the queried data and processing state; they do not imply a discovery.

## Run locally

Web application:

```bash
cd web
npm install
cp .env.example .env.local
npm run dev
```

Set `SPHEREX_BACKEND_URL` in `.env.local` to the FastAPI service URL.

Python API:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

Run backend tests from `backend/`:

```bash
python -m pytest -q
```

## Scientific rules

- Preserve original archive products and their provenance.
- Inspect multi-extension FITS products; do not assume the primary HDU contains the science image.
- Respect spatial and wavelength-dependent WCS.
- Mask missing coverage explicitly and compare only compatible products.
- Keep synthetic fixtures distinct from archive observations.
- Treat residuals as investigation candidates, not discoveries.

## Official data sources

- [IRSA SPHEREx Data Access](https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-access/)
- [SPHEREx Data Releases](https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-releases/)
- [IRSA SPHEREx data products](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products/)
- [IRSA NEOWISE archive](https://irsa.ipac.caltech.edu/applications/wise/)

## License

MIT
