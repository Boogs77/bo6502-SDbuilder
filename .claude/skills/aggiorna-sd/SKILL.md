---
name: aggiorna-sd
description: Controlla se in "MiniVIC Games/bin" ci sono giochi nuovi o aggiornati e rigenera l'SD del BO6502 (program*.bin, programs.txt, sd.img). Usala quando l'utente chiede di aggiornare o rifare l'SD, di aggiungere i giochi nuovi di MiniVIC, o di controllare cosa è cambiato rispetto all'SD attuale.
---

# Aggiornare l'SD con i giochi di MiniVIC

Tutto il lavoro lo fa `aggiorna_sd.py`, nella cartella del progetto. Non rinumerare i file a mano.

## Passi

1. **Anteprima.** Lancia `python aggiorna_sd.py --dry-run` dalla cartella del progetto. Lo script elenca i
   programmi della nuova SD nell'ordine del menu: prima i giochi in ordine alfabetico, poi le canzoni. Accanto a ogni voce
   scrive NUOVO, AGGIORNATO o TOLTO rispetto all'SD attuale.
2. **Se ci sono 0 differenze**, dillo all'utente e fermati: l'SD è già aggiornata.
3. **Se ci sono giochi nuovi**, lo script ricava il nome dal file (es. `lunar_lander.bin` -> "Lunar Lander").
   Mostra il nome all'utente. Se ne vuole un altro, correggilo in `minivic.txt` dopo il passo 4 e rilancia lo script.
4. **Generazione.** Lancia `python aggiorna_sd.py`. Lo script:
   - aggiunge i giochi nuovi a `minivic.txt`;
   - salva i vecchi `program*.bin`, `programs.txt` e `sd.img` in `.backup/<data-ora>/`;
   - riscrive `program1..N.bin` e `programs.txt`;
   - lancia `make_sd.py`, che crea `sd.img` e la rilegge per verificarla.
5. **Controllo.** L'output deve finire con `Verifica OK`. Se `make_sd.py` dà errore (programma troppo grande,
   indirizzo fuori RAM, ...), riporta il messaggio così com'è, senza correggere i binari di MiniVIC.

## Regole

- Scrivi `sd.img` e basta. Per scrivere direttamente su una scheda (`-- -o '\\.\PhysicalDrive2'` o
  `-- -o /dev/sdX`) serve una richiesta esplicita dell'utente, con il device indicato da lui: cancella tutto quello che c'è sulla scheda.
- Non fare commit né push, a meno che l'utente non lo chieda. Se lo chiede, i file da caricare sono `programs.txt`
  e `minivic.txt`: i `.bin` e le `.img` sono esclusi dal `.gitignore`.
- Rispondi in italiano. Nel riepilogo finale metti: giochi aggiunti, aggiornati o tolti, numero totale di programmi
  e pagine del menu, esito della verifica.
- Aggiorna il diario della sessione con la skill `session-log`.

## File

- `minivic.txt`: `file.bin = Nome` per ogni gioco di MiniVIC. Il nome nel menu diventa `NOME - GAME` e il gioco viene caricato a `$0FD0`.
- `songs.txt`: `file.bin = Nome` per le canzoni in `songs/`, nell'ordine del menu. Il nome diventa `NOME - SONG` e la canzone viene caricata a `$1000`.
- Cartella dei giochi diversa: `--minivic PERCORSO`.
