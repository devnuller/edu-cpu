# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

EDU-CPU is an educational 8-bit processor with a two-pass assembler and cycle-accurate simulator, both written in pure Python 3 with no external dependencies.

## Commands

```bash
# Assemble a program (produces .bin and .lst files)
python3 assembler.py <source.asm>

# Run a compiled program
python3 simulator.py <program.bin>

# Run with execution trace (CPU state before each instruction)
python3 simulator.py <program.bin> --trace

# Run with cycle limit
python3 simulator.py <program.bin> --max-cycles 1000

# Assemble and run in one shot
python3 assembler.py examples/hello.asm && python3 simulator.py examples/hello.bin
```

There is no test suite, linter, or build system. Verify changes by assembling and running the example programs in `examples/`.

## Architecture

The codebase is three files:

- **`assembler.py`** — Two-pass assembler. Pass 1 builds the symbol table (labels, `.EQU` constants) and computes addresses. Pass 2 emits machine code and generates the listing. Key sections: instruction tables (top), `encode_ld_st()`/`encode_alu()` for opcode encoding, `Assembler` class for orchestration.

- **`simulator.py`** — Cycle-accurate CPU simulator. The `CPU` class holds all state (registers, memory, flags, hardware stack). `step()` decodes and executes one instruction. `run()` is the main loop with optional tracing. I/O writes to address 0xFF go to stdout.

- **`README.md`** — Complete ISA specification and architecture reference. This is the authoritative source for instruction encoding, opcode values, addressing modes, and flag behavior.

## CPU Design Essentials

When modifying the assembler or simulator, keep these constraints consistent:

- **Opcode format**: `IIIII R MM` — 5-bit instruction, 1-bit register modifier, 2-bit addressing mode
- **Four addressing modes**: immediate (`#val`, MM=00), register (MM=01), direct (`[addr]`, MM=10), indexed (`[Rn+off]`, MM=11)
- **LD/ST for all registers**: 6 instruction codes (LD A, LD R0, LD R1, ST A, ST R0, ST R1). Two-operand syntax: `LD A, R0` / `ST R1, [addr]`
- **Register mode R-bit mapping**: R selects from the two registers NOT the instruction's primary register. For LD A/ST A/ALU: R=0→R0, R=1→R1. For LD R0/ST R0: R=0→A, R=1→R1. For LD R1/ST R1: R=0→A, R=1→R0
- **ALU ops**: one-operand syntax (`ADD R0`), A is always implicit accumulator
- **Carry flag uses 6502/ARM convention**: SUB/CMP set C=1 when A >= operand (no borrow), C=0 when A < operand
- **Hardware stack**: 4 entries, not memory-mapped, shared by PUSH/POP and CALL/RET
- **Memory**: 256 bytes total, 0x00-0xFE is RAM, 0xFF is I/O output port
- **INC/DEC**: affect Z flag only (not C), support A/R0/R1. Register encoded in bits 1-0 (00=A, 01=R0, 10=R1)
