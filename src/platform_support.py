"""OS primitives shared by aidev and its installer (standard library only)."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys

WINDOWS = sys.platform == "win32"


def data_home():
    if WINDOWS:
        value = os.environ.get("LOCALAPPDATA")
        if not value or not Path(value).is_absolute():
            raise ValueError("LOCALAPPDATA must be an absolute directory")
        return Path(value) / "aidev"
    return Path.home() / ".local/share/aidev"


def is_link(path):
    """Include Windows junctions and other reparse points, also on Python 3.11."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def kernel32():
    import ctypes
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreateSemaphoreW": ([w.LPVOID, w.LONG, w.LONG, w.LPCWSTR], w.HANDLE),
        "WaitForSingleObject": ([w.HANDLE, w.DWORD], w.DWORD),
        "ReleaseSemaphore": ([w.HANDLE, w.LONG, w.LPVOID], w.BOOL),
        "CloseHandle": ([w.HANDLE], w.BOOL),
        "CreateJobObjectW": ([w.LPVOID, w.LPCWSTR], w.HANDLE),
        "SetInformationJobObject": ([w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD], w.BOOL),
        "AssignProcessToJobObject": ([w.HANDLE, w.HANDLE], w.BOOL),
        "OpenProcess": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
    }
    for name, (args, result) in signatures.items():
        getattr(kernel, name).argtypes = args
        getattr(kernel, name).restype = result
    return kernel


@contextmanager
def directory_lock(root):
    """Nonblocking exclusion without changing repository contents."""
    if not WINDOWS:
        import fcntl
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)
        return
    import ctypes
    kernel = kernel32()
    name = "Global\\aidev-" + hashlib.sha256(os.path.normcase(str(root.resolve())).encode()).hexdigest()
    handle = kernel.CreateSemaphoreW(None, 1, 1, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    acquired = False
    try:
        result = kernel.WaitForSingleObject(handle, 0)
        if result == 258:
            raise BlockingIOError("aidev is already running")
        if result != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        acquired = True
        yield
    finally:
        if acquired:
            kernel.ReleaseSemaphore(handle, 1, None)
        kernel.CloseHandle(handle)


class WindowsJob:
    """A job handle which cannot be inherited; close kills all descendants."""
    def __init__(self):
        import ctypes
        from ctypes import wintypes as w
        class Basic(ctypes.Structure):
            _fields_ = [("ProcessTime", ctypes.c_longlong), ("JobTime", ctypes.c_longlong),
                        ("LimitFlags", w.DWORD), ("MinWorkingSet", ctypes.c_size_t),
                        ("MaxWorkingSet", ctypes.c_size_t), ("ActiveProcessLimit", w.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")]
        class Extended(ctypes.Structure):
            _fields_ = [("Basic", Basic), ("IO", IO), ("ProcessMemory", ctypes.c_size_t),
                        ("JobMemory", ctypes.c_size_t), ("PeakProcessMemory", ctypes.c_size_t), ("PeakJobMemory", ctypes.c_size_t)]
        self.kernel = kernel32()
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Extended()
        limits.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, pid):
        import ctypes
        # PROCESS_SET_QUOTA | PROCESS_TERMINATE; no private Popen attributes.
        process = self.kernel.OpenProcess(0x100 | 0x1, False, pid)
        if not process:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self.kernel.AssignProcessToJobObject(self.handle, process):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self.kernel.CloseHandle(process)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


@contextmanager
def child_process(argv, root, env, output):
    job = WindowsJob() if WINDOWS else None
    # The bootstrap waits for a byte until assigned to the job, so even a very
    # fast provider cannot spawn a descendant outside our job during startup.
    command = [sys.executable, "-B", "-I", str(Path(__file__).resolve()), *argv] if WINDOWS else argv
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {"start_new_session": True}
    proc = None
    try:
        proc = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.PIPE if WINDOWS else subprocess.DEVNULL,
                                stdout=output, stderr=subprocess.STDOUT, **options)
        if job:
            job.assign(proc.pid)
            proc.stdin.write(b"1")
            proc.stdin.close()
        yield proc
    finally:
        if job:
            job.close()
        if proc is not None:
            if proc.stdin is not None and not proc.stdin.closed:
                proc.stdin.close()
            if proc.poll() is None:
                if not WINDOWS:
                    stop_process(proc)
                else:
                    proc.kill()  # Also covers failure before job assignment.
            proc.wait()


def stop_process(proc):
    if WINDOWS:
        # The context manager closes the job before waiting.
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    # A parent may exit on TERM while a grandchild ignores it.
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait()


if __name__ == "__main__":
    if sys.stdin.buffer.read(1) != b"1":
        raise SystemExit(2)
    raise SystemExit(subprocess.call(sys.argv[1:], stdin=subprocess.DEVNULL))
