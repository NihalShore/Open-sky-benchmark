# TimeLens backend

The backend is a FastAPI service plus reusable astronomy/image-analysis modules. The index.py file is the Vercel entrypoint and imports the same app.main:app used locally. Run all commands in this guide from the `backend/` directory.

## Requirements and local run

Python 3.13 is the CI and `.python-version` target (Python 3.11+ supported).

```bash
python -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
# .venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m uvicorn app.main:app --reload --port 8000
```

API documentation: http://127.0.0.1:8000/docs

The browser frontend calls this service from a separate Vercel project. CORS allows the TimeLens production hostname, matching Vercel preview hostnames and local development by default. Set TIMELENS_CORS_ORIGINS to a comma-separated allowlist when deploying elsewhere.

## HTTP endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/health` | Process health; does not contact IRSA |
| POST | `/api/v1/search` | SPHEREx spectral-image product discovery through IRSA SIA2 |
| GET | `/api/v1/cube/search` | DR1 All-Sky Cube tile discovery |
| GET | `/api/v1/cube/preview` | Display-only PNG from one DR1 cube channel |
| GET | `/api/v1/neowise/search` | NEOWISE-R single-exposure source measurements |

### SPHEREx spectral-image search

`POST /api/v1/search` accepts JSON:

```json
{
  "ra_deg": 127.69444,
  "dec_deg": -39.17760,
  "radius_arcsec": 36,
  "collections": ["spherex_dr1", "spherex_qr3"]
}
```

Coordinates are ICRS degrees. Right ascension must be in [0, 360), declination in [-90, 90], and the search radius must be positive and no greater than 1,800 arcseconds. The response contains SIA2 metadata, not a guarantee of an exact cutout.

### DR1 All-Sky Cube

`GET /api/v1/cube/search?ra_deg=...&dec_deg=...` discovers tiles in the `spherex_dr1_cube` collection.

`GET /api/v1/cube/preview?ra_deg=...&dec_deg=...&channel_index=0` retrieves a bounded FITS product from the official IRSA HTTPS host, validates the required extensions, extracts one channel, applies the `NHITS > 0` coverage mask, and returns a display-only PNG (returning `502` on upstream IRSA failures and `422` when a FITS structure is unusable).

The zero-based channel index is 0–101. Response headers include source, observation ID, collection, channel number, wavelength when available, coverage fraction, units, covered flagged-pixel count, and a synthetic-data flag. The preview is not a calibrated photometry product. The code reads the FITS `IMAGE`, `NHITS`, `FLAGS`, and `SPECTRAL_CHANNELS` extensions; it does not use HiPS PNGs as science input.

A small inspection utility is available:

```bash
python scripts/inspect_spherex_cube.py --ra 127.69444 --dec -39.17760
```

This performs a live archive query and download, so it requires network access and may be rate-limited.

### NEOWISE-R single-exposure search

`GET /api/v1/neowise/search?ra_deg=...&dec_deg=...&radius_arcsec=15&limit=200` queries the `neowiser_p1bs_psd` catalog. Results are ordered by MJD (`ORDER BY mjd ASC, scan_id ASC, frame_num ASC`), expose a `truncated` flag when more rows exist beyond `limit`, and retain W1/W2 magnitudes, uncertainties, S/N, photometric quality, frame quality, contamination flags, and scan/frame identifiers.

The catalog contains artifacts and low-quality rows. A returned measurement is not, by itself, evidence of a moving object. Quality fields are preserved for downstream filtering and review.

## Image-analysis modules

### Difference engine

`app.services.difference.compare_aligned_images` compares two 2-D, same-shape image planes. It computes target-minus-reference residuals only where both inputs are finite, estimates the residual center and scatter using the median and median absolute deviation, and ranks pixels exceeding the requested significance threshold.

A zero MAD is treated as unresolved residual scatter; the implementation does not substitute a standard deviation that could be dominated by sparse outliers. Returned candidates are pixel coordinates for follow-up, not detections.

### WCS registration pipeline

`app.services.reprojection.reproject_to_reference_grid` bilinearly samples an input plane onto a reference celestial WCS grid. `app.services.image_pipeline.compare_wcs_images` then estimates interpolation support, applies a coverage threshold, and calls the difference engine.

Example:

```python
from app.services.image_pipeline import compare_wcs_images

result = compare_wcs_images(
    reference_image,
    reference_wcs,
    target_image,
    target_wcs,
    sigma_threshold=5.0,
)
```

**Caller responsibilities and limitations:**

- Both planes must already use compatible units and photometric calibration.
- The pipeline does not perform photometric scaling, background matching, PSF matching, or uncertainty propagation.
- The coverage fraction measures bilinear interpolation support from finite target pixels. It is not an exposure map or an instrument-supplied footprint.
- The algorithm flags image residuals; it does not classify moving objects or confirm an astronomical discovery.

## Tests

Run from this directory after installing `requirements-dev.txt`:

```bash
python -m pytest -q
```

Tests use generated FITS fixtures and mocked IRSA calls. They do not require live archive queries and do not validate live archive availability.

## Scientific references

- [IRSA SPHEREx data access](https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-access/)
- [SPHEREx data releases](https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-releases/)
- [IRSA SPHEREx spectral-image tutorial](https://caltech-ipac.github.io/irsa-tutorials/spherex-intro/)
- [SPHEREx data products](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products/)


## Vercel deployment

Deploy this directory as a separate Vercel project with `backend` as its root directory. Vercel detects the FastAPI application through the top-level `index.py` entrypoint. Python is pinned to `3.13`. No build command or output directory is required.

Note: `astropy` + `astroquery` + `numpy` + `Pillow` push serverless unzipped package limits (~250 MB) and DR1 FITS cubes can be hundreds of MiB, so container or dedicated VM hosting is recommended if serverless bundle limits or FITS memory timeouts are hit.

`GET /api/v1/health` is a process check only; it does not query IRSA. Test SIA2 discovery and FITS retrieval separately.
