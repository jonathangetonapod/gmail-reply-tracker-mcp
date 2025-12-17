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

    # Capture error details before raising
    if not response.ok:
        error_details = {
            "status_code": response.status_code,
            "error_text": response.text,
            "url": url,
            "content_length": len(content)
        }
        # Create detailed error message
        error_msg = f"{response.status_code} Client Error: {response.reason} for url: {url}"
        error_msg += f" | Response: {response.text[:200]}"  # First 200 chars of error
        raise requests.exceptions.HTTPError(error_msg, response=response)

    return response.json()
