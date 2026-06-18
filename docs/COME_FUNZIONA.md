# Fantamondiale 2026 Optimizer — come funziona

Documento sintetico: flusso, dati, formule e limiti.

---

## Come aggiungere correzioni

1. Scorri le sezioni sotto.
2. In ogni box **📝 Correzioni** scrivi cosa va cambiato (regolamento, numeri, flusso, priorità…).
3. Usa `- [ ]` per todo aperti, `- [x]` quando è già chiarito.
4. In chat: *«applica le correzioni in COME_FUNZIONA»* oppure `@docs/COME_FUNZIONA.md`.

**Indice rapido correzioni**


| ID  | Sezione              | Stato |
| --- | -------------------- | ----- |
| C1  | Cosa fa              | ⬜     |
| C2  | Flusso               | ⬜     |
| C3  | Lettura roster       | ⬜     |
| C4  | Fonti quote          | ⬜     |
| C5  | H/I/J/Superbonus     | ⬜     |
| C6  | Formazione           | ⬜     |
| C7  | Eventi K/L           | ⬜     |
| C8  | Output               | ⬜     |
| C9  | Devig                | ⬜     |
| C10 | Config               | ⬜     |
| C11 | Limiti               | ⬜     |
| C12 | File chiave          | ⬜     |
| C0  | **Generale / altro** | ⬜     |


*(Cambia ⬜ → ✅ nella tabella quando una sezione è ok.)*

---

## 1. Cosa fa

Per **una partita alla volta** suggerisce:


| Output                     | Regolamento FM                  | Cosa ottimizza                 |
| -------------------------- | ------------------------------- | ------------------------------ |
| **H / I / J / Superbonus** | Risultato 1T, 90′, segno, combo | EV massimo sui punteggi esatti |
| **Formazione**             | 4 giocatori personali + vice    | EV somma bonus/malus giocatori |
| **K**                      | Primo sostituito                | EV = P × 5 pt                  |
| **L**                      | Primo ammonito                  | EV = P × 4 pt                  |


L’EV (valore atteso) = **probabilità stimata × punti FM se indovini**.

> **📝 Correzioni (C1)**
>
> - 
> - 

---

## 2. Flusso end-to-end

```
Screenshot FM  ──►  Lettura roster (vision AI o testo incollato)
                         │
                         ▼
              MatchRoster (casa, ospite, giocatori, bonus, vice)
                         │
                         ▼
              Fetch quote in parallelo (cache di default)
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
   The Odds API    OddsPapi (opt.)   SofaScore lite (opt.)
   h2h, totals,   correct score,   solo se manca qualcosa
   goalscorer      props, 1° cart.   (max 1 HTTP via sofa id)
                         │
                         ▼
              MatchData unificato per la partita
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
   rank_predictions   attach_player_probs   K / L
   (H/I/J)            (gol, cartellini…)   eventi
         │               │               │
         └───────────────┴───────────────┘
                         ▼
              Report HTML (web) o CLI
```

**Web:** `POST /predict` → `analyze_match_from_roster()` in `src/predict/analyze.py`.

> **📝 Correzioni (C2)**
>
> - 
> - 

---

## 3. Lettura roster

### Screenshot (primario su cloud)

1. **OpenAI Vision** (`gpt-4o-mini`) legge 1–6 screenshot → JSON strutturato (casa, ospite, giocatori, ruolo, bonus, vice).
2. Richiede `OPENAI_API_KEY` su Render.

### Testo incollato (fallback)

Parser regex su testo tipo app FM → stesso `MatchRoster`.

### Match con le quote

I nomi squadra (IT o EN) vengono confrontati con l’elenco partite API tramite **score fuzzy** (0–1), non match testuale rigido:

- normalizzazione (trattini, accenti, alias IT→EN)
- overlap token + similarità caratteri
- soglia minima **0.72**; se due partite sono troppo simili → errore “ambiguo”

File: `src/odds/api_normalize.py` → `find_event()`, `team_match_score()`.

> **📝 Correzioni (C3)**
>
> - 
> - 

---

## 4. Fonti quote


| Fonte            | Dati                                                       | Quando                                                                                |
| ---------------- | ---------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| **The Odds API** | 1X2, under/over, 1T, anytime goalscorer                    | Sempre (obbligatorio)                                                                 |
| **OddsPapi**     | Correct score FT/HT, gol/cartellini giocatore, 1° ammonito | Se `ODDSPAPI_API_KEY`                                                                 |
| **SofaScore**    | Correct score, props, 1° carta                             | Solo gap: no calendario/search, 1 call `/odds/1/all` se OddsPapi espone `sofascoreId` |


