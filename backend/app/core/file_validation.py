"""
File validation utilities — magic bytes check and extension allow-list.
Prevents malicious files disguised with an allowed extension.
"""
from typing import Optional

# Magic byte signatures mapped to their expected MIME type prefix
MAGIC_BYTES: dict[bytes, str] = {
    b"%PDF":          "application/pdf",
    b"\x89PNG\r\n":   "image/png",
    b"\xff\xd8\xff":  "image/jpeg",
    b"PK\x03\x04":    "application/vnd.openxmlformats",  # DOCX / XLSX / ZIP family
    b"GIF87a":        "image/gif",
    b"GIF89a":        "image/gif",
    b"RIFF":          "audio/",  # WAV starts with RIFF
    b"ID3":           "audio/mpeg",  # MP3 with ID3 tag
    b"\xff\xfb":      "audio/mpeg",  # MP3 without ID3
}

# Allowed extensions for knowledge base uploads
KNOWLEDGE_ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".docx", ".csv"}

# Allowed extensions for chat file uploads
CHAT_ALLOWED_EXTENSIONS = {".pdf", ".txt", ".png", ".jpg", ".jpeg", ".wav", ".mp3"}


def validate_magic_bytes(content: bytes, declared_content_type: str) -> bool:
    """
    Return True if the file's magic bytes match a known type compatible with
    the declared content type, or if the file has no known magic bytes (e.g. TXT/MD/CSV).

    Returns False if the magic bytes clearly identify a type that does NOT match
    the declared content type (e.g. a PDF disguised as an image).
    """
    for signature, expected_mime_prefix in MAGIC_BYTES.items():
        if content.startswith(signature):
            # File has a known signature — check it matches what was declared
            declared = declared_content_type.lower()
            if expected_mime_prefix.lower() in declared:
                return True
            # Allow octet-stream for binary uploads (browser sometimes sends this)
            if "octet-stream" in declared:
                return True
            # Mismatch — file claims to be something it's not
            return False

    # No known magic bytes → plain text formats (TXT, MD, CSV) — allow
    return True


def validate_extension(filename: str, allowed: Optional[set] = None) -> bool:
    """Return True if the file's extension is in the allowed set."""
    if allowed is None:
        allowed = KNOWLEDGE_ALLOWED_EXTENSIONS
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in allowed


def validate_upload(content: bytes, filename: str, content_type: str,
                    allowed_extensions: Optional[set] = None) -> tuple[bool, str]:
    """
    Full upload validation: extension + magic bytes.
    Returns (ok: bool, error_message: str).
    """
    if not validate_extension(filename, allowed_extensions):
        ext = filename.rsplit(".", 1)[-1] if "." in filename else filename
        return False, f"Extension '.{ext}' non autorisée."

    if not validate_magic_bytes(content, content_type):
        return False, "Le contenu du fichier ne correspond pas à son extension déclarée."

    return True, ""
