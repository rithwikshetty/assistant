import logging
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from openai import APIError

from ..auth.dependencies import get_current_user
from ..database.models import User
from ..logging import log_event
from ..schemas.voice import VoiceStatusResponse, VoiceTranscriptionResponse
from ..services.voice_service import VoiceTranscriptionError, voice_service

router = APIRouter(prefix="/voice", tags=["voice"])
logger = logging.getLogger(__name__)


@router.get("/status", response_model=VoiceStatusResponse)
async def voice_status(_: User = Depends(get_current_user)) -> VoiceStatusResponse:
    """Expose availability metadata for the voice transcription service."""
    payload = voice_service.status()
    return VoiceStatusResponse(**payload)


@router.post("/transcribe", response_model=VoiceTranscriptionResponse, status_code=status.HTTP_200_OK)
async def transcribe_audio(
    audio: UploadFile = File(..., description="Audio file to transcribe"),
    user: User = Depends(get_current_user),
) -> VoiceTranscriptionResponse:
    """Accept an audio upload and return the transcribed text."""
    try:
        contents = await audio.read()
    except Exception as exc:  # pragma: no cover - defensive guard
        log_event(
            logger,
            "ERROR",
            "voice.transcribe.read_failed",
            "error",
            user_id=str(user.id),
            filename=audio.filename,
            content_type=audio.content_type,
            exc_info=exc,
        )
        raise HTTPException(status_code=400, detail="Unable to read uploaded audio.") from exc

    try:
        text = await voice_service.transcribe(
            filename=audio.filename,
            content_type=audio.content_type,
            contents=contents,
            analytics_context={
                "user_id": str(user.id),
            },
        )
    except VoiceTranscriptionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except APIError as exc:
        log_event(
            logger,
            "ERROR",
            "voice.transcribe.provider_error",
            "error",
            user_id=str(user.id),
            filename=audio.filename,
            content_type=audio.content_type,
            error=str(exc),
            exc_info=exc,
        )
        raise HTTPException(status_code=502, detail="Failed to transcribe audio. Please try again.") from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        log_event(
            logger,
            "ERROR",
            "voice.transcribe.unexpected_error",
            "error",
            user_id=str(user.id),
            filename=audio.filename,
            content_type=audio.content_type,
            exc_info=exc,
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred during transcription.") from exc
    finally:
        try:
            await audio.close()
        except Exception:
            pass

    return VoiceTranscriptionResponse(text=text)