Merge: OddsPapi arricchisce; SofaScore riempie solo buchi (`merge_match_data_fill_gaps`).

**Cache:** 3 ore su disco + memoria. Spunta **Refresh** nel form solo per forzare chiamate live (consuma crediti API).

> **📝 Correzioni (C4)**
>
> - 
> - 

---

## 5. Risultato H / I / J / Superbonus

### Punteggi FM (se indovini tutto)


| Voce           | Condizione           | Punti | Eccezione 0-0 |
| -------------- | -------------------- | ----- | ------------- |
| **H**          | Risultato esatto 1T  | +4    | +2            |
| **I**          | Risultato esatto 90′ | +8    | +6            |
| **J**          | Segno 1/X/2 (da I)   | +2    | —             |
| **Superbonus** | H + I + J insieme    | +12   | +8            |


File: `src/scoring/result_points.py`.

### Probabilità — priorità delle fonti

`build_distribution()` sceglie **un solo metodo**, in ordine:

| Priorità | Condizione | Fonte | Affidabilità |
|----------|------------|-------|--------------|
| 1 | Mercato HT/FT combinato | Quote `1-0/2-1` | Alta |
| 2 | Correct score FT **e** HT | OddsPapi / SofaScore | Alta |
| 3 | Solo correct score FT | OddsPapi (+ 1X2 1T da Odds API) | Media–alta |
| 4 | Nessun correct score | 1X2 + under/over (Odds API) | Bassa–media → **Poisson** |

**Quanto spesso Poisson?** Con `ODDSPAPI_API_KEY` attiva, per il Mondiale di solito abbiamo CS FT+HT → **priorità 2, Poisson quasi mai**. Poisson scatta senza OddsPapi, se fallisce, o se mancano mercati CS per quella partita.

File: `src/odds/distribution.py` → `build_distribution()`.

### Metodo A — Quote dirette (priorità 1–3)

**Dual correct score (OddsPapi, caso tipico):** devig su ogni punteggio FT e HT → marginali per somma → joint `P(HT,FT) ∝ P(HT)×P(FT)` con vincolo HT ≤ FT.

**Solo CS FT:** marginali FT dirette; per ogni FT si ripartisce su HT possibili pesando 1X2 al 1T (se c’è) e ~45% gol nel 1T.

### Metodo B — Poisson (fallback)

1. Devig **1X2** (+ opz. **over/under** per total gol atteso).
2. Grid search su **λ_casa, λ_ospite** per riprodurre 1X2 con matrice Poisson 0–9.
3. Split 1T/2T: λ_1T = 45% × λ, λ_2T = 55% × λ.
4. Joint = Poisson(1T) × Poisson(2T); marginali HT/FT per somma.

**Limite:** gol indipendenti → punteggi esatti meno precisi dei mercati CS diretti.

### EV per un candidato (ht, ft)

```
EV = P(HT esatto) × punti_H
   + P(FT esatto) × punti_I
   + P(segnо)     × punti_J
   + P(HT+FT+segno) × punti_superbonus
```

Si valutano tutte le coppie HT/FT plausibili (0–9 gol) e si ordina per EV totale.

File: `src/predict/result_ev.py` → `compute_ev()`, `rank_predictions()`.

> **📝 Correzioni (C5)**
>
> - [x] Spiegazione Poisson / marginali / frequenza — vedi sezioni sopra e risposta in chat
> -

---

## 6. Formazione (4 + vice)

### Vincoli

- **4 slot** scelti dal pool roster (escluso vice).
- Almeno **1 giocatore casa** e **1 ospite** nella formazione.
- **Vice allenatore**: fisso dallo screenshot (bonus gol ≥ 5).

### Probabilità giocatore

Per ogni giocatore nel roster, stima:

- `p_goal` — anytime scorer (API / OddsPapi / SofaScore / fallback Poisson per ruolo)
- `p_yellow`, `p_red`, rigori, autogol, clean sheet — da props mercato o euristiche per90

File: `src/odds/goalscorer.py`, `src/odds/player_props.py`.

### EV giocatore

```
EV = p_gol_azione × bonus_gol
   + p_rigore      × 3
   + p_gol_portiere × 10
   + p_clean_sheet × bonus (GK: da app; DEF: +1 fisso)
   + p_rigore_parato × 4
   − malus (giallo −1, rosso −2, autogol −2, rigore sbagliato −3)
```

