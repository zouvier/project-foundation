"""Bounded POSIX subprocess transport; this is not an OS security sandbox."""
import math
import os
import selectors
import signal
import subprocess
import time


class ProcessError(RuntimeError):
    pass


def capture(argv, *, env, cwd=None, timeout=10, max_output=2 * 1024 * 1024,
            input_bytes=None, cancel=None):
    """Capture bounded bytes and stop the private process group on every exit.

    Callers own command and environment policy. Children that deliberately leave
    the process group require OS containment; this transport does not supply it.
    """
    if (os.name != "posix" or not math.isfinite(timeout) or not 0 < timeout <= 120
            or type(max_output) is not int or not 0 < max_output <= 2 * 1024 * 1024):
        raise ProcessError("invalid inspection process bounds")
    if input_bytes is not None and (not isinstance(input_bytes, bytes) or len(input_bytes) > 65536):
        raise ProcessError("inspection input exceeds limit")
    if cancel is not None and cancel():
        raise ProcessError("inspection cancelled")
    process = subprocess.Popen(argv, cwd=cwd, env=env, start_new_session=True,
        stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    selector = selectors.DefaultSelector()
    chunks = {"stdout": bytearray(), "stderr": bytearray()}
    total = 0
    written = 0
    deadline = time.monotonic() + timeout
    try:
        for name in chunks:
            stream = getattr(process, name)
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        if process.stdin is not None:
            if input_bytes:
                os.set_blocking(process.stdin.fileno(), False)
                selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
            else:
                process.stdin.close()
        while selector.get_map() or process.poll() is None:
            if cancel is not None and cancel():
                raise ProcessError("inspection cancelled")
            if time.monotonic() >= deadline:
                raise ProcessError("inspection timed out")
            if not selector.get_map():
                time.sleep(0.01)
                continue
            for key, _ in selector.select(timeout=min(0.05, max(0, deadline - time.monotonic()))):
                if key.data == "stdin":
                    try:
                        written += os.write(key.fileobj.fileno(), input_bytes[written:written + 4096])
                    except BrokenPipeError:
                        written = len(input_bytes)
                    except BlockingIOError:
                        continue
                    if written == len(input_bytes):
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                    continue
                try:
                    data = os.read(key.fileobj.fileno(), min(4096, max_output - total + 1))
                except BlockingIOError:
                    continue
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                total += len(data)
                if total > max_output:
                    raise ProcessError("inspection output limit exceeded")
                chunks[key.data].extend(data)
        return process.wait(timeout=max(0.001, deadline - time.monotonic())), bytes(chunks["stdout"]), bytes(chunks["stderr"])
    except subprocess.TimeoutExpired:
        raise ProcessError("inspection timed out") from None
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            raise ProcessError("inspection process did not stop") from None
        finally:
            selector.close()
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
