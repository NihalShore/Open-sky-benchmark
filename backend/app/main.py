"""TimeLens API: SPHEREx archive discovery and cube preview."""
from __future__ import annotations

import logging
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from app.services.irsa import ALLOWED_COLLECTIONS, search_spherex
from app.services.neowise import search_neowise
from app.services.spherex_cube import (
    CubeDataError,
    discover_cube_products,
    download_cube,
    inspect_cube,
    render_preview_png,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="SPHEREx TimeLens API",
    description=(
        "Science-first discovery and exploration of public SPHEREx observations. "
        "Archive-backed products are distinguished from test fixtures and previews."
    ),
    version="0.2.0",
)


class SearchRequest(BaseModel):
    """Validated sky-position search request."""

    model_config = ConfigDict(extra="forbid")

    ra_deg: float = Field(ge=0, lt=360, description="ICRS right ascension in degrees")
    dec_deg: float = Field(ge=-90, le=90, description="ICRS declination in degrees")
    radius_arcsec: float = Field(default=30, gt=0, le=1800)
    collections: list[
        Literal[
            "spherex_dr1",
            "spherex_dr1_deep",
            "spherex_dr1_cube",
            "spherex_qr3",
            "spherex_qr3_deep",
        ]
    ] = Field(default_factory=lambda: ["spherex_dr1", "spherex_qr3"], min_length=1)


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    """Return process health without making a remote archive request."""
    return {
        "status": "ok",
        "service": "spherex-timelens-api",
        "archive": "IRSA",
        "archive_check": "not_run",
    }


@app.post("/api/v1/search")
async def search_observations(request: SearchRequest) -> dict:
    """Discover public SPHEREx spectral-image products overlapping a position."""
    if not set(request.collections).issubset(ALLOWED_COLLECTIONS):
        raise HTTPException(status_code=422, detail="Unsupported SPHEREx collection")
    try:
        observations = await run_in_threadpool(
            search_spherex,
            request.ra_deg,
            request.dec_deg,
            request.radius_arcsec,
            request.collections,
        )
    except Exception as exc:
        logger.exception("SPHEREx SIA2 spectral-image search failed")
        raise HTTPException(status_code=502, detail="IRSA SPHEREx search failed; retry later") from exc

    return {
        "search_id": f"SEARCH-{uuid4().hex[:12].upper()}",
        "status": "completed",
        "source_archive": "NASA/IPAC IRSA",
        "synthetic": False,
        "query": {
            "ra_deg": request.ra_deg,
            "dec_deg": request.dec_deg,
            "radius_arcsec": request.radius_arcsec,
            "collections": request.collections,
        },
        "result_count": len(observations),
        "observations": observations,
        "notice": (
            "SIA2 returns overlapping image-product metadata. An access URL may refer "
            "to a larger multi-extension FITS product, not an exact cutout."
        ),
    }


@app.get("/api/v1/neowise/search")
async def search_neowise_sources(
    ra_deg: float = Query(ge=0, lt=360),
    dec_deg: float = Query(ge=-90, le=90),
    radius_arcsec: float = Query(default=15, gt=0, le=1800),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict:
    """Return dated NEOWISE-R single-exposure source measurements."""
    try:
        detections = await run_in_threadpool(
            search_neowise, ra_deg, dec_deg, radius_arcsec, limit
        )
    except Exception as exc:
        logger.exception("NEOWISE single-exposure search failed")
        raise HTTPException(status_code=502, detail="IRSA NEOWISE search failed; retry later") from exc

    return {
        "status": "completed",
        "source_archive": "NASA/IPAC IRSA",
        "catalog": "neowiser_p1bs_psd",
        "query": {
            "ra_deg": ra_deg,
            "dec_deg": dec_deg,
            "radius_arcsec": radius_arcsec,
            "limit": limit,
        },
        "result_count": len(detections),
        "detections": detections,
        "time_field": "mjd",
        "bands": ["W1", "W2"],
        "notice": (
            "Single-exposure catalog rows include real detections and artifacts. "
            "Quality fields are returned for review; this endpoint does not classify "
            "moving objects or confirm a source association."
        ),
        "synthetic": False,
    }


@app.get("/api/v1/cube/search")
async def search_cube(
    ra_deg: float = Query(ge=0, lt=360),
    dec_deg: float = Query(ge=-90, le=90),
    radius_arcsec: float = Query(default=30, gt=0, le=1800),
) -> dict:
    """Find DR1 All-Sky Cube FITS tiles overlapping an ICRS coordinate."""
    try:
        products = await run_in_threadpool(
            discover_cube_products, ra_deg, dec_deg, radius_arcsec
        )
    except Exception as exc:
        logger.exception("SPHEREx DR1 cube discovery failed")
        raise HTTPException(status_code=502, detail="IRSA cube discovery failed; retry later") from exc
    return {
        "status": "completed",
        "source_archive": "NASA/IPAC IRSA",
        "collection": "spherex_dr1_cube",
        "query": {"ra_deg": ra_deg, "dec_deg": dec_deg, "radius_arcsec": radius_arcsec},
        "result_count": len(products),
        "products": products,
        "synthetic": False,
    }


@app.get("/api/v1/cube/preview")
async def cube_preview(
    ra_deg: float = Query(ge=0, lt=360),
    dec_deg: float = Query(ge=-90, le=90),
    channel_index: int = Query(default=0, ge=0, le=101),
    radius_arcsec: float = Query(default=30, gt=0, le=1800),
) -> Response:
    """Return a display-only PNG made from a real DR1 FITS cube channel."""
    try:
        products = await run_in_threadpool(
            discover_cube_products, ra_deg, dec_deg, radius_arcsec
        )
        if not products:
            raise HTTPException(status_code=404, detail="No DR1 cube tile covers this position")
        payload = await run_in_threadpool(download_cube, products[0]["access_url"])
        metadata, plane = await run_in_threadpool(inspect_cube, payload, channel_index)
        png = await run_in_threadpool(render_preview_png, plane)
    except HTTPException:
        raise
    except CubeDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("SPHEREx cube preview failed")
        raise HTTPException(status_code=502, detail="Could not retrieve or inspect the cube; retry later") from exc

    headers = {
        "X-SPHEREX-Source": "NASA/IPAC IRSA",
        "X-SPHEREX-Product": "DR1 All-Sky Cube",
        "X-SPHEREX-Channel": str(metadata["channel_number"]),
        "X-SPHEREX-Coverage-Fraction": str(metadata["coverage_fraction"]),
        "X-SPHEREX-Units": str(metadata["units"]),
        "X-SPHEREX-Synthetic": "false",
        "Cache-Control": "no-store",
    }
    if metadata["wavelength_um"] is not None:
        headers["X-SPHEREX-Wavelength-Um"] = str(metadata["wavelength_um"])
    return Response(content=png, media_type="image/png", headers=headers)
