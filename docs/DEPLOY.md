# Deploy online (link pubblico)

L’app è **FastAPI + Python**. **Supabase** (Postgres, auth, storage) non ospita questo tipo di backend; va bene se in futuro vuoi salvare roster o cache in cloud.

Per un link gratuito consigliamo **Render** (free tier) o **Railway** (crediti trial).

## Render (gratuito, consigliato)

1. Crea un repo GitHub e carica il progetto (`.env` **non** va committato).
2. Vai su [render.com](https://render.com) → **New** → **Blueprint** (oppure **Web Service** da repo).
3. Se usi Blueprint, Render legge `render.yaml` in root.
4. In **Environment** imposta:
   - `ODDS_API_KEY` — da [the-odds-api.com](https://the-odds-api.com/)
   - `ODDSPAPI_API_KEY` — opzionale, da [oddspapi.io](https://oddspapi.io/)
5. Deploy → otterrai un URL tipo `https://fantamondiale-xxxx.onrender.com`.

**Nota free tier:** il servizio si **addormenta** dopo ~15 min senza visite (prima richiesta lenta). La cache quote su disco **non persiste** tra redeploy — usa Refresh solo quando serve.

### Deploy manuale con Docker (senza GitHub)

```powershell
docker build -t fantamondiale .
docker run -p 8765:8765 -e ODDS_API_KEY=xxx -e ODDSPAPI_API_KEY=yyy fantamondiale
```

Poi esponi la porta con Render/Fly/ngrok a tua scelta.

## Railway

1. `npm i -g @railway/cli` oppure [cli.new](https://cli.new)
2. `railway login`
3. Nella cartella del progetto: `railway init` → nuovo progetto
4. Imposta variabili: `railway variable set ODDS_API_KEY=...`
5. `railway up -m "fantamondiale web"`

Railway usa `Dockerfile` e `railway.toml` già presenti.

## Variabili ambiente

| Variabile | Obbligatoria | Descrizione |
|-----------|--------------|-------------|
| `ODDS_API_KEY` | Sì | The Odds API |
| `ODDSPAPI_API_KEY` | No | Correct score / props |
| `ODDS_REGION` | No | Default `eu` |
| `ODDS_SPORT` | No | Default `soccer_fifa_world_cup` |
| `PORT` | Auto | Impostata dal provider (Render/Railway) |

## Supabase in futuro (opzionale)

Se vuoi centralizzare i roster YAML:

- **Storage**: bucket `rosters/` con file per partita
- **Postgres**: tabella giocatori per query

Richiede codice aggiuntivo; l’app funziona già con YAML incollato nel form web.
