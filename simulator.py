#!/usr/bin/env python3
"""EDU-CPU Simulator — executes binary images for the EDU-CPU 8-bit processor."""

import sys
import os
import argparse

# ---------------------------------------------------------------------------
# Instruction decode tables
# ---------------------------------------------------------------------------

# LD/ST IIIII codes -> (mnemonic, primary register)
LD_OPCODES = {
    0b00000: ("LD",  "A"),
    0b00001: ("LD",  "R0"),
    0b00010: ("LD",  "R1"),
}

ST_OPCODES = {
    0b00011: ("ST",  "A"),
    0b00100: ("ST",  "R0"),
    0b00101: ("ST",  "R1"),
}

ALU_OPCODES = {
    0b00110: "ADD",
    0b00111: "SUB",
    0b01000: "AND",
    0b01001: "OR",
    0b01010: "XOR",
    0b01011: "CMP",
}

BRANCH_CONDITION = {
    0x68: ("BZ",  lambda z, c: z),
    0x69: ("BNZ", lambda z, c: not z),
    0x6A: ("BC",  lambda z, c: c),
    0x6B: ("BNC", lambda z, c: not c),
}

# Register mode R-bit mapping: for each primary register, R=0 and R=1
# select the "other two" registers.
#   primary_reg -> {0: reg_name, 1: reg_name}
REG_MODE_MAP = {
    "A":  {0: "R0", 1: "R1"},
    "R0": {0: "A",  1: "R1"},
    "R1": {0: "A",  1: "R0"},
}

# PUSH/POP/INC/DEC register encoding (bits 1-0)
REG_ENCODING = {0: "A", 1: "R0", 2: "R1"}

IO_ADDR = 0xFF
STACK_DEPTH = 4

# ---------------------------------------------------------------------------
# File format parsers — return {address: byte} dicts
# ---------------------------------------------------------------------------

def parse_bin(data):
    """Parse a raw binary image. Returns {addr: byte}."""
    return {i: b for i, b in enumerate(data) if i < 256}


def parse_hex(text):
    """Parse Intel HEX format. Returns {addr: byte}."""
    result = {}
    for line_num, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if not line.startswith(":"):
            raise ValueError(
                f"Intel HEX line {line_num}: missing start code ':'")
        raw = bytes.fromhex(line[1:])
        if len(raw) < 5:
            raise ValueError(
                f"Intel HEX line {line_num}: record too short")
        byte_count = raw[0]
        addr = (raw[1] << 8) | raw[2]
        rec_type = raw[3]
        data = raw[4:-1]
        checksum = raw[-1]
        calc = (~sum(raw[:-1]) + 1) & 0xFF
        if calc != checksum:
            raise ValueError(
                f"Intel HEX line {line_num}: checksum mismatch "
                f"(expected {calc:02X}, got {checksum:02X})")
        if len(data) != byte_count:
            raise ValueError(
                f"Intel HEX line {line_num}: byte count mismatch")
        if rec_type == 0x01:  # EOF
            break
        if rec_type == 0x00:  # Data
            for i, b in enumerate(data):
                a = addr + i
                if a < 256:
                    result[a] = b
    return result


def parse_srec(text):
    """Parse Motorola S-record format. Returns {addr: byte}."""
    result = {}
    for line_num, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if not line.startswith("S"):
            raise ValueError(
                f"SREC line {line_num}: missing 'S' prefix")
        rec_type = line[1]
        raw = bytes.fromhex(line[2:])
        if len(raw) < 1:
            raise ValueError(
                f"SREC line {line_num}: record too short")
        byte_count = raw[0]
        if len(raw) != byte_count + 1:
            raise ValueError(
                f"SREC line {line_num}: byte count mismatch")
        calc = (~sum(raw[:-1])) & 0xFF
        if calc != raw[-1]:
            raise ValueError(
                f"SREC line {line_num}: checksum mismatch "
                f"(expected {calc:02X}, got {raw[-1]:02X})")
        if rec_type == "0":  # Header
            continue
        elif rec_type == "1":  # Data with 16-bit address
            addr = (raw[1] << 8) | raw[2]
            data = raw[3:-1]
            for i, b in enumerate(data):
                a = addr + i
                if a < 256:
                    result[a] = b
        elif rec_type == "9":  # End record
            break
    return result


# ---------------------------------------------------------------------------
# CPU state
# ---------------------------------------------------------------------------

