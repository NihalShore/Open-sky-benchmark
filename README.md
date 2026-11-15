# Open-sky-benchmark
NASA Space Apps 2026 | Planet X &amp; SPHEREx – Open tool to benchmark and detect moving objects in all-sky survey images

## SPHEREx TimeLens

Pick a sky position, pull every SPHEREx spectral-image cutout that covers it from IRSA, align them, and
compare epochs. All pixels come from IRSA (TAP `spherex.artifact` / `spherex.plane`); nothing is simulated.

Panels: sky view (click to re-centre), observation timeline, A/B blink comparator, spectral lab
(aperture flux vs wavelength), evidence table (provenance, masked fraction, unmatched detections).

### Run

```
cd backend && pip install -r requirements.txt && uvicorn app.main:app --port 8000
cd frontend && npm install && npm run dev        # http://localhost:5173, proxies /api to :8000
```

Deploy: `npm run build` in `frontend/`, then run only uvicorn; it serves `frontend/dist`.

### Tests

```
cd backend && pytest
cd frontend && npm test
```

### Limits

- First query for a position is slow (TAP + cutout downloads, tens of seconds); results are cached in memory.
- Frames sit at different wavelengths (the SPHEREx filter varies across the detector), so A/B differences are not
  automatically motion. The evidence panel says so when it applies.
- Any non-zero FLAGS bit is masked; refine per the SPHEREx Explanatory Supplement.
- No Gaia/WISE cross-match yet.
