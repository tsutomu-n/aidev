"""Linux run-scoped supervisor. Interrupt the recovery owner before descendants."""
from pathlib import Path
import ctypes
import errno
import json
import os
import signal
import subprocess
import time


def identity(pid):
    try:
        fields = (Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()
        return fields[19], fields[0]
    except (OSError, IndexError):
        return None


def observe(owner, known):
    pending = [owner]
    pending.extend(pid for pid, started in list(known.items()) if (now := identity(pid)) is not None and now[0] == started and now[1] != 'Z')
    visited = set()
    while pending:
        pid = pending.pop()
        if pid in visited:
            continue
        visited.add(pid)
        current = identity(pid)
        if current is None or (pid in known and known[pid] != current[0]):
            continue
        known[pid] = current[0]
        for task in (Path('/proc') / str(pid) / 'task').glob('*/children'):
            try:
                pending.extend(int(x) for x in task.read_text().split())
            except (OSError, ValueError):
                continue


def living(known):
    return [pid for pid, started in known.items()
            if (now := identity(pid)) is not None and now[0] == started and now[1] != 'Z']


def signal_owned(pid, started, sig, report):
    # pidfd binds the signal to the observed process even if it exits/reuses PID.
    fd = None
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        fd = libc.pidfd_open(pid, 0)
        if fd < 0:
            raise OSError(ctypes.get_errno(), "pidfd_open")
        now = identity(pid)
        if now is None or now[0] != started or now[1] == 'Z':
            return
        if libc.pidfd_send_signal(fd, int(sig), None, 0) < 0:
            raise OSError(ctypes.get_errno(), "pidfd_send_signal")
        report['signals'].append({'pid': pid, 'start_ticks': started, 'signal': sig.name})
    except ProcessLookupError:
        pass
    except OSError as exc:
        report['stop_errors'].append({'pid': pid, 'errno': exc.errno, 'signal': sig.name})
    finally:
        if fd is not None and fd >= 0:
            os.close(fd)


def cancel_for_recovery(proc, known, grace=10, report=None, recovery_target=None):
    if report is None:
        report = {}
    observe(proc.pid, known)
    target_pid = proc.pid if recovery_target is None else recovery_target
    if target_pid not in known:
        raise ValueError('Recovery target process ownership unconfirmed')
    report.update({'signals': [], 'stop_errors': [], 'repeat_interrupts': 0, 'grace_seconds': grace,
                   'wrapper_pid': proc.pid, 'recovery_target_pid': target_pid,
                   'recovery_target_start_ticks': known[target_pid]})
    previous = signal.getsignal(signal.SIGINT)
    def repeated(_sig, _frame):
        report['repeat_interrupts'] += 1
    signal.signal(signal.SIGINT, repeated)
    try:
        observe(proc.pid, known)
        signal_owned(target_pid, known[target_pid], signal.SIGINT, report)
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            observe(proc.pid, known)
            proc.poll()
            if not living(known):
                break
            time.sleep(.02)
        report['residual_after_grace'] = living(known)
        report['method'] = 'forced-TERM-KILL' if report['residual_after_grace'] else 'cooperative-SIGINT'
        for sig in (signal.SIGTERM, signal.SIGKILL):
            if not living(known):
                break
            observe(proc.pid, known)
            for pid in living(known):
                signal_owned(pid, known[pid], sig, report)
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline and living(known):
                observe(proc.pid, known)
                proc.poll()
                time.sleep(.02)
        report['remaining'] = living(known)
        report['exit_code'] = proc.poll()
        report['status'] = 'FAIL' if report['remaining'] or report['stop_errors'] else 'PASS'
        return report
    finally:
        report['remaining'] = living(known)
        report['exit_code'] = proc.poll()
        report['status'] = 'FAIL' if report['remaining'] or report['stop_errors'] else 'PASS'
        signal.signal(signal.SIGINT, previous)


def run_owned(argv, cwd, env, log, result, timeout=600, grace=10, violation=None, recovery_target=None):
    report = {'status': 'RUNNING', 'stage': 'starting', 'reason': None, 'observed': {}, 'cleanup': None, 'violation': {'signals': [], 'stop_errors': []}}
    if Path(result).exists():
        raise FileExistsError(result)
    known = {}; proc = None
    try:
        with Path(log).open('xb') as stream:
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            report['stage'] = 'running'
            deadline = time.monotonic() + timeout
            try:
                while proc.poll() is None:
                    observe(proc.pid, known)
                    if violation:
                        offenders = violation(dict(known))
                        if offenders:
                            report['reason'] = 'violation'
                            for pid in offenders:
                                if pid not in known:
                                    raise ValueError('Violation process ownership unconfirmed')
                                signal_owned(pid, known[pid], signal.SIGKILL, report['violation'])
                            report['status'] = 'VIOLATION'
                            break
                    if time.monotonic() >= deadline:
                        raise subprocess.TimeoutExpired(argv, timeout)
                    time.sleep(.02)
                report['exit_code'] = proc.returncode
                if report['status'] == 'RUNNING':
                    report['status'] = 'PASS' if proc.returncode == 0 else 'FAIL'
            except (KeyboardInterrupt, subprocess.TimeoutExpired) as exc:
                report['reason'] = type(exc).__name__
                report['status'] = 'INTERRUPTED'
            finally:
                report['stage'] = 'recovery'
                observe(proc.pid, known)
                if proc.poll() is None or living(known):
                    report['cleanup'] = {}
                    target = proc.pid if recovery_target is None else recovery_target(dict(known))
                    cancel_for_recovery(proc, known, grace, report['cleanup'], target)
                    if report['cleanup']['status'] != 'PASS':
                        report['status'] = 'STOP_FAILED'
                report['exit_code'] = proc.poll()
    except BaseException as exc:
        report['status'] = 'FAIL'
        report['exception'] = type(exc).__name__
        report['reason'] = report['reason'] or type(exc).__name__
        raise
    finally:
        report['stopped_at_stage'] = report['stage']
        report['stage'] = 'finished'
        report['remaining'] = living(known)
        if report['remaining'] or report['violation']['stop_errors']:
            report['status'] = 'STOP_FAILED'
        report['observed'] = {str(pid): start for pid, start in known.items()}
        report['limitations'] = 'Polling cannot guarantee capture of descendants that detach before first observation.'
        target = Path(result)
        temp = target.with_suffix('.tmp')
        temp.write_text(json.dumps(report, indent=2) + '\n')
        temp.replace(target)
    return report
