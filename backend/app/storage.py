"""Controlled file store.

Files are content-addressed: the storage key contains the SHA-256 of the bytes, files are written
once (temporary name, then an atomic rename) and never overwritten. Every read can be verified
against the hash recorded in the database, so a file changed on disk is detected.
"""
from __future__ import annotations

import hashlib
import io
import os
import shutil
import tempfile

from .config import settings

MAGIC = {
    b"%PDF": ("application/pdf", ".pdf"),
    b"\x89PNG": ("image/png", ".png"),
    b"\xff\xd8\xff": ("image/jpeg", ".jpg"),
    b"II*\x00": ("image/tiff", ".tif"),
    b"MM\x00*": ("image/tiff", ".tif"),
    b"PK\x03\x04": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
}


class StorageError(Exception):
    pass


def root() -> str:
    return os.path.abspath(settings.data_dir)


def sniff(data: bytes, filename: str) -> tuple[str, str]:
    for magic, (mime, ext) in MAGIC.items():
        if data.startswith(magic):
            if ext == ".docx" and not filename.lower().endswith(".docx"):
                break
            return mime, ext
    raise StorageError("Upload a PDF, PNG, JPEG, TIFF or Word (.docx) file.")


def key_for(tenant_id: str, sha: str, ext: str) -> str:
    return f"tenants/{tenant_id}/files/{sha[:2]}/{sha}{ext}"


def put(tenant_id: str, data: bytes, ext: str) -> tuple[str, str]:
    sha = hashlib.sha256(data).hexdigest()
    key = key_for(tenant_id, sha, ext)
    path = os.path.join(root(), key)
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, 0o440)
        os.replace(tmp, path)
    return sha, key


def path_of(key: str) -> str:
    p = os.path.abspath(os.path.join(root(), key))
    if not p.startswith(root() + os.sep):
        raise StorageError("Invalid storage key")
    return p


def verify(key: str, sha: str) -> str:
    """Return the path after checking the bytes still match the recorded SHA-256."""
    p = path_of(key)
    if not os.path.exists(p):
        raise StorageError("The stored file is missing from the file store. Upload the same file again to restore it "
                           "(it is accepted only if its SHA-256 matches the record), then run again.")
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != sha:
        raise StorageError("The stored file no longer matches its recorded SHA-256; it was changed outside Comproof.")
    return p


def work_dir(tenant_id: str, comparison_id: str) -> str:
    return os.path.join(root(), "tenants", str(tenant_id), "comparisons", str(comparison_id))


def clear_work_dir(tenant_id: str, comparison_id: str) -> None:
    d = work_dir(tenant_id, comparison_id)
    if os.path.isdir(d):
        shutil.rmtree(d)


def describe(data: bytes, mime: str) -> tuple[int | None, str]:
    """Page count and document kind, read without running OCR."""
    if mime == "application/pdf":
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(io.BytesIO(data))
        n = len(pdf)
        chars = 0
        for i in range(min(n, 3)):
            tp = pdf[i].get_textpage()
            chars += tp.count_chars()
        return n, "pdf-vector" if chars > 40 else "pdf-scan"
    if mime.startswith("image/"):
        return 1, "image"
    return None, "docx"
