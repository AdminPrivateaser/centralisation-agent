"""Centra Audit — FastAPI app."""
import asyncio
import json
import os
import uuid
from datetime import datetime
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from datetime import date as _date

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'), override=True)

from scraper import scrape_all_channels
from audit_engine import run_audit, _precompute_quanti
from notion_writer import create_audit_page

app = FastAPI(title="Centra Audit")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# In-memory store: audit_id -> {status, progress, result, params}
audits: dict[str, dict] = {}

REQUIRED_FIELDS = ["venue_name", "segment", "address"]
OPTIONAL_FIELDS = ["website", "instagram", "gmb", "joy_widget", "vitrine", "mvi", "rwg_active"]


def get_missing_fields(params: dict) -> list[str]:
    return [f for f in REQUIRED_FIELDS if not params.get(f)]


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    params = dict(request.query_params)
    missing = get_missing_fields(params)
    return templates.TemplateResponse("index.html", {
        "request": request,
        "params": params,
        "missing": missing,
    })


@app.post("/audit/start")
async def start_audit(
    request: Request,
    background_tasks: BackgroundTasks,
    venue_name: str = Form(...),
    segment: str = Form(...),
    address: str = Form(...),
    website: str = Form(""),
    instagram: str = Form(""),
    gmb: str = Form(""),
    joy_widget: str = Form(""),
    vitrine: str = Form(""),
    mvi: str = Form(""),
    rwg_active: str = Form("non"),
    linktree: str = Form(""),
    gmb_reservation_doublon: str = Form("inconnu"),
    saas_platforms: str = Form(""),
    autres_canaux: str = Form(""),
):
    audit_id = str(uuid.uuid4())[:8]
    params = {
        "venue_name": venue_name,
        "segment": segment,
        "address": address,
        "website": website,
        "instagram": instagram,
        "gmb": gmb,
        "joy_widget": joy_widget,
        "vitrine": vitrine,
        "mvi": mvi,
        "rwg_active": rwg_active,
        "linktree": linktree,
        "gmb_reservation_doublon": gmb_reservation_doublon,
        "saas_platforms": saas_platforms,
        "autres_canaux": autres_canaux,
    }
    audits[audit_id] = {
        "status": "running",
        "progress": ["Démarrage de l'audit..."],
        "result": None,
        "params": params,
        "created_at": datetime.now().isoformat(),
        "notion_url": None,
    }
    background_tasks.add_task(run_audit_task, audit_id, params, request)
    return JSONResponse({"audit_id": audit_id})


async def run_audit_task(audit_id: str, params: dict, request: Request):
    store = audits[audit_id]

    async def progress(msg: str):
        store["progress"].append(msg)

    try:
        await progress("🔍 Scraping des canaux en cours...")
        scraped = await scrape_all_channels(params)
        await progress(f"✅ Scraping terminé — {len([k for k,v in scraped.items() if isinstance(v, dict) and v.get('available')])} canaux trouvés")

        # Pre-compute quanti facts in Python (source of truth — not Claude)
        quanti_facts = _precompute_quanti(params, scraped)
        store["quanti_facts"] = quanti_facts

        await progress("🤖 Analyse Claude du playbook de centralisation...")
        audit_result = await run_audit(params, scraped, progress_callback=progress)
        await progress("✅ Audit structuré généré")

        # Override Claude's quanti with Python-computed facts (guaranteed correct)
        ch = audit_result.get("channels", {})
        mapping = {"website": "website_quanti", "instagram": "instagram_quanti",
                   "rwg": "rwg_quanti", "gmb": "gmb_quanti"}
        for ch_key, fact_key in mapping.items():
            val = quanti_facts.get(fact_key)
            if val is not None and ch_key in ch:
                ch[ch_key]["quanti_ok"] = val
        # Force MVI criterion status in instagram
        ig_has_mvi = quanti_facts.get("instagram_has_mvi")
        for c in ch.get("instagram", {}).get("criteria", []):
            label = c.get("label", "").lower()
            if "mvi" in label or "numéro" in label or "numero" in label:
                if ig_has_mvi:
                    c["status"] = "ok"
                    c["points"] = c.get("max_points", 4)

        base_url = os.getenv("RAILWAY_PUBLIC_DOMAIN", str(request.base_url).rstrip("/"))
        railway_url = f"{base_url}/result/{audit_id}"

        await progress("📝 Création de la page Notion...")
        notion_url = await create_audit_page(params, audit_result, railway_url)
        store["notion_url"] = notion_url
        await progress(f"✅ Page Notion créée")

        store["result"] = audit_result
        store["status"] = "done"
        await progress("🎉 Audit terminé !")

    except Exception as e:
        store["status"] = "error"
        store["error"] = str(e)
        await progress(f"❌ Erreur : {e}")


@app.get("/audit/{audit_id}/progress")
async def audit_progress(audit_id: str):
    """SSE endpoint to stream audit progress."""
    async def event_stream() -> AsyncGenerator[str, None]:
        last_idx = 0
        while True:
            store = audits.get(audit_id)
            if not store:
                yield "data: {\"error\": \"Audit non trouvé\"}\n\n"
                break

            messages = store["progress"]
            for msg in messages[last_idx:]:
                yield f"data: {json.dumps({'msg': msg, 'status': store['status']})}\n\n"
                last_idx = len(messages)

            if store["status"] in ("done", "error"):
                redirect = f"/result/{audit_id}" if store["status"] == "done" else None
                yield f"data: {json.dumps({'done': True, 'redirect': redirect, 'status': store['status']})}\n\n"
                break

            await asyncio.sleep(1)

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@app.get("/result/{audit_id}", response_class=HTMLResponse)
async def result(request: Request, audit_id: str):
    store = audits.get(audit_id)
    if not store:
        return HTMLResponse("<h1>Audit non trouvé</h1>", status_code=404)
    if store["status"] != "done":
        return templates.TemplateResponse("loading.html", {"request": request, "audit_id": audit_id})
    return templates.TemplateResponse("result.html", {
        "request": request,
        "audit": store["result"],
        "params": store["params"],
        "notion_url": store.get("notion_url"),
        "audit_id": audit_id,
        "now": _date.today().strftime("%d/%m/%Y"),
        "quanti_facts": store.get("quanti_facts", {}),
        "quanti_override": {
            "website":  store.get("quanti_facts", {}).get("website_quanti"),
            "gmb":      store.get("quanti_facts", {}).get("gmb_quanti"),
            "rwg":      store.get("quanti_facts", {}).get("rwg_quanti"),
            "instagram": store.get("quanti_facts", {}).get("instagram_quanti"),
            "instagram_has_mvi": store.get("quanti_facts", {}).get("instagram_has_mvi"),
        },
    })


@app.get("/health")
async def health():
    return {"status": "ok"}
