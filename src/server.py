import os
import logging
import asyncio
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Dict, Any

from src.scraper import MapsScraper
from src.utils import save_to_csv, calculate_activity_score, get_cached_leads, save_raw_leads_to_cache
from src.ai_generator import OutreachGenerator
from src.auditor import WebsiteAuditor

# Custom Log Handler to stream logs to UI
class InMemoryLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        log_entry = self.format(record)
        self.records.append(log_entry)

    def clear(self):
        self.records.clear()

    def get_all(self):
        return self.records

# Initialize logger and add handler
logger = logging.getLogger("src")
logger.setLevel(logging.INFO)
in_memory_logger = InMemoryLogHandler()
in_memory_logger.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
logger.addHandler(in_memory_logger)

# Also intercept main-level logs if needed
main_logger = logging.getLogger("__main__")
main_logger.addHandler(in_memory_logger)

app = FastAPI(title="AI Lead Finder Dashboard")

# Global pipeline state
class PipelineState:
    def __init__(self):
        self.is_running = False
        self.stop_requested = False
        self.leads = []
        self.error = None
        self.niche = ""
        self.location = ""
        
        # Load existing leads from CSV on startup if present
        csv_path = "leads_output.csv"
        if os.path.exists(csv_path):
            import csv
            try:
                with open(csv_path, "r", newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        try:
                            row["activity_score"] = float(row.get("activity_score", 0.0))
                        except ValueError:
                            row["activity_score"] = 0.0
                        self.leads.append(row)
            except Exception as e:
                logging.getLogger("src").warning(f"Failed to load initial leads from CSV: {e}")

state = PipelineState()

class ScrapeRequest(BaseModel):
    niche: str = ""
    location: str
    max_results: int = 0
    use_cache: bool = True
    headless: bool = True

async def audit_all_websites(raw_leads, check_stop_cb=None):
    auditor = WebsiteAuditor()
    sem = asyncio.Semaphore(10)  # Limit concurrency to 10 audits at a time
    
    async def audit_with_sem(lead):
        if check_stop_cb and check_stop_cb():
            return {"website_status": "NONE", "audit_notes": "Audit stopped."}
        url = lead.get("website")
        async with sem:
            return await auditor.check_website(url)
            
    tasks = [audit_with_sem(lead) for lead in raw_leads]
    return await asyncio.gather(*tasks)

def run_pipeline_task(niche: str, location: str, max_results: int, use_cache: bool, headless: bool):
    global state
    state.is_running = True
    state.stop_requested = False
    state.error = None
    
    is_multi_scan = False
    if not niche or niche.strip() == "":
        is_multi_scan = True
        niches_to_search = ["shops", "restaurants", "salons", "auto repair", "dentists", "bakeries"]
        state.niche = "Multi-Category Scan"
    else:
        niches_to_search = [niche]
        state.niche = niche
        
    state.location = location
    in_memory_logger.clear()
    
    logger.info(f"Starting web pipeline for Niche: '{state.niche}', Location: '{location}'")
    
    try:
        raw_leads = []
        seen_links = set()
        
        for current_niche in niches_to_search:
            if state.stop_requested:
                logger.info("Pipeline stopped by user request before category search.")
                break
                
            query = f"{current_niche} in {location}"
            niche_leads = []
            
            if use_cache:
                logger.info(f"Checking SQLite cache for '{query}'...")
                try:
                    cached = get_cached_leads(query)
                    if cached:
                        logger.info(f"Found {len(cached)} cached leads for '{query}'.")
                        if max_results > 0:
                            cached = cached[:max_results]
                        niche_leads = cached
                except Exception as e:
                    logger.warning(f"Cache load error: {e}. Scraping fresh data.")

            if not niche_leads:
                logger.info(f"Launching Playwright scraper for '{query}'...")
                delay_min = int(os.getenv("SCRAPE_DELAY_MIN", "1"))
                delay_max = int(os.getenv("SCRAPE_DELAY_MAX", "3"))
                
                scraper = MapsScraper(headless=headless, delay_range=(delay_min, delay_max))
                niche_leads = scraper.run_search(
                    niche=current_niche,
                    location=location,
                    max_results=max_results,
                    check_stop_cb=lambda: state.stop_requested
                )
                
                if niche_leads and not state.stop_requested:
                    logger.info(f"Scraped {len(niche_leads)} raw leads for '{query}'. Caching results...")
                    save_raw_leads_to_cache(niche_leads, query)
            else:
                logger.info(f"Loaded {len(niche_leads)} leads from cache for '{query}'.")

            for lead in niche_leads:
                link = lead.get("location_link")
                if link not in seen_links:
                    seen_links.add(link)
                    lead["niche_context"] = current_niche
                    raw_leads.append(lead)

            if state.stop_requested:
                logger.info("Pipeline stopped by user request during Category loop.")
                break

        if not raw_leads:
            logger.warning("No leads found or process aborted early before any leads found. Exiting pipeline.")
            state.is_running = False
            return
            
        logger.info(f"Finished gathering leads. Total unique leads collected: {len(raw_leads)}")

        # Website Audit
        audit_results = []
        if not state.stop_requested:
            logger.info("Auditing business websites asynchronously...")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            audit_results = loop.run_until_complete(
                audit_all_websites(raw_leads, check_stop_cb=lambda: state.stop_requested)
            )
            loop.close()
        else:
            logger.info("Skipping website audit due to stop request.")

        # Qualification and AI Outreach
        logger.info("Qualifying leads and generating personalized AI outreach pitches...")
        pitch_generator = OutreachGenerator()
        
        from concurrent.futures import ThreadPoolExecutor
        
        def process_lead_item(item):
            lead, audit = item
            status = audit["website_status"]
            if status not in ["NONE", "BROKEN", "OUTDATED"]:
                return None
                
            activity_score = calculate_activity_score(lead["rating"], lead["review_count"])
            lead_context = {**lead, "website_status": status, "audit_notes": audit["audit_notes"]}
            current_niche = lead.get("niche_context", niche or "shops")
            pitch = pitch_generator.generate_pitch(lead_context, current_niche)
                
            return {
                "business_name": lead["business_name"],
                "address": lead["address"],
                "location_link": lead["location_link"],
                "phone_number": lead["phone_number"],
                "website": lead["website"] or "",
                "website_status": status,
                "activity_score": activity_score,
                "ai_pitch_draft": pitch,
                "audit_notes": audit["audit_notes"]
            }
            
        processed_leads = []
        if not state.stop_requested:
            with ThreadPoolExecutor(max_workers=10) as executor:
                results = executor.map(process_lead_item, zip(raw_leads, audit_results))
                processed_leads = [r for r in results if r is not None]

        if processed_leads:
            logger.info("Saving final results to CSV...")
            save_to_csv(processed_leads, "leads_output.csv")
            state.leads = processed_leads
            logger.info("Pipeline completed (or partially stopped). Results updated.")
        else:
            logger.info("No leads processed.")
        
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        state.error = str(e)
    finally:
        state.is_running = False

@app.post("/api/run")
def start_scrape(req: ScrapeRequest, background_tasks: BackgroundTasks):
    if state.is_running:
        raise HTTPException(status_code=400, detail="Pipeline is already running.")
    background_tasks.add_task(
        run_pipeline_task,
        req.niche,
        req.location,
        req.max_results,
        req.use_cache,
        req.headless
    )
    return {"message": "Pipeline started in background."}

@app.post("/api/stop")
def stop_scrape():
    global state
    if not state.is_running:
        raise HTTPException(status_code=400, detail="Pipeline is not running.")
    state.stop_requested = True
    logger.info("Stop request received. Stopping pipeline...")
    return {"message": "Stop request submitted."}

@app.get("/api/status")
def get_status():
    return {
        "is_running": state.is_running,
        "leads_count": len(state.leads),
        "leads": state.leads,
        "error": state.error
    }

@app.get("/api/logs")
def get_logs():
    return {"logs": in_memory_logger.get_all()}

@app.get("/api/download")
def download_csv():
    csv_path = "leads_output.csv"
    if os.path.exists(csv_path):
        # Format a dynamic user-friendly filename based on search query
        safe_niche = "".join(c for c in state.niche if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
        safe_location = "".join(c for c in state.location if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
        if safe_niche and safe_location:
            filename = f"leads_report_{safe_niche}_{safe_location}.csv"
        else:
            filename = "leads_output.csv"
        return FileResponse(csv_path, media_type="text/csv", filename=filename)
    raise HTTPException(status_code=404, detail="CSV file not found. Run a search first.")

# Serve Dashboard UI
@app.get("/")
def get_dashboard():
    # Attempt to load static/index.html
    html_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    # If not written yet, serve temporary message
    return HTMLResponse("<h2>Loading AI Lead Finder Dashboard...</h2>")

# Mount static folder
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)
app.mount("/static", StaticFiles(directory=static_dir), name="static")
