import httpx
from bs4 import BeautifulSoup
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class WebsiteAuditor:
    async def check_website(self, url: str) -> Dict[str, Any]:
        """
        Pings the listed URL asynchronously, verifies HTTP status,
        and parses HTML to verify mobile-responsiveness and SSL.
        """
        if not url:
            return {
                "website_status": "NONE",
                "audit_notes": "No website URL listed for this business."
            }
        
        # Ensure url starts with a protocol
        target_url = url.strip()
        if not target_url.startswith("http://") and not target_url.startswith("https://"):
            target_url = "http://" + target_url
            
        try:
            # We set a desktop user-agent to minimize false negatives from security blocks
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            # verify=False to avoid failing on self-signed certificates (still flags SSL status though)
            async with httpx.AsyncClient(follow_redirects=True, timeout=10.0, verify=False) as client:
                response = await client.get(target_url, headers=headers)
                
            if response.status_code >= 400:
                return {
                    "website_status": "BROKEN",
                    "audit_notes": f"Website returned HTTP status code: {response.status_code}"
                }
                
            # Run layout/SEO auditing with BeautifulSoup
            soup = BeautifulSoup(response.text, "html.parser")
            
            # 1. Mobile Responsiveness check
            viewport = soup.find("meta", attrs={"name": "viewport"})
            has_viewport = viewport is not None
            
            # 2. SSL/TLS check
            is_ssl = url.strip().startswith("https://") or response.url.scheme == "https"
            
            # 3. Simple layout/content thickness check
            text_content = soup.get_text()
            words = text_content.split()
            word_count = len(words)
            
            issues = []
            if not has_viewport:
                issues.append("missing viewport meta tag for mobile responsiveness")
            if not is_ssl:
                issues.append("not served over HTTPS (no SSL)")
            if word_count < 100:
                issues.append("low content/empty styling framework detected")
                
            if issues:
                return {
                    "website_status": "OUTDATED",
                    "audit_notes": f"Website accessibility OK, but has issues: {', '.join(issues)}."
                }
            else:
                return {
                    "website_status": "OK",
                    "audit_notes": "Website is fully operational, secure, and mobile-friendly."
                }
                
        except (httpx.RequestError, Exception) as e:
            logger.warning(f"Failed to audit website URL '{url}': {e}")
            return {
                "website_status": "BROKEN",
                "audit_notes": "Website is inaccessible (Error/Timeout)."
            }
