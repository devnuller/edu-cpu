#!/usr/bin/env python3
"""EDU-CPU Assembler — two-pass assembler for the EDU-CPU 8-bit processor."""

import sys
import os
import re

# ---------------------------------------------------------------------------
# Instruction encoding tables
# ---------------------------------------------------------------------------

# LD instruction IIIII codes, keyed by destination register.
LD_CODES = {"A": 0b00000, "R0": 0b00001, "R1": 0b00010}

# ST instruction IIIII codes, keyed by source register.
ST_CODES = {"A": 0b00011, "R0": 0b00100, "R1": 0b00101}

# ALU instructions that use addressing modes (A is implicit accumulator).
# Maps mnemonic -> IIIII (bits 7-3 before shifting).
ALU_INSTRUCTIONS = {
    "ADD": 0b00110,
    "SUB": 0b00111,
    "AND": 0b01000,
    "OR":  0b01001,
    "XOR": 0b01010,
    "CMP": 0b01011,
}

# Register mode R-bit mapping.
# In register mode (MM=01), the R bit selects from the two registers that
# are NOT the instruction's primary register.
#   (primary_reg, other_reg) -> R bit value
REG_MODE_R_BIT = {
    ("A",  "R0"): 0,  ("A",  "R1"): 1,
    ("R0", "A"):  0,  ("R0", "R1"): 1,
    ("R1", "A"):  0,  ("R1", "R0"): 1,
}

# Fixed-encoding instructions (no addressing mode field).
FIXED_OPCODES = {
    "JMP":     0x60,
    "BZ":      0x68,
    "BNZ":     0x69,
    "BC":      0x6A,
    "BNC":     0x6B,
    "CALL":    0x70,
    "RET":     0x78,
    "PUSH A":  0x80,
    "PUSH R0": 0x81,
    "PUSH R1": 0x82,
    "POP A":   0x88,
    "POP R0":  0x89,
    "POP R1":  0x8A,
    "INC A":   0x90,
    "INC R0":  0x91,
    "INC R1":  0x92,
    "DEC A":   0x98,
    "DEC R0":  0x99,
    "DEC R1":  0x9A,
    "NOP":     0xA0,
    "HLT":     0xA8,
}

# Instructions that take no operand byte at all.
NO_OPERAND = {"RET", "PUSH A", "PUSH R0", "PUSH R1",
              "POP A", "POP R0", "POP R1",
              "INC A", "INC R0", "INC R1",
              "DEC A", "DEC R0", "DEC R1",
              "NOP", "HLT"}

# Branch instructions (need signed displacement).
BRANCH_INSTRUCTIONS = {"BZ", "BNZ", "BC", "BNC"}

# Register names (for detection).
REGISTER_NAMES = {"A", "R0", "R1"}

# ---------------------------------------------------------------------------
# Number parsing
# ---------------------------------------------------------------------------

ESCAPE_MAP = {
    "n": 0x0A,   # newline
    "t": 0x09,   # tab
    "r": 0x0D,   # carriage return
    "0": 0x00,   # null
    "\\": 0x5C,  # backslash
}


def decode_string(s):
    """Decode escape sequences in a string, return list of byte values."""
    result = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            ch = s[i + 1]
            if ch in ESCAPE_MAP:
                result.append(ESCAPE_MAP[ch])
                i += 2
                continue
            raise ValueError(f"Unknown escape sequence '\\{ch}'")
        if ord(s[i]) > 0x7F:
            raise ValueError(
                f"Non-ASCII character '{s[i]}' (0x{ord(s[i]):02X})")
        result.append(ord(s[i]))
        i += 1
    return result


def parse_number(s, symbols=None):
    """Parse a number literal or symbol name, return integer value."""
    s = s.strip()
    if symbols and s in symbols:
        return symbols[s]
    if s.startswith("0x") or s.startswith("0X"):
        return int(s, 16)
    if s.startswith("0b") or s.startswith("0B"):
        return int(s, 2)
    try:
        return int(s)
    except ValueError:
        return None

# ---------------------------------------------------------------------------
# Operand parsing
# ---------------------------------------------------------------------------

# Regex for indexed addressing: [R0+5], [R1+0x10], [R0], [R1]
RE_INDEXED = re.compile(
    r"^\[\s*(R[01])\s*(?:\+\s*(.+?))?\s*\]$", re.IGNORECASE)

