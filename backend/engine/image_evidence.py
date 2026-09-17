"""
Resolve amounts for financial events whose `amount` column is blank.

Some financial events carry no machine-readable amount: the figure only
exists on an attached receipt, payslip or invoice image, linked through
`images.csv.related_event_id`. This module resolves those amounts.

Resolution order
----------------
1. **Evidence sidecar** -- a JSON file mapping ``event_id`` to a
   transcribed amount. This is how human-verified readings of images are
   supplied. The file lives *outside* version control (see
   ``.gitignore``), so no dataset-specific figures are ever committed.
   It is looked up, in order, at:

   * ``$BUY_OR_WAIT_IMAGE_EVIDENCE`` (explicit path to a JSON file)
   * ``<dataset_dir>/image_evidence.json``
   * ``<project_root>/local_evidence/image_evidence.json``

2. **OCR fallback** -- if no sidecar entry exists and ``pytesseract`` plus
   ``Pillow`` are installed, the linked image is OCR'd and a total-like
   figure is extracted.

3. **Hard failure** -- if neither succeeds, :class:`EvidenceResolutionError`
   is raised. A blank amount is *never* silently treated as zero, because
   doing so would understate a debit and could make an unsafe payment look
   safe.

Sidecar format::

    {
      "event_id_here": {
        "amount": 1234.56,
        "currency": "USD",
        "image_id": "receipt_image_id",
        "source_field": "Total (tax invoice)"
      }
    }

Only ``amount`` is required. ``currency``, when present, is checked against
the currency on the event row and a mismatch raises, which catches
transcription slips. ``image_id`` and ``source_field`` are optional
provenance notes kept for auditability.
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, Optional

SIDECAR_FILENAME = "image_evidence.json"
LOCAL_EVIDENCE_DIRNAME = "local_evidence"
ENV_VAR = "BUY_OR_WAIT_IMAGE_EVIDENCE"

# Labels that, on a receipt/invoice/payslip, precede the figure we want.
_TOTAL_LABELS = (
    r"grand total|total amount received|total amount|balance due|amount due|"
    r"net pay|net amount|amount received|total paid|total"
)
_OCR_AMOUNT_RE = re.compile(
    rf"(?:{_TOTAL_LABELS})\D{{0,15}}([\d,]+\.\d{{2}}|[\d,]+)",
    flags=re.IGNORECASE,
)


class EvidenceResolutionError(RuntimeError):
    """Raised when a blank event amount cannot be resolved from evidence."""


def _project_root() -> str:
    # backend/engine/image_evidence.py -> project root is three levels up.
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _candidate_sidecar_paths(dataset_dir: Optional[str]) -> list:
    paths = []
    env_path = os.environ.get(ENV_VAR)
    if env_path:
        paths.append(env_path)
    if dataset_dir:
        paths.append(os.path.join(dataset_dir, SIDECAR_FILENAME))
    paths.append(os.path.join(_project_root(), LOCAL_EVIDENCE_DIRNAME, SIDECAR_FILENAME))
    return paths


def load_evidence_sidecar(dataset_dir: Optional[str] = None) -> Dict[str, dict]:
    """Load the first evidence sidecar found, or an empty mapping.

    Entries given as a bare number are normalized to ``{"amount": number}``
    so both the short and the full provenance form are accepted.
    """
    for path in _candidate_sidecar_paths(dataset_dir):
        if not path or not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        normalized: Dict[str, dict] = {}
        for event_id, value in raw.items():
            if isinstance(value, (int, float)):
                normalized[event_id] = {"amount": float(value)}
            elif isinstance(value, dict) and "amount" in value:
                entry = dict(value)
                entry["amount"] = float(entry["amount"])
                normalized[event_id] = entry
            else:
                raise EvidenceResolutionError(
                    f"Malformed evidence entry for {event_id} in {path}: {value!r}"
                )
        return normalized
    return {}


def ocr_amount(image_path: str) -> Optional[float]:
    """Best-effort OCR of a total-like figure from a receipt image.

    Returns ``None`` when OCR dependencies are unavailable, the file is
    missing, or no total-like figure is found.
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return None
    if not os.path.isfile(image_path):
        return None
    try:
        text = pytesseract.image_to_string(Image.open(image_path))
    except Exception:
        return None
    matches = _OCR_AMOUNT_RE.findall(text)
    if not matches:
        return None
    try:
        return float(matches[-1].replace(",", ""))
    except ValueError:
        return None


class ImageEvidenceResolver:
    """Resolves blank event amounts from image-derived evidence.

    One instance is built per :class:`~engine.data_loader.Dataset`; the
    sidecar is read once and cached, keeping loading deterministic.
    """

    def __init__(self, dataset_dir: Optional[str] = None, media_dir: Optional[str] = None):
        self.dataset_dir = dataset_dir
        self.media_dir = media_dir or (
            os.path.join(dataset_dir, "media", "images") if dataset_dir else None
        )
        self.sidecar = load_evidence_sidecar(dataset_dir)

    def _image_path(self, image_id: Optional[str]) -> Optional[str]:
        if not image_id or not self.media_dir:
            return None
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            candidate = os.path.join(self.media_dir, f"{image_id}{ext}")
            if os.path.isfile(candidate):
                return candidate
        return None

    def resolve(self, event_id: str, currency: str, image_id: Optional[str] = None) -> float:
        """Return the amount for ``event_id``, raising if it cannot be found."""
        entry = self.sidecar.get(event_id)
        if entry is not None:
            declared = entry.get("currency")
            if declared and currency and declared != currency:
                raise EvidenceResolutionError(
                    f"Currency mismatch for {event_id}: event row says {currency}, "
                    f"evidence sidecar says {declared}"
                )
            return entry["amount"]

        path = self._image_path(image_id or entry and entry.get("image_id"))
        if path:
            amount = ocr_amount(path)
            if amount is not None:
                return amount

        raise EvidenceResolutionError(
            f"Blank amount for {event_id} could not be resolved. Add an entry to an "
            f"image evidence sidecar ({SIDECAR_FILENAME}) or install pytesseract/Pillow "
            f"and make the linked image available under {self.media_dir!r}. "
            f"A blank amount is never assumed to be zero."
        )
