"""
OCR Service — Extracts text from images and PDFs.
Uses Pillow for basic image processing and optional EasyOCR/PyMuPDF for advanced.
Falls back to placeholder if heavy dependencies are unavailable.
"""
import io
import logging
from typing import Optional

logger = logging.getLogger(__name__)

SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp", "image/bmp", "image/tiff"}
SUPPORTED_DOC_TYPES = {"application/pdf"}
MAX_FILE_SIZE = 15 * 1024 * 1024  # 15 MB


class OCRService:
    def __init__(self):
        self._easyocr_reader = None
        self._easyocr_available = False
        self._pymupdf_available = False
        self._init_backends()

    def _init_backends(self):
        try:
            import easyocr
            self._easyocr_reader = easyocr.Reader(["fr", "en"], gpu=False)
            self._easyocr_available = True
            logger.info("EasyOCR backend loaded")
        except ImportError:
            logger.warning("EasyOCR not installed — using fallback OCR")

        try:
            import fitz  # PyMuPDF
            self._pymupdf_available = True
            logger.info("PyMuPDF backend loaded")
        except ImportError:
            logger.warning("PyMuPDF not installed — PDF extraction disabled")

    def validate_file(self, content_type: str, file_size: int) -> Optional[str]:
        """Returns error message if invalid, None if OK."""
        if file_size > MAX_FILE_SIZE:
            return f"Fichier trop volumineux ({file_size // (1024*1024)}MB). Max: 15MB"
        all_supported = SUPPORTED_IMAGE_TYPES | SUPPORTED_DOC_TYPES
        if content_type not in all_supported:
            return f"Format non supporté: {content_type}"
        return None

    async def extract_text(self, file_bytes: bytes, content_type: str, filename: str = "") -> str:
        """Extract text from image or PDF bytes."""
        if content_type in SUPPORTED_DOC_TYPES:
            return self._extract_from_pdf(file_bytes, filename)
        elif content_type in SUPPORTED_IMAGE_TYPES:
            return self._extract_from_image(file_bytes, filename)
        return ""

    def _extract_from_image(self, file_bytes: bytes, filename: str) -> str:
        if self._easyocr_available and self._easyocr_reader:
            try:
                results = self._easyocr_reader.readtext(file_bytes)
                text = " ".join([r[1] for r in results])
                logger.info(f"EasyOCR extracted {len(text)} chars from {filename}")
                return text.strip()
            except Exception as e:
                logger.error(f"EasyOCR failed for {filename}: {e}")

        # Fallback: basic Pillow metadata
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(file_bytes))
            return f"[Image: {filename}, {img.size[0]}x{img.size[1]}, {img.mode}]"
        except Exception as e:
            logger.error(f"Pillow fallback failed: {e}")
            return f"[Image jointe: {filename}]"

    def _extract_from_pdf(self, file_bytes: bytes, filename: str) -> str:
        if self._pymupdf_available:
            try:
                import fitz
                doc = fitz.open(stream=file_bytes, filetype="pdf")
                text_parts = []
                for page in doc:
                    page_text = page.get_text().strip()
                    if page_text:
                        text_parts.append(page_text)
                    elif self._easyocr_available and self._easyocr_reader:
                        # Scanned page — render to image at 2× zoom then OCR
                        try:
                            mat = fitz.Matrix(2, 2)
                            pix = page.get_pixmap(matrix=mat)
                            img_bytes = pix.tobytes("png")
                            results = self._easyocr_reader.readtext(img_bytes)
                            ocr_text = " ".join(r[1] for r in results).strip()
                            if ocr_text:
                                text_parts.append(ocr_text)
                        except Exception as ocr_err:
                            logger.warning("EasyOCR page fallback failed: %s", ocr_err)
                doc.close()
                text = "\n".join(text_parts).strip()
                if text:
                    logger.info("PyMuPDF extracted %d chars from %s", len(text), filename)
                    return text
                return f"[PDF sans texte extractible: {filename}]"
            except Exception as e:
                logger.error(f"PyMuPDF failed for {filename}: {e}")

        return f"[Document PDF joint: {filename}]"


# Singleton
ocr_service = OCRService()
