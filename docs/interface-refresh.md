# TimeLens interface refresh

## Scope

Refresh the existing static frontend in `web/index.html`. Keep the FastAPI service in `backend/` and its current API contract. Do not replace the application with a separate Vite or Next.js project.

## Design direction

- Keep the dark observatory palette, but improve contrast, spacing, focus states and responsive behavior.
- Make the coordinate query and archive-backed viewer the primary workspace.
- Keep provenance visible beside the viewer rather than hiding it in a secondary screen.
- Keep SPHEREx spectral channels and NEOWISE-R measurements as separate data paths.
- Preserve the compact archive-record list and the method/data-source sections.
- Prefer clear labels and stable controls over decorative animation.

## Data and scientific constraints

- Only responses from NASA/IPAC IRSA may be described as archive observations.
- HiPS PNG frames are display-only previews, not calibrated FITS analysis.
- FITS product discovery, preview loading and scientific validation are separate states.
- A missing or unavailable archive frame must remain visibly unavailable; never substitute a generated star field or fixture.
- Keep blank channels blank when IRSA does not publish a frame.
- Do not imply that a residual confirms a moving object or Planet X.
- Keep NEOWISE-R W1/W2 single-exposure measurements distinct from SPHEREx wavelength channels.

## Implementation notes

- The current frontend is a static HTML/CSS/JavaScript page. No framework migration is part of this change.
- The first pass adds responsive and accessibility-oriented CSS without changing API requests or data interpretation.
- Keep API calls pointed at the existing TimeLens API deployment.
- Avoid adding dependencies unless a tested requirement cannot be met with the current page.

## Review checklist

- [ ] Desktop layout keeps query controls, viewer and provenance readable.
- [ ] Mobile layout has no horizontal overflow and keeps controls usable.
- [ ] Keyboard focus is visible on links, inputs, range controls and buttons.
- [ ] Reduced-motion preference is respected.
- [ ] API health, SPHEREx discovery, HiPS metadata/frame loading and NEOWISE query behavior remain unchanged.
- [ ] HTTP errors and unavailable frames remain explicit; no synthetic fallback appears.
- [ ] Preview deployment is checked before any production merge.
- [ ] Backend scientific validation remains a separate required gate.
