"""TimeLens API: SPHEREx archive discovery and cube preview."""
from __future__ import annotations

import logging
import os
import requests
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Path, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from app.services.irsa import ALLOWED_COLLECTIONS, search_spherex
from app.services.neowise import search_neowise_with_status
from app.services.spherex_cube import (
    CubeDataError,
    discover_cube_products,
    download_cube,
    inspect_cube,
    render_preview_png,
    trusted_cube_url,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="SPHEREx TimeLens API",
    description=(
        "Science-first discovery and exploration of public SPHEREx observations. "
        "Archive-backed products are distinguished from test fixtures and previews."
    ),
    version="0.3.0",
)

_default_origins = [
    "https://open-sky-timelens.vercel.app",
    "https://open-sky-timelens-achme-63b5.vercel.app",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
cors_origins = [
    origin.strip()
    for origin in os.getenv("TIMELENS_CORS_ORIGINS", ",".join(_default_origins)).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=r"https://open-sky-timelens(?:-[a-z0-9-]+)?\.vercel\.app",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
    expose_headers=[
        "X-SPHEREX-Source", "X-SPHEREX-Product", "X-SPHEREX-Channel",
        "X-SPHEREX-Coverage-Fraction", "X-SPHEREX-Units", "X-SPHEREX-Synthetic",
        "X-SPHEREX-Wavelength-Um", "X-SPHEREX-Flags-Nonzero-Pixels",
    ],
    max_age=600,
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
async def search_observations(request: SearchRequest, response: Response) -> dict:
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
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("SPHEREx SIA2 spectral-image search failed")
        raise HTTPException(status_code=502, detail="IRSA SPHEREx search failed; retry later") from exc

    response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=600"
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
    response: Response,
    ra_deg: float = Query(ge=0, lt=360),
    dec_deg: float = Query(ge=-90, le=90),
    radius_arcsec: float = Query(default=15, gt=0, le=1800),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict:
    """Return bounded, dated NEOWISE-R single-exposure source measurements."""
    try:
        detections, truncated = await run_in_threadpool(
            search_neowise_with_status, ra_deg, dec_deg, radius_arcsec, limit
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("NEOWISE single-exposure search failed")
        raise HTTPException(status_code=502, detail="IRSA NEOWISE search failed; retry later") from exc
    response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=600"

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
        "truncated": truncated,
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




_HIPS_PROPERTIES_URL = "https://irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube/properties"


@app.get("/api/v1/hips/metadata")
async def hips_metadata(response: Response) -> dict:
    """Return official wavelength metadata for the display-only HiPS cube."""
    response.headers["Cache-Control"] = "public, max-age=86400"
    try:
        response = await run_in_threadpool(requests.get, _HIPS_PROPERTIES_URL, timeout=15)
        response.raise_for_status()
        properties = {}
        for line in response.text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            properties[key.strip()] = value.strip()
        wavelengths = [
            float(value) for value in properties["data_cube_crval3_arr"].split()
        ]
        if len(wavelengths) != 102:
            raise ValueError("IRSA HiPS wavelength table does not contain 102 channels")
        return {
            "source_archive": "NASA/IPAC IRSA",
            "hips_url": "https://irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube",
            "frame_count": len(wavelengths),
            "wavelength_um": wavelengths,
            "display_only": True,
            "synthetic": False,
        }
    except Exception as exc:
        logger.exception("SPHEREx HiPS metadata retrieval failed")
        raise HTTPException(status_code=502, detail="Could not retrieve IRSA HiPS metadata") from exc




@app.get("/api/v1/hips/frame/{tile_id}/{channel_index}")
async def hips_frame(
    tile_id: int = Path(ge=0, le=12287),
    channel_index: int = Path(ge=0, le=101),
) -> Response:
    """Proxy one small official IRSA HiPS PNG frame for browser display."""
    directory = (tile_id // 10000) * 10000
    frame_url = (
        "https://irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube/"
        f"Norder5/Dir{directory}/Npix{tile_id}" + (f"_{channel_index}" if channel_index > 0 else "") + ".png"
    )
    try:
        response = await run_in_threadpool(requests.get, frame_url, timeout=20)
        response.raise_for_status()
        if not response.headers.get("Content-Type", "").lower().startswith("image/png"):
            raise ValueError("IRSA HiPS response is not a PNG image")
        if not response.content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("IRSA HiPS response has an invalid PNG signature")
        return Response(
            content=response.content,
            media_type="image/png",
            headers={
                "X-SPHEREX-Source": "NASA/IPAC IRSA",
                "X-SPHEREX-Display": "HiPS PNG; display only",
                "Cache-Control": "public, max-age=86400",
            },
        )
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 502
        logger.warning("IRSA HiPS frame request failed: HTTP %s", status)
        if status == 404:
            raise HTTPException(
                status_code=404,
                detail="IRSA does not publish this HiPS frame for the selected tile and channel",
            ) from exc
        raise HTTPException(status_code=502, detail=f"IRSA HiPS returned HTTP {status}") from exc
    except Exception as exc:
        logger.exception("SPHEREx HiPS frame retrieval failed")
        raise HTTPException(status_code=502, detail=f"IRSA HiPS frame error ({type(exc).__name__}): {str(exc)[:240]}") from exc


@app.get("/api/v1/cube/search")
async def search_cube(
    response: Response,
    ra_deg: float = Query(ge=0, lt=360),
    dec_deg: float = Query(ge=-90, le=90),
    radius_arcsec: float = Query(default=30, gt=0, le=1800),
) -> dict:
    """Find DR1 All-Sky Cube FITS tiles overlapping an ICRS coordinate."""
    try:
        products = await run_in_threadpool(
            discover_cube_products, ra_deg, dec_deg, radius_arcsec
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("SPHEREx DR1 cube discovery failed")
        raise HTTPException(status_code=502, detail="IRSA cube discovery failed; retry later") from exc
    response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=600"
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
    access_url: str | None = Query(default=None, min_length=1, max_length=2048),
    metadata_only: bool = Query(default=False),
) -> Response:
    """Return a display-only PNG made from a real DR1 FITS cube channel."""
    try:
        if access_url:
            product_url = trusted_cube_url(access_url)
        else:
            products = await run_in_threadpool(
                discover_cube_products, ra_deg, dec_deg, radius_arcsec
            )
            if not products:
                raise HTTPException(status_code=404, detail="No DR1 cube tile covers this position")
            product_url = products[0]["access_url"]
        payload = await run_in_threadpool(download_cube, product_url)
        metadata, plane = await run_in_threadpool(inspect_cube, payload, channel_index)
        if metadata_only:
            return JSONResponse(content=metadata)
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
        "X-SPHEREX-Flags-Nonzero-Pixels": str(metadata.get("flags_nonzero_pixel_count", 0)),
        "X-SPHEREX-Synthetic": "false",
        "Cache-Control": "no-store",
    }
    if metadata["wavelength_um"] is not None:
        headers["X-SPHEREX-Wavelength-Um"] = str(metadata["wavelength_um"])
    return Response(content=png, media_type="image/png", headers=headers)
