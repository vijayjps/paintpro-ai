"""
AI photo assessment using Groq vision (llama-3.2-11b-vision-preview).
Free tier: ~7,000 requests/day. No extra API key needed — reuses GROQ_API_KEY.
"""

import base64
import os
import json
import urllib.request


def assess_photo(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    """
    Send a house photo to Groq vision model and return structured assessment.
    Returns dict with keys: condition, prep_needed, color_suggestions, quote_range, summary.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return {"error": "GROQ_API_KEY not set"}

    b64 = base64.b64encode(image_bytes).decode()
    prompt = (
        "You are an expert painting contractor assessing a house exterior photo. "
        "Provide a concise JSON response with exactly these keys:\n"
        "  condition: one of 'Excellent', 'Good', 'Fair', 'Poor', 'Very Poor'\n"
        "  prep_needed: list of prep tasks needed (e.g. ['Power washing', 'Scraping', 'Priming'])\n"
        "  color_suggestions: list of 2-3 suggested colour schemes (e.g. 'Warm beige + white trim')\n"
        "  estimated_sqft: rough exterior sq footage estimate as integer\n"
        "  quote_range: estimated job cost range as string (e.g. '$3,500 - $5,000')\n"
        "  priority: HOT, WARM, or COLD as a painting lead\n"
        "  summary: 2-sentence description of what you see and why it needs painting\n"
        "Respond with valid JSON only, no markdown."
    )

    payload = json.dumps({
        "model": "llama-3.2-11b-vision-preview",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
                {"type": "text",      "text": prompt}
            ]
        }],
        "max_tokens": 512,
        "temperature": 0.3,
    }).encode()

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read().decode())
            text = resp["choices"][0]["message"]["content"].strip()
            # Strip markdown fences if present
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text)
    except Exception as exc:
        return {"error": str(exc)}
