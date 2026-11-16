# Contributing to SPHEREx TimeLens

Thanks for helping improve TimeLens. Contributions should make the code more reproducible and the scientific limits more explicit.

## Development setup

Use Python 3.11 and run commands from `backend/`:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

## Before opening a pull request

- Add or update tests for behavior changes.
- Keep remote IRSA calls mocked in unit tests; tests should not depend on archive uptime.
- Use generated, clearly synthetic FITS fixtures for parser tests.
- Preserve source identifiers, units, quality fields, and coverage metadata.
- Explain assumptions about calibration, image alignment, and uncertainty.
- Do not label a residual candidate as a moving object or discovery.
- Update the README or backend guide when an endpoint or limitation changes.

## Scientific review checklist

- Are the input products and archive collections identified?
- Are FITS extensions and WCS assumptions explicit?
- Are missing-coverage pixels masked rather than filled with zero?
- Are image units and calibration compatibility stated?
- Are synthetic fixtures clearly distinguished from archive observations?
- Are limitations and unverified live behavior documented?

## Scope

TimeLens is an independent research prototype. A contribution must not imply NASA endorsement or claim to detect Planet X without a validated scientific method and independent evidence.
