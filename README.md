# EDU-CPU: Educational 8-bit Processor

A minimal 8-bit CPU designed for teaching processor concepts. Simple enough to
build with off-the-shelf 74-series logic ICs or synthesize in Verilog/VHDL.

## Architecture Overview

```
┌────────────────────────────────────────────┐
│                  EDU-CPU                   │
│                                            │
│  ┌─────┐  ┌─────┐  ┌─────┐  ┌───────────┐  │
│  │  A  │  │ R0  │  │ R1  │  │  Stack    │  │
│  │ 8b  │  │ 8b  │  │ 8b  │  │  4 x 8b   │  │
│  └──┬──┘  └──┬──┘  └──┬──┘  │  SP: 2b   │  │
│     │        │        │     └───────────┘  │
│     └────────┴────┬───┘                    │
│              ┌────┴────┐   ┌────┐          │
│              │   ALU   │   │ PC │          │
│              │         │   │ 8b │          │
│              └────┬────┘   └──┬─┘          │
│              ┌────┴────┐      │            │
│              │  Flags  │      │            │
│              │  Z | C  │      │            │
│              └─────────┘      │            │
│                               │            │
│  ════════════╤════════════════╧══════════  │
│         8-bit data bus    8-bit addr bus   │
└──────────────┼────────────────┼────────────┘
               │                │
         ┌─────┴────────────────┴─────┐
         │     256-byte Memory        │
         │     0x00-0xFE: RAM         │
         │     0xFF: I/O output port  │
         └────────────────────────────┘
```

### Registers

| Register | Width | Description |
|----------|-------|-------------|
| A        | 8-bit | Accumulator — implicit destination for all ALU operations |
| R0       | 8-bit | General-purpose register |
| R1       | 8-bit | General-purpose register |
| PC       | 8-bit | Program counter — starts at 0x00 on reset |
| SP       | 2-bit | Stack pointer (0–3) — starts at 0 on reset |
| Z        | 1-bit | Zero flag — set when ALU result is zero |
| C        | 1-bit | Carry flag — set on unsigned overflow/no-borrow |

### Memory Map

| Address Range | Description |
|---------------|-------------|
| 0x00 – 0xFE  | General-purpose RAM (code and data) |
| 0xFF          | Output port — writing a byte sends it to external output |

Memory is unified (von Neumann): code and data share the same 256-byte space.
Execution begins at address 0x00 after reset.

### Internal Stack

The CPU contains a 4-level hardware stack (not mapped to main memory).
The stack is shared between PUSH/POP and CALL/RET instructions.

- **PUSH**: `stack[SP] = value; SP = SP + 1`
- **POP**: `SP = SP - 1; value = stack[SP]`
- **CALL**: pushes return address (PC after CALL), then jumps
- **RET**: pops address, sets PC

Stack overflow (push when SP=4) and underflow (pop when SP=0) are errors.

---

## Instruction Encoding

Every instruction is 1 or 2 bytes: an 8-bit opcode, optionally followed by an
8-bit operand.

### Opcode Format

```
  Bit:  7   6   5   4   3   2   1   0
       ├───┴───┴───┴───┴───┤   ├───┴───┤
       │  IIIII (instr)    │ R │  MM   │
       │  5 bits           │1b │ 2 bits│
       └───────────────────┘   └───────┘
```

| Field | Bits | Description |
|-------|------|-------------|
| IIIII | 7–3  | Instruction code (32 possible operations) |
| R     | 2    | Register select / modifier |
| MM    | 1–0  | Addressing mode |

### Addressing Modes (MM)

| MM | Mode      | Operand byte | Effective value | Assembly syntax |
|----|-----------|-------------|-----------------|-----------------|
| 00 | Immediate | value       | The operand byte itself | `#value` |
| 01 | Register  | *(none)*    | Contents of a register (see below) | `A`, `R0`, or `R1` |
| 10 | Direct    | address     | Contents of memory[address] | `[address]` |
| 11 | Indexed   | offset      | Contents of memory[Rn + offset] | `[R0+offset]` or `[R1+offset]` |

- **Immediate** and **Direct** modes ignore the R bit (assembler sets R=0).
- **Indexed** mode: the R bit selects the index register (R=0 → R0, R=1 → R1).
- **Register** mode: the R bit selects the source/destination register.
  See the register mode tables below for the full mapping.