File: `src/scoring/lineup_points.py`, payoffs in `src/scoring/lineup_rules.py`.

### Ottimizzazione

Enumerazione di tutte le combinazioni da 4 giocatori valide → massimo EV totale (+ vice).

File: `src/predict/lineup_ev.py` → `optimize_lineup()`.

> **📝 Correzioni (C6)**
>
> - 
> - 

---

## 7. Eventi K e L

### K — Primo sostituito (+5 pt)

Modello attuale (storico NT **disabilitato** in produzione):

- Prior per **ruolo** (es. attaccante > centrocampista > difensore)
- Aggiustamenti da **contesto partita** (favorita/sfavorita, total goals attesi, prob gol giocatore)
- Normalizzazione → P(primo sub) per ogni giocatore schierabile

```
EV_K = P(miglior candidato) × 5
```

File: `src/odds/event_kl_model.py` → `estimate_first_sub_probs()`.

### L — Primo ammonito (+4 pt)

1. Se disponibili: quote **first card** da OddsPapi / SofaScore.
2. Altrimenti: stima da probabilità cartellino giallo giocatore + peso partita.

```
EV_L = P(miglior candidato) × 4
```

File: `src/odds/event_kl_model.py` → `estimate_first_card_probs()`.

> **📝 Correzioni (C7)**
>
> - 
> - 

---

## 8. Output totale

```
EV formazione  = somma EV dei 4 scelti + vice
EV eventi      = EV_K + EV_L
```

Il report web mostra: miglior H/I/J, top alternative risultato, formazione consigliata, K/L, ranking giocatori per EV.

> **📝 Correzioni (C8)**
>
> - 
> - 

---

## 9. Devig e mediane

- Quote decimali → probabilità implicite → **devig** (proporzionale o two-way) per rimuovere margine bookmaker.
- Più bookmaker sulla stessa quota → **mediana** dei prezzi.

File: `src/odds/devig.py`, mediane in `src/odds/api_normalize.py`.

> **📝 Correzioni (C9)**
>
> - 
> - 

---

## 10. Configurazione


| Variabile                    | Ruolo                                                   |
| ---------------------------- | ------------------------------------------------------- |
| `ODDS_API_KEY`               | Obbligatoria — listing partite + quote base             |
| `OPENAI_API_KEY`             | Screenshot su cloud                                     |
| `ODDSPAPI_API_KEY`           | Correct score e props avanzati                          |
| `ODDS_REGION` / `ODDS_SPORT` | Default `eu`, `soccer_fifa_world_cup`                   |
| `FM_FAST_MODE`               | Timeout HTTP più stretti su cloud (vision esclusa: 90s) |


> **📝 Correzioni (C10)**
>
> - 
> - 

---

## 11. Limiti noti

- **K (sub):** senza storico sostituzioni NT reale, stima più debole.
- **Props giocatore:** dipende da copertura bookmaker; nomi OCR/vision devono matchare (`players_match` fuzzy).
- **Correct score:** se manca su tutte le fonti, distribuzione solo Poisson da 1X2 (meno precisa sui punteggi rari).
- **Crediti API:** ogni analisi con Refresh può costare 1–3+ richieste Odds API + OddsPapi; usare cache in produzione.
- **Render free tier:** cold start ~30s; analisi tipica 30–90s dopo lettura roster.

> **📝 Correzioni (C11)**
>
> - 
> - 

---

## 12. File chiave


| Area              | Path                                                       |
| ----------------- | ---------------------------------------------------------- |
| Entry analisi     | `src/predict/analyze.py`                                   |
| Prefetch quote    | `src/predict/prefetch.py`                                  |
| Vision screenshot | `src/players/vision_parse.py`                              |
| Match squadre     | `src/odds/api_normalize.py`                                |
| Distribuzione gol | `src/odds/distribution.py`                                 |
| EV risultato      | `src/predict/result_ev.py`                                 |
| EV formazione     | `src/predict/lineup_ev.py`, `src/scoring/lineup_points.py` |
| Eventi K/L        | `src/predict/event_ev.py`, `src/odds/event_kl_model.py`    |
| Web UI            | `src/web/app.py`                                           |


> **📝 Correzioni (C12)**
>
> - 
> - 

---

## 0. Note generali (non legate a una sezione)

> **📝 Correzioni (C0)**
>
> - 
> - 

