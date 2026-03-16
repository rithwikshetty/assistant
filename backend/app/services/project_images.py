"""Helpers for resolving project public image URLs."""

from __future__ import annotations

from typing import Any, Optional

from .files import blob_storage_service


def build_public_image_url(
    project: Any,
    *,
    expiry_minutes: int = 1440,
    append_version: bool = True,
) -> Optional[str]:
    """Build a display URL for a project's public image.

    Prefers a signed URL when a tracked blob exists, and falls back to the
    persisted `public_image_url` when signing fails.
    """
    image_url = getattr(project, "public_image_url", None) or None
    blob_name = getattr(project, "public_image_blob", None)

    if blob_name:
        try:
            image_url = blob_storage_service.build_sas_url(
                filename=blob_name,
                expiry_minutes=expiry_minutes,
            )
        except Exception:
            image_url = getattr(project, "public_image_url", None) or None

    if append_version and image_url:
        updated_at = getattr(project, "public_image_updated_at", None)
        if updated_at:
            try:
                version = int(updated_at.timestamp())
                separator = "&" if "?" in image_url else "?"
                image_url = f"{image_url}{separator}v={version}"
            except Exception:
                pass

    return image_url