Instruction size:
- Modes 00, 10, 11: **2 bytes** (opcode + operand)
- Mode 01: **1 byte** (opcode only)
- Special instructions (RET, NOP, HLT, PUSH, POP, INC, DEC): **1 byte**
- JMP, CALL, branches: **2 bytes** (opcode + address/displacement)

### Register Mode — R Bit Mapping

In register mode (MM=01), the R bit selects from the two registers that are
**not** the instruction's primary register:

| Instruction          | R=0 register | R=1 register |
|----------------------|--------------|--------------|
| LD A / ST A / ALU ops | R0          | R1           |
| LD R0 / ST R0        | A           | R1           |
| LD R1 / ST R1        | A           | R0           |

This provides complete register-to-register transfers using LD and ST.

---

## Instruction Reference

### LD — Load Register

The LD instruction loads a value into any register (A, R0, or R1) using any
of the four addressing modes.

| IIIII  | Hex base | Mnemonic | Operation |
|--------|----------|----------|-----------|
| 00000  | 0x00     | LD A     | A ← source |
| 00001  | 0x08     | LD R0    | R0 ← source |
| 00010  | 0x10     | LD R1    | R1 ← source |

LD does not affect any flags.

#### Complete LD Opcode Map

**LD A** (IIIII=00000):

| Assembly         | R | MM | Opcode | Operand | Description |
|------------------|---|----|--------|---------|-------------|
| `LD A, #imm`     | 0 | 00 | 0x00   | imm     | A ← immediate value |
| `LD A, R0`       | 0 | 01 | 0x01   | —       | A ← R0 |
| `LD A, [addr]`   | 0 | 10 | 0x02   | addr    | A ← memory[addr] |
| `LD A, [R0+off]` | 0 | 11 | 0x03   | off     | A ← memory[R0 + off] |
| `LD A, R1`       | 1 | 01 | 0x05   | —       | A ← R1 |
| `LD A, [R1+off]` | 1 | 11 | 0x07   | off     | A ← memory[R1 + off] |

**LD R0** (IIIII=00001):

| Assembly          | R | MM | Opcode | Operand | Description |
|-------------------|---|----|--------|---------|-------------|
| `LD R0, #imm`     | 0 | 00 | 0x08   | imm     | R0 ← immediate value |
| `LD R0, A`        | 0 | 01 | 0x09   | —       | R0 ← A |
| `LD R0, [addr]`   | 0 | 10 | 0x0A   | addr    | R0 ← memory[addr] |
| `LD R0, [R0+off]` | 0 | 11 | 0x0B   | off     | R0 ← memory[R0 + off] |
| `LD R0, R1`       | 1 | 01 | 0x0D   | —       | R0 ← R1 |
| `LD R0, [R1+off]` | 1 | 11 | 0x0F   | off     | R0 ← memory[R1 + off] |

**LD R1** (IIIII=00010):

| Assembly          | R | MM | Opcode | Operand | Description |
|-------------------|---|----|--------|---------|-------------|
| `LD R1, #imm`     | 0 | 00 | 0x10   | imm     | R1 ← immediate value |
| `LD R1, A`        | 0 | 01 | 0x11   | —       | R1 ← A |
| `LD R1, [addr]`   | 0 | 10 | 0x12   | addr    | R1 ← memory[addr] |
| `LD R1, [R0+off]` | 0 | 11 | 0x13   | off     | R1 ← memory[R0 + off] |
| `LD R1, R0`       | 1 | 01 | 0x15   | —       | R1 ← R0 |
| `LD R1, [R1+off]` | 1 | 11 | 0x17   | off     | R1 ← memory[R1 + off] |

### ST — Store Register

The ST instruction stores a register value to a destination. ST supports
register, direct, and indexed addressing modes. ST with immediate mode is
invalid and produces an assembler error.

| IIIII  | Hex base | Mnemonic | Operation |
|--------|----------|----------|-----------|
| 00011  | 0x18     | ST A     | destination ← A |
| 00100  | 0x20     | ST R0    | destination ← R0 |
| 00101  | 0x28     | ST R1    | destination ← R1 |

ST does not affect any flags.

#### Complete ST Opcode Map

**ST A** (IIIII=00011):

