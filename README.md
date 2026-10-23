# bo6502-SDbuilder

Strumenti per preparare la scheda SD del **BO6502** (computer homebrew 65C02): lo script `make_sd.py`
impacchetta fino a 255 programmi in un'immagine RAW, senza filesystem, che il menu **SD PROGRAMS** del BIOS
mostra a pagine da 9 voci e carica in RAM.

## Contenuto

| File | Descrizione |
|---|---|
| `make_sd.py` | Crea l'immagine `sd.img` o scrive direttamente sulla scheda |
| `aggiorna_sd.py` | Prende i giochi da `../MiniVIC Games/bin` e le canzoni da `songs/`, li ordina (giochi in ordine alfabetico, poi canzoni) e lancia `make_sd.py`; `--dry-run` mostra solo cosa cambia |
| `minivic.txt` / `songs.txt` | Nome nel menu di ogni gioco MiniVIC e di ogni canzone (`file.bin = Nome`) |
| `programs.txt` | Elenco dei nomi del menu (uno per programma, separati da `;`) |
| `prog.s` | Programma d'esempio in assembly ca65 (banner, test RAM con `PROGNUM=4`) |
| `ex.cfg` | Configurazione ld65: codice a `$1000`, max `$7000` byte |
| `bios_jt.inc` | Indirizzi fissi della jumptable del BIOS (`$FD00`–`$FD15`) |
| `build.py` | Assembla `prog.s` in `program1..4.bin` (richiede cc65) |
| `songs/` | Copia di sicurezza delle canzoni (Imperial March, The Final Countdown, Super Mario Bros) |

I binari dei programmi (`programN.bin`) e le immagini `.img` non sono nel repository: mettili nella
cartella prima di lanciare lo script, oppure generali con `build.py`. Le canzoni in `songs/` vanno copiate
come `programN.bin` nello slot voluto.

## Uso

```sh
python3 make_sd.py                          # legge programs.txt e program1..N.bin -> sd.img
python3 make_sd.py -n 4 -l nomi.txt         # solo i primi 4 programmi, nomi da nomi.txt
python3 make_sd.py -o /dev/sdX --yes        # scrive DIRETTAMENTE sulla scheda (distrugge i dati!)
python3 make_sd.py -o '\\.\PhysicalDrive2'  # Windows, da prompt Amministratore
```

Opzioni principali: `--run-all` (esegue tutti i programmi dopo il caricamento), `--keep-case` (non mette i nomi
in maiuscolo), `--allow-missing` (lascia vuoto il blocco di un programma mancante), `--min-load` (indirizzo minimo
di caricamento, default `0F00`), `--no-verify` (salta la rilettura di controllo). L'elenco completo si ottiene con `-h`.

Usa una SD standard capacity (fino a 2 GB): il BIOS indirizza la scheda a byte.

### Programmi

Ogni programma può essere:
- `programN.bin`: binario grezzo;
- `programN.txt` / `programN.hex`: dump esadecimale in stile WozMon (`0FD0: 4C 27 11 ...`), da cui lo script
  ricava anche l'indirizzo di caricamento.

### Nomi (`programs.txt`)

```
[!]Nome[@LOAD[:ENTRY]]
```

- `!`: il programma viene eseguito subito dopo il caricamento (nel menu appare come `N>`; senza `!` appare come `N.` e viene solo caricato);
- `@LOAD`: indirizzo RAM di caricamento in esadecimale (default `1000`);
- `:ENTRY`: indirizzo di esecuzione (default `1000` se cade nell'immagine, altrimenti `LOAD`).

Esempio: `Banner; !Arcade Tank@0FD0; Test RAM@1000`

Prima di scrivere, lo script controlla dimensione (max 28 KB), limiti della RAM (`$0F00`–`$7FFF`) ed entry point.

## Formato della SD

```
offset        contenuto
$00000000     blocco programma 1 (32 KB)
$00008000     blocco programma 2
...           (N-1) * $8000
```

Ogni blocco da 32 KB è fatto così:

| Offset nel blocco | Contenuto |
|---|---|
| `+$0000` (settore 0) | pagina di directory P, nel blocco P (solo per i primi blocchi) |
| `+$0200` (settore 1) | riga di info ASCII (slot, file, load, len, entry, CRC32) |
| `+$1000` – `+$7FFF` | byte del programma (max `$7000`) |

La zona riservata `+$0000..+$0FFF` non viene mai copiata in RAM. Il BIOS scrive esattamente
`[load, load+len)` e lascia intatto il resto della memoria.

### Settore di directory (versione 3)

| Offset | Dimensione | Campo |
|---|---|---|
| `0` | 4 | magic `"BOGS"` |
| `4` | 1 | versione (`3`) |
| `5` | 1 | programmi in questa pagina (1..9) |
| `6` | 9 | flag di ogni voce (bit0 = esegui) |
| `15` | 1 | numero totale di programmi |
| `16 + i*8` | 8 | load (lo,hi), lunghezza (lo,hi), entry (lo,hi), 0, 0 |
| `96 + i*32` | 32 | nome ASCII (max 31 caratteri + `$00`) |

Dal menu si cambia pagina con **A**/**D** e si sceglie il programma con **1**..**9**.

## Scrivere programmi

`bios_jt.inc` espone le routine del BIOS:

| Simbolo | Indirizzo | Funzione |
|---|---|---|
| `JT_CHROUT` | `$FD00` | stampa il carattere in A |
| `JT_CHRIN_NOECHO` | `$FD03` | C=1 e A=tasto, C=0 se nessun tasto |
| `JT_RESET_TERM` | `$FD06` | reset del terminale |
| `JT_INIT_CRT` | `$FD09` | inizializza il video |
| `JT_LOAD_RUN_SLOT` | `$FD0C` | carica ed esegue lo slot in A (JMP, non ritorna) |
| `JT_SHOW_MENU` | `$FD0F` | torna al menu del BIOS (JMP, non ritorna) |
| `JT_INIT_SDCARD` | `$FD12` | carica lo slot in A e ritorna (C=1 errore) |
| `JT_FLUSH_KB` | `$FD15` | svuota la tastiera (~0,5 s) |

Compilazione dell'esempio con [cc65](https://cc65.github.io/):

```sh
ca65 -D PROGNUM=1 prog.s -o p1.o
ld65 -C ex.cfg p1.o -o program1.bin
```

> **Attenzione:** `build.py` sovrascrive `program1.bin`..`program4.bin`. Se in quegli slot hai già altri programmi,
> lancialo in una cartella separata.
