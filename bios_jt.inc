; FIXED addresses of the BIOS jump table (see jumptable.s)
JT_CHROUT        = $FD00   ; A = character
JT_CHRIN_NOECHO  = $FD03   ; C=1 + A=key, C=0 no key
JT_RESET_TERM    = $FD06
JT_INIT_CRT      = $FD09
JT_LOAD_RUN_SLOT = $FD0C   ; A=slot (JMP, never RTS)
JT_SHOW_MENU     = $FD0F   ; back to the BIOS menu (JMP, never RTS)
JT_INIT_SDCARD   = $FD12   ; A=slot, loads and RETURNS (C=1 error)
JT_FLUSH_KB      = $FD15   ; flushes the keyboard (~0.5 s): call it before waiting for a key