| Assembly          | R | MM | Opcode | Operand | Description |
|-------------------|---|----|--------|---------|-------------|
| `ST A, R0`        | 0 | 01 | 0x19   | —       | R0 ← A |
| `ST A, [addr]`    | 0 | 10 | 0x1A   | addr    | memory[addr] ← A |
| `ST A, [R0+off]`  | 0 | 11 | 0x1B   | off     | memory[R0 + off] ← A |
| `ST A, R1`        | 1 | 01 | 0x1D   | —       | R1 ← A |
| `ST A, [R1+off]`  | 1 | 11 | 0x1F   | off     | memory[R1 + off] ← A |

**ST R0** (IIIII=00100):

| Assembly           | R | MM | Opcode | Operand | Description |
|--------------------|---|----|--------|---------|-------------|
| `ST R0, A`         | 0 | 01 | 0x21   | —       | A ← R0 |
| `ST R0, [addr]`    | 0 | 10 | 0x22   | addr    | memory[addr] ← R0 |
| `ST R0, [R0+off]`  | 0 | 11 | 0x23   | off     | memory[R0 + off] ← R0 |
| `ST R0, R1`        | 1 | 01 | 0x25   | —       | R1 ← R0 |
| `ST R0, [R1+off]`  | 1 | 11 | 0x27   | off     | memory[R1 + off] ← R0 |

**ST R1** (IIIII=00101):

| Assembly           | R | MM | Opcode | Operand | Description |
|--------------------|---|----|--------|---------|-------------|
| `ST R1, A`         | 0 | 01 | 0x29   | —       | A ← R1 |
| `ST R1, [addr]`    | 0 | 10 | 0x2A   | addr    | memory[addr] ← R1 |
| `ST R1, [R0+off]`  | 0 | 11 | 0x2B   | off     | memory[R0 + off] ← R1 |
| `ST R1, R0`        | 1 | 01 | 0x2D   | —       | R0 ← R1 |
| `ST R1, [R1+off]`  | 1 | 11 | 0x2F   | off     | memory[R1 + off] ← R1 |

### ALU Instructions

These instructions use the full addressing mode encoding. The accumulator (A)
is always the implicit first operand and destination. In register mode,
R=0 → R0, R=1 → R1.

| IIIII  | Hex base | Mnemonic | Operation                     | Flags affected |
|--------|----------|----------|-------------------------------|----------------|
| 00110  | 0x30     | ADD      | A ← A + source                | Z, C           |
| 00111  | 0x38     | SUB      | A ← A − source                | Z, C           |
| 01000  | 0x40     | AND      | A ← A & source                | Z, C←0         |
| 01001  | 0x48     | OR       | A ← A \| source               | Z, C←0         |
| 01010  | 0x50     | XOR      | A ← A ^ source                | Z, C←0         |
| 01011  | 0x58     | CMP      | A − source (result discarded) | Z, C           |

"Hex base" is the opcode when R=0 and MM=00. Add the addressing mode and
register bits to get the actual opcode.

#### ALU Opcode Map Example

**ADD** (IIIII=00110):

| Assembly         | R | MM | Opcode | Operand | Description |
|------------------|---|----|--------|---------|-------------|
| `ADD #imm`        | 0 | 00 | 0x30   | imm     | A ← A + immediate |
| `ADD R0`          | 0 | 01 | 0x31   | —       | A ← A + R0 |
| `ADD [addr]`      | 0 | 10 | 0x32   | addr    | A ← A + memory[addr] |
| `ADD [R0+off]`    | 0 | 11 | 0x33   | off     | A ← A + memory[R0 + off] |
| `ADD R1`          | 1 | 01 | 0x35   | —       | A ← A + R1 |
| `ADD [R1+off]`    | 1 | 11 | 0x37   | off     | A ← A + memory[R1 + off] |

The same pattern applies to SUB, AND, OR, XOR, CMP — replace IIIII accordingly.

### Control Instructions

These instructions repurpose the R and MM bits for encoding.

#### JMP — Absolute Jump

| Assembly   | Opcode | Operand | Description |
|------------|--------|---------|-------------|
| `JMP addr` | 0x60   | addr    | PC ← addr |

#### Conditional Branches — PC-relative

The operand is a **signed 8-bit displacement** added to the PC after the
branch instruction is fetched (i.e., PC points to the instruction *after*
the branch). Target = PC_after_branch + displacement.

| Assembly    | Opcode | Condition |
|-------------|--------|-----------|
| `BZ label`  | 0x68   | Branch if Z = 1 (result was zero) |
| `BNZ label` | 0x69   | Branch if Z = 0 (result was not zero) |
| `BC label`  | 0x6A   | Branch if C = 1 (carry / no borrow) |
| `BNC label` | 0x6B   | Branch if C = 0 (no carry / borrow) |

