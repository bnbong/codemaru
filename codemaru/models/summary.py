"""The CodemaruSummary joins identity, snapshots, scores, strengths, and metrics.

It is the single object consumed by the renderer and ``/api/summary.json``.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from codemaru.models.input import ProfileInput
from codemaru.models.score import Axis, NormalizedScores
from codemaru.models.snapshot import PlatformStatus, SnapshotBundle


class SupportingMetric(BaseModel):
    """A single labeled metric shown in the card's supporting-metric row."""

    key: str
    label: str
    # Pre-formatted display value, e.g. "1.2k" or "Platinum III".
    value: str


class CodemaruSummary(BaseModel):
    input: ProfileInput
    snapshots: SnapshotBundle
    scores: NormalizedScores
    # Top-3 axes by score, highest first — drives the strength trophies.
    strengths: list[Axis]
    metrics: list[SupportingMetric]
    # Worst status across attempted platforms — drives the stale/degraded UI.
    overall_status: PlatformStatus = Field(serialization_alias="overallStatus")
    updated_at: datetime = Field(serialization_alias="updatedAt")
    # True when this is a last-successful (last-good) summary served as a
    # fallback during a live outage — the data is genuine but from an earlier
    # successful fetch, not the current one.
    stale: bool = False

    model_config = {"populate_by_name": True}
