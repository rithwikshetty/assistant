import io
from time import perf_counter
from typing import Any, Optional

from openai import APIError, AsyncOpenAI

from ..config.settings import settings
from .model_usage_tracker import (
    extract_openai_transcription_usage,
    record_estimated_model_usage,
)


class VoiceTranscriptionError(Exception):
    """Raised when transcription cannot be completed due to a client-side issue."""


class VoiceService:
    """Service for validating and transcribing audio uploads."""

    _ALLOWED_EXTENSIONS = {
        "mp3",
        "mp4",
        "mpeg",
        "mpga",
        "m4a",
        "wav",
        "webm",
    }
    _CONTENT_TYPE_EXTENSION_FALLBACK = {
        "audio/mpeg": "mp3",
        "audio/mp3": "mp3",
        "audio/mp4": "mp4",
        "audio/webm": "webm",
        "audio/ogg": "mp3",
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/x-m4a": "m4a",
    }
    _MAX_FILE_BYTES = 25 * 1024 * 1024  # 25MB
    _MODEL_NAME = "gpt-4o-mini-transcribe"

    def __init__(self) -> None:
        pass

    def status(self) -> dict:
        """Return service availability metadata."""
        configured = bool(settings.openai_api_key)
        return {
            "status": "available" if configured else "disabled",
            "supported_formats": sorted(self._ALLOWED_EXTENSIONS),
            "max_file_size_mb": self._MAX_FILE_BYTES // (1024 * 1024),
        }

    async def transcribe(
        self,
        *,
        filename: Optional[str],
        content_type: Optional[str],
        contents: bytes,
        analytics_context: Optional[dict[str, Any]] = None,
    ) -> str:
        """Transcribe uploaded audio into text."""
        if not settings.openai_api_key:
            raise VoiceTranscriptionError("Voice transcription is not configured. Contact an administrator.")

        if not contents:
            raise VoiceTranscriptionError("The uploaded audio file is empty.")

        if len(contents) > self._MAX_FILE_BYTES:
            raise VoiceTranscriptionError("Audio file too large. Maximum size is 25MB.")

        extension = self._infer_extension(filename=filename, content_type=content_type)

        buffer = io.BytesIO(contents)
        buffer.name = filename or f"recording.{extension}"

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        started_at = perf_counter()

        try:
            transcription = await client.audio.transcriptions.create(
                model=self._MODEL_NAME,
                file=buffer,
                temperature=0,
            )
        except APIError as exc:
            raise exc
        except Exception as exc:  # pragma: no cover - defensive guard
            raise exc

        usage = extract_openai_transcription_usage(transcription)
        record_estimated_model_usage(
            provider="openai",
            model_name=self._MODEL_NAME,
            operation_type="voice_transcription",
            usage=usage,
            analytics_context=analytics_context,
            db=(analytics_context or {}).get("db"),
            latency_ms=max(0, int((perf_counter() - started_at) * 1000)),
        )

        text = (transcription.text or "").strip()
        if not text:
            raise VoiceTranscriptionError("No transcription text returned. Try recording again.")

        return text

    def _infer_extension(self, *, filename: Optional[str], content_type: Optional[str]) -> str:
        """Infer a supported extension from filename or content type."""
        extension: Optional[str] = None

        if filename and "." in filename:
            extension = filename.rsplit(".", 1)[-1].lower()

        if not extension and content_type:
            extension = self._CONTENT_TYPE_EXTENSION_FALLBACK.get(content_type.lower())

        if not extension:
            extension = "webm"

        if extension not in self._ALLOWED_EXTENSIONS:
            raise VoiceTranscriptionError(
                "Unsupported audio format. Allowed formats: "
                + ", ".join(sorted(self._ALLOWED_EXTENSIONS))
            )

        return extension


voice_service = VoiceService()