Useful idiom after `CMP`:
- `BZ` = branch if equal
- `BNZ` = branch if not equal
- `BC` = branch if greater or equal (unsigned)
- `BNC` = branch if less than (unsigned)

#### CALL / RET — Subroutine Support

| Assembly    | Opcode | Operand | Description |
|-------------|--------|---------|-------------|
| `CALL addr` | 0x70   | addr    | Push PC (next instr), PC ← addr |
| `RET`       | 0x78   | —       | Pop PC |

### Stack Instructions

Register encoding uses bits 1–0: 00 = A, 01 = R0, 10 = R1.

| Assembly  | Opcode | Description |
|-----------|--------|-------------|
| `PUSH A`  | 0x80   | Push accumulator onto stack |
| `PUSH R0` | 0x81   | Push R0 onto stack |
| `PUSH R1` | 0x82   | Push R1 onto stack |
| `POP A`   | 0x88   | Pop top of stack into accumulator |
| `POP R0`  | 0x89   | Pop top of stack into R0 |
| `POP R1`  | 0x8A   | Pop top of stack into R1 |

### Register Instructions

Register encoding uses bits 1–0: 00 = A, 01 = R0, 10 = R1.

| Assembly  | Opcode | Flags |
|-----------|--------|-------|
| `INC A`   | 0x90   | Z |
| `INC R0`  | 0x91   | Z |
| `INC R1`  | 0x92   | Z |
| `DEC A`   | 0x98   | Z |
| `DEC R0`  | 0x99   | Z |
| `DEC R1`  | 0x9A   | Z |

INC/DEC wrap around on overflow/underflow (0xFF + 1 = 0x00, 0x00 − 1 = 0xFF).
The carry flag is **not** affected (useful for loop counters that shouldn't
disturb carry from a previous ALU operation).

### System Instructions

| Assembly | Opcode | Description |
|----------|--------|-------------|
| `NOP`    | 0xA0   | No operation |
| `HLT`    | 0xA8   | Halt the CPU |

---

## Flag Details

### Carry Flag (C) Convention

This CPU uses the **6502/ARM convention** for subtraction:

- **ADD**: `C = 1` if the result exceeds 255 (unsigned overflow)
- **SUB / CMP**: `C = 1` if A ≥ operand (no borrow needed); `C = 0` if A < operand

This means after `CMP`:
| Condition       | Test |
|-----------------|------|
| A == operand    | Z = 1 |
| A != operand    | Z = 0 |
| A >= operand    | C = 1 |
| A < operand     | C = 0 |
| A > operand     | C = 1 and Z = 0 |
| A <= operand    | C = 0 or Z = 1 |

---

## Assembly Language Syntax

### General Format

```
[label:]  [instruction [operand]]  [; comment]
```

- Labels must end with a colon and start with a letter or underscore.
- Comments start with `;` and extend to end of line.
- Mnemonics are case-insensitive (`ld`, `LD`, `Ld` are equivalent).

### Number Formats

| Format   | Example   | Value |
|----------|-----------|-------|
| Decimal  | `42`      | 42    |
| Hex      | `0x2A`    | 42    |
| Binary   | `0b00101010` | 42 |

### LD / ST Syntax (two-operand)

```
LD <register>, <source>
ST <register>, <destination>
```

Where `<register>` is `A`, `R0`, or `R1`, and the source/destination uses the
standard operand syntax below.

### ALU Syntax (one-operand, A is implicit)

```
ADD <source>
SUB <source>
AND <source>
OR  <source>
XOR <source>
CMP <source>
```

### Operand Syntax

| Syntax        | Addressing Mode | Example |
|---------------|-----------------|---------|
| `#value`      | Immediate       | `LD A, #0x42` |
| `A`, `R0`, `R1` | Register     | `LD A, R0` or `ADD R1` |
| `[address]`   | Direct          | `LD A, [0x80]` |
| `[Rn+offset]` | Indexed         | `LD A, [R0+5]` |
| `[Rn]`        | Indexed (off=0) | `LD A, [R0]` |

Labels can be used wherever an address or value is expected:

```
    JMP loop        ; absolute address
    BZ  done        ; branch displacement (computed by assembler)
    LD  A, #msg     ; immediate (low byte of label address)
    LD  A, [data]   ; direct addressing to labeled location
```

### Assembler Directives

