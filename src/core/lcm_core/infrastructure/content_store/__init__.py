"""PAv1 content store — validators, detectors, and extractors.

This package vendors the JSON schemas under `schemas/` and provides:

- :class:`PAv1Validator`: validates manifest / lifecycle / scenario YAML payloads.
- :class:`PodTypeDetector`: deterministic priority chain to infer ``PodType``
  from an extracted directory or an in-memory ``ZipFile``.
- :class:`ContentExtractor`: skeleton (Phase 1 will implement extraction).
- :class:`ExtractedContent`: typed container of fields extracted from PAv1/.
- Errors: :class:`PAv1ValidationError`, :class:`PodTypeIndeterminate`.

See ``docs/architecture/content-format/PAv1.md`` and the CPA↔SE integration plan
for the full specification and rationale.
"""

from lcm_core.infrastructure.content_store.content_extractor import ContentExtractor, ExtractedContent
from lcm_core.infrastructure.content_store.pav1_errors import PAv1ValidationError, PodTypeIndeterminate
from lcm_core.infrastructure.content_store.pav1_validator import PAv1Validator
from lcm_core.infrastructure.content_store.pod_type_detector import PodTypeDetector

__all__ = [
    "ContentExtractor",
    "ExtractedContent",
    "PAv1Validator",
    "PAv1ValidationError",
    "PodTypeDetector",
    "PodTypeIndeterminate",
]
