# TimeLens web UI

This directory serves the interactive workspace build.

## Mode

The workspace UI includes a **demonstration catalog** for target comparison UX
(blink / split / difference modes). Photometry and rendered frames in the
demo catalog are labeled as simulation / preview and must not be treated as
NASA/IPAC IRSA measurements.

Live archive queries remain available through the TimeLens API:

- API: `https://open-sky-timelens-api.vercel.app`
- Health: `/api/v1/health`

For archive-backed HiPS channel inspection without the demo catalog, use the
API endpoints and prior static explorer revisions on `main` history.
