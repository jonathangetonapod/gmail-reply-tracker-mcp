"""
AI-powered interest detection to find missed opportunities in campaign replies.

This module uses a hybrid approach:
1. Fast keyword-based analysis for obvious interest signals
2. Claude API for nuanced/unclear cases
"""

import re
import os
import logging
from typing import Dict, List, Optional
from anthropic import Anthropic

logger = logging.getLogger(__name__)


# Interest signal keywords (strong positive indicators)
STRONG_INTEREST_KEYWORDS = [
    r'\bpricing\b',
    r'\bcost\b',
    r'\bschedule\b',
    r'\bmeeting\b',
    r'\bdemo\b',
    r'\bcall\b',
    r'\binterested\b',
    r'\byes\b',
    r'\bsounds good\b',
    r'\btell me more\b',
    r'\bsend.*info\b',
    r'\bbudget\b',
    r'\bwhen can\b',
    r'\bhow much\b',
    r'\blet\'s talk\b',
    r'\blet\'s discuss\b',
    r'\blet\'s connect\b',
    r'\blet\'s chat\b',
    r'\bwould love to\b',
    r'\bwould like to\b',
    r'\bi\'d like to\b',
    r'\bi want to\b',
    r'\bi need\b',
    r'\bwe need\b',
    r'\bcan you\b',
    r'\bplease send\b',
    r'\bshare.*detail\b',
    r'\bmore information\b',
    r'\bfollow up\b',
    r'\bnext step\b',
]

# Neutral/question keywords (moderate interest)
MODERATE_INTEREST_KEYWORDS = [
    r'\bhow does\b',
    r'\bwhat is\b',
    r'\btell me about\b',
    r'\bcurious about\b',
    r'\bexplain\b',
    r'\bquestion\b',
    r'\bclarif\b',
]

# Negative indicators (definitely not interested)
NEGATIVE_KEYWORDS = [
    r'\bnot interested\b',
    r'\bno thank\b',
    r'\bunsubscribe\b',
    r'\bremove me\b',
    r'\bstop.*email\b',
    r'\bdon\'t contact\b',
    r'\bnot.*right time\b',
    r'\bnot a fit\b',
    r'\balready have\b',
    r'\bnot looking\b',
    r'\bno longer\b',
]

# Auto-reply indicators
AUTO_REPLY_KEYWORDS = [
    r'\bout of office\b',
    r'\bautomatic reply\b',
    r'\bauto.{0,5}reply\b',
    r'\bvacation\b',
    r'\bmaternity leave\b',
    r'\bparental leave\b',
    r'\bon leave\b',
    r'\breturning.*\d+/\d+\b',  # "returning 12/25"
]


def analyze_reply_with_keywords(reply_text: str) -> Dict:
    """
    Fast keyword-based analysis to categorize email replies.

    Args:
        reply_text: The email reply body text

    Returns:
        {
            "category": "hot" | "warm" | "cold" | "auto_reply" | "unclear",
            "confidence": 0-100,
            "matched_keywords": [...],
            "reason": str
        }
    """
    if not reply_text or not reply_text.strip():
        return {
            "category": "unclear",
            "confidence": 0,
            "matched_keywords": [],
            "reason": "Empty reply"
        }

    text_lower = reply_text.lower()

    # Check for auto-replies first (highest priority)
    auto_matches = []
    for pattern in AUTO_REPLY_KEYWORDS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            auto_matches.append(pattern)

    if auto_matches:
        return {
            "category": "auto_reply",
            "confidence": 95,
            "matched_keywords": auto_matches,
            "reason": "Auto-reply detected (out of office, vacation, etc.)"
        }

    # Check for negative signals
    negative_matches = []
    for pattern in NEGATIVE_KEYWORDS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            negative_matches.append(pattern)

    if negative_matches:
        return {
            "category": "cold",
            "confidence": 90,
            "matched_keywords": negative_matches,
            "reason": f"Negative interest signals found: {', '.join(negative_matches[:2])}"
        }

    # Check for strong interest signals
    strong_matches = []
    for pattern in STRONG_INTEREST_KEYWORDS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            strong_matches.append(pattern)

    if len(strong_matches) >= 2:
        return {
            "category": "hot",
            "confidence": 85,
            "matched_keywords": strong_matches,
            "reason": f"Multiple strong interest signals: {', '.join(strong_matches[:3])}"
        }
    elif len(strong_matches) == 1:
        return {
            "category": "hot",
            "confidence": 75,
            "matched_keywords": strong_matches,
            "reason": f"Strong interest signal: {strong_matches[0]}"
        }

    # Check for moderate interest signals
    moderate_matches = []
    for pattern in MODERATE_INTEREST_KEYWORDS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            moderate_matches.append(pattern)

    if moderate_matches:
        return {
            "category": "warm",
            "confidence": 60,
            "matched_keywords": moderate_matches,
            "reason": f"Moderate interest signals: {', '.join(moderate_matches[:2])}"
        }

    # Very short replies are usually unclear
    if len(reply_text.strip()) < 20:
        return {
            "category": "unclear",
            "confidence": 30,
            "matched_keywords": [],
            "reason": "Reply too short to determine intent"
        }

    # No clear signals = unclear
    return {
        "category": "unclear",
        "confidence": 40,
        "matched_keywords": [],
        "reason": "No clear interest or disinterest signals detected"
    }