# Regex for direct addressing: [addr] or [symbol]
RE_DIRECT = re.compile(r"^\[\s*(.+?)\s*\]$")

# Regex for immediate: #value or #symbol
RE_IMMEDIATE = re.compile(r"^#\s*(.+)$")


def parse_operand(text, symbols=None):
    """Parse an operand string and return (mode, reg_name, value).

    mode:     "imm", "reg", "direct", "indexed", "value"
    reg_name: register name for register/indexed modes, None otherwise
    value:    integer or symbol name (string) if not yet resolved
    """
    text = text.strip()

    # Register mode: A, R0, R1
    upper = text.upper()
    if upper in REGISTER_NAMES:
        return ("reg", upper, None)

    # Indexed: [Rn+offset] or [Rn]
    m = RE_INDEXED.match(text)
    if m:
        reg = m.group(1).upper()
        if m.group(2) is not None:
            val = parse_number(m.group(2), symbols)
            if val is None:
                return ("indexed", reg, m.group(2))  # unresolved symbol
            return ("indexed", reg, val)
        return ("indexed", reg, 0)

    # Direct: [addr]
    m = RE_DIRECT.match(text)
    if m:
        val = parse_number(m.group(1), symbols)
        if val is None:
            return ("direct", None, m.group(1))  # unresolved symbol
        return ("direct", None, val)

    # Immediate: #value
    m = RE_IMMEDIATE.match(text)
    if m:
        val = parse_number(m.group(1), symbols)
        if val is None:
            return ("imm", None, m.group(1))  # unresolved symbol
        return ("imm", None, val)

    # Bare symbol or number (used by JMP, CALL, branches)
    val = parse_number(text, symbols)
    if val is not None:
        return ("value", None, val)
    return ("value", None, text)  # unresolved symbol

# ---------------------------------------------------------------------------
# Encoding functions
# ---------------------------------------------------------------------------

def encode_ld_st(is_store, primary_reg, mode, other_reg, value):
    """Encode an LD or ST instruction. Returns (opcode, operand|None).

    is_store:    True for ST, False for LD
    primary_reg: "A", "R0", or "R1"
    mode:        "imm", "reg", "direct", "indexed"
    other_reg:   register name for register/indexed modes
    value:       operand value for imm/direct/indexed
    """
    iiiii = ST_CODES[primary_reg] if is_store else LD_CODES[primary_reg]

    if mode == "imm":
        if is_store:
            raise ValueError("ST does not support immediate addressing mode")
        opcode = (iiiii << 3) | 0b000  # R=0, MM=00
        return (opcode, value & 0xFF)

    elif mode == "reg":
        key = (primary_reg, other_reg)
        if key not in REG_MODE_R_BIT:
            kind = "ST" if is_store else "LD"
            raise ValueError(
                f"Cannot use {other_reg} with {kind} {primary_reg} "
                f"in register mode")
        r_bit = REG_MODE_R_BIT[key]
        opcode = (iiiii << 3) | (r_bit << 2) | 0b01  # MM=01
        return (opcode, None)

    elif mode == "direct":
        opcode = (iiiii << 3) | 0b010  # R=0, MM=10
        return (opcode, value & 0xFF)

    elif mode == "indexed":
        r_bit = 0 if other_reg == "R0" else 1
        opcode = (iiiii << 3) | (r_bit << 2) | 0b11  # MM=11
        return (opcode, value & 0xFF)

    else:
        raise ValueError(f"Invalid addressing mode '{mode}'")


def encode_alu(mnemonic, mode, reg, value):
    """Encode an ALU instruction. Returns (opcode, operand|None).

    For ALU ops, A is always the implicit accumulator.
    In register mode, only R0 and R1 are valid sources.
    """
    iiiii = ALU_INSTRUCTIONS[mnemonic]

    if mode == "imm":
        opcode = (iiiii << 3) | 0b000  # R=0, MM=00
        return (opcode, value & 0xFF)

    elif mode == "reg":
        if reg not in ("R0", "R1"):
            raise ValueError(
                f"{mnemonic} only accepts R0 or R1 in register mode, "
                f"not {reg}")
        r_bit = 0 if reg == "R0" else 1
        opcode = (iiiii << 3) | (r_bit << 2) | 0b01  # MM=01
        return (opcode, None)

    elif mode == "direct":
        opcode = (iiiii << 3) | 0b010  # R=0, MM=10
        return (opcode, value & 0xFF)

    elif mode == "indexed":
        r_bit = 0 if reg == "R0" else 1
        opcode = (iiiii << 3) | (r_bit << 2) | 0b11  # MM=11
        return (opcode, value & 0xFF)

    else:
        raise ValueError(f"Invalid addressing mode '{mode}' for {mnemonic}")

