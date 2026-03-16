"""Local filesystem storage service for uploaded and generated files."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import BinaryIO, Optional
from urllib.parse import quote

import anyio

from ...config.settings import settings


class BlobStorageService:
    """Handles file persistence on the local filesystem."""

    def __init__(self) -> None:
        self.storage_root = Path(settings.local_storage_path).expanduser().resolve()
        self.storage_root.mkdir(parents=True, exist_ok=True)
        # Compatibility attribute used by parts of the older codebase.
        self.blob_client = None

    def _resolve_path(self, filename: str) -> Path:
        candidate = self.storage_root / str(filename or "").strip().lstrip("/")
        resolved = candidate.resolve()
        if self.storage_root not in resolved.parents and resolved != self.storage_root:
            raise ValueError("Invalid storage path")
        return resolved

    def _download_url(self, filename: str, original_filename: Optional[str] = None) -> str:
        encoded_path = quote(str(filename or "").strip().lstrip("/"), safe="/")
        base_url = settings.resolve_api_base_url()
        url = f"{base_url}/files/blob/{encoded_path}" if base_url else f"/files/blob/{encoded_path}"
        if original_filename:
            url = f"{url}?download_name={quote(original_filename)}"
        return url

    async def upload(self, filename: str, content: bytes) -> str:
        path = self._resolve_path(filename)

        def _write() -> str:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return self._download_url(filename)

        return await anyio.to_thread.run_sync(_write)

    async def upload_fileobj(self, filename: str, file_obj: BinaryIO) -> str:
        path = self._resolve_path(filename)

        def _write() -> str:
            path.parent.mkdir(parents=True, exist_ok=True)
            file_obj.seek(0)
            with path.open("wb") as target:
                shutil.copyfileobj(file_obj, target)
            return self._download_url(filename)

        return await anyio.to_thread.run_sync(_write)

    def upload_sync(self, filename: str, content: bytes) -> str:
        path = self._resolve_path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return self._download_url(filename)

    def upload_fileobj_sync(self, filename: str, file_obj: BinaryIO) -> str:
        path = self._resolve_path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_obj.seek(0)
        with path.open("wb") as target:
            shutil.copyfileobj(file_obj, target)
        return self._download_url(filename)

    def delete(self, filename: str) -> bool:
        try:
            path = self._resolve_path(filename)
            if path.exists():
                path.unlink()
            return True
        except Exception:
            return False

    def get_bytes(self, filename: str) -> Optional[bytes]:
        try:
            path = self._resolve_path(filename)
            if not path.exists():
                return None
            return path.read_bytes()
        except Exception:
            return None

    def build_sas_url(
        self,
        *,
        filename: str,
        expiry_minutes: int = 10080,
        original_filename: Optional[str] = None,
    ) -> str:
        del expiry_minutes
        return self._download_url(filename, original_filename=original_filename)

    def download_range(self, filename: str, offset: int, length: int) -> bytes:
        path = self._resolve_path(filename)
        with path.open("rb") as handle:
            handle.seek(offset)
            return handle.read(length)


blob_storage_service = BlobStorageService()
