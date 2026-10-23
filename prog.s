; Example program for the BO6502 SD - loads at $1000 (use 'ca65 -D PROGNUM=n').
; PROGNUM=4 adds a RAM test of $1200-$7FFF (pattern = lo(addr) XOR hi(addr)).
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
    jsr JT_FLUSH_KB          ; drop stray scancodes (e.g. the release of the menu key)
wait:
    jsr JT_CHRIN_NOECHO
    bcc wait
    jmp JT_SHOW_MENU

; prints a 0-terminated string: A=lo, X=hi. CHROUT may clobber every register,
; so the pointer lives in RAM (self-modified operand), not in registers.
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
; Checks $1200-$7FFF: expected lo(addr) EOR hi(addr). C=1 on error. No zero page.
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
