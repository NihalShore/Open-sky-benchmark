"""TimeLens API: first-light SPHEREx discovery slice."""
from __future__ import annotations

from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from app.services.irsa import ALLOWED_COLLECTIONS, search_spherex

app = FastAPI(
    title="SPHEREx TimeLens API",
    description=(
        "Science-first discovery and exploration of public SPHEREx observations. "
        "Search results are real archive metadata, not claims of object discovery."
    ),
    version="0.1.0",
)


class SearchRequest(BaseModel):
    """Validated sky-position search request."""

    model_config = ConfigDict(extra="forbid")

    ra_deg: float = Field(ge=0, lt=360, description="ICRS right ascension in degrees")
    dec_deg: float = Field(ge=-90, le=90, description="ICRS declination in degrees")
    radius_arcsec: float = Field(
        default=30,
        gt=0,
        le=1800,
        description="Search radius in arcseconds; maximum 30 arcminutes",
    )
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
    """Discover public SPHEREx image products overlapping a sky coordinate."""
    # Defensive check retained even though the request schema uses Literals.
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
        # Do not leak archive internals or stack traces to the public API.
        raise HTTPException(
            status_code=502,
            detail=(
                "IRSA SPHEREx search failed. Retry the request or use a "
                "previously cached real observation."
            ),
        ) from exc

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
            "SIA2 returns overlapping image-product metadata. An access URL "
            "may refer to a larger multi-extension FITS product, not an exact "
            "cutout of the requested field."
        ),
    }
