"""Compatibility import for package-style validation tests."""

from scripts import validate_author_research_legacy as _implementation


validate_document = _implementation.validate_document
_is_http_url = _implementation._is_http_url
_is_iso_date_or_datetime = _implementation._is_iso_date_or_datetime
_validate_evidence = _implementation._validate_evidence
