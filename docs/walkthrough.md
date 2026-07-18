# Walkthrough: AI Lead Finder Agent

This walkthrough outlines how the completed **AI Lead Finder Agent** operates, the files included in the project, and how you can run and use it.

---

## 1. Project Directory Structure

The completed project is organized as follows:
```text
ai-agent/
├── docs/
│   ├── problem_statement.md   # Core goals and business context
│   ├── architecture.md        # Technical design and data flow diagrams
│   └── implementation.md      # Phase-by-phase implementation details
├── src/
│   ├── __init__.py
│   ├── scraper.py             # Playwright Google Maps search & scaper module
│   ├── auditor.py             # Async website pinger & SEO/mobile responsiveness auditor
│   ├── ai_generator.py        # Gemini API pitch generation & fallback mock system
│   └── utils.py               # Helper scripts (Pandas CSV saver, SQLite caching, activity scorer)
├── main.py                    # Typer command-line interface entry point
├── requirements.txt           # Python dependency specifications
├── .env                       # Environment configuration file
├── .env.example               # Template environment configuration file
└── leads_cache.db             # Local SQLite database caching raw scraped results
```

---

## 2. Command-Line Options

The CLI is run via `main.py` inside the virtual environment:
```bash
.venv/bin/python main.py [OPTIONS]
```

### Available Options:
* `-n, --niche TEXT`: The business category to search (e.g., `Plumbers`, `Dentists`, `Restaurants`). **[Required]**
* `-l, --location TEXT`: The geographic target (e.g., `Burlingame`, `Chicago`). **[Required]**
* `-o, --output TEXT`: The filepath to save the final `.csv` leads list. (Default: `leads_output.csv`)
* `-m, --max-results INTEGER`: Maximum count of leads to extract. (Default: `20`)
* `--headless / --no-headless`: Runs the browser scraper hidden (headless) or visible. (Default: `--headless`)
* `--use-cache / --no-cache`: Instructs the agent to check the local SQLite cache (`leads_cache.db`) before launching a new maps scraper. (Default: `--use-cache`)

---

## 3. How the Pipeline Works

```text
[Input Niche & Location]
         │
         ▼
 ┌──────────────┐      Yes      ┌────────────────────────┐
 │ Cached Leads?├──────────────>│ Load leads from Cache  │
 └──────┬───────┘               └───────────┬────────────┘
        │ No                                │
        ▼                                   │
 ┌──────────────┐                           │
 │ Scraping     │                           │
 │ Playwright   │                           │
 └──────┬───────┘                           │
        │                                   │
        ▼                                   │
 ┌──────────────┐                           │
 │ Save Cache   │                           │
 └──────┬───────┘                           │
        ├───────────────────────────────────┘
        ▼
 ┌──────────────┐
 │ Async Audit  │<── httpx checks HTTP status, SSL, mobile responsiveness
 └──────┬───────┘
        ▼
 ┌──────────────┐
 │ Score Leads  │<── Weighs ratings & reviews to calculate Activity Score
 └──────┬───────┘
        ▼
 ┌──────────────┐
 │ AI Outreach  │<── Generates custom 3-sentence email pitches using Gemini
 └──────┬───────┘
        ▼
 ┌──────────────┐
 │ CSV Export   │──> Saves final formatted list to leads_output.csv
 └──────────────┘
```

---

## 4. Run Example & Verification

If you run the search twice:
1. **First Run (Scraping):**
   ```bash
   .venv/bin/python main.py --niche "Plumbers" --location "Burlingame" --max-results 2 --use-cache
   ```
   *Logs show:*
   * Starting scraping for query "Plumbers in Burlingame"...
   * Found 18 business links... Scraping JK Plumbing, USA Leak Detector.
   * Saving to SQLite cache...
   * Auditing websites...
   * Calculating scores and generating pitches...
   * Saving final results to `leads_output.csv`.

2. **Second Run (Loaded from Cache):**
   ```bash
   .venv/bin/python main.py --niche "Plumbers" --location "Burlingame" --max-results 2 --use-cache
   ```
   *Logs show:*
   * Checking SQLite cache for query: 'Plumbers in Burlingame'...
   * Found 2 cached leads for 'Plumbers in Burlingame'. Skipping Google Maps scraping.
   * Loaded 2 raw leads from cache.
   * Auditing websites...
   * Saving final results to `leads_output.csv`. (Execution time drops from 35s to under 3s!)

---

## 5. Phase 6: E2E Verification & Safety Features

### Safety Configurations:
* **User-Agent Rotation:** The scraper selects a random user agent from a pool of modern browser profiles (Chrome, Edge, Firefox, Safari on Windows/Mac) to avoid footprinting:
  ```text
  [INFO] src.scraper: Using rotated User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ... Edg/120.0.0.0
  ```
* **Randomized Sleep Delays:** Inter-page navigations wait for a random interval within the config ranges (e.g., `SCRAPE_DELAY_MIN` to `SCRAPE_DELAY_MAX` seconds) to mimic human interactions.

### Final Pipeline Test (Niche: Bakery, Location: Burlingame):
* **Execution:** `.venv/bin/python main.py --niche "Bakery" --location "Burlingame" --max-results 2 --no-cache`
* **Output Headers verified:** `business_name`, `address`, `location_link`, `phone_number`, `website_status`, `activity_score`, `ai_pitch_draft`
* **CSV Result file:** **[leads_output.csv](file:///Users/saisuryawanshi/Desktop/ai%20agent/leads_output.csv)**
