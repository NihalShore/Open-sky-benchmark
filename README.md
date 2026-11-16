<!-- PROJECT BANNER -->
<p align="center">
  <img src="docs/timelens-banner.svg" alt="SPHEREx TimeLens — infrared sky exploration" width="100%">
</p>

<p align="center">
  <a href="https://github.com/NihalShore/Open-sky-benchmark/actions/workflows/backend-tests.yml">
    <img src="https://github.com/NihalShore/Open-sky-benchmark/actions/workflows/backend-tests.yml/badge.svg?branch=main" alt="Backend tests">
  </a>
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Astronomy-SPHEREx-172554" alt="SPHEREx">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="MIT License"></a>
</p>

<h1 align="center">SPHEREx TimeLens</h1>

<p align="center">
  <strong>Explore the infrared sky across position, wavelength, and time.</strong><br>
  An API-first research prototype for working with public SPHEREx and NEOWISE archive data.
</p>

<p align="center">
  <a href="#what-it-does">Capabilities</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#api-at-a-glance">API</a> ·
  <a href="backend/README.md">Backend guide</a> ·
  <a href="#scientific-integrity">Scientific integrity</a>
</p>

---

## What it does

TimeLens brings several archive and image-analysis steps into one small, reproducible backend. Start with a sky position, discover relevant observations, inspect real FITS data, and compare compatible image planes while keeping coverage and provenance visible.

**The project is an investigation tool, not a Planet X detector.** A residual or catalog row is a lead for further analysis—not a discovery.

### Current capabilities

| Capability | What is implemented |
|---|---|
| **SPHEREx discovery** | IRSA SIA2 searches for DR1 / QR3 spectral-image metadata |
| **SPHEREx DR1 cube** | Tile discovery, bounded FITS retrieval, channel extraction, coverage-masked PNG preview |
| **NEOWISE-R** | Single-exposure source measurements ordered by Modified Julian Date, with quality fields retained |
| **WCS registration** | Bilinear reprojection of a target image onto a reference celestial grid |
| **Difference analysis** | Common-coverage masking and robust residual ranking using median absolute deviation |

<p align="center">
  <img src="docs/architecture.svg" alt="TimeLens system architecture" width="100%">
</p>

## Project status

> **Research prototype · Public archive explorer + FastAPI service**
>
> Archive queries depend on IRSA availability and may be rate-limited. Automated tests use generated FITS fixtures and mocked archive responses; they do not prove that every live archive request will succeed.

| Available now | Not implemented or not yet validated |
|---|---|
| Coordinate-validated FastAPI endpoints | Calibrated multi-epoch comparison with PSF matching and uncertainty propagation |
| SPHEREx SIA2 and DR1 cube discovery | PSF matching or photometric scaling across epochs |
| NEOWISE-R single-exposure query | Uncertainty-map propagation |
| FITS channel preview with coverage masking | Automated moving-object classification or Planet X detection |
| WCS reprojection and difference primitives | Verified live end-to-end science result or hosted deployment |

## Quick start

The frontend and API are separate Vercel projects. The frontend uses the web directory; the FastAPI service uses the backend directory. The browser API base is open-sky-timelens-api.vercel.app.


**Requirements:** Python 3.11 recommended. Install and run from the `backend/` directory.

```bash
cd backend
python -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
# .venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

Then open:

- **Interactive API docs:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **Health endpoint:** [http://127.0.0.1:8000/api/v1/health](http://127.0.0.1:8000/api/v1/health)

The health endpoint checks that the API process is alive. It deliberately does not make a remote IRSA request.

## API at a glance

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/v1/health` | Local process health |
| `POST` | `/api/v1/search` | Search SPHEREx spectral-image products through IRSA SIA2 |
| `GET` | `/api/v1/cube/search` | Find DR1 All-Sky Cube tiles around an ICRS position |
| `GET` | `/api/v1/cube/preview` | Return a display-only PNG for one zero-based cube channel |
| `GET` | `/api/v1/neowise/search` | Query NEOWISE-R single-exposure source measurements |

