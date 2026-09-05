"""Shared platform-capability probes and skip decorators (issue #781).

Windows lacks the POSIX primitives several OMH surfaces are built on
(O_NOFOLLOW / O_DIRECTORY dirfd-anchored opens, fcntl advisory locks,
mode-bit enforcement, mkfifo, killpg). Product code fails closed on such
platforms by design; these decorators keep the corresponding tests scoped
to hosts where the exercised contract can hold, following the guard
conventions established by #771 and #778.
"""

from __future__ import annotations

import os
import unittest

try:  # probe only; mirrors the product's degraded-import pattern
    import fcntl as _fcntl  # noqa: F401
except ImportError:
    HAS_FCNTL = False
else:
    HAS_FCNTL = True

HAS_SECURE_DIR_IO = bool(
    getattr(os, "O_NOFOLLOW", 0)
    and getattr(os, "O_DIRECTORY", 0)
    and os.open in os.supports_dir_fd
    and hasattr(os, "fchmod")
)

requires_posix = unittest.skipUnless(
    os.name == "posix",
    "exercises POSIX-only process or filesystem semantics",
)
requires_windows = unittest.skipUnless(
    os.name == "nt",
    "exercises Windows-only process or filesystem semantics",
)
requires_posix_permissions = unittest.skipUnless(
    os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() != 0,
    "POSIX permission bits do not restrict root and do not exist off POSIX",
)
requires_symlinks = unittest.skipUnless(
    os.name == "posix",
    "symlink creation and resolution differ off POSIX",
)
requires_fcntl_locks = unittest.skipUnless(
    HAS_FCNTL,
    "fcntl advisory locking is POSIX-only",
)
requires_secure_dir_io = unittest.skipUnless(
    HAS_SECURE_DIR_IO,
    "secure dirfd-anchored file access requires POSIX O_NOFOLLOW/O_DIRECTORY/dir_fd",
)
requires_domain_intelligence_store = unittest.skipUnless(
    HAS_SECURE_DIR_IO and HAS_FCNTL,
    "domain-intelligence safe stores require POSIX dirfd/O_NOFOLLOW/fcntl primitives",
)
requires_posix_select = unittest.skipUnless(
    os.name == "posix",
    "select() on Windows accepts only sockets, not pipe/tty descriptors",
)
