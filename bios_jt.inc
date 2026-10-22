; Indirizzi FISSI della jumptable BIOS (vedi jumptable.s)
JT_CHROUT        = $FD00   ; A = carattere
JT_CHRIN_NOECHO  = $FD03   ; C=1 + A=tasto, C=0 nessun tasto
JT_RESET_TERM    = $FD06
JT_INIT_CRT      = $FD09
JT_LOAD_RUN_SLOT = $FD0C   ; A=slot (JMP, mai RTS)
JT_SHOW_MENU     = $FD0F   ; torna al menu BIOS (JMP, mai RTS)
JT_INIT_SDCARD   = $FD12   ; A=slot, carica e RITORNA (C=1 errore)
JT_FLUSH_KB      = $FD15   ; svuota la tastiera (~0.5 s): chiamala prima di aspettare un tasto
