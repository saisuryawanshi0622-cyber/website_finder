import os
import logging
import typer
from dotenv import load_dotenv
from src.scraper import MapsScraper
from src.utils import save_to_csv, calculate_activity_score, get_cached_leads, save_raw_leads_to_cache
from src.ai_generator import OutreachGenerator

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

app = typer.Typer(help="AI Lead Finder Agent Command Line Interface")

import asyncio
from src.auditor import WebsiteAuditor

async def audit_all_websites(raw_leads):
    auditor = WebsiteAuditor()
    audited_results = []
    for lead in raw_leads:
        url = lead.get("website")
        audit_res = await auditor.check_website(url)
        audited_results.append(audit_res)
    return audited_results

@app.command()
def run(
    niche: str = typer.Option(None, "--niche", "-n", help="Business niche/category (optional)"),
    location: str = typer.Option(..., "--location", "-l", help="Target city/location (e.g., Chicago)"),
    output: str = typer.Option("leads_output.csv", "--output", "-o", help="Output CSV path"),
    max_results: int = typer.Option(0, "--max-results", "-m", help="Maximum number of leads to scrape (0 for unlimited)"),
    headless: bool = typer.Option(True, "--headless/--no-headless", help="Run browser in headless mode"),
    use_cache: bool = typer.Option(True, "--use-cache/--no-cache", help="Use local SQLite cache if query has been executed previously")
):
    """
    Runs the lead generation, verification, and qualification pipeline.
    """
    # Determine categories to scan
    is_multi_scan = False
    if not niche or niche.strip() == "":
        is_multi_scan = True
        niches_to_search = ["shops", "restaurants", "salons", "auto repair", "dentists", "bakeries"]
        logger.info(f"Starting full city scan for location: '{location}' across categories: {niches_to_search}")
    else:
        niches_to_search = [niche]
        logger.info(f"Starting pipeline for Niche: '{niche}', Location: '{location}'")

    raw_leads = []
    seen_links = set()

    for current_niche in niches_to_search:
        query = f"{current_niche} in {location}"
        niche_leads = []

        if use_cache:
            logger.info(f"Checking SQLite cache for query: '{query}'...")
            try:
                cached = get_cached_leads(query)
                if cached:
                    logger.info(f"Found {len(cached)} cached leads for '{query}'.")
                    if max_results > 0:
                        cached = cached[:max_results]
                    niche_leads = cached
            except Exception as e:
                logger.warning(f"Failed to load leads from cache: {e}. Scraping fresh data.")

        if not niche_leads:
            logger.info(f"Step 1: Scraping Google Maps for '{query}'...")
            delay_min = int(os.getenv("SCRAPE_DELAY_MIN", "1"))
            delay_max = int(os.getenv("SCRAPE_DELAY_MAX", "3"))
            
            scraper = MapsScraper(headless=headless, delay_range=(delay_min, delay_max))
            niche_leads = scraper.run_search(niche=current_niche, location=location, max_results=max_results)
            
            if niche_leads:
                logger.info(f"Successfully scraped {len(niche_leads)} raw leads for '{query}'. Saving to SQLite cache...")
                try:
                    save_raw_leads_to_cache(niche_leads, query)
                except Exception as e:
                    logger.warning(f"Failed to save leads to SQLite cache: {e}")

        for lead in niche_leads:
            link = lead.get("location_link")
            if link not in seen_links:
                seen_links.add(link)
                # Attach specific niche context to the lead for custom pitch personalization
                lead["niche_context"] = current_niche
                raw_leads.append(lead)

    if not raw_leads:
        logger.warning("No leads were scraped or found in cache. Exiting.")
        raise typer.Exit(code=1)

    logger.info(f"Finished gathering leads. Total unique leads collected: {len(raw_leads)}")
    
    # 2. Auditing
    logger.info("Step 2: Checking and Auditing Websites...")
    audit_results = asyncio.run(audit_all_websites(raw_leads))
    
    # 3. AI Generation & Activity Scoring
    logger.info("Step 3: Calculating Activity Scores and Generating AI Pitches...")
    pitch_generator = OutreachGenerator()
    
    processed_leads = []
    for lead, audit in zip(raw_leads, audit_results):
        # Calculate qualified activity score
        activity_score = calculate_activity_score(lead["rating"], lead["review_count"])
        
        # We only generate pitch draft for leads that actually have website issues (NONE, BROKEN, OUTDATED)
        if audit["website_status"] in ["NONE", "BROKEN", "OUTDATED"]:
            lead_context = {**lead, "website_status": audit["website_status"], "audit_notes": audit["audit_notes"]}
            current_niche = lead.get("niche_context", niche or "shops")
            pitch = pitch_generator.generate_pitch(lead_context, current_niche)
        else:
            pitch = "N/A (Business already has a functional, modern website)."
            
        processed_leads.append({
            "business_name": lead["business_name"],
            "address": lead["address"],
            "location_link": lead["location_link"],
            "phone_number": lead["phone_number"],
            "website_status": audit["website_status"],
            "activity_score": activity_score,
            "ai_pitch_draft": pitch
        })
        
    logger.info(f"Saving final results to {output}...")
    save_to_csv(processed_leads, output)
    logger.info("Phase 5 pipeline execution completed successfully.")

@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Bind socket to this host"),
    port: int = typer.Option(8000, "--port", "-p", help="Bind socket to this port")
):
    """
    Launches the web dashboard and REST API server.
    """
    import uvicorn
    logger.info(f"Starting web server at http://{host}:{port}...")
    uvicorn.run("src.server:app", host=host, port=port, reload=True)

if __name__ == "__main__":
    app()
