# SPHEREx TimeLens

**NASA Space Apps 2026 — Planet X & SPHEREx**

TimeLens is a science-first interface for exploring real SPHEREx infrared observations across sky position, observation time, and wavelength. The project aims to help users inspect changes and understand the evidence behind them. It does not claim to identify Planet X.

## Current build status

### Implemented on `feat/spherex-first-light`

- FastAPI application with a health endpoint.
- Validated ICRS coordinate search request.
- IRSA SIA2 discovery through Astroquery.
- Default search across the SPHEREx DR1 and QR3 wide-survey collections.
- Normalized observation metadata with provenance and a real/synthetic flag.
- API contract tests using a mocked archive response.

### Not implemented yet

- FITS downloads or cutout retrieval.
- FITS multi-extension inspection and science-image extraction.
- Image normalization or browser rendering.
- WCS reprojection and cross-epoch registration.
- Timeline, blink comparator, spectral profile, or change analysis.
- Persistent cache and deployed hosting.

These items are deliberately not represented as completed features.

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

Run tests from the `backend` directory:

```bash
pytest -q
```

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

1. **First light:** Search IRSA and return genuine observation metadata. (Current branch.)
2. **FITS inspection:** Retrieve one real product, select its science HDU, preserve flags/variance, and read spatial and spectral WCS.
3. **Browser image:** Render a documented science-image preview with masked pixels and explicit stretch metadata.
4. **Temporal comparison:** Find compatible observations, reproject to a common grid, and display valid-coverage masks.
5. **Spectral exploration:** Expose measured wavelength information and a source/region spectrum only where the product supports it.
6. **Evidence report:** Explain each flagged change with data provenance, uncertainty, and limitations.
