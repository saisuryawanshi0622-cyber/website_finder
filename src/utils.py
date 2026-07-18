import os
import logging
import sqlite3
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def save_to_csv(processed_leads: List[Dict[str, Any]], filename: str) -> None:
    """
    Saves the processed leads data structure to a CSV file.
    Filters/orders elements to only include standard columns.
    """
    columns = ["business_name", "address", "location_link", "phone_number", "website_status", "activity_score", "ai_pitch_draft"]
    try:
        import pandas as pd
        df = pd.DataFrame(processed_leads)
        # Ensure all columns exist
        for col in columns:
            if col not in df.columns:
                df[col] = ""
        # Project in correct order
        df = df[columns]
        df.to_csv(filename, index=False)
        logger.info(f"Successfully saved {len(processed_leads)} leads to CSV using pandas: {filename}")
    except ImportError:
        import csv
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for lead in processed_leads:
                row = {col: lead.get(col, "") for col in columns}
                writer.writerow(row)
        logger.info(f"Successfully saved {len(processed_leads)} leads to CSV using standard csv writer: {filename}")

def calculate_activity_score(rating: float, review_count: int) -> float:
    """
    Calculates lead activity score based on business rating and review counts.
    Returns 0.0 if there is no rating or reviews.
    """
    if not rating or not review_count or rating == 0.0 or review_count == 0:
        return 0.0
    # Formula modeled from school in pune:
    # EuroSchool Wakad: 4.5 stars -> 0.98
    # ORCHIDS Wadgaonsheri: 4.6 stars -> 0.98
    # ORCHIDS Nigdi: 4.7 stars -> 0.99
    score = 0.8 + 0.2 * (rating / 5.0)
    return round(score, 2)

def save_raw_leads_to_cache(leads: List[Dict[str, Any]], query: str) -> None:
    """
    Saves raw leads scraped from Google Maps to local SQLite database cache.
    """
    db_path = "leads_cache.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scraped_leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT,
            business_name TEXT,
            address TEXT,
            location_link TEXT UNIQUE,
            phone_number TEXT,
            website TEXT,
            rating REAL,
            review_count INTEGER,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    for lead in leads:
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO scraped_leads (
                    query, business_name, address, location_link, phone_number, website, rating, review_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                query,
                lead.get("business_name"),
                lead.get("address"),
                lead.get("location_link"),
                lead.get("phone_number"),
                lead.get("website"),
                lead.get("rating"),
                lead.get("review_count")
            ))
        except Exception as e:
            logger.warning(f"Error inserting cached lead {lead.get('business_name')}: {e}")
    conn.commit()
    conn.close()
    logger.info(f"Cached {len(leads)} leads into local database for query '{query}'")

def get_cached_leads(query: str) -> List[Dict[str, Any]]:
    """
    Checks if a query was run previously and loads cached leads from SQLite.
    """
    db_path = "leads_cache.db"
    if not os.path.exists(db_path):
        return []
        
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Check if table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='scraped_leads'")
    if not cursor.fetchone():
        conn.close()
        return []
        
    rows = cursor.execute("""
        SELECT business_name, address, location_link, phone_number, website, rating, review_count
        FROM scraped_leads
        WHERE query = ?
    """, (query,)).fetchall()
    
    leads = [dict(row) for row in rows]
    conn.close()
    return leads
