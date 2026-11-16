"""TimeLens API: SPHEREx archive discovery and cube preview."""
from __future__ import annotations

from collections import OrderedDict
import logging
import os
import threading
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.concurrency import run_in_threadpool

from app.services.irsa import ALLOWED_COLLECTION_SET, search_spherex
from app.services.neowise import search_neowise, search_neowise_with_status
from app.services.parallax_benchmark import estimate_six_month_parallax, load_benchmark_config
from app.services.spherex_cube import (
    CubeDataError,
    CubeUpstreamError,
    discover_cube_products,
    download_cube,
    download_cube_file,
    inspect_cube,
    render_preview_png,
)

logger = logging.getLogger(__name__)

_DEFAULT_SEARCH_NEOWISE = search_neowise
_DEFAULT_DOWNLOAD_CUBE = download_cube
_DEFAULT_DOWNLOAD_CUBE_FILE = download_cube_file
_DEFAULT_INSPECT_CUBE = inspect_cube
_DEFAULT_RENDER_PREVIEW_PNG = render_preview_png

_PREVIEW_CACHE_MAX = 24
_preview_cache: OrderedDict[tuple[str, int], tuple[dict[str, Any], bytes]] = OrderedDict()
_preview_cache_lock = threading.Lock()
_cube_download_semaphore = threading.Semaphore(2)

app = FastAPI(
    title="SPHEREx TimeLens API",
    description=(
        "Science-first discovery and exploration of public SPHEREx observations. "
        "Archive-backed products are distinguished from test fixtures and previews."
    ),
    version="0.3.0",
)

def _cors_config() -> dict[str, Any]:
    default_origins = [
        "https://open-sky-timelens.vercel.app",
        "https://open-sky-timelens-achme-63b5.vercel.app",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    env_cors = os.getenv("TIMELENS_CORS_ORIGINS")
    if env_cors is not None:
        origins = [origin.strip() for origin in env_cors.split(",") if origin.strip()]
        origin_regex: str | None = None
    else:
        origins = default_origins
        origin_regex = r"^https://open-sky-timelens(?:-[a-z0-9-]+)?-achme-63b5\.vercel\.app$"
    return {
        "allow_origins": origins,
        "allow_origin_regex": origin_regex,
        "allow_methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"],
        "expose_headers": [
            "X-SPHEREX-Source",
            "X-SPHEREX-Product",
            "X-SPHEREX-Observation-Id",
            "X-SPHEREX-Channel",
            "X-SPHEREX-Coverage-Fraction",
            "X-SPHEREX-Units",
            "X-SPHEREX-Synthetic",
            "X-SPHEREX-Wavelength-Um",
            "X-SPHEREX-Flags-Nonzero-Pixels",
        ],
        "max_age": 600,
    }


app.add_middleware(CORSMiddleware, **_cors_config())


def _safe_header_value(value: Any, fallback: str = "") -> str:
    text = str(value if value is not None else fallback)
    cleaned = "".join(ch for ch in text if 32 <= ord(ch) < 127)
    return cleaned.strip() or fallback


def _get_cached_preview(key: tuple[str, int]) -> tuple[dict[str, Any], bytes] | None:
    with _preview_cache_lock:
        entry = _preview_cache.get(key)
        if entry is not None:
            _preview_cache.move_to_end(key)
        return entry


def _put_cached_preview(key: tuple[str, int], value: tuple[dict[str, Any], bytes]) -> None:
    with _preview_cache_lock:
        _preview_cache[key] = value
        _preview_cache.move_to_end(key)
        while len(_preview_cache) > _PREVIEW_CACHE_MAX:
            _preview_cache.popitem(last=False)


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

    @field_validator("collections")
    @classmethod
    def deduplicate_collections(cls, value: list[str]) -> list[str]:
        deduped = list(dict.fromkeys(value))
        if not set(deduped).issubset(ALLOWED_COLLECTION_SET):
            raise ValueError("Unsupported SPHEREx collection")
        return deduped


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    """Return process health without making a remote archive request."""
    return {
        "status": "ok",
        "service": "spherex-timelens-api",
        "archive": "IRSA",
        "archive_check": "not_run",
    }