# ---------------------------------------------------------------------------
# Line parsing
# ---------------------------------------------------------------------------

def strip_comment(line):
    """Remove comment from line, respecting that ; starts a comment."""
    idx = line.find(";")
    if idx >= 0:
        return line[:idx]
    return line


def parse_line(raw_line):
    """Parse a source line into (label, mnemonic, operand_text).

    All can be None if the line is empty/comment-only.
    """
    line = strip_comment(raw_line).strip()
    if not line:
        return (None, None, None)

    label = None
    # Check for label
    m = re.match(r"^([A-Za-z_]\w*)\s*:", line)
    if m:
        label = m.group(1)
        line = line[m.end():].strip()

    if not line:
        return (label, None, None)

    # Split mnemonic from operand
    parts = line.split(None, 1)
    mnemonic = parts[0].upper()
    operand_text = parts[1].strip() if len(parts) > 1 else None

    return (label, mnemonic, operand_text)

# ---------------------------------------------------------------------------
# Assembler
# ---------------------------------------------------------------------------

class AssemblerError(Exception):
    def __init__(self, line_num, message):
        self.line_num = line_num
        super().__init__(f"Line {line_num}: {message}")


class Assembler:
    def __init__(self):
        self.symbols = {}   # name -> value
        self.pc = 0
        self.errors = []

    def error(self, line_num, msg):
        self.errors.append(AssemblerError(line_num, msg))

    def resolve(self, value_or_sym, line_num):
        """Resolve a value that might be a symbol name."""
        if isinstance(value_or_sym, str):
            if value_or_sym in self.symbols:
                return self.symbols[value_or_sym]
            self.error(line_num, f"Undefined symbol '{value_or_sym}'")
            return 0
        return value_or_sym

    def _parse_ld_st_operand(self, operand_text):
        """Split LD/ST operand into (register, source/dest text).

        E.g. "A, #5" -> ("A", "#5"), "R0, [0x50]" -> ("R0", "[0x50]")
        """
        if operand_text is None:
            return (None, None)
        parts = operand_text.split(",", 1)
        if len(parts) < 2:
            return (parts[0].strip().upper(), None)
        return (parts[0].strip().upper(), parts[1].strip())

    def _operand_size(self, operand_text):
        """Return 1 if register mode (no operand byte), else 2."""
        if operand_text is None:
            return 1
        mode, _, _ = parse_operand(operand_text)
        return 1 if mode == "reg" else 2

    def instruction_size(self, mnemonic, operand_text):
        """Return the number of bytes this instruction will occupy."""

        # Directives
        if mnemonic == ".ORG":
            return 0
        if mnemonic == ".EQU":
            return 0
        if mnemonic == ".DB":
            if operand_text:
                items = [x.strip() for x in operand_text.split(",")]
                count = 0
                for item in items:
                    if item.startswith('"') or item.startswith("'"):
                        s = item.strip("\"'")
                        count += len(s)
                    else:
                        count += 1
                return count
            return 0
        if mnemonic == ".DS":
            if operand_text:
                s = operand_text.strip()
                if (s.startswith('"') and s.endswith('"')) or \
                   (s.startswith("'") and s.endswith("'")):
                    return len(decode_string(s[1:-1])) + 1  # +1 for null
                return 1  # error will be caught in pass 2
            return 1

        # LD / ST — two-operand
        if mnemonic in ("LD", "ST"):
            reg, src_text = self._parse_ld_st_operand(operand_text)
            if src_text is None:
                return 1  # error will be caught later
            return self._operand_size(src_text)

        # Compound fixed instructions (PUSH/POP/INC/DEC with register operand)
        if operand_text:
            combined = f"{mnemonic} {operand_text.strip().upper()}"
            if combined in FIXED_OPCODES:
                return 1  # all compound fixed are 1 byte

        # Simple fixed instructions
        if mnemonic in FIXED_OPCODES:
            if mnemonic in NO_OPERAND:
                return 1
            return 2  # JMP, CALL, branches

        # ALU instructions
        if mnemonic in ALU_INSTRUCTIONS:
            if operand_text is None:
                return 1  # error will be caught later
            return self._operand_size(operand_text)

        return 1  # unknown — will error in pass 2

    # -------------------------------------------------------------------
    # Pass 1: build symbol table
    # -------------------------------------------------------------------
    def pass1(self, lines):
        self.pc = 0
        for line_num, raw_line in enumerate(lines, 1):
            label, mnemonic, operand_text = parse_line(raw_line)

            if label:
                if label in self.symbols:
                    self.error(line_num, f"Duplicate label '{label}'")
                else:
                    self.symbols[label] = self.pc

            if mnemonic is None:
                continue

            if mnemonic == ".ORG":
                val = parse_number(operand_text, self.symbols) if operand_text else None
                if val is None:
                    self.error(line_num, "Invalid .ORG address")
                else:
                    self.pc = val
                continue

            if mnemonic == ".EQU":
                if operand_text:
                    parts = [x.strip() for x in operand_text.split(",", 1)]
                    if len(parts) == 2:
                        name = parts[0]
                        val = parse_number(parts[1], self.symbols)
                        if val is None:
                            self.error(line_num,
                                       f"Invalid .EQU value '{parts[1]}'")
                        else:
                            self.symbols[name] = val
                    else:
                        self.error(line_num,
                                   "Invalid .EQU syntax "
                                   "(expected: .EQU name, value)")
                continue

            size = self.instruction_size(mnemonic, operand_text)
            self.pc += size

    # -------------------------------------------------------------------
    # Pass 2: generate machine code
    # -------------------------------------------------------------------
    def pass2(self, lines):
        self.pc = 0
        output = {}    # address -> byte
        listing = []   # (address, bytes, raw_source_line)

        for line_num, raw_line in enumerate(lines, 1):
            label, mnemonic, operand_text = parse_line(raw_line)

            if mnemonic is None:
                listing.append((None, [], raw_line))
                continue

            if mnemonic == ".ORG":
                val = parse_number(operand_text, self.symbols) \
                    if operand_text else 0
                if val is not None:
                    self.pc = val
                listing.append((self.pc, [], raw_line))
                continue

            if mnemonic == ".EQU":
                listing.append((None, [], raw_line))
                continue

            start_pc = self.pc
            emitted = []

            if mnemonic == ".DB":
                if operand_text:
                    items = [x.strip() for x in operand_text.split(",")]
                    for item in items:
                        if item.startswith('"') or item.startswith("'"):
                            s = item.strip("\"'")
                            for ch in s:
                                emitted.append(ord(ch))
                        else:
                            val = parse_number(item, self.symbols)
                            if val is None:
                                val = self.resolve(item, line_num)
                            emitted.append(val & 0xFF)

            elif mnemonic == ".DS":
                if operand_text:
                    s = operand_text.strip()
                    if (s.startswith('"') and s.endswith('"')) or \
                       (s.startswith("'") and s.endswith("'")):
                        try:
                            emitted.extend(decode_string(s[1:-1]))
                        except ValueError as e:
                            self.error(line_num, str(e))
                    else:
                        self.error(line_num,
                                   ".DS requires a quoted string")
                else:
                    self.error(line_num, ".DS requires a quoted string")
                emitted.append(0x00)  # null terminator

            # --- LD / ST (two-operand) ---
            elif mnemonic in ("LD", "ST"):
                is_store = (mnemonic == "ST")
                reg, src_text = self._parse_ld_st_operand(operand_text)

                if reg not in REGISTER_NAMES:
                    self.error(line_num,
                               f"{mnemonic} requires A, R0, or R1 as "
                               f"first operand, got '{reg}'")
                    emitted.append(0)
                elif src_text is None:
                    self.error(line_num,
                               f"{mnemonic} {reg} requires a second operand")
                    emitted.append(0)
                else:
                    mode, other_reg, val = parse_operand(
                        src_text, self.symbols)
                    # Resolve "value" mode as immediate for LD,
                    # or as direct for ST
                    if mode == "value":
                        if is_store:
                            mode = "direct"
                        else:
                            mode = "imm"
                    if val is not None and isinstance(val, str):
                        val = self.resolve(val, line_num)
                    try:
                        opcode, operand = encode_ld_st(
                            is_store, reg, mode, other_reg,
                            val if val is not None else 0)
                        emitted.append(opcode)
                        if operand is not None:
                            emitted.append(operand)
                    except ValueError as e:
                        self.error(line_num, str(e))
                        emitted.append(0)

            # --- Compound fixed (PUSH/POP/INC/DEC reg) ---
            elif operand_text and \
                    f"{mnemonic} {operand_text.strip().upper()}" \
                    in FIXED_OPCODES:
                combined = f"{mnemonic} {operand_text.strip().upper()}"
                emitted.append(FIXED_OPCODES[combined])

            # --- Simple fixed: no-operand ---
            elif mnemonic in NO_OPERAND and mnemonic in FIXED_OPCODES:
                emitted.append(FIXED_OPCODES[mnemonic])

            # --- JMP / CALL ---
            elif mnemonic in ("JMP", "CALL"):
                opcode = FIXED_OPCODES[mnemonic]
                emitted.append(opcode)
                if operand_text is None:
                    self.error(line_num, f"{mnemonic} requires an address")
                    emitted.append(0)
                else:
                    parsed = parse_operand(operand_text, self.symbols)
                    val = self.resolve(parsed[2], line_num)
                    emitted.append(val & 0xFF)

            # --- Branches ---
            elif mnemonic in BRANCH_INSTRUCTIONS:
                opcode = FIXED_OPCODES[mnemonic]
                emitted.append(opcode)
                if operand_text is None:
                    self.error(line_num, f"{mnemonic} requires a target")
                    emitted.append(0)
                else:
                    parsed = parse_operand(operand_text, self.symbols)
                    target = self.resolve(parsed[2], line_num)
                    # PC after this instruction = start_pc + 2
                    disp = target - (start_pc + 2)
                    if disp < -128 or disp > 127:
                        self.error(
                            line_num,
                            f"Branch displacement {disp} out of range "
                            f"(-128..+127)")
                        disp = 0
                    emitted.append(disp & 0xFF)  # two's complement

            # --- ALU instructions ---
            elif mnemonic in ALU_INSTRUCTIONS:
                if operand_text is None:
                    self.error(line_num,
                               f"{mnemonic} requires an operand")
                    emitted.append(0)
                else:
                    mode, reg, val = parse_operand(
                        operand_text, self.symbols)
                    if mode == "value":
                        # Bare number/symbol — treat as immediate
                        mode = "imm"
                    if val is not None and isinstance(val, str):
                        val = self.resolve(val, line_num)
                    try:
                        opcode, operand = encode_alu(
                            mnemonic, mode, reg,
                            val if val is not None else 0)
                        emitted.append(opcode)
                        if operand is not None:
                            emitted.append(operand)
                    except ValueError as e:
                        self.error(line_num, str(e))
                        emitted.append(0)

            else:
                self.error(line_num,
                           f"Unknown instruction '{mnemonic}'")
                emitted.append(0)

            # Write emitted bytes to output
            for i, b in enumerate(emitted):
                addr = start_pc + i
                if addr > 0xFF:
                    self.error(line_num,
                               f"Address 0x{addr:02X} exceeds memory")
                    break
                output[addr] = b

            listing.append((start_pc, emitted, raw_line))
            self.pc = start_pc + len(emitted)

        return output, listing

    # -------------------------------------------------------------------
    # Main assemble entry point
    # -------------------------------------------------------------------
    def assemble(self, source_text):
        lines = source_text.splitlines()
        self.pass1(lines)
        if self.errors:
            return None, None
        output, listing = self.pass2(lines)
        return output, listing

