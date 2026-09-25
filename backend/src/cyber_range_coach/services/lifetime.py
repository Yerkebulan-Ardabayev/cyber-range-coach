"""Tie helper processes to the academy's own lifetime on Windows.

The keep-alive `wsl.exe` must not outlive the academy: the windowed academy is
closed with Task Manager or `taskkill /F` by the installer, and Windows does
not end child processes then. An orphaned `wsl.exe` would keep WSL running until
reboot and every new start would add one more. A Job Object with
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE ends its members when the academy's handle
to it closes, which the OS does however the academy ends.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class ChildLifetime:
    """Processes bound here end when the current process ends (Windows only)."""

    def __init__(self) -> None:
        self._job: int | None = None

    def bind(self, pid: int) -> bool:
        if sys.platform != "win32":
            return False
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        if self._job is None:
            # Not inheritable (no security attributes): a child holding the
            # handle would keep the job, and itself, alive.
            job = kernel32.CreateJobObjectW(None, None)
            if not job:
                return False
            limits = _ExtendedLimits()
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not kernel32.SetInformationJobObject(
                job,
                JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            ):
                kernel32.CloseHandle(job)
                return False
            self._job = int(job)
        process = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
        if not process:
            return False
        try:
            return bool(kernel32.AssignProcessToJobObject(self._job, process))
        finally:
            kernel32.CloseHandle(process)
