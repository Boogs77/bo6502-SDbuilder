; Programma d'esempio per la SD BO6502 - si carica a $1000 (usa 'ca65 -D PROGNUM=n').
; PROGNUM=4 aggiunge un test della RAM $1200-$7FFF (pattern = lo(addr) XOR hi(addr)).
.setcpu "65C02"
.include "bios_jt.inc"
.ifndef PROGNUM
  PROGNUM = 1
.endif

.segment "CODE"
start:
    jsr JT_RESET_TERM
    jsr JT_INIT_CRT

    lda #<msg_banner
    ldx #>msg_banner
    jsr print
.if PROGNUM = 4
    lda #<msg_check
    ldx #>msg_check
    jsr print
    jsr ramcheck
    bcs fail
    lda #<msg_ok
    ldx #>msg_ok
    jsr print
    jmp done
fail:
    lda #<msg_fail
    ldx #>msg_fail
    jsr print
.endif
done:
    lda #<msg_key
    ldx #>msg_key
    jsr print
    jsr JT_FLUSH_KB          ; scarta eventuali scancode spuri (es. rilascio del tasto del menu)
wait:
    jsr JT_CHRIN_NOECHO
    bcc wait
    jmp JT_SHOW_MENU

; stampa stringa 0-terminata: A=lo, X=hi. CHROUT puo' sporcare tutti i registri,
; quindi il puntatore sta in RAM (auto-modifica dell'operando), non nei registri.
print:
    sta @ld+1
    stx @ld+2
    lda #0
    sta idx
@lp:
    ldx idx
@ld:
    lda $FFFF,x
    beq @end
    jsr JT_CHROUT
    inc idx
    bne @lp
@end:
    rts
idx: .byte 0

.if PROGNUM = 4
; Controlla $1200-$7FFF: atteso lo(addr) EOR hi(addr). C=1 se errore. Senza zero page.
ramcheck:
    ldy #$12
@pg:
    sty @ld+2
    sty @e+1
    ldx #0
@lp:
    txa
@e: eor #0
@ld:
    cmp $1200,x
    bne @bad
    inx
    bne @lp
    iny
    cpy #$80
    bne @pg
    clc
    rts
@bad:
    sec
    rts
.endif

msg_banner:
    .byte $0D,$0A, "*** SD PROGRAM ", '0'+PROGNUM, " ***", $0D,$0A
    .byte "LOADED FROM SD SLOT ", '0'+PROGNUM-1, " AT $1000", $0D,$0A, 0
.if PROGNUM = 4
msg_check: .byte "CHECKING RAM $1200-$7FFF...", $0D,$0A, 0
msg_ok:    .byte "RAM CHECK OK", $0D,$0A, 0
msg_fail:  .byte "RAM CHECK FAILED!", $0D,$0A, 0
.endif
msg_key:
    .byte $0D,$0A, "PRESS ANY KEY FOR MENU", $0D,$0A, 0
