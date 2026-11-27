# Using SPHEREx TimeLens

TimeLens is an archive investigation workspace. It helps you locate a sky field, inspect SPHEREx wavelength channels, inspect one DR1 FITS cube channel, and review nearby dated NEOWISE-R catalog measurements.

It does not automatically detect Planet X or confirm a moving object.

## 1. Open a field

Open the [live TimeLens workspace](https://open-sky-timelens.vercel.app/). Choose a reference target or enter ICRS right ascension and declination in decimal degrees. Set a search radius, then select **Load archive field**.

The workspace requests three separate archive resources:

- SPHEREx DR1 All-Sky Cube product discovery.
- SPHEREx spectral-image metadata through IRSA SIA2.
- Official SPHEREx HiPS wavelength metadata and PNG frames.

The API health indicator only checks that the FastAPI process is responding. It does not test IRSA. Each archive panel reports its own result or failure.

## 2. Compare SPHEREx wavelength channels

The spectral viewer loads official IRSA HiPS PNG frames. Select channels A and B, then use Blink, Swipe, Side by side or Difference.

The HiPS PNGs are display products. The Difference mode subtracts palette-stretched PNG display values; it is not calibrated photometry, a FITS residual, or a time-domain comparison.

Channel A and B represent wavelength planes from a co-added cube. They are not separate observation dates. The HiPS viewer does not display a coordinate reticle because the tile-local HEALPix pixel values have not been validated against the rendered PNG's pixel orientation.

Some channels are blank at the relevant dichroic boundaries. The UI reports an unavailable frame rather than substituting another image.

## 3. Load a FITS-derived channel preview

The FITS preview is a separate panel in the channel inspector.

1. Run an archive field search and wait for a DR1 cube FITS product to be discovered.
2. Choose the desired channel with the Frame A channel control.
3. Select **Load FITS preview**.
4. Review the channel, wavelength, units, NHITS coverage and nonzero FLAGS count.

The API downloads the discovered IRSA FITS product and inspects its `IMAGE`, `NHITS`, `FLAGS` and `SPECTRAL_CHANNELS` extensions. Uncovered pixels are transparent in the rendered PNG.

When the FITS IMAGE celestial WCS maps the requested coordinates to a pixel inside the image, the preview shows a query-position marker. If the WCS transform is unavailable or the position falls outside the image, no marker is shown.

The grayscale preview is for visual inspection. It is not calibrated photometry, a source detection, or a completed scientific validation.

## 4. Review NEOWISE-R measurements

Select **Query NEOWISE** to request nearby NEOWISE-R single-exposure catalog measurements. The time plot shows W1/W2 magnitudes against Modified Julian Date. The sky-position plot shows individual catalog positions relative to the query center.

The optional strict quality screen is reversible. It requires:

- `qual_frame > 0`, `qi_fact > 0` and `saa_sep > 0`.
- `moon_masked = '00'`.
- `cc_flags` beginning with `00`.
- `w1frtr = '0000'` and `w2frtr = '0000'`.
- An A, B or C photometric-quality value in W1 or W2.

This is a conservative screen. It can remove genuine detections, especially objects that are measured in only one band. Turn it off to review the unfiltered returned rows.

The results table shows AllWISE and 2MASS positional association evidence, including match counts and separations. These are positional cross-matches within 3 arcseconds, not confirmed source identifications. Repeated unique catalog matches are summarized as a review aid; the app does not turn those rows into source tracks.

NEOWISE `cntr` and `source_id` identify a per-exposure extraction, not a persistent source. The `sso_flg = 1` value means that a catalog row is positionally associated with a known object's predicted position; it is not confirmation of a moving-object detection.

## 5. Interpret results conservatively

Keep these distinctions in mind:

| Display or result | What it means | What it does not establish |
|---|---|---|
| HiPS frame | Official archive PNG for a wavelength channel | Calibrated flux or an observation epoch |
| HiPS Difference | Difference between two display-stretched PNGs | A scientific FITS residual or object motion |
| FITS preview | One FITS channel rendered with NHITS coverage | Calibrated photometry or a detection |
| FITS WCS marker | Requested sky coordinate mapped to an image pixel | A source at that pixel |
| NEOWISE row | One dated single-exposure catalog measurement | A persistent source identity |
| AllWISE / 2MASS match | Positional catalog association | A confirmed identification |
| `sso_flg = 1` | Positional association with a predicted known-object position | Confirmation of a Solar System detection |

The current comparison utilities do not perform PSF matching, photometric scaling, background matching or uncertainty propagation. The project does not currently build validated multi-epoch moving-object tracks or classify Planet X candidates.

## 6. When something does not load

- **API online, archive unavailable:** the API health check can pass even when IRSA is slow, rate-limited or unavailable. Check the individual SPHEREx or NEOWISE panel for its archive error.
- **No cube product:** SIA2 may return no DR1 All-Sky Cube product for the selected field. FITS preview is only enabled after a trusted cube access URL is discovered.
- **HiPS frame unavailable:** IRSA may not publish a frame for a particular tile/channel. The viewer does not substitute synthetic or neighbouring data.
- **FITS preview unavailable:** the product download, FITS extension validation or WCS mapping may fail. The UI reports the error and does not label the product as scientifically validated.
- **NEOWISE results truncated:** narrow the search radius or query a smaller field. The API returns the truncation state rather than silently implying the catalogue search was exhaustive.

For endpoint details and local development, see the [backend guide](../backend/README.md).
