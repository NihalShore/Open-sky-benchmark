# SPHEREx TimeLens API

FastAPI service for SPHEREx archive discovery, DR1 All-Sky Cube inspection, NEOWISE-R single-exposure queries, and WCS-aware image comparison primitives.

## Run locally

Python 3.12 is the deployment target.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

Health and API documentation:

- `GET /api/v1/health`
- `GET /docs`
- `GET /api/v1/pipeline/capabilities`

## Archive endpoints

### SPHEREx SIA2 discovery

`POST /api/v1/search` accepts ICRS coordinates, a radius, and one or more supported DR1/QR3 collections. It returns normalized archive product metadata. SIA2 access URLs identify products; they are not guaranteed to be cutouts centred on the query.

### DR1 All-Sky Cube

- `GET /api/v1/cube/search?ra_deg=...&dec_deg=...`
- `GET /api/v1/cube/preview?ra_deg=...&dec_deg=...&channel_index=...`

The preview path discovers a tile, validates a bounded FITS download, reads `IMAGE`, `NHITS`, `FLAGS`, and `SPECTRAL_CHANNELS`, rejects channels marked blank, masks pixels where `NHITS = 0`, and returns a display-only PNG. Response headers record source, channel, wavelength (when available), coverage, units, and synthetic status. This is not calibrated photometry or a WCS-projected sky cutout.

### NEOWISE-R

`GET /api/v1/neowise/search` returns NEOWISE-R single-exposure source measurements ordered by MJD. W1/W2 magnitudes, reported uncertainties, SNR, photometric quality, frame quality, and contamination flags are preserved. The table includes low-quality measurements and artifacts; the API does not classify moving objects.

## WCS comparison primitives

`app.services.image_pipeline.compare_wcs_images` reprojects the target image onto the reference celestial WCS, computes finite-pixel coverage support, masks pixels below the configured coverage threshold, and forms a target-minus-reference difference.

When both `reference_variance` and `target_variance` maps are supplied, variance is propagated through bilinear interpolation using squared interpolation weights. The calculation assumes independent input pixel errors. It does not propagate covariance from resampling or correlated detector noise. The returned significance map uses the supplied variance maps and a robust median background offset.

Both images must already be in compatible units and photometrically calibrated. PSF matching, photometric scaling, background matching, source extraction, astrometric association, and moving-object classification are not implemented. A ranked residual is a candidate for follow-up, not a discovery.

## Tests

```bash
python -m pytest -q
```

The test suite uses generated FITS fixtures and mocked archive calls; it does not claim a successful live IRSA response. GitHub Actions installs `requirements-dev.txt` and runs the same suite.

## Deployment

This folder is the root directory for the separate Vercel FastAPI project. It uses `app/main.py` as the application entry point and `requirements.txt` for runtime dependencies. No database or credentials are required for the public read-only archive endpoints.

Live requests depend on IRSA availability and can return no overlapping data or an upstream error. No synthetic values are returned by the archive endpoints.
