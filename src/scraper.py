import logging
import random
import time
from typing import List, Dict, Any
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

class MapsScraper:
    def __init__(self, headless: bool = True, delay_range: tuple = (1, 3)):
        self.headless = headless
        self.delay_range = delay_range

    def run_search(self, niche: str, location: str, max_results: int = 20, check_stop_cb=None) -> List[Dict[str, Any]]:
        """
        Runs browser automation to search Google Maps and extract business details.
        """
        query = f"{niche} in {location}"
        logger.info(f"Starting Playwright scraper for search: '{query}' (headless={self.headless})")
        
        leads = []
        
        with sync_playwright() as p:
            # Configure browser launch options to prevent detection
            browser = p.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-gpu",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled"
                ]
            )
            
            # Modern user agents for rotation
            user_agents = [
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/120.0",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
            ]
            selected_ua = random.choice(user_agents)
            logger.info(f"Using rotated User-Agent: {selected_ua}")

            # Set a normal desktop browser user-agent and viewport
            context = browser.new_context(
                user_agent=selected_ua,
                viewport={"width": 1280, "height": 800}
            )
            
            # Route requests to block heavy assets (images, media, fonts) to save CPU and network bandwidth
            def block_heavy_assets(route):
                if route.request.resource_type in ["image", "media", "font"]:
                    route.abort()
                else:
                    route.continue_()
            context.route("**/*", block_heavy_assets)
            
            page = context.new_page()
            
            # Go to Google Maps
            logger.info("Navigating to Google Maps...")
            try:
                page.goto("https://www.google.com/maps", timeout=60000)
                # Wait for either searchbox or consent form to appear
                page.wait_for_timeout(2000) # Short pause to allow redirection if any
                
                # Check for Google Consent Form
                consent_selector = (
                    'form[action*="consent"] button, '
                    'button[aria-label="Accept all"], '
                    'button:has-text("Accept all"), '
                    'button:has-text("I agree"), '
                    'button:has-text("Alle akzeptieren"), '
                    'button:has-text("Tout accepter"), '
                    'button:has-text("Aceptar todo"), '
                    'button:has-text("Accetta tutto"), '
                    'button:has-text("Akkoord")'
                )
                consent_buttons = page.locator(consent_selector)
                if consent_buttons.count() > 0:
                    logger.info("Google Consent/Cookie banner detected. Clicking accept...")
                    try:
                        consent_buttons.first.click()
                        # Wait for page to reload/redirect after consent
                        page.wait_for_load_state("load")
                        page.wait_for_timeout(2000)
                    except Exception as ce:
                        logger.warning(f"Could not click consent button: {ce}")
            except Exception as e:
                logger.error(f"Failed to load Google Maps: {e}")
                browser.close()
                return leads

            # Search for the query
            logger.info(f"Searching for '{query}'...")
            try:
                search_selector = "input#searchboxinput, input[name='q']"
                page.wait_for_selector(search_selector, timeout=20000)
                
                # Click to focus the search box
                page.locator(search_selector).click()
                # Clear any existing value
                page.locator(search_selector).fill("")
                # Fill with query
                page.locator(search_selector).fill(query)
                page.wait_for_timeout(1000)
                
                # Try to click the search button
                search_btn = page.locator("button#searchbox-searchbutton")
                if search_btn.count() > 0:
                    logger.info("Found search button, clicking it...")
                    search_btn.click()
                else:
                    logger.info("Search button not found, pressing Enter...")
                    page.keyboard.press("Enter")
                
                # Wait for results or navigation to begin
                page.wait_for_timeout(3000)
                
                # Check if results started loading; if not, try pressing Enter as a fallback
                feed_count = page.locator('div[role="feed"], a[href*="/maps/place/"]').count()
                if feed_count == 0 and "/maps/place/" not in page.url:
                    logger.info("Results not loaded yet, trying secondary Enter keypress...")
                    page.locator(search_selector).focus()
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(3000)
            except Exception as e:
                logger.error(f"Search box input element not found or search failed: {e}")
                screenshot_path = "src/static/debug_screenshot.png"
                try:
                    page.screenshot(path=screenshot_path)
                    logger.info(f"Saved debug screenshot to {screenshot_path} for analysis.")
                except Exception as se:
                    logger.error(f"Failed to save screenshot: {se}")
                browser.close()
                return leads

            # Wait for the results pane/feed to load or single result redirect
            logger.info("Waiting for search results...")
            feed_selector = 'div[role="feed"]'
            place_links = []
            
            try:
                # Wait for feed or place links to appear on the page
                page.wait_for_selector('div[role="feed"], a[href*="/maps/place/"]', timeout=20000)
            except Exception as e:
                # If wait_for_selector timed out, it might be a single result redirect or CAPTCHA
                if "/maps/place/" in page.url:
                    logger.info("Single business listing detected via direct URL redirection.")
                else:
                    screenshot_path = "src/static/debug_screenshot.png"
                    try:
                        page.screenshot(path=screenshot_path)
                        logger.error(f"Results feed not found. Saved debug screenshot to {screenshot_path}. Current URL: {page.url}, Title: {page.title()}")
                    except Exception as se:
                        logger.error(f"Failed to save screenshot: {se}")
                    browser.close()
                    return leads

            # Determine if we are on a single listing detail page or a search results page
            if "/maps/place/" in page.url:
                logger.info(f"Direct listing redirect detected. Single target link: {page.url}")
                place_links = [page.url]
            else:
                # Wait a bit for page stabilization
                page.wait_for_timeout(2000)
                
                # Check if feed selector exists
                feed_exists = page.locator(feed_selector).count() > 0
                
                if feed_exists:
                    logger.info("Scrolling results pane to gather business links...")
                    last_height = page.evaluate(f"document.querySelector('{feed_selector}').scrollHeight")
                    no_change_count = 0
                    
                    while True:
                        if check_stop_cb and check_stop_cb():
                            logger.info("Scraper scrolling stopped by user request.")
                            break
                        
                        # Scroll the feed element down
                        page.evaluate(f"document.querySelector('{feed_selector}').scrollBy(0, 3000)")
                        time.sleep(random.uniform(1.5, 2.5))
                        
                        # Extract currently loaded links that are place listings
                        current_links = page.evaluate(
                            f"Array.from(document.querySelectorAll('{feed_selector} a[href*=\"/maps/place/\"]')).map(a => a.href)"
                        )
                        
                        # Filter duplicates while maintaining order
                        for link in current_links:
                            if link not in place_links:
                                place_links.append(link)
                        
                        logger.info(f"Found {len(place_links)} business links so far...")
                        if max_results > 0 and len(place_links) >= max_results:
                            place_links = place_links[:max_results]
                            break
                        
                        # Check scroll height to see if we reached the end
                        new_height = page.evaluate(f"document.querySelector('{feed_selector}').scrollHeight")
                        if new_height == last_height:
                            no_change_count += 1
                            if no_change_count >= 5:  # Retried 5 times and height didn't change
                                logger.info("Reached the end of the Google Maps results list.")
                                break
                        else:
                            no_change_count = 0
                            last_height = new_height
                else:
                    # Feed selector does not exist but we might have place links on the page
                    logger.info("Feed selector not found on page, gathering direct place links...")
                    current_links = page.evaluate(
                        "Array.from(document.querySelectorAll('a[href*=\"/maps/place/\"]')).map(a => a.href)"
                    )
                    for link in current_links:
                        if link not in place_links:
                            place_links.append(link)
                    logger.info(f"Found {len(place_links)} business links without feed scroll.")

            # Restrict list to max_results requested
            if max_results > 0:
                place_links = place_links[:max_results]
            logger.info(f"Gathered {len(place_links)} total target links. Starting detailed extraction...")
            
            # Navigate to each business listing detail page and extract information
            for i, link in enumerate(place_links):
                if check_stop_cb and check_stop_cb():
                    logger.info("Scraper detail extraction stopped by user request.")
                    break
                logger.info(f"Processing lead {i+1}/{len(place_links)}: {link}")
                
                # Add random delay to prevent detection
                delay = random.uniform(self.delay_range[0], self.delay_range[1])
                time.sleep(delay)
                
                try:
                    # Load using 'domcontentloaded' to return immediately after DOM is parsed, skipping heavy async assets
                    page.goto(link, timeout=30000, wait_until="domcontentloaded")
                    # Wait for details panel header to load (usually an h1)
                    page.wait_for_selector("h1", timeout=10000)
                    
                    # Extract Business Name
                    name = ""
                    h1_element = page.locator("h1")
                    if h1_element.count() > 0:
                        name = h1_element.first.inner_text().strip()
                    
                    if not name:
                        logger.warning(f"Could not extract name for listing: {link}. Skipping.")
                        continue
                    
                    # Extract Address (Data Item ID is stable)
                    address = ""
                    address_btn = page.locator('button[data-item-id="address"]')
                    if address_btn.count() > 0:
                        raw_address = address_btn.first.inner_text().strip()
                        # Clean map pin icon  and strip newlines
                        address = raw_address.replace("", "").replace("\n", " ").strip()
                    
                    # Extract Phone Number (Data Item ID contains phone:tel:)
                    phone = ""
                    phone_btn = page.locator('button[data-item-id^="phone"]')
                    if phone_btn.count() > 0:
                        raw_phone = phone_btn.first.inner_text().strip()
                        # Clean special icons like  and format
                        phone = raw_phone.replace("", "").strip()
                    
                    # Extract Website (Data Item ID authority is stable)
                    website = ""
                    website_btn = page.locator('a[data-item-id="authority"]')
                    if website_btn.count() > 0:
                        website = website_btn.first.get_attribute("href") or ""
                    else:
                        # Fallback check on authority buttons
                        website_btn_fallback = page.locator('button[data-item-id="authority"]')
                        if website_btn_fallback.count() > 0:
                            website = website_btn_fallback.first.inner_text().strip()
                    
                    # Clean up URL parameter tracking from website URL
                    if website and "?" in website:
                        website = website.split("?")[0]
                        
                    # Extract rating and review count
                    rating = 0.0
                    review_count = 0
                    
                    # Google Maps rating wrapper is div.F7nice
                    rating_selector = "div.F7nice"
                    if page.locator(rating_selector).count() > 0:
                        rating_text = page.locator(rating_selector).first.inner_text().strip()
                        # Output format is usually "4.5(120)" or "4.5\n(120)"
                        if rating_text:
                            parts = rating_text.split("(")
                            if len(parts) >= 2:
                                try:
                                    rating = float(parts[0].replace(",", ".").strip())
                                    review_count = int(parts[1].replace(")", "").replace(",", "").replace(".", "").strip())
                                except ValueError:
                                    pass
                    
                    lead_data = {
                        "business_name": name,
                        "address": address,
                        "location_link": link,
                        "phone_number": phone,
                        "website": website,
                        "rating": rating,
                        "review_count": review_count
                    }
                    
                    logger.info(f"Scraped Lead: {name} | Phone: {phone} | Website: {website} | Rating: {rating} ({review_count} reviews)")
                    leads.append(lead_data)
                    
                except Exception as e:
                    logger.error(f"Error scraping details for link {link}: {e}")
                    continue
            
            browser.close()
            
        logger.info(f"Scraper finished. Extracted {len(leads)} raw leads.")
        return leads
