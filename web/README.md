# TimeLens web UI

Live workspace: https://open-sky-timelens.vercel.app/

This static frontend queries the TimeLens API at https://open-sky-timelens-api.vercel.app and NASA/IPAC IRSA archive-backed endpoints.

The UI currently supports:
- Coordinate-based archive discovery (SPHEREx SIA2 and DR1 cube products)
- Real SPHEREx HiPS channel previews
- Blink, swipe, side-by-side, and display-value difference between two spectral channels from the same co-added cube
- Separate NEOWISE-R dated catalog query and plotting

The spectral comparison is not a multi-epoch comparison. The frontend does not yet expose the FITS/WCS registration and calibrated multi-epoch difference pipeline. HiPS PNG comparisons are display-only and should not be interpreted as calibrated science.

Deploy this directory as the Vercel frontend project root.