def analyze_reply_with_claude(reply_text: str, subject: str = "") -> Dict:
    """
    Use Claude API to analyze nuanced/unclear replies.

    Args:
        reply_text: The email reply body text
        subject: The email subject line (optional, provides context)

    Returns:
        {
            "category": "hot" | "warm" | "cold" | "auto_reply" | "unclear",
            "confidence": 0-100,
            "reason": str
        }
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")

    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set. Falling back to keyword analysis only.")
        return {
            "category": "unclear",
            "confidence": 0,
            "reason": "Claude API not configured"
        }

    try:
        client = Anthropic(api_key=api_key)

        prompt = f"""Analyze this email reply from a cold outreach campaign and categorize the lead's interest level.

Subject: {subject}

Reply:
{reply_text}

Categorize this reply as one of:
- HOT: Strong buying signals, wants to talk/meet/get pricing
- WARM: Shows interest, asking questions, wants more info
- COLD: Not interested, unsubscribe, already have solution
- AUTO_REPLY: Out of office, vacation, automated response
- UNCLEAR: Cannot determine intent from the message

Respond in JSON format:
{{
    "category": "hot|warm|cold|auto_reply|unclear",
    "confidence": 0-100,
    "reason": "brief explanation"
}}"""

        response = client.messages.create(
            model="claude-3-5-haiku-20241022",  # Fast and cheap model
            max_tokens=200,
            temperature=0,  # Deterministic
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )

        # Parse Claude's response
        response_text = response.content[0].text.strip()

        # Extract JSON (Claude sometimes wraps in markdown)
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()

        import json
        result = json.loads(response_text)

        logger.debug("Claude analysis: %s (confidence: %d%%)", result["category"], result["confidence"])

        return result

    except Exception as e:
        logger.error("Claude API error: %s", str(e))
        return {
            "category": "unclear",
            "confidence": 0,
            "reason": f"Claude API error: {str(e)}"
        }


def analyze_reply_hybrid(reply_text: str, subject: str = "") -> Dict:
    """
    Hybrid approach: Use keywords first, then Claude for unclear cases.

    This is the recommended function to use - it's fast for obvious cases
    and accurate for nuanced cases.

    Args:
        reply_text: The email reply body text
        subject: The email subject line (optional)

    Returns:
        {
            "category": "hot" | "warm" | "cold" | "auto_reply" | "unclear",
            "confidence": 0-100,
            "method": "keyword" | "claude",
            "reason": str,
            "matched_keywords": [...] (if method=keyword)
        }
    """
    # Step 1: Try keyword analysis (fast)
    keyword_result = analyze_reply_with_keywords(reply_text)

    # If keyword analysis is confident (>70%), use it
    if keyword_result["confidence"] >= 70:
        keyword_result["method"] = "keyword"
        logger.debug("Keyword analysis confident: %s (%d%%)",
                    keyword_result["category"], keyword_result["confidence"])
        return keyword_result

    # Step 2: For unclear cases, use Claude API
    logger.debug("Keyword analysis unclear (%d%%), trying Claude...", keyword_result["confidence"])
    claude_result = analyze_reply_with_claude(reply_text, subject)

    # If Claude is available and confident, use it
    if claude_result["confidence"] >= 50:
        claude_result["method"] = "claude"
        logger.debug("Claude analysis: %s (%d%%)",
                    claude_result["category"], claude_result["confidence"])
        return claude_result

    # Fallback to keyword result (even if low confidence)
    keyword_result["method"] = "keyword_fallback"
    logger.debug("Using keyword analysis as fallback: %s (%d%%)",
                keyword_result["category"], keyword_result["confidence"])
    return keyword_result


def categorize_leads(leads: List[Dict], use_claude: bool = True) -> Dict:
    """
    Categorize a list of leads into hot/warm/cold/auto/unclear buckets.

    Args:
        leads: List of lead dicts with "reply_body" and optionally "subject"
        use_claude: Whether to use Claude API for unclear cases (default: True)

    Returns:
        {
            "hot": [...],
            "warm": [...],
            "cold": [...],
            "auto_reply": [...],
            "unclear": [...],
            "summary": {
                "total_analyzed": int,
                "hot_count": int,
                "warm_count": int,
                "cold_count": int,
                "auto_reply_count": int,
                "unclear_count": int
            }
        }
    """
    categorized = {
        "hot": [],
        "warm": [],
        "cold": [],
        "auto_reply": [],
        "unclear": []
    }

    for lead in leads:
        reply_text = lead.get("reply_body", "")
        subject = lead.get("subject", "")

        if use_claude:
            analysis = analyze_reply_hybrid(reply_text, subject)
        else:
            analysis = analyze_reply_with_keywords(reply_text)
            analysis["method"] = "keyword"

        # Add analysis to lead
        lead_with_analysis = {
            **lead,
            "ai_category": analysis["category"],
            "ai_confidence": analysis["confidence"],
            "ai_reason": analysis["reason"],
            "ai_method": analysis.get("method", "unknown")
        }

        categorized[analysis["category"]].append(lead_with_analysis)

    # Build summary
    summary = {
        "total_analyzed": len(leads),
        "hot_count": len(categorized["hot"]),
        "warm_count": len(categorized["warm"]),
        "cold_count": len(categorized["cold"]),
        "auto_reply_count": len(categorized["auto_reply"]),
        "unclear_count": len(categorized["unclear"])
    }

    categorized["summary"] = summary

    return categorized
