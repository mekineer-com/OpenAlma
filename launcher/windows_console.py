"""Request Ctrl+C from a verified private service console, without terminating it."""
from __future__ import annotations

import argparse
import ctypes
import os
import time
from ctypes import wintypes

import psutil


def request_stop(pid: int, created: float) -> None:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.AttachConsole.argtypes = [wintypes.DWORD]
    kernel.GetConsoleProcessList.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
    kernel.SetConsoleCtrlHandler.argtypes = [ctypes.c_void_p, wintypes.BOOL]
    handle = kernel.OpenProcess(0x00100000 | 0x1000, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if psutil.Process(pid).create_time() != created:
            raise RuntimeError("Service PID identity changed; no shutdown signal sent")
        kernel.FreeConsole()
        if not kernel.AttachConsole(pid):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not kernel.SetConsoleCtrlHandler(None, True):
                raise ctypes.WinError(ctypes.get_last_error())
            members = (wintypes.DWORD * 64)()
            count = kernel.GetConsoleProcessList(members, len(members))
            if count > len(members):
                members = (wintypes.DWORD * count)()
                count = kernel.GetConsoleProcessList(members, len(members))
            if not count or count > len(members):
                raise RuntimeError("Could not inspect the complete service console")
            console = set(members[:count])
            owned = {pid, os.getpid(), *(child.pid for child in psutil.Process(pid).children(recursive=True))}
            if not {pid, os.getpid()} <= console or console - owned:
                raise RuntimeError("Service shares its console with another process; no shutdown signal sent")
            if (kernel.WaitForSingleObject(handle, 0) != 258
                    or psutil.Process(pid).create_time() != created):
                raise RuntimeError("Service exited or changed identity; no shutdown signal sent")
            if not kernel.GenerateConsoleCtrlEvent(0, 0):
                raise ctypes.WinError(ctypes.get_last_error())
            # Dispatch is asynchronous; only the launcher's existing PID waiter confirms exit.
            time.sleep(0.1)
        finally:
            kernel.FreeConsole()
    finally:
        kernel.CloseHandle(handle)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("pid", type=int)
    parser.add_argument("created", type=float)
    args = parser.parse_args()
    request_stop(args.pid, args.created)
