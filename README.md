# Fantamondiale 2026

Tool per pronostici Fantamondiale: risultato (H, I, J, superbonus) + formazione 4 giocatori.
Ogni raccomandazione include **EV totale e breakdown**.

**Una partita alla volta:** inserisci casa e ospite; per la formazione serve anche il roster bonus da screenshot FM.

## Setup rapido

1. Leggi **[docs/API_SETUP.md](docs/API_SETUP.md)** — guida completa alle due API
2. `copy .env.example .env` e compila le credenziali
3. `py -3 -m pip install -e ".[dev]"` — include `curl_cffi` per lo scrape
4. `py -3 -m cli.test_apis` — verifica che funzioni tutto

## Fase 2 — Risultato + formazione

Quando carichi gli **screenshot bonus giocatori**, salvo/aggiorno un file YAML e lancio:

```powershell
py -3 -m cli.predict_match --home Inghilterra --away Croazia --roster data/players/eng-cro.yaml
```

Output: pronostico risultato (H/I/J) **con EV** + eventi **K/L** + formazione **4+vice** **con EV**.

Nel YAML segna `vice_allenatore: true` sul giocatore già ticcato nello screen FM (bonus gol ≥ 5).

Template roster: `data/players/eng-cro.yaml`

## Interfaccia web (browser)

```powershell
py -3 -m pip install -e ".[web]"
py -3 -m cli.serve
```

Apri **http://127.0.0.1:8765** — form con casa/ospite, roster salvato o YAML incollato.
Usa cache di default; spunta **Refresh quote** solo quando vuoi chiamate API live.

**Deploy online (link pubblico):** vedi [docs/DEPLOY.md](docs/DEPLOY.md) — Render gratuito o Railway; Supabase non ospita FastAPI Python.

## Uso (solo risultato, Fase 1)

```powershell
# Analizza SOLO la partita che inserisci
py -3 -m cli.fetch_and_predict --home Inghilterra --away Croazia

# Solo elenco partite disponibili (nessun calcolo)
py -3 -m cli.fetch_and_predict --list
```

## Struttura

```
FM/
├── docs/API_SETUP.md       # Guida credenziali + spiegazione chiamate API
├── .env.example            # Template credenziali
├── data/cache/             # Cache automatica (Odds API + OddsPapi)
├── src/
│   ├── odds/
│   │   ├── api_client.py       # The Odds API
│   │   ├── goalscorer.py         # Goalscorer + Poisson fallback
│   │   ├── oddspapi_client.py    # OddsPapi (correct score)
│   │   ├── distribution.py       # Poisson / dual correct score
│   │   └── scrape_sofascore.py   # Fallback scrape
│   ├── players/
│   │   ├── models.py           # PlayerBonus, MatchRoster
│   │   └── roster_loader.py    # YAML da screenshot FM
│   ├── scoring/
│   │   ├── result_points.py
│   │   └── lineup_points.py    # EV per giocatore
│   ├── predict/
│   │   ├── result_ev.py
│   │   ├── lineup_ev.py        # Ottimizzatore 4 giocatori
│   │   └── ev_report.py        # Output EV unificato
│   └── cli/
│       ├── fetch_and_predict.py  # Solo risultato (Fase 1)
│       ├── predict_match.py      # Risultato + formazione (Fase 2)
│       └── test_apis.py
├── data/
│   ├── players/              # Roster bonus per partita (da screenshot)
│   ├── penalty_takers.yaml   # Rigoristi ufficiali per nazionale
│   └── national_stats.yaml   # Gol/cartellini per90 nazionale
└── tests/
```

## Provider

| | The Odds API | OddsPapi | Web scrape |
|---|---|---|---|
| 1X2, O/U | ✅ | — | — |
| Correct score FT + 1T | — | ✅ | ✅ (fallback) |
| Goalscorer | OddsPapi props / SofaScore scrape / The Odds API / Poisson (ultimo) | — | — |
| Cartellini giocatore | OddsPapi props / SofaScore scrape+stats / stats NT | — | — |

## Test

```powershell
py -3 -m pytest
```
