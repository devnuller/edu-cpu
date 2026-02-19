; add.asm — Add two numbers and print the result as decimal digits
;
; Demonstrates: ADD, SUB, CMP, CALL, RET, PUSH, POP, branches, LD/ST
;
; Computes 37 + 28 = 65 and prints "65" followed by newline.
;
    .EQU IO, 0xFF

start:
    LD  A, #37       ; first number
    ADD #28          ; A = 37 + 28 = 65
    CALL print_dec   ; print A as decimal
    LD  A, #0x0A     ; newline
    ST  A, [IO]
    HLT

; -------------------------------------------------------
; print_dec: Print accumulator value as decimal (0–255)
;   Input: A = value to print
;   Clobbers: A, R0, R1
; -------------------------------------------------------
print_dec:
    LD  R0, A        ; R0 = value to print
    LD  R1, #0       ; R1 = leading-zero suppression flag

    ; --- Hundreds digit ---
    LD  A, #0        ; digit counter
    PUSH A           ; save digit counter
    LD  A, R0        ; reload value
hundreds:
    CMP #100
    BNC tens_out     ; A < 100, done counting hundreds
    SUB #100
    LD  R0, A        ; update remaining value
    POP A            ; get digit counter
    ADD #1
    PUSH A           ; save updated counter
    LD  A, R0
    JMP hundreds

tens_out:
    POP A            ; A = hundreds digit
    CMP #0
    BZ  skip_h       ; skip leading zero
    ADD #0x30        ; convert to ASCII
    ST  A, [IO]
    LD  R1, #1       ; mark that we printed something
skip_h:

    ; --- Tens digit ---
    LD  A, #0        ; digit counter
    PUSH A
    LD  A, R0
tens:
    CMP #10
    BNC ones_out     ; A < 10, done counting tens
    SUB #10
    LD  R0, A
    POP A
    ADD #1
    PUSH A
    LD  A, R0
    JMP tens

ones_out:
    POP A            ; A = tens digit
    CMP #0
    BNZ print_t      ; non-zero tens digit, always print
    LD  A, R1        ; check if hundreds was printed
    CMP #0
    BZ  skip_t       ; skip if no hundreds and tens is zero
    LD  A, #0        ; reload tens digit (was 0)
print_t:
    ADD #0x30
    ST  A, [IO]
skip_t:

    ; --- Ones digit (always print) ---
    LD  A, R0
    ADD #0x30
    ST  A, [IO]

    RET
