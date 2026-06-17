"""Local web UI for Fantamondiale predictions."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse

from odds.api_client import get_api_key, load_env_file
from predict.analyze import analyze_match, analyze_match_from_yaml
from web.html_render import render_analysis

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLAYERS_DIR = PROJECT_ROOT / "data" / "players"

app = FastAPI(title="Fantamondiale 2026", docs_url=None, redoc_url=None)

PAGE_CSS = """
:root {
  --bg: #0f1419;
  --card: #1a2332;
  --text: #e7ecf3;
  --muted: #8b9cb3;
  --accent: #3d9cf5;
  --green: #34d399;
  --border: #2a3544;
}
* { box-sizing: border-box; }
body {
  font-family: "Segoe UI", system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
  margin: 0;
  line-height: 1.5;
}
.wrap { max-width: 920px; margin: 0 auto; padding: 1.5rem; }
header { margin-bottom: 2rem; }
header h1 { margin: 0; font-size: 1.6rem; }
header p { color: var(--muted); margin: 0.4rem 0 0; }
form {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1.25rem;
  display: grid;
  gap: 1rem;
}
label { display: grid; gap: 0.35rem; font-size: 0.9rem; }
input[type=text], select, textarea {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  padding: 0.55rem 0.75rem;
  font: inherit;
}
textarea { min-height: 140px; font-family: ui-monospace, monospace; font-size: 0.85rem; }
.row { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
.checks { display: flex; flex-wrap: wrap; gap: 1rem; }
.checks label { display: flex; align-items: center; gap: 0.4rem; }
button {
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 0.75rem 1.25rem;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}
button:hover { filter: brightness(1.08); }
.error {
  background: #3f1d1d;
  border: 1px solid #7f1d1d;
  color: #fecaca;
  padding: 1rem;
  border-radius: 8px;
  margin-bottom: 1rem;
}
.report, .analysis > section {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1.1rem 1.25rem;
  margin: 1rem 0;
}
.report h2, .analysis h1 { margin-top: 0; font-size: 1.15rem; }
.meta { color: var(--muted); font-size: 0.88rem; }
.pick { font-size: 1.05rem; }
.ev-total { color: var(--green); font-size: 1.1rem; }
.summary { font-size: 1.05rem; margin: 1rem 0; }
table { width: 100%; border-collapse: collapse; font-size: 0.88rem; margin-top: 0.75rem; }
th, td { text-align: left; padding: 0.35rem 0.5rem; border-bottom: 1px solid var(--border); }
th { color: var(--muted); font-weight: 500; }
.alts, .analysis ul { color: var(--muted); font-size: 0.9rem; }
.baseline { color: var(--muted); font-size: 0.88rem; }
.roster-toggle { font-size: 0.85rem; color: var(--accent); cursor: pointer; }
@media (max-width: 640px) { .row { grid-template-columns: 1fr; } }
"""


def _list_rosters() -> list[str]:
    if not PLAYERS_DIR.is_dir():
        return []
    return sorted(p.name for p in PLAYERS_DIR.glob("*.yaml"))


def _page(body: str, title: str = "Fantamondiale 2026") -> str:
    return f"""<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>{PAGE_CSS}</style>
</head>
<body>
  <div class="wrap">
    <header>
      <h1>Fantamondiale 2026 — Optimizer</h1>
      <p>Risultato H/I/J · Formazione 4+vice · Eventi K/L · una partita alla volta</p>
    </header>
    {body}
  </div>
</body>
</html>"""


def _form_html(
    *,
    home: str = "Inghilterra",
    away: str = "Croazia",
    roster: str = "",
    roster_yaml: str = "",
    refresh: bool = False,
    no_oddspapi: bool = False,
    no_scrape: bool = False,
) -> str:
    rosters = _list_rosters()
    default_roster = roster or (rosters[0] if rosters else "")
    options = "".join(
        f'<option value="{r}"{" selected" if r == default_roster else ""}>{r}</option>'
        for r in rosters
    )
    roster_block = ""
    if roster_yaml:
        roster_block = f"""
<label>Roster YAML (incolla dallo screenshot)
  <textarea name="roster_yaml" placeholder="home: Inghilterra&#10;away: Croazia&#10;players: ...">{roster_yaml}</textarea>
</label>
"""
    else:
        roster_block = f"""
<label>Roster salvato
  <select name="roster">{options}</select>
</label>
<p class="meta"><a href="/?paste=1">Oppure incolla YAML</a></p>
"""

    return f"""
<form method="post" action="/predict">
  <div class="row">
    <label>Casa
      <input type="text" name="home" value="{home}" required>
    </label>
    <label>Ospite
      <input type="text" name="away" value="{away}" required>
    </label>
  </div>
  {roster_block}
  <div class="checks">
    <label><input type="checkbox" name="refresh" value="1"{" checked" if refresh else ""}> Refresh quote (API live)</label>
    <label><input type="checkbox" name="no_oddspapi" value="1"{" checked" if no_oddspapi else ""}> Salta OddsPapi</label>
    <label><input type="checkbox" name="no_scrape" value="1"{" checked" if no_scrape else ""}> Salta scraping</label>
  </div>
  <button type="submit">Analizza partita</button>
</form>
<p class="meta" style="margin-top:1rem">Usa cache di default — spunta Refresh solo quando vuoi aggiornare le quote.</p>
"""


@app.on_event("startup")
def _startup() -> None:
    load_env_file()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    paste = request.query_params.get("paste") == "1"
    body = _form_html(roster_yaml=" " if paste else "")
    return HTMLResponse(_page(body))


@app.post("/predict", response_class=HTMLResponse)
async def predict(
    home: str = Form(...),
    away: str = Form(...),
    roster: str = Form(""),
    roster_yaml: str = Form(""),
    refresh: str = Form(""),
    no_oddspapi: str = Form(""),
    no_scrape: str = Form(""),
) -> HTMLResponse:
    do_refresh = refresh == "1"
    use_oddspapi = no_oddspapi != "1"
    use_scrape = no_scrape != "1"
    yaml_text = roster_yaml.strip()

    try:
        get_api_key()
    except RuntimeError as exc:
        err = f'<div class="error">{exc}</div>'
        return HTMLResponse(_page(err + _form_html(home=home, away=away, roster=roster)))

    try:
        if yaml_text:
            analysis = analyze_match_from_yaml(
                home,
                away,
                yaml_text,
                refresh=do_refresh,
                use_oddspapi=use_oddspapi,
                use_scrape=use_scrape,
            )
        else:
            roster_path = str(PLAYERS_DIR / roster)
            if not Path(roster_path).is_file():
                raise ValueError(f"Roster non trovato: {roster}")
            analysis = analyze_match(
                home,
                away,
                roster_path,
                refresh=do_refresh,
                use_oddspapi=use_oddspapi,
                use_scrape=use_scrape,
            )
    except ValueError as exc:
        err = f'<div class="error">{exc}</div>'
        return HTMLResponse(
            _page(
                err
                + _form_html(
                    home=home,
                    away=away,
                    roster=roster,
                    roster_yaml=yaml_text,
                    refresh=do_refresh,
                    no_oddspapi=not use_oddspapi,
                    no_scrape=not use_scrape,
                )
            )
        )

    result_html = render_analysis(analysis)
    back = _form_html(
        home=home,
        away=away,
        roster=roster,
        roster_yaml=yaml_text,
        refresh=do_refresh,
        no_oddspapi=not use_oddspapi,
        no_scrape=not use_scrape,
    )
    return HTMLResponse(_page(result_html + back, title=f"{home} vs {away}"))


def main() -> int:
    import argparse
    import os

    import uvicorn

    parser = argparse.ArgumentParser(description="Avvia interfaccia web Fantamondiale")
    default_host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    default_port = int(os.environ.get("PORT", "8765"))
    parser.add_argument("--host", default=default_host)
    parser.add_argument("--port", type=int, default=default_port)
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    print(f"Fantamondiale web UI: {url}", file=sys.stderr)
    print("Ctrl+C per fermare", file=sys.stderr)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
