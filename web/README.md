# TimeLens web workspace

Live workspace: https://open-sky-timelens.vercel.app/

The deployed static frontend connects to the TimeLens API and public NASA/IPAC IRSA archive services. It provides coordinate-based discovery, real SPHEREx HiPS PNG channel previews, spectral-channel blink/swipe/side-by-side/display-value comparisons, and separate NEOWISE-R catalog measurements.

HiPS PNGs are display-only and are not calibrated FITS science images. Channel comparisons are different wavelengths within a co-added cube, not a time baseline. FITS discovery does not mean validation or analysis. NEOWISE-R results are separate dated catalog rows; the workspace does not perform source association or claim moving-object detection.

Deploy this directory as the Vercel frontend project root.
