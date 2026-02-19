; hello.asm — Print "Hello, World!" via I/O port at 0xFF
;
; Demonstrates: LD, ST, CMP, INC, BZ, JMP, indexed addressing, .EQU, .DS
;
    .EQU IO, 0xFF

start:
    LD  R0, #0       ; R0 = string index

loop:
    LD  A, [R0+msg]  ; load character at msg[R0]
    CMP #0           ; null terminator?
    BZ  done         ; yes — we're done
    ST  A, [IO]      ; write character to output
    INC R0           ; advance to next character
    JMP loop         ; repeat

done:
    HLT

msg:
    .DS "Hello, World!\n"
