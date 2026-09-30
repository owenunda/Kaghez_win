"""Windows-only process handling for the bundled Suwayomi server.

Gio.Subprocess isn't a good fit on Windows: there is no SIGTERM, and
spawning java.exe from a GUI app flashes a console window. We use a plain
Popen with CREATE_NO_WINDOW instead, and put the server in a job object
with KILL_ON_JOB_CLOSE so Windows kills it when Kaghez exits, even if
Kaghez crashes or is killed from Task Manager. Otherwise java.exe would
keep running in the background, holding port 4567.
"""

import ctypes
import subprocess
import threading
from ctypes import wintypes

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
SERVER_STOP_TIMEOUT = 10


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ('ReadOperationCount', ctypes.c_ulonglong),
        ('WriteOperationCount', ctypes.c_ulonglong),
        ('OtherOperationCount', ctypes.c_ulonglong),
        ('ReadTransferCount', ctypes.c_ulonglong),
        ('WriteTransferCount', ctypes.c_ulonglong),
        ('OtherTransferCount', ctypes.c_ulonglong),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('PerProcessUserTimeLimit', ctypes.c_int64),
        ('PerJobUserTimeLimit', ctypes.c_int64),
        ('LimitFlags', wintypes.DWORD),
        ('MinimumWorkingSetSize', ctypes.c_size_t),
        ('MaximumWorkingSetSize', ctypes.c_size_t),
        ('ActiveProcessLimit', wintypes.DWORD),
        ('Affinity', ctypes.c_size_t),
        ('PriorityClass', wintypes.DWORD),
        ('SchedulingClass', wintypes.DWORD),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('BasicLimitInformation', JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ('IoInfo', IO_COUNTERS),
        ('ProcessMemoryLimit', ctypes.c_size_t),
        ('JobMemoryLimit', ctypes.c_size_t),
        ('PeakProcessMemoryUsed', ctypes.c_size_t),
        ('PeakJobMemoryUsed', ctypes.c_size_t),
    ]


kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
kernel32.CreateJobObjectW.restype = wintypes.HANDLE
kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
kernel32.SetInformationJobObject.restype = wintypes.BOOL
kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
kernel32.AssignProcessToJobObject.restype = wintypes.BOOL

# Never closed on purpose: the handle closes when our process exits, and
# that is exactly what triggers KILL_ON_JOB_CLOSE.
_job = None


def get_kill_on_close_job():
    global _job
    if _job is not None:
        return _job
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                                            ctypes.byref(info), ctypes.sizeof(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    _job = job
    return _job


def spawn_server(argv: list[str]) -> subprocess.Popen:
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        if not kernel32.AssignProcessToJobObject(get_kill_on_close_job(), int(proc._handle)):
            raise ctypes.WinError(ctypes.get_last_error())
    except OSError as e:
        # Not fatal: the server still runs, it just won't be cleaned up if
        # Kaghez dies without going through stop_server().
        print(f"[suwayomi] couldn't attach server to job object: {e}", flush=True)

    threading.Thread(target=pump_output, args=(proc,), daemon=True).start()
    return proc


def pump_output(proc: subprocess.Popen):
    """Drain the server's output so logs are visible and the pipe never
    fills up and blocks the server."""
    for line in proc.stdout:
        print(f"[suwayomi] {line.decode('utf-8', errors='replace').rstrip()}", flush=True)


def stop_server(proc: subprocess.Popen):
    # Windows has no SIGTERM for console-less processes, so this is a hard
    # kill (TerminateProcess), same as SIGKILL on Linux.
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(SERVER_STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            print("[suwayomi] server didn't exit in time", flush=True)
