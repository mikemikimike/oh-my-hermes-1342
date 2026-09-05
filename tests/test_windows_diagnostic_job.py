"""Platform-neutral state-machine tests for Windows diagnostic Job Objects."""

from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.local_diagnostic_process_owner import (  # noqa: E402
    WINDOWS_OWNED_PROCESS_FLAGS,
    WindowsJobObjectOwner,
)


class _FakeProcess:
    pid = 41
    _handle = 99

    def poll(self) -> int:
        return 0

    def wait(self, timeout: float) -> int:
        del timeout
        return 0


class _FakeWindowsJobApi:
    def __init__(
        self,
        *,
        assigned: bool = True,
        resumed: bool = True,
        active: tuple[int | None, ...] = (2, 0),
    ) -> None:
        self.assigned = assigned
        self.resumed = resumed
        self.active = list(active)
        self.calls: list[tuple[object, ...]] = []

    def create_kill_on_close_job(self) -> int:
        self.calls.append(("create",))
        return 7

    def assign_process(self, job: int, process_handle: int) -> bool:
        self.calls.append(("assign", job, process_handle))
        return self.assigned

    def resume_process(self, process_id: int) -> bool:
        self.calls.append(("resume", process_id))
        return self.resumed

    def active_processes(self, job: int) -> int | None:
        self.calls.append(("active", job))
        if not self.active:
            return 0
        return self.active.pop(0)

    def terminate_job(self, job: int) -> bool:
        self.calls.append(("terminate", job))
        return True

    def close_job(self, job: int) -> None:
        self.calls.append(("close", job))


class WindowsJobObjectOwnerTests(unittest.TestCase):
    def test_job_owns_suspended_process_and_verifies_empty_on_finish(self) -> None:
        api = _FakeWindowsJobApi()

        owner = WindowsJobObjectOwner.attach(_FakeProcess(), api=api)
        cleaned = owner.terminate(15)

        self.assertTrue(cleaned)
        self.assertEqual(
            api.calls,
            [
                ("create",),
                ("assign", 7, 99),
                ("resume", 41),
                ("active", 7),
                ("terminate", 7),
                ("active", 7),
                ("close", 7),
            ],
        )

    def test_unobservable_job_fails_closed(self) -> None:
        api = _FakeWindowsJobApi(active=(None,))

        owner = WindowsJobObjectOwner.attach(_FakeProcess(), api=api)

        self.assertFalse(owner.terminate(15))
        self.assertEqual(api.calls[-1], ("close", 7))

    def test_assignment_failure_closes_job_and_refuses_process(self) -> None:
        api = _FakeWindowsJobApi(assigned=False)

        with self.assertRaises(OSError):
            WindowsJobObjectOwner.attach(_FakeProcess(), api=api)

        self.assertEqual(api.calls[-1], ("close", 7))

    def test_windows_launch_flags_suspend_before_job_assignment(self) -> None:
        self.assertEqual(
            WINDOWS_OWNED_PROCESS_FLAGS,
            0x00000004 | 0x00000200,
        )


if __name__ == "__main__":
    unittest.main()
