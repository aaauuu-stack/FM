"""Local web UI for Fantamondiale predictions."""

from __future__ import annotations

import asyncio
import html
import logging
import os
import sys
import time

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse

from odds.api_client import get_api_key, load_env_file, _project_root
from odds.memory_cache import warm_all_caches
from odds.request_cache import clear_request_cache
from players.screen_parse import roster_from_screenshots
from predict.analyze import analyze_match_from_roster
from predict.timing import reset_timings, timed, timing_summary
from web.html_render import render_analysis

logger = logging.getLogger(__name__)
IS_RENDER = bool(os.environ.get("RENDER"))

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
input[type=file] {
  background: var(--bg);
  border: 1px dashed var(--border);
  border-radius: 8px;
  color: var(--text);
  padding: 1rem;
  font: inherit;
}
.upload-hint { color: var(--muted); font-size: 0.85rem; margin: 0; }
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
.info {
  background: #1e293b;
  border: 1px solid var(--border);
  color: var(--text);
  padding: 0.85rem 1rem;
  border-radius: 8px;
  margin-bottom: 1rem;
  font-size: 0.9rem;
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
"""


def _esc(text: str) -> str:
    return html.escape(str(text))


def _page(body: str, title: str = "Fantamondiale 2026") -> str:
    return f"""<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(title)}</title>
  <style>{PAGE_CSS}</style>
</head>
<body>
  <div class="wrap">
    <header>
      <h1>Fantamondiale 2026 — Optimizer</h1>
      <p>Carica gli screenshot FM · partita e roster letti in automatico</p>
    </header>
    {body}
  </div>
</body>
</html>"""


def _form_html(
    *,
    refresh: bool = False,
    no_oddspapi: bool | None = None,
    no_scrape: bool | None = None,
    error: str = "",
) -> str:
    if no_scrape is None:
        no_scrape = False
    if no_oddspapi is None:
        no_oddspapi = False
    err = f'<div class="error">{_esc(error)}</div>' if error else ""
    return f"""
{err}
<form method="post" action="/predict" enctype="multipart/form-data">
  <label>Screenshot FM (partita + bonus giocatori)
    <input type="file" name="screenshots" accept="image/*" multiple required>
  </label>
  <p class="upload-hint">
    Carica 1–5 screen dall'app Fantamondiale (ordine libero).
    Almeno uno deve mostrare il banner partita in alto (es. Uzbekistan – Colombia);
    gli altri possono essere scroll con più giocatori.
  </p>
  {"<p class='upload-hint'>Analisi ~30–90 sec su cloud (tutte le fonti). Non chiudere la pagina.</p>" if IS_RENDER else ""}
  <div class="checks">
    <label><input type="checkbox" name="refresh" value="1"{" checked" if refresh else ""}> Refresh quote (API live)</label>
    <label><input type="checkbox" name="no_oddspapi" value="1"{" checked" if no_oddspapi else ""}> Salta OddsPapi</label>
    <label><input type="checkbox" name="no_scrape" value="1"{" checked" if no_scrape else ""}> Salta scraping</label>
  </div>
  <button type="submit" id="submit-btn">Analizza partita</button>