| Directive           | Description |
|---------------------|-------------|
| `.ORG address`      | Set the assembly origin (next instruction placed at address) |
| `.DB val1, val2, …` | Define raw data bytes |
| `.DS "string"`      | Define a null-terminated ASCII string |
| `.EQU name, value`  | Define a symbolic constant |

`.DS` supports escape sequences: `\n` (newline), `\t` (tab), `\r` (carriage return), `\0` (null), `\\` (backslash). A `0x00` null terminator is appended automatically.

---

## Tools

### Assembler

```
python3 assembler.py <source.asm> [--format {bin,hex,srec}]
```

The `--format` flag selects the output format (default: `bin`):

| Format | Extension | Description |
|--------|-----------|-------------|
| `bin`  | `.bin`    | Raw binary image (default) |
| `hex`  | `.hex`    | Intel HEX (`:LLAAAATTDD...CC` records) |
| `srec` | `.srec`   | Motorola S-record (S0/S1/S9 records) |

A listing file (`.lst`) is always produced alongside the chosen format.

Examples:

```bash
python3 assembler.py program.asm                # produces program.bin + program.lst
python3 assembler.py program.asm --format hex   # produces program.hex + program.lst
python3 assembler.py program.asm --format srec  # produces program.srec + program.lst
```

### Simulator

```
python3 simulator.py <program> [<program> ...] [--trace] [--max-cycles N]
```

The simulator accepts `.bin`, `.hex`, and `.srec` files. The format is
auto-detected from the file extension, with a fallback to content inspection
(`:` prefix → Intel HEX, `S` prefix → Motorola S-record, otherwise raw binary).

- `--trace`: print CPU state before each instruction
- `--max-cycles N`: stop after N cycles (default: 65536)
- Writes to address **0xFF** are sent to standard output as raw bytes

#### Loading Multiple Files

Multiple `.hex` and/or `.srec` files can be specified to compose a memory image
from separately assembled modules (e.g., code and data in different files using
`.ORG` to target different address ranges). All files are loaded before
execution begins at address 0x00.

The simulator checks for **address overlaps** between files. If any two files
write to the same address, the simulator reports the conflict and exits:

```
ERROR: Overlap between code.hex and data.hex at 0x00, 0x01, 0x02
```

Raw binary (`.bin`) files are only supported when loading a single file, since
they have no embedded address information.

#### Runaway Protection

The simulator tracks which memory addresses were loaded from input files. If
the program counter reaches an address that contains no loaded program data —
for example by falling off the end of code without a `HLT`, or jumping to an
uninitialized address — execution stops immediately with an error:

```
Runtime error at cycle 3: PC entered unloaded memory at address 0x05
```

This only applies to instruction fetches. Reading unloaded memory as *data*
(via LD, ALU, etc.) is still permitted and returns zero.

Examples:

```bash
python3 simulator.py program.bin
python3 simulator.py program.hex --trace
python3 simulator.py program.srec --max-cycles 1000
python3 simulator.py code.hex data.srec          # load code + data from separate files
```

---

## Example Program

### Hello World

```asm
; hello.asm — Print "Hello, World!" via I/O port at 0xFF
;
    .EQU IO, 0xFF

start:
    LD  R0, #0       ; R0 = string index

loop:
    LD  A, [R0+msg]  ; load character from msg + R0
    CMP #0           ; null terminator?
    BZ  done         ; yes — stop
    ST  A, [IO]      ; output character
    INC R0           ; next character
    JMP loop         ; repeat

done:
    HLT

msg:
    .DS "Hello, World!\n"
```

---

## Hardware Implementation Notes

The instruction encoding is designed for straightforward decoding:

- **Bits 7–3** drive the instruction decoder (a ROM or PLA)
- **Bits 1–0** select the addressing mode (controls operand fetch mux)
- **Bit 2** is a register modifier (mux control line)

The 4-level stack can be implemented with 4 × 8-bit registers and a 2-bit
up/down counter. The ALU needs only add, subtract, AND, OR, XOR, and compare
(subtract without writeback).

Suggested IC-level building blocks:
- 74LS181 (4-bit ALU, two for 8-bit) or 74HC283 (adder) + logic gates
- 74HC574 (8-bit register with clock enable) for A, R0, R1, PC
- 74HC245 (bus transceiver) for bus interfacing
- 62256 or similar SRAM for memory
- AT28C256 EEPROM for instruction decode ROM