# ---------------------------------------------------------------------------
# Output generation
# ---------------------------------------------------------------------------

def generate_bin(output):
    """Generate a raw binary image from the output dict (addr -> byte)."""
    if not output:
        return bytes()
    max_addr = max(output.keys())
    buf = bytearray(max_addr + 1)
    for addr, val in output.items():
        buf[addr] = val
    return bytes(buf)


def generate_hex(output):
    """Generate Intel HEX format from the output dict (addr -> byte)."""
    if not output:
        return ":00000001FF\n"
    lines = []
    # Collect addresses in order, emit up to 16 bytes per record
    addrs = sorted(output.keys())
    i = 0
    while i < len(addrs):
        base = addrs[i]
        data = []
        # Gather contiguous bytes, up to 16 per record
        while i < len(addrs) and addrs[i] == base + len(data) and len(data) < 16:
            data.append(output[addrs[i]])
            i += 1
        # Data record: :LLAAAATT[DD...]CC
        length = len(data)
        addr_hi = (base >> 8) & 0xFF
        addr_lo = base & 0xFF
        record = [length, addr_hi, addr_lo, 0x00] + data
        checksum = (~sum(record) + 1) & 0xFF
        hex_str = "".join(f"{b:02X}" for b in record) + f"{checksum:02X}"
        lines.append(f":{hex_str}")
    # EOF record
    lines.append(":00000001FF")
    return "\n".join(lines) + "\n"