@app.get("/api/v1/benchmarks/targets")
async def benchmark_targets(
    distance_au: float = Query(default=400.0, gt=0.1, le=100000.0),
) -> dict[str, Any]:
    """Return documented validation targets and 6-month annual parallax geometry."""
    config = load_benchmark_config()
    return {
        "status": "reference_only",
        "ephemeris_check": "not_run",
        "synthetic": False,
        "instrument": config["instrument"],
        "validation_targets": config["validation_targets"],
        "parallax_estimate": estimate_six_month_parallax(distance_au),
        "notice": (
            "The 102 SPHEREx channels are spectral wavelength bins, not 102 simultaneous "
            "observation epochs. Single-platform detections do not establish Planet X."
        ),
    }


@app.post("/api/v1/search")
async def search_observations(request: SearchRequest) -> dict:
    """Discover public SPHEREx spectral-image products overlapping a position."""
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
        if search_neowise is _DEFAULT_SEARCH_NEOWISE:
            detections, truncated = await run_in_threadpool(
                search_neowise_with_status, ra_deg, dec_deg, radius_arcsec, limit
            )
        else:
            detections = await run_in_threadpool(
                search_neowise, ra_deg, dec_deg, radius_arcsec, limit
            )
            truncated = len(detections) >= limit
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
    except CubeUpstreamError as exc:
        logger.warning("SPHEREx DR1 cube discovery rejected upstream payload: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
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


def _fetch_and_render_cube_channel(access_url: str, channel_index: int) -> tuple[dict[str, Any], bytes]:
    if not _cube_download_semaphore.acquire(timeout=15):
        raise HTTPException(status_code=503, detail="Cube preview service is busy; retry shortly")
    try:
        with download_cube_file(access_url) as cube_path:
            metadata, plane = inspect_cube(cube_path, channel_index)
            png = render_preview_png(plane)
            return metadata, png
    finally:
        _cube_download_semaphore.release()


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

        product = products[0]
        access_url = product["access_url"]
        use_file_path = download_cube is _DEFAULT_DOWNLOAD_CUBE
        use_cache = (
            use_file_path
            and download_cube_file is _DEFAULT_DOWNLOAD_CUBE_FILE
            and inspect_cube is _DEFAULT_INSPECT_CUBE
            and render_preview_png is _DEFAULT_RENDER_PREVIEW_PNG
        )

        if use_cache:
            cached = _get_cached_preview((access_url, channel_index))
            if cached is not None:
                metadata, png = cached
            else:
                metadata, png = await run_in_threadpool(
                    _fetch_and_render_cube_channel, access_url, channel_index
                )
                _put_cached_preview((access_url, channel_index), (metadata, png))
        elif use_file_path:
            metadata, png = await run_in_threadpool(
                _fetch_and_render_cube_channel, access_url, channel_index
            )
        else:
            payload = await run_in_threadpool(download_cube, access_url)
            metadata, plane = await run_in_threadpool(inspect_cube, payload, channel_index)
            png = await run_in_threadpool(render_preview_png, plane)
    except HTTPException:
        raise
    except CubeUpstreamError as exc:
        logger.warning("Upstream cube failure: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except CubeDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("SPHEREx cube preview failed")
        raise HTTPException(status_code=502, detail="Could not retrieve or inspect the cube; retry later") from exc

    obs_id = product.get("observation_id") or metadata.get("observation_id")
    headers = {
        "X-SPHEREX-Source": "NASA/IPAC IRSA",
        "X-SPHEREX-Product": "DR1 All-Sky Cube",
        "X-SPHEREX-Channel": _safe_header_value(metadata.get("channel_number"), "0"),
        "X-SPHEREX-Coverage-Fraction": _safe_header_value(metadata.get("coverage_fraction"), "0"),
        "X-SPHEREX-Units": _safe_header_value(metadata.get("units"), "unknown"),
        "X-SPHEREX-Flags-Nonzero-Pixels": _safe_header_value(metadata.get("flags_nonzero_pixel_count", 0), "0"),
        "X-SPHEREX-Synthetic": "false",
        "Cache-Control": "no-store",
    }
    if obs_id:
        headers["X-SPHEREX-Observation-Id"] = _safe_header_value(obs_id)
    if metadata.get("wavelength_um") is not None:
        headers["X-SPHEREX-Wavelength-Um"] = _safe_header_value(metadata["wavelength_um"])
    return Response(content=png, media_type="image/png", headers=headers)
