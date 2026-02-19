.EQU IO, 0xFF
.ORG 0

start:
    LD  R0, #0       ; R0 = memory index

loop:
    LD  R1, [R0+0] 
    ST  R1, [IO]     ; Write content
    LD  A, R0
    CMP 0xFF         ; are we done?
    BZ  done         ; yes — we're done
    INC R0
    JMP loop         ; repeat

done:
    HLT
