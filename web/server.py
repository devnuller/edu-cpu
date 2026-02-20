#!/usr/bin/env python3
"""Web server for the EDU-CPU CTF challenge."""

import sys
import os
import io

from flask import Flask, request, jsonify, render_template

# Import assembler and simulator from parent directory
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from assembler import Assembler, generate_lst  # noqa: E402
from simulator import CPU, parse_hex  # noqa: E402

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FLAG_HEX_DEFAULT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "ctf", "flag.hex"
)
FLAG_HEX_PATH = os.environ.get("FLAG_HEX", FLAG_HEX_DEFAULT)

MAX_CODE_LEN = 4096
MAX_CYCLES = 10000

# Load flag data once at startup
with open(FLAG_HEX_PATH) as f:
    FLAG_MAP = parse_hex(f.read())

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StdoutCapture:
    """Drop-in replacement for sys.stdout that captures I/O port writes."""

    def __init__(self):
        self.buffer = io.BytesIO()

    def write(self, s):
        # text writes (e.g. accidental print()) are silently dropped
        pass

    def flush(self):
        pass


def _adjust_line(msg):
    """Shift line numbers down by 1 to account for the prepended .ORG 0."""
    if not msg.startswith("Line "):
        return msg
    try:
        rest = msg[5:]
        num_str, tail = rest.split(":", 1)
        num = max(int(num_str) - 1, 1)
        return f"Line {num}:{tail}"
    except (ValueError, IndexError):
        return msg


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/run", methods=["POST"])
def api_run():
    data = request.get_json(force=True)
    code = data.get("code", "")
    trace = bool(data.get("trace", False))

    if len(code) > MAX_CODE_LEN:
        return jsonify(
            success=False,
            errors=[f"Source code exceeds {MAX_CODE_LEN} character limit"],
            listing="",
            stdout="",
            stderr="",
        )

    # Assemble (user code always starts at address 0)
    source = ".ORG 0\n" + code
    asm = Assembler()
    output, listing = asm.assemble(source)

    if asm.errors:
        errors = [_adjust_line(str(e)) for e in asm.errors]
        return jsonify(
            success=False, errors=errors, listing="", stdout="", stderr=""
        )

    lst_text = generate_lst(listing) if listing else ""

    # Reject code that overlaps with the flag region
    overlap = set(output.keys()) & set(FLAG_MAP.keys())
    if overlap:
        addrs = ", ".join(f"0x{a:02X}" for a in sorted(overlap)[:10])
        return jsonify(
            success=False,
            errors=[f"Code overlaps with reserved memory at: {addrs}"],
            listing=lst_text,
            stdout="",
            stderr="",
        )

    # Create CPU, load user code first, then flag data
    cpu = CPU()
    cpu.load_map(output)
    cpu.load_map(FLAG_MAP)

    # Run with captured I/O
    cap_out = _StdoutCapture()
    cap_err = io.StringIO()
    saved_out, saved_err = sys.stdout, sys.stderr
    try:
        sys.stdout = cap_out
        sys.stderr = cap_err
        exit_code = cpu.run(trace=trace, max_cycles=MAX_CYCLES)
    finally:
        sys.stdout, sys.stderr = saved_out, saved_err

    return jsonify(
        success=True,
        errors=[],
        listing=lst_text,
        stdout=cap_out.buffer.getvalue().decode("latin-1"),
        stderr=cap_err.getvalue(),
        exit_code=exit_code,
        cycles=cpu.cycles,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