def generate_srec(output):
    """Generate Motorola S-record format from the output dict (addr -> byte)."""
    lines = []
    # S0 header record (optional, contains "EDU-CPU" as data)
    header_data = list(b"EDU-CPU")
    s0_count = 2 + 1 + len(header_data)  # addr(2) + data + checksum
    s0_bytes = [s0_count, 0x00, 0x00] + header_data
    s0_checksum = (~sum(s0_bytes)) & 0xFF
    lines.append("S0" + "".join(f"{b:02X}" for b in s0_bytes)
                  + f"{s0_checksum:02X}")

    if output:
        # S1 data records (16-bit address)
        addrs = sorted(output.keys())
        i = 0
        while i < len(addrs):
            base = addrs[i]
            data = []
            while (i < len(addrs) and addrs[i] == base + len(data)
                   and len(data) < 16):
                data.append(output[addrs[i]])
                i += 1
            # byte count = addr(2) + data + checksum(1)
            count = 2 + len(data) + 1
            addr_hi = (base >> 8) & 0xFF
            addr_lo = base & 0xFF
            rec_bytes = [count, addr_hi, addr_lo] + data
            checksum = (~sum(rec_bytes)) & 0xFF
            lines.append("S1" + "".join(f"{b:02X}" for b in rec_bytes)
                          + f"{checksum:02X}")

    # S9 end record (start address 0x0000)
    s9_bytes = [0x03, 0x00, 0x00]
    s9_checksum = (~sum(s9_bytes)) & 0xFF
    lines.append("S9" + "".join(f"{b:02X}" for b in s9_bytes)
                  + f"{s9_checksum:02X}")
    return "\n".join(lines) + "\n"


