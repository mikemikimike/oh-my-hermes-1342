"""Public discovery facade for the work-artifact show-shape action tests.

The cases live in two responsibility modules that are deliberately not
``test_``-prefixed, so unittest discovery and pytest collect each case exactly
once, through this module:

- ``_work_artifact_shape_listing_cases``: shape advertisement in the copy
  listing, legacy copy compatibility, and payload immutability.
- ``_work_artifact_shape_show_cases``: show-shape rendering, unavailable
  paths, Mermaid capability gating, and privacy.
"""

from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from _work_artifact_shape_listing_cases import WorkArtifactShapeListingTests
from _work_artifact_shape_show_cases import WorkArtifactShowShapeActionTests

__all__ = [
    "WorkArtifactShapeListingTests",
    "WorkArtifactShowShapeActionTests",
]


if __name__ == "__main__":
    unittest.main()
