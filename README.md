# SPHEREx TimeLens

**NASA Space Apps 2026 — Planet X & SPHEREx**

An open exploration tool for real SPHEREx infrared observations. TimeLens is designed to help people inspect the sky across observation time and wavelength, compare valid data, and understand the evidence behind changes.

## Product direction

**Integrated, science-first exploration.**

The intended workflow is:

1. Select a sky region using ICRS right ascension and declination.
2. Discover available SPHEREx observations from IRSA.
3. Inspect spectral-image products and their wavelength information.
4. Compare compatible observations with coverage-aware visualization.
5. Investigate flagged changes with provenance and uncertainty.
6. Export a reproducible evidence report.

TimeLens is an exploration and investigation tool. It does not claim to detect or confirm Planet X.

## Build status

The first backend vertical slice is on the `feat/spherex-first-light` branch:

- FastAPI health and coordinate-validated SPHEREx search endpoints.
- IRSA SIA2 discovery for DR1/QR3 spectral images and the DR1 All-Sky Cube.
- Bounded FITS download and validation for the cube product.
- Channel extraction using `IMAGE`, `NHITS`, `FLAGS`, and `SPECTRAL_CHANNELS`.
- Coverage-masked, display-only PNG preview with archive provenance.
- FITS-fixture tests, API contract tests, and a GitHub Actions test workflow.

A live end-to-end IRSA download and local test run have **not yet been verified**. Spatial WCS rendering, time comparison, and source analysis remain future work. See [backend setup and status](backend/README.md).

## Official data sources

- [NASA/IPAC IRSA SPHEREx Data Access](https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-access/)
- [SPHEREx Data Releases](https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-releases/)
- [IRSA SPHEREx spectral-image tutorial](https://caltech-ipac.github.io/irsa-tutorials/spherex-intro/)

## Scientific integrity

- Preserve original archive products and record their provenance.
- Inspect multi-extension FITS products; never assume the primary HDU is the science image.
- Respect spatial and wavelength-dependent WCS.
- Compare compatible data and explicitly mask missing coverage.
- Treat image differences as investigation candidates, not proof of motion or discovery.
- Distinguish real observations from synthetic test fixtures in the UI and reports.