### Example: discover SPHEREx observations

```bash
curl -X POST http://127.0.0.1:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "ra_deg": 127.69444,
    "dec_deg": -39.17760,
    "radius_arcsec": 36,
    "collections": ["spherex_dr1", "spherex_qr3"]
  }'
```

### Example: preview a DR1 cube channel

```bash
curl -o channel-1.png \
  "http://127.0.0.1:8000/api/v1/cube/preview?ra_deg=127.69444&dec_deg=-39.17760&channel_index=0"
```

The channel index is zero-based. The preview is for visual inspection, not calibrated photometry. The response includes provenance, wavelength when available, units, and coverage metadata.

### Example: query NEOWISE-R

```bash
curl \
  "http://127.0.0.1:8000/api/v1/neowise/search?ra_deg=127.69444&dec_deg=-39.17760&radius_arcsec=15"
```

Measurements are returned in MJD order. Photometric and contamination-quality fields are preserved so downstream analysis can make explicit quality decisions.

## WCS comparison pipeline

The lower-level comparison utility is available as `app.services.image_pipeline.compare_wcs_images`. It reprojects a target plane onto a reference WCS, estimates interpolation support from finite input pixels, masks insufficiently covered pixels, and computes target-minus-reference residuals.

Inputs must already have compatible units and photometric calibration. The pipeline does **not** perform background matching, PSF matching, photometric scaling, or uncertainty propagation. See the [backend guide](backend/README.md) for details and an example.

## Run the tests

```bash
cd backend
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

GitHub Actions is configured to run the backend test suite on relevant pushes and pull requests. The tests use generated FITS fixtures and mocked remote archive calls; live IRSA access remains an external dependency.

## Deployment layout

- Frontend: Vercel project open-sky-timelens, root directory web.
- API: Vercel project open-sky-timelens-api, root directory backend.
- CORS: TIMELENS_CORS_ORIGINS overrides the default production, preview and local origins.
- Python: API runtime pinned in backend/.python-version.

## Scientific integrity

TimeLens is intentionally conservative about what its outputs mean:

1. **Preserve provenance.** Keep archive identifiers and source information with returned products.
2. **Inspect FITS structure.** Do not assume the primary HDU is the science image; inspect the relevant extensions.
3. **Respect coverage.** Pixels without valid input coverage are masked, not interpreted as zero-valued measurements.
4. **Compare like with like.** Inputs to image subtraction must already be on compatible grids, units, and photometric scales.
5. **Treat residuals as candidates.** A difference image or high-significance pixel is not proof of motion, an unknown object, or Planet X.
6. **Separate test data from observations.** Synthetic fixtures are for tests only and must never be presented as NASA archive measurements.

## Data sources

- [NASA/IPAC IRSA — SPHEREx data access](https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-access/)
- [SPHEREx data releases](https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-releases/)
- [IRSA tutorial — Introduction to SPHEREx spectral images](https://caltech-ipac.github.io/irsa-tutorials/spherex-intro/)
- [SPHEREx data products and documentation](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products/)
- [NEOWISE data at IRSA](https://irsa.ipac.caltech.edu/Missions/wise.html)

## Roadmap

- [x] SPHEREx SIA2 observation discovery
- [x] DR1 All-Sky Cube tile discovery and channel preview
- [x] NEOWISE-R single-exposure source query
- [x] WCS reprojection and coverage-aware difference primitives
- [ ] Public interactive sky viewer and blink comparison
- [ ] Photometric / PSF matching and uncertainty propagation
- [ ] Reproducible candidate-evidence report

## Contributing

Contributions should preserve scientific provenance and avoid overstating what the data show. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, tests, and review expectations.

## License and disclaimer

Released under the [MIT License](LICENSE).

SPHEREx TimeLens is an independent community research prototype built using public archive services. It is not an official NASA, Caltech, or IPAC product and is not endorsed by those organizations.
