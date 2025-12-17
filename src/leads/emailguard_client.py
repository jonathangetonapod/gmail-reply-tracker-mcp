"""
EmailGuard API wrapper for spam checking.
"""

import requests


def check_content_spam(api_key: str, content: str):
    """
    Check content for spam using EmailGuard API.

    Args:
        api_key: EmailGuard API key
        content: Email content to check (subject + body)

    Returns:
        {
            "data": {
                "message": {
                    "is_spam": bool,
                    "spam_score": float,
                    "number_of_spam_words": int,
                    "spam_words": list,
                    "comma_separated_spam_words": str
                }
            }
        }
    """
    url = "https://app.emailguard.io/api/v1/content-spam-check"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "content": content
    }

    response = requests.post(url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()

    return response.json()