def generate_lst(listing):
    """Generate listing file content."""
    lines = []
    for addr, bytelist, raw in listing:
        raw_stripped = raw.rstrip("\n\r")
        if addr is not None and bytelist:
            hex_bytes = " ".join(f"{b:02X}" for b in bytelist)
            lines.append(f"{addr:04X}  {hex_bytes:<12s}  {raw_stripped}")
        elif addr is not None:
            lines.append(f"{addr:04X}                {raw_stripped}")
        else:
            lines.append(f"                    {raw_stripped}")
    return "\n".join(lines) + "\n"

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="EDU-CPU Assembler")
    parser.add_argument("source", help="Assembly source file (.asm)")
    parser.add_argument(
        "--format", choices=["bin", "hex", "srec"], default="bin",
        help="Output format: bin (raw binary, default), "
             "hex (Intel HEX), srec (Motorola S-record)")
    args = parser.parse_args()

    source_path = args.source
    base_name = os.path.splitext(source_path)[0]

    with open(source_path, "r") as f:
        source = f.read()

    asm = Assembler()
    output, listing = asm.assemble(source)

    if asm.errors:
        for err in asm.errors:
            print(f"ERROR: {err}", file=sys.stderr)
        sys.exit(1)

    # Write output in selected format
    if args.format == "hex":
        out_path = base_name + ".hex"
        with open(out_path, "w") as f:
            f.write(generate_hex(output))
        print(f"Intel HEX: {out_path}")
    elif args.format == "srec":
        out_path = base_name + ".srec"
        with open(out_path, "w") as f:
            f.write(generate_srec(output))
        print(f"Motorola SREC: {out_path}")
    else:
        out_path = base_name + ".bin"
        bin_data = generate_bin(output)
        with open(out_path, "wb") as f:
            f.write(bin_data)
        print(f"Binary:  {out_path} ({len(bin_data)} bytes)")

    # Write .LST
    lst_path = base_name + ".lst"
    with open(lst_path, "w") as f:
        f.write(generate_lst(listing))
    print(f"Listing: {lst_path}")


if __name__ == "__main__":
    main()