</form>
<p class="meta" style="margin-top:1rem">Usa cache di default — spunta Refresh solo quando vuoi aggiornare le quote.</p>
<script>
document.querySelector('form').addEventListener('submit', function() {{
  const btn = document.getElementById('submit-btn');
  btn.disabled = true;
  btn.textContent = 'Analisi in corso (30–90 sec)…';
}});
</script>
"""


@app.on_event("startup")
def _startup() -> None:
    load_env_file()
    logging.basicConfig(level=logging.INFO)
    warmed = warm_all_caches(_project_root())
    if warmed:
        logger.info("Cache in memoria: %d file da disco", warmed)


def _run_analysis(
    blobs: list[bytes],
    *,
    refresh: bool,
    use_oddspapi: bool,
    use_scrape: bool,
):
    reset_timings()
    clear_request_cache()
    started = time.perf_counter()
    with timed("ocr"):
        roster = roster_from_screenshots(blobs)
    logger.info(
        "OCR ok: %s vs %s, %d giocatori",
        roster.home,
        roster.away,
        len(roster.players),
    )
    with timed("quote_e_calcolo"):
        analysis = analyze_match_from_roster(
            roster,
            refresh=refresh,
            use_oddspapi=use_oddspapi,
            use_scrape=use_scrape,
        )
    logger.info(
        "Analisi totale %.1fs — %s",
        time.perf_counter() - started,
        timing_summary(),
    )
    return analysis


async def _read_uploads(screenshots: list[UploadFile]) -> list[bytes]:
    blobs: list[bytes] = []
    for upload in screenshots:
        if not upload.filename:
            continue
        data = await upload.read()
        if data:
            blobs.append(data)
    return blobs


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(_page(_form_html()))


@app.post("/predict", response_class=HTMLResponse)
async def predict(
    screenshots: list[UploadFile] = File(default=[]),
    screenshot: UploadFile | None = File(default=None),
    refresh: str = Form(""),
    no_oddspapi: str = Form(""),
    no_scrape: str = Form(""),
) -> HTMLResponse:
    do_refresh = refresh == "1"
    use_oddspapi = no_oddspapi != "1"
    use_scrape = no_scrape != "1"
    skip_scrape_checked = no_scrape == "1"
    skip_oddspapi_checked = no_oddspapi == "1"

    try:
        get_api_key()
    except RuntimeError as exc:
        return HTMLResponse(_page(_form_html(error=str(exc))))

    uploads = list(screenshots)
    if screenshot and screenshot.filename:
        uploads.append(screenshot)
    blobs = await _read_uploads(uploads)

    if not blobs:
        return HTMLResponse(
            _page(
                _form_html(
                    error="Nessuna immagine caricata.",
                    refresh=do_refresh,
                    no_scrape=skip_scrape_checked,
                )
            )
        )

    try:
        analysis = await asyncio.wait_for(
            asyncio.to_thread(
                _run_analysis,
                blobs,
                refresh=do_refresh,
                use_oddspapi=use_oddspapi,
                use_scrape=use_scrape,
            ),
            timeout=300.0,
        )
    except TimeoutError:
        diag = timing_summary()
        return HTMLResponse(
            _page(
                _form_html(
                    error=(
                        "Analisi troppo lenta (>5 min). "
                        f"Timing parziale: {diag}. "
                        "Se OCR è alto: usa 1 screenshot nitido. "
                        "Se sofascore/oddspapi è alto: riprova senza Refresh "
                        "(Render free tier, rete lenta verso SofaScore)."
                    ),
                    refresh=do_refresh,
                    no_oddspapi=skip_oddspapi_checked,
                    no_scrape=skip_scrape_checked,
                )
            )
        )
    except (ValueError, RuntimeError) as exc:
        return HTMLResponse(
            _page(
                _form_html(
                    error=str(exc),
                    refresh=do_refresh,
                    no_oddspapi=skip_oddspapi_checked,
                    no_scrape=skip_scrape_checked,
                )
            )
        )
    except Exception as exc:
        logger.exception("Analisi fallita")
        return HTMLResponse(
            _page(
                _form_html(
                    error=f"Errore durante l'analisi: {exc}",
                    refresh=do_refresh,
                    no_oddspapi=skip_oddspapi_checked,
                    no_scrape=skip_scrape_checked,
                )
            )
        )

    detected = (
        f'<div class="info">Letto dagli screenshot: '
        f"<strong>{_esc(analysis.home)}</strong> vs "
        f"<strong>{_esc(analysis.away)}</strong>"
    )
    if analysis.vice_name:
        detected += f" · Vice: {_esc(analysis.vice_name)} (+{analysis.vice_bonus})"
    detected += "</div>"

    result_html = detected + render_analysis(analysis)
    back = _form_html(
        refresh=do_refresh,
        no_oddspapi=skip_oddspapi_checked,
        no_scrape=skip_scrape_checked,
    )
    return HTMLResponse(
        _page(result_html + back, title=f"{analysis.home} vs {analysis.away}")
    )


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
