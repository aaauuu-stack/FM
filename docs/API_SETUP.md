# Guida setup API — The Odds API + OddsPapi

Questa guida spiega **passo passo** come ottenere le credenziali e come funzionano le chiamate.  
Una volta configurato il `.env`, **non devi più fare nulla manualmente** — il tool chiama tutto in automatico.

---

## Panoramica: chi fa cosa

```
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│   The Odds API      │     │      OddsPapi       │     │   Web scrape        │
├─────────────────────┤     ├─────────────────────┤     ├─────────────────────┤
│ 1X2 (h2h)           │     │ Correct Score (FT)  │     │ SofaScore (FT + 1T) │
│ Over/Under 2.5      │     │ Correct Score (1T)  │     │ se mancano quote    │
│ Goalscorer (fase 2) │     │ multi-bookmaker     │     │                     │
└─────────┬───────────┘     └──────────┬──────────┘     └──────────┬──────────┘
          │                            │                            │
          └────────────────────────────┴────────────────────────────┘
                                       ▼
                              fetch_and_predict
                                       ▼
                             Raccomandazione FM
```

| Provider | Cosa fornisce | Quando serve |
|---|---|---|
| **The Odds API** | 1X2, O/U | Sempre (base + fallback Poisson) |
| **OddsPapi** | Risultato esatto FT + 1T | Confidenza **high** (superbonus) |
| **Web scrape** | Correct score mancanti | Fallback automatico se OddsPapi incompleto |

---

## Parte 1 — The Odds API

### 1.1 Registrazione

