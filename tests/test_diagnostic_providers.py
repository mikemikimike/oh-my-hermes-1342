"""Compatibility facade for the split diagnostic-provider contract tests.

The contract tests for `diagnostic_providers/v1` (issue #1297, T1.2) live in
five single-responsibility modules: `diagnostic_provider_config_tests.py`,
`diagnostic_provider_scope_privacy_tests.py`,
`diagnostic_provider_scheduler_tests.py`,
`diagnostic_provider_outcomes_tests.py`, and
`diagnostic_provider_claims_records_tests.py`, with shared fixtures in
`_diagnostic_provider_helpers.py`.

This module re-exports their classes so `PYTHONPATH=tests uv run python -m
unittest tests/test_diagnostic_providers.py -v` still runs the whole
contract in one command. The split modules deliberately do not match the
`test*.py` discovery pattern, so `unittest discover` collects each class
exactly once, through this facade.
"""

from __future__ import annotations

import unittest

from diagnostic_provider_claims_records_tests import ClaimBoundaryTests, OutcomeRecordTests
from diagnostic_provider_config_tests import (
    ConfigIdentityTests,
    ProviderAllowlistTests,
    ProviderBoundsTests,
)
from diagnostic_provider_outcomes_tests import CompatibilityMarkerTests, OutcomeVocabularyTests
from diagnostic_provider_scope_privacy_tests import (
    ChangedFileScopeTests,
    MetadataOnlyShapeTests,
    MovingRevisionEqualityTests,
)
from diagnostic_provider_scheduler_tests import ModuleBoundaryTests, StatefulSerialFallbackTests

__all__ = (
    "ChangedFileScopeTests",
    "ClaimBoundaryTests",
    "CompatibilityMarkerTests",
    "ConfigIdentityTests",
    "MetadataOnlyShapeTests",
    "ModuleBoundaryTests",
    "MovingRevisionEqualityTests",
    "OutcomeRecordTests",
    "OutcomeVocabularyTests",
    "ProviderAllowlistTests",
    "ProviderBoundsTests",
    "StatefulSerialFallbackTests",
)


if __name__ == "__main__":
    unittest.main()
