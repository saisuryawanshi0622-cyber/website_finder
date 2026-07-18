import os
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class OutreachGenerator:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.model = None
        if self.api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                self.model = genai.GenerativeModel("gemini-1.5-flash")
                logger.info("OutreachGenerator: Configured Gemini generative model (gemini-1.5-flash).")
            except Exception as e:
                logger.warning(f"OutreachGenerator: Could not initialize Gemini API: {e}. Using template fallbacks.")
        else:
            logger.info("OutreachGenerator: GEMINI_API_KEY not found. Operating with fallback template logic.")

    def generate_pitch(self, lead_context: Dict[str, Any], niche: str) -> str:
        """
        Generates a 3-sentence sales pitch targeting the lead's website weaknesses.
        """
        # If Gemini is configured, use it
        if self.model:
            try:
                prompt = self._build_prompt(lead_context, niche)
                response = self.model.generate_content(prompt)
                pitch = response.text.strip()
                # Clean enclosing quotes if added by the LLM
                if pitch.startswith('"') and pitch.endswith('"'):
                    pitch = pitch[1:-1]
                return pitch
            except Exception as e:
                logger.warning(f"OutreachGenerator: Gemini API invocation failed: {e}. Falling back to templates.")

        # Fallback template logic
        return self._generate_fallback_pitch(lead_context, niche)

    def _build_prompt(self, lead_context: Dict[str, Any], niche: str) -> str:
        name = lead_context.get("business_name", "your business")
        address = lead_context.get("address", "your area")
        rating = lead_context.get("rating", 0.0)
        review_count = lead_context.get("review_count", 0)
        status = lead_context.get("website_status", "NONE")
        notes = lead_context.get("audit_notes", "")

        prompt = (
            f"You are an expert sales copywriter. Write a short, highly personalized cold pitch to {name} based in {address}.\n"
            f"They are a {niche} business.\n"
        )

        if status == "NONE":
            prompt += f"They do not have a website listed, but they have a strong presence on Google Maps with {rating} stars and {review_count} reviews.\n"
            prompt += "Explain the benefit of having a website in exactly 3 sentences, offering a custom booking system.\n"
        elif status == "BROKEN":
            prompt += f"They have a website listed, but the link is currently broken ({notes}). They have {rating} stars and {review_count} reviews.\n"
            prompt += "Explain the benefit of fixing and upgrading their broken link to a modern website in exactly 3 sentences, offering a custom landing page/booking system.\n"
        else:
            prompt += f"Their website was audited and found to have issues: {notes}. They have {rating} stars and {review_count} reviews.\n"
            prompt += "Explain the benefit of updating their outdated website in exactly 3 sentences, offering a custom redesign.\n"

        prompt += (
            "\nRule: Write exactly three sentences. Do not use markdown styling. Keep it professional, friendly, and output ONLY the sales pitch."
        )
        return prompt

    def _generate_fallback_pitch(self, lead_context: Dict[str, Any], niche: str) -> str:
        name = lead_context.get("business_name", "your business")
        rating = lead_context.get("rating", 0.0)
        review_count = lead_context.get("review_count", 0)
        status = lead_context.get("website_status", "NONE")
        
        # Capitalize niche
        n_cap = niche.strip().title() if niche else "your specialty"

        if status == "NONE":
            return (
                f"Hi {name} Team, we noticed your business has a strong presence on Google with {rating} stars and {review_count} reviews, but you don't have a website listed. "
                f"A professional, mobile-friendly website for {n_cap} services can help you automate bookings and stand out from local competitors. "
                f"Would you be open to a quick, 5-minute chat this week to see how a custom site could help grow your business?"
            )
        elif status == "BROKEN":
            # Matches original copy: "Hi Delhi Public School Pune Team, we noticed your business is doing amazing work in the community on Google. Since you currently has a website listed, but the link is broken (404/500/timeout), we would love to build you a modern, mobile-optimized site to automate bookings and capture local search leads. Let us know if you'd be open to a quick chat!"
            return (
                f"Hi {name} Team, we noticed your business is doing amazing work in the community on Google. "
                f"Since you currently have a website listed, but the link is broken (404/500/timeout), we would love to build you a modern, mobile-optimized site to automate bookings and capture local search leads. "
                f"Let us know if you'd be open to a quick chat!"
            )
        else: # OUTDATED
            return (
                f"Hi {name} Team, we found your business on Google with a great {rating}-star rating and {review_count} reviews. "
                f"While checking your website, we noticed some areas for improvement such as mobile responsiveness and security. "
                f"Upgrading to a modern, fast-loading design can significantly improve your conversion rate and customer experience. "
                f"Would you be open to a brief chat about this?"
            )