1. Vai su [https://the-odds-api.com/](https://the-odds-api.com/)
2. Clicca **Get API Key** / registrati
3. Piano free: **500 crediti/mese** (bastano per ~70 partite Mondiale)

### 1.2 Metti la key nel progetto

```powershell
cd C:\Users\elias\OneDrive\Desktop\FM
copy .env.example .env
```

Apri `.env` e incolla:

```
ODDS_API_KEY=la_tua_key_qui
```

### 1.3 Come funziona la chiamata (sotto il cofano)

**Endpoint usato dal tool:**

```
GET https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/odds/
    ?apiKey=LA_TUA_KEY
    &regions=eu
    &markets=h2h,totals
    &oddsFormat=decimal
```

Il tool:
1. Scarica la risposta (o riusa **cache 3 ore** in `data/cache/odds/`)
2. Fa la **mediana** delle quote tra i bookmaker
3. Rimuove il margine (**de-vig**) per ottenere probabilità

### 1.4 Test

```powershell
py -3 -m cli.test_apis --odds-only
```

---

## Parte 2 — OddsPapi (correct score)

Alternativa semplice a Betfair: **una sola API key**, niente account exchange né certificati.

### 2.1 Registrazione

1. Vai su [https://oddspapi.io/](https://oddspapi.io/)
2. Registrati e copia la **API key** dal dashboard
3. Piano free: ~**250 richieste/mese** (catalogo + fixture + odds per partita)

### 2.2 Configura `.env`

```
ODDSPAPI_API_KEY=la_tua_key_oddspapi
```

### 2.3 Come funzionano le chiamate OddsPapi

Il tool fa **3 chiamate** per ogni partita (con cache):

#### A — Catalogo mercati calcio (cache 7 giorni)

```
GET https://api.oddspapi.io/v4/markets?sportId=10&language=en&apiKey=...
```

Trova gli ID dei mercati **Correct Score** (FT) e **Correct Score 1st Half**.

#### B — Fixture nel range della partita (cache 3 ore)

```
GET https://api.oddspapi.io/v4/fixtures
    ?sportId=10
    &from=2026-06-12T21:00:00Z
    &to=2026-06-18T21:00:00Z
    &hasOdds=true
    &bookmakers=pinnacle
    &apiKey=...
```

Cerca `England` vs `Croatia` (accetta anche nomi italiani: `Inghilterra`, `Croazia`).

#### C — Quote correct score (cache 3 ore)

```
GET https://api.oddspapi.io/v4/odds
    ?fixtureId=...
    &bookmakers=pinnacle
    &oddsFormat=decimal
    &apiKey=...
```

Estrae le quote per ogni risultato esatto (es. `1-0`, `2-1`).

### 2.4 Test

```powershell
py -3 -m cli.test_apis --oddspapi-only
py -3 -m cli.test_apis --oddspapi-only --home England --away Croatia
```

---

## Parte 3 — Web scrape (fallback quote mancanti)

Se OddsPapi non ha il correct score (es. Pinnacle non lo pubblica per quella partita), il tool prova automaticamente **SofaScore** via web.

### 3.1 Dipendenza consigliata

SofaScore blocca richieste bot. Installa `curl_cffi` per impersonare un browser reale:

```powershell
py -3 -m pip install curl_cffi
# oppure con dev deps:
py -3 -m pip install -e ".[dev]"
```

Nessuna API key richiesta — cache locale in `data/cache/scrape/`.

### 3.2 Test

```powershell
py -3 -m cli.test_apis --scrape-only --home England --away Croatia
```

### 3.3 Disabilitare lo scrape

```powershell
py -3 -m cli.fetch_and_predict --home Inghilterra --away Croazia --no-scrape
```

---

## Parte 4 — Uso (una partita alla volta)

```powershell
# Raccomandazione per la partita che inserisci (IT o EN)
py -3 -m cli.fetch_and_predict --home Inghilterra --away Croazia

# Solo elenco partite su Odds API (nessun fetch extra, nessun calcolo)
py -3 -m cli.fetch_and_predict --list

# Disabilita fonti opzionali
py -3 -m cli.fetch_and_predict --home England --away Croatia --no-oddspapi --no-scrape
```

Output atteso con OddsPapi + scrape:

```
Fonte: The Odds API + OddsPapi + SofaScore (live) | Modello: dual_correct_score | Confidenza: high
```

Senza OddsPapi:

```
Fonte: The Odds API (live) | Modello: poisson_h2h | Confidenza: medium
```

---

## Troubleshooting

| Errore | Causa | Soluzione |
|---|---|---|
| `ODDS_API_KEY not set` | `.env` mancante | Copia `.env.example` → `.env` |
| Odds API 401 | Key sbagliata | Ricontrolla key su the-odds-api.com |
| Odds API 0 partite | Mondiale non ancora in calendario API | Normale prima del torneo |
| `ODDSPAPI_API_KEY non impostata` | Key mancante | Registrati su oddspapi.io |
| OddsPapi HTTP 401/403 | Key invalida o scaduta | Rigenera key nel dashboard |
| Fixture non trovato | Partita fuori range o non su Pinnacle | Prova nome inglese; verifica che la partita abbia quote |
| `Nessuna quota correct score` | Mercato non su Pinnacle | Lo scrape SofaScore prova a colmarlo |
| Scrape FAIL / 403 | Anti-bot | `pip install curl_cffi` |

---

## Costi

| Servizio | Costo | Limite free |
|---|---|---|
| The Odds API | Gratis / da $30/mese | 500 crediti/mese |
| OddsPapi | Gratis / piani a pagamento | ~250 req/mese |

Per il Mondiale FM i free tier **bastano** se non ricalcoli ogni partita decine di volte al giorno.

---

## Fase 2 — formazione (attiva)

```powershell
py -3 -m cli.predict_match --home Inghilterra --away Croazia --roster data/players/eng-cro.yaml
```

- **Risultato** (H/I/J/superbonus) con EV — come Fase 1
- **Formazione 4 giocatori** (≥1 casa + ≥1 ospite) con EV
- Bonus giocatori da YAML (`data/players/*.yaml`), compilato dagli screenshot FM

### Goalscorer

The Odds API espone `player_goal_scorer_anytime` solo su alcune competizioni.
Per il Mondiale 2026 il mercato può rispondere **422** (non ancora supportato): in quel caso
il tool stima **P(gol) con Poisson** dalle quote partita (1X2/O-U).

Quando il mercato goalscorer sarà disponibile, verrà usato automaticamente al posto del fallback.
