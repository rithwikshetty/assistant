from datetime import datetime, timezone
from types import SimpleNamespace

from app.services import project_images


def test_build_public_image_url_prefers_signed_blob_and_appends_version(monkeypatch) -> None:
    project = SimpleNamespace(
        public_image_blob="public-projects/p1/image.png",
        public_image_url="https://stored.example.com/image.png",
        public_image_updated_at=datetime(2026, 2, 27, 12, 0, tzinfo=timezone.utc),
    )

    monkeypatch.setattr(
        project_images.blob_storage_service,
        "build_sas_url",
        lambda filename, expiry_minutes: f"https://signed.example.com/{filename}?sig=abc",
    )

    url = project_images.build_public_image_url(project, expiry_minutes=1440, append_version=True)

    assert url == "https://signed.example.com/public-projects/p1/image.png?sig=abc&v=1772193600"


def test_build_public_image_url_falls_back_to_stored_url_on_signing_error(monkeypatch) -> None:
    project = SimpleNamespace(
        public_image_blob="public-projects/p1/image.png",
        public_image_url="https://stored.example.com/image.png",
        public_image_updated_at=None,
    )

    def _raise(*_args, **_kwargs):
        raise RuntimeError("blob service down")

    monkeypatch.setattr(project_images.blob_storage_service, "build_sas_url", _raise)

    url = project_images.build_public_image_url(project, expiry_minutes=1440, append_version=False)

    assert url == "https://stored.example.com/image.png"
