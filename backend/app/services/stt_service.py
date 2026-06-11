"""
STT Service — Speech-to-Text using OpenAI Whisper API.
Falls back to placeholder if Whisper/OpenAI is not available.
"""
import io
import logging
from typing import Optional

from app.core.config import OPENAI_API_KEY

logger = logging.getLogger(__name__)

SUPPORTED_AUDIO_TYPES = {
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav",
    "audio/ogg", "audio/webm", "audio/flac", "audio/mp4", "audio/m4a"
}
MAX_AUDIO_SIZE = 25 * 1024 * 1024  # 25 MB (Whisper limit)


class STTService:
    def __init__(self):
        self._openai_available = False
        self._init_backend()

    def _init_backend(self):
        if OPENAI_API_KEY and OPENAI_API_KEY != "sk-placeholder-set-your-real-key":
            try:
                import openai
                self._openai_available = True
                logger.info("OpenAI Whisper STT backend available")
            except ImportError:
                logger.warning("openai package not installed — STT disabled")
        else:
            logger.warning("No OpenAI API key — STT using fallback")

    def validate_audio(self, content_type: str, file_size: int) -> Optional[str]:
        """Returns error message if invalid, None if OK."""
        if file_size > MAX_AUDIO_SIZE:
            return f"Fichier audio trop volumineux ({file_size // (1024*1024)}MB). Max: 25MB"
        if content_type not in SUPPORTED_AUDIO_TYPES:
            return f"Format audio non supporté: {content_type}"
        return None

    async def transcribe(self, file_bytes: bytes, content_type: str, filename: str = "") -> str:
        """Transcribe audio bytes to text."""
        if self._openai_available:
            return await self._transcribe_whisper(file_bytes, filename)
        return f"[Audio joint: {filename} — configurez OPENAI_API_KEY pour la transcription]"

    async def _transcribe_whisper(self, file_bytes: bytes, filename: str) -> str:
        try:
            import openai
            client = openai.OpenAI(api_key=OPENAI_API_KEY)

            audio_file = io.BytesIO(file_bytes)
            audio_file.name = filename or "audio.wav"

            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="fr"
            )
            text = transcript.text.strip()
            logger.info(f"Whisper transcribed {len(text)} chars from {filename}")
            return text if text else f"[Audio transcrit vide: {filename}]"
        except Exception as e:
            logger.error(f"Whisper STT failed for {filename}: {e}")
            return f"[Erreur transcription: {str(e)[:80]}]"


# Singleton
stt_service = STTService()
