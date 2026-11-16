# SPHEREx TimeLens

NASA Space Apps 2026 — Planet X & SPHEREx

Backend for inspecting real SPHEREx and NEOWISE archive data.
TimeLens helps explore observations across position, time, and wavelength.
It does not claim to detect or confirm Planet X.

## What works

FastAPI backend on this tree:

- IRSA SIA2 discovery for SPHEREx spectral images (DR1 / QR3)
- DR1 All-Sky Cube tile search, FITS channel extraction, coverage-masked PNG preview
- NEOWISE-R single-exposure source search (MJD-ordered, quality fields kept)
- WCS reprojection of a target image onto a reference grid (bilinear)
- Coverage-aware difference imaging on aligned planes
- End-to-end path: reproject → coverage mask → common-valid mask → residual candidates

All science pixels come from IRSA. Live paths do not invent data.

## What does not work yet

- No public frontend / blink UI / spectral lab panels
- No PSF matching or photometric scaling between epochs
- No uncertainty-map propagation
- No moving-object classifier
- Live IRSA downloads are rate-limited and not guaranteed in every environment

## Run

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API docs: http://127.0.0.1:8000/docs  
Health: http://127.0.0.1:8000/api/v1/health

## Tests

```bash
cd backend && pytest -q
```

GitHub Actions runs the same suite on pull requests and `feat/**` pushes.

## Scientific rules

- Preserve original archive products and record provenance
- Inspect multi-extension FITS; do not assume the primary HDU is science data
- Respect spatial and wavelength-dependent WCS
- Compare only compatible data; mask missing coverage explicitly
- Treat residuals as investigation candidates, not discoveries
- Label synthetic fixtures clearly; never present them as NASA observations

## Official data sources

- [IRSA SPHEREx Data Access](https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-access/)
- [SPHEREx Data Releases](https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-releases/)
- [IRSA SPHEREx spectral-image tutorial](https://caltech-ipac.github.io/irsa-tutorials/spherex-intro/)

## License

MIT