class CPU:
    def __init__(self):
        self.a = 0       # accumulator
        self.r = [0, 0]  # R0, R1
        self.pc = 0      # program counter
        self.z = False   # zero flag
        self.c = False   # carry flag
        self.sp = 0      # stack pointer (0..3)
        self.stack = [0] * STACK_DEPTH
        self.mem = bytearray(256)
        self.loaded = set()  # addresses that contain loaded program data
        self.halted = False
        self.cycles = 0

    def _get_reg(self, name):
        """Read a register by name."""
        if name == "A":
            return self.a
        elif name == "R0":
            return self.r[0]
        elif name == "R1":
            return self.r[1]

    def _set_reg(self, name, val):
        """Write a register by name."""
        val &= 0xFF
        if name == "A":
            self.a = val
        elif name == "R0":
            self.r[0] = val
        elif name == "R1":
            self.r[1] = val

    def load_map(self, addr_map):
        """Apply an address->byte map to memory."""
        for addr, val in addr_map.items():
            if addr < 256:
                self.mem[addr] = val
                self.loaded.add(addr)

    def load_bin(self, data):
        self.load_map(parse_bin(data))

    def load_hex(self, text):
        self.load_map(parse_hex(text))

    def load_srec(self, text):
        self.load_map(parse_srec(text))

    def fetch(self):
        val = self.mem[self.pc]
        self.pc = (self.pc + 1) & 0xFF
        return val

    def mem_read(self, addr):
        return self.mem[addr & 0xFF]

    def mem_write(self, addr, val):
        addr &= 0xFF
        val &= 0xFF
        self.mem[addr] = val
        if addr == IO_ADDR:
            sys.stdout.buffer.write(bytes([val]))
            sys.stdout.buffer.flush()

    def push(self, val):
        if self.sp >= STACK_DEPTH:
            raise RuntimeError(f"Stack overflow (SP={self.sp})")
        self.stack[self.sp] = val & 0xFF
        self.sp += 1

    def pop(self):
        if self.sp <= 0:
            raise RuntimeError(f"Stack underflow (SP={self.sp})")
        self.sp -= 1
        return self.stack[self.sp]

    def set_zc(self, result):
        """Set Z and C flags from a 9-bit result (bit 8 = carry)."""
        val8 = result & 0xFF
        self.z = (val8 == 0)
        self.c = bool(result & 0x100)

    def set_z_only(self, val):
        """Set Z flag only (INC/DEC)."""
        self.z = ((val & 0xFF) == 0)

    def set_z_clear_c(self, val):
        """Set Z flag, clear C (logic ops)."""
        self.z = ((val & 0xFF) == 0)
        self.c = False

    # -------------------------------------------------------------------
    # Resolve source value based on addressing mode
    # -------------------------------------------------------------------
    def resolve_source(self, mm, r_bit, primary_reg):
        """Fetch the source value based on addressing mode.

        For register mode, primary_reg determines which two registers
        the R bit selects from.
        """
        if mm == 0b00:  # immediate
            return self.fetch()
        elif mm == 0b01:  # register
            src_reg = REG_MODE_MAP[primary_reg][r_bit]
            return self._get_reg(src_reg)
        elif mm == 0b10:  # direct
            addr = self.fetch()
            return self.mem_read(addr)
        elif mm == 0b11:  # indexed
            offset = self.fetch()
            addr = (self.r[r_bit] + offset) & 0xFF
            return self.mem_read(addr)

    def resolve_dest(self, mm, r_bit, primary_reg, value):
        """Write value to the destination based on addressing mode.

        For register mode, primary_reg determines which two registers
        the R bit selects from. For memory modes, writes to memory.
        """
        if mm == 0b00:  # immediate — invalid for ST
            raise RuntimeError("ST with immediate mode is invalid")
        elif mm == 0b01:  # register
            dst_reg = REG_MODE_MAP[primary_reg][r_bit]
            self._set_reg(dst_reg, value)
        elif mm == 0b10:  # direct
            addr = self.fetch()
            self.mem_write(addr, value)
        elif mm == 0b11:  # indexed
            offset = self.fetch()
            addr = (self.r[r_bit] + offset) & 0xFF
            self.mem_write(addr, value)

    # -------------------------------------------------------------------
    # Execute one instruction
    # -------------------------------------------------------------------
    def step(self, trace=False):
        if self.halted:
            return False

        if self.pc not in self.loaded:
            raise RuntimeError(
                f"PC entered unloaded memory at address 0x{self.pc:02X}")

        pc_before = self.pc
        opcode = self.fetch()

        iiiii = (opcode >> 3) & 0x1F
        r_bit = (opcode >> 2) & 1
        mm = opcode & 0x03

        if trace:
            self._trace(pc_before, opcode)

        # --- LD instructions ---
        if iiiii in LD_OPCODES:
            _, primary_reg = LD_OPCODES[iiiii]
            value = self.resolve_source(mm, r_bit, primary_reg)
            self._set_reg(primary_reg, value)

        # --- ST instructions ---
        elif iiiii in ST_OPCODES:
            _, primary_reg = ST_OPCODES[iiiii]
            value = self._get_reg(primary_reg)
            self.resolve_dest(mm, r_bit, primary_reg, value)

        # --- ALU instructions ---
        elif iiiii in ALU_OPCODES:
            mnemonic = ALU_OPCODES[iiiii]
            src = self.resolve_source(mm, r_bit, "A")

            if mnemonic == "ADD":
                result = self.a + src
                self.set_zc(result)
                self.a = result & 0xFF

            elif mnemonic == "SUB":
                # 6502 convention: C=1 if no borrow (A >= src)
                self.c = (self.a >= src)
                self.a = (self.a - src) & 0xFF
                self.z = (self.a == 0)

            elif mnemonic == "AND":
                self.a = self.a & src
                self.set_z_clear_c(self.a)

            elif mnemonic == "OR":
                self.a = self.a | src
                self.set_z_clear_c(self.a)

            elif mnemonic == "XOR":
                self.a = self.a ^ src
                self.set_z_clear_c(self.a)

            elif mnemonic == "CMP":
                result = self.a - src
                self.c = (self.a >= src)
                self.z = ((result & 0xFF) == 0)

        # --- JMP ---
        elif opcode == 0x60:
            addr = self.fetch()
            self.pc = addr

        # --- Conditional branches ---
        elif opcode in BRANCH_CONDITION:
            disp_byte = self.fetch()
            # Signed displacement
            disp = disp_byte if disp_byte < 128 else disp_byte - 256
            _, cond_fn = BRANCH_CONDITION[opcode]
            if cond_fn(self.z, self.c):
                self.pc = (self.pc + disp) & 0xFF

        # --- CALL ---
        elif opcode == 0x70:
            addr = self.fetch()
            self.push(self.pc)  # return address (already past operand)
            self.pc = addr

        # --- RET ---
        elif opcode == 0x78:
            self.pc = self.pop()

        # --- PUSH ---
        elif iiiii == 0b10000:  # PUSH group
            reg_code = mm  # bits 1-0
            if reg_code in REG_ENCODING:
                reg_name = REG_ENCODING[reg_code]
                self.push(self._get_reg(reg_name))
            else:
                raise RuntimeError(
                    f"Invalid PUSH encoding 0x{opcode:02X} "
                    f"at address 0x{pc_before:02X}")

        # --- POP ---
        elif iiiii == 0b10001:  # POP group
            reg_code = mm  # bits 1-0
            if reg_code in REG_ENCODING:
                reg_name = REG_ENCODING[reg_code]
                self._set_reg(reg_name, self.pop())
            else:
                raise RuntimeError(
                    f"Invalid POP encoding 0x{opcode:02X} "
                    f"at address 0x{pc_before:02X}")

        # --- INC ---
        elif iiiii == 0b10010:  # INC group
            reg_code = mm
            if reg_code in REG_ENCODING:
                reg_name = REG_ENCODING[reg_code]
                val = (self._get_reg(reg_name) + 1) & 0xFF
                self._set_reg(reg_name, val)
                self.set_z_only(val)
            else:
                raise RuntimeError(
                    f"Invalid INC encoding 0x{opcode:02X} "
                    f"at address 0x{pc_before:02X}")

        # --- DEC ---
        elif iiiii == 0b10011:  # DEC group
            reg_code = mm
            if reg_code in REG_ENCODING:
                reg_name = REG_ENCODING[reg_code]
                val = (self._get_reg(reg_name) - 1) & 0xFF
                self._set_reg(reg_name, val)
                self.set_z_only(val)
            else:
                raise RuntimeError(
                    f"Invalid DEC encoding 0x{opcode:02X} "
                    f"at address 0x{pc_before:02X}")

        # --- NOP ---
        elif opcode == 0xA0:
            pass

        # --- HLT ---
        elif opcode == 0xA8:
            self.halted = True

        else:
            raise RuntimeError(
                f"Invalid opcode 0x{opcode:02X} "
                f"at address 0x{pc_before:02X}")

        self.cycles += 1
        return not self.halted

    def _trace(self, pc, opcode):
        flags = ""
        flags += "Z" if self.z else "."
        flags += "C" if self.c else "."
        print(
            f"  PC={pc:02X} OP={opcode:02X}  "
            f"A={self.a:02X} R0={self.r[0]:02X} R1={self.r[1]:02X}  "
            f"SP={self.sp} [{flags}]",
            file=sys.stderr,
        )

    def run(self, trace=False, max_cycles=65536):
        while self.cycles < max_cycles:
            try:
                if not self.step(trace=trace):
                    break
            except RuntimeError as e:
                print(f"\nRuntime error at cycle {self.cycles}: {e}",
                      file=sys.stderr)
                return 1

        if self.cycles >= max_cycles:
            print(f"\nExecution stopped: max cycles ({max_cycles}) reached",
                  file=sys.stderr)
            return 1

        if trace:
            print(f"\nHalted after {self.cycles} cycles.", file=sys.stderr)
        return 0

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def detect_format(path, data):
    """Detect file format from extension or content."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".hex":
        return "hex"
    if ext == ".srec":
        return "srec"
    if ext == ".bin":
        return "bin"
    # Fallback: inspect content
    try:
        text = data.decode("ascii").lstrip()
        if text.startswith(":"):
            return "hex"
        if text.startswith("S"):
            return "srec"
    except (UnicodeDecodeError, ValueError):
        pass
    return "bin"


def parse_file(path):
    """Read and parse a file, returning its address map."""
    with open(path, "rb") as f:
        data = f.read()
    fmt = detect_format(path, data)
    if fmt == "hex":
        return parse_hex(data.decode("ascii"))
    elif fmt == "srec":
        return parse_srec(data.decode("ascii"))
    else:
        return parse_bin(data)


def check_overlaps(file_maps):
    """Check for address overlaps between files.

    file_maps: list of (path, addr_map) tuples.
    Returns a list of error strings, empty if no overlaps.
    """
    # For each address, track which file(s) wrote to it
    addr_owners = {}  # addr -> list of filenames
    for path, addr_map in file_maps:
        for addr in addr_map:
            addr_owners.setdefault(addr, []).append(path)

    errors = []
    # Collect addresses that appear in more than one file
    conflicts = {a: owners for a, owners in addr_owners.items()
                 if len(owners) > 1}
    if not conflicts:
        return errors

    # Group by the same pair/set of conflicting files for a compact message
    groups = {}  # frozenset of filenames -> sorted list of addresses
    for addr in sorted(conflicts):
        key = frozenset(conflicts[addr])
        groups.setdefault(key, []).append(addr)

    for files, addrs in groups.items():
        names = " and ".join(sorted(files))
        if len(addrs) <= 8:
            addr_str = ", ".join(f"0x{a:02X}" for a in addrs)
        else:
            shown = ", ".join(f"0x{a:02X}" for a in addrs[:8])
            addr_str = f"{shown}, ... ({len(addrs)} addresses total)"
        errors.append(f"Overlap between {names} at {addr_str}")

    return errors


def main():
    parser = argparse.ArgumentParser(description="EDU-CPU Simulator")
    parser.add_argument("programs", nargs="+",
                        help="Program files to load (.bin, .hex, or .srec)")
    parser.add_argument("--trace", action="store_true",
                        help="Print CPU state before each instruction")
    parser.add_argument("--max-cycles", type=int, default=65536,
                        help="Maximum number of cycles (default: 65536)")
    args = parser.parse_args()

    # Parse all files
    file_maps = []
    for path in args.programs:
        fmt = detect_format(path, b"")
        if len(args.programs) > 1 and fmt == "bin":
            print(f"ERROR: raw binary format ({path}) cannot be used "
                  f"when loading multiple files — use .hex or .srec",
                  file=sys.stderr)
            sys.exit(1)
        file_maps.append((path, parse_file(path)))

    # Check for overlaps between files
    if len(file_maps) > 1:
        errors = check_overlaps(file_maps)
        if errors:
            for err in errors:
                print(f"ERROR: {err}", file=sys.stderr)
            sys.exit(1)

    # Load all into CPU
    cpu = CPU()
    for _, addr_map in file_maps:
        cpu.load_map(addr_map)

    rc = cpu.run(trace=args.trace, max_cycles=args.max_cycles)
    sys.exit(rc)


if __name__ == "__main__":
    main()
