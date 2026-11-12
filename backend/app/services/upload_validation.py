"""Hardening for every file a person uploads (KYC documents, update photos).

Defence in depth, in order:
  1. hard size cap while streaming (done by the caller via read_limited)
  2. type decided by magic bytes, never by the filename or the client-supplied content type
  3. images are fully decoded and RE-ENCODED: this drops EXIF/GPS, embedded payloads and polyglot tricks,
     and bounds pixel count against decompression bombs
  4. PDFs are rebuilt page by page (drops JavaScript, launch actions, attachments, forms) and refused if
     they are encrypted, too long, or still contain active content
"""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

JPEG, PNG, PDF, WEBP = "image/jpeg", "image/png", "application/pdf", "image/webp"
_MAX_PDF_PAGES = 12
_MAX_EDGE = 3000
_ACTIVE_PDF = re.compile(rb"/(JavaScript|JS|Launch|EmbeddedFile|RichMedia|XFA|OpenAction|AA|SubmitForm|ImportData)\b")


class UploadRejected(ValueError):
    """The message is safe to show to the person who uploaded the file."""


@dataclass(frozen=True)
class CleanUpload:
    data: bytes
    mime: str
    sha256: bytes

    @property
    def size(self) -> int:
        return len(self.data)


def sniff(head: bytes) -> str | None:
    if head.startswith(b"\xff\xd8\xff"):
        return JPEG
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if head.startswith(b"%PDF-"):
        return PDF
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return WEBP
    return None


def _clean_image(data: bytes, max_pixels: int, out_format: str) -> bytes:
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(data)) as img:
            if img.width * img.height > max_pixels:
                raise UploadRejected("That image is too large. Please upload a smaller photo.")
            img = ImageOps.exif_transpose(img)
            img.load()
            if max(img.size) > _MAX_EDGE:
                img.thumbnail((_MAX_EDGE, _MAX_EDGE))
            out = io.BytesIO()
            if out_format == "JPEG":
                img.convert("RGB").save(out, "JPEG", quality=88, optimize=True)
            elif out_format == "WEBP":
                img.convert("RGB").save(out, "WEBP", quality=85)
            else:
                img.save(out, "PNG", optimize=True)
            return out.getvalue()
    except UploadRejected:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise UploadRejected("We could not read that image. Please upload a clear JPEG or PNG photo.") from exc


def _clean_pdf(data: bytes) -> bytes:
    from pypdf import PdfReader, PdfWriter
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise UploadRejected("Password-protected PDFs can't be reviewed. Please upload an unlocked copy.")
        if not 1 <= len(reader.pages) <= _MAX_PDF_PAGES:
            raise UploadRejected(f"Please upload a PDF of at most {_MAX_PDF_PAGES} pages.")
        writer = PdfWriter()
        for page in reader.pages:
            if "/Annots" in page:
                del page["/Annots"]
            if "/AA" in page:
                del page["/AA"]
            writer.add_page(page)
        out = io.BytesIO()
        writer.write(out)
        cleaned = out.getvalue()
    except UploadRejected:
        raise
    except (PyPdfError, ValueError, KeyError, OSError, RecursionError) as exc:
        raise UploadRejected("We could not read that PDF. Please upload a clear scan or photo instead.") from exc
    if _ACTIVE_PDF.search(cleaned):
        raise UploadRejected("That PDF contains interactive content, which we can't accept. Please upload a plain scan or photo.")
    return cleaned


def sanitize_kyc_upload(data: bytes, max_pixels: int) -> CleanUpload:
    """KYC documents: JPEG, PNG (both stored as JPEG) or PDF."""
    kind = sniff(data[:16])
    if kind in (JPEG, PNG, WEBP):
        cleaned, mime = _clean_image(data, max_pixels, "JPEG"), JPEG
    elif kind == PDF:
        cleaned, mime = _clean_pdf(data), PDF
    else:
        raise UploadRejected("Please upload a JPEG, PNG or PDF file.")
    return CleanUpload(cleaned, mime, hashlib.sha256(cleaned).digest())


def sanitize_public_image(data: bytes, max_pixels: int) -> CleanUpload:
    """Photos attached to public updates: images only, stored as WebP."""
    if sniff(data[:16]) not in (JPEG, PNG, WEBP):
        raise UploadRejected("Photos must be JPEG, PNG or WebP images.")
    cleaned = _clean_image(data, max_pixels, "WEBP")
    return CleanUpload(cleaned, WEBP, hashlib.sha256(cleaned).digest())
