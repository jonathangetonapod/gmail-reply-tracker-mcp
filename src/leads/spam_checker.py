"""
Campaign spam checker - scans Bison and Instantly campaigns for spam content.
"""

from typing import List, Dict, Any, Optional
from . import bison_client, instantly_client, emailguard_client, sheets_client


def check_bison_campaign_spam(
    api_key: str,
    emailguard_key: str,
    campaign_id: int,
    campaign_name: str
) -> Dict[str, Any]:
    """
    Check a single Bison campaign for spam.

    Args:
        api_key: Bison API key
        emailguard_key: EmailGuard API key
        campaign_id: Campaign ID
        campaign_name: Campaign name

    Returns:
        {
            "campaign_id": int,
            "campaign_name": str,
            "total_steps": int,
            "spam_steps": int,
            "steps": [
                {
                    "step_order": int,
                    "subject": str,
                    "is_spam": bool,
                    "spam_score": float,
                    "spam_words": list
                }
            ]
        }
    """
    # Get campaign sequences
    sequences = bison_client.get_bison_campaign_sequences(api_key, campaign_id)
    steps_data = sequences.get("data", {}).get("sequence_steps", [])

    results = {
        "campaign_id": campaign_id,
        "campaign_name": campaign_name,
        "total_steps": len(steps_data),
        "spam_steps": 0,
        "steps": []
    }

    # Check each step
    for step in steps_data:
        subject = step.get("email_subject", "")
        body = step.get("email_body", "")
        order = step.get("order", 0)

        # Combine subject and body for spam check
        content = f"Subject: {subject}\n\n{body}"

        try:
            # Check with EmailGuard
            spam_result = emailguard_client.check_content_spam(emailguard_key, content)
            message = spam_result.get("data", {}).get("message", {})

            is_spam = message.get("is_spam", False)
            spam_score = message.get("spam_score", 0)
            spam_words = message.get("spam_words", [])

            if is_spam:
                results["spam_steps"] += 1

            results["steps"].append({
                "step_order": order,
                "subject": subject,
                "is_spam": is_spam,
                "spam_score": spam_score,
                "spam_words": spam_words
            })

        except Exception as e:
            print(f"[ERROR] Failed to check step {order}: {e}")
            results["steps"].append({
                "step_order": order,
                "subject": subject,
                "error": str(e)
            })

    return results


def check_all_bison_campaigns_spam(
    emailguard_key: str,
    status: str = "active",
    client_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Check spam for all Bison campaigns across all clients.

    Args:
        emailguard_key: EmailGuard API key
        status: Campaign status to filter (default: "active")
        client_name: Optional specific client name to check

    Returns:
        {
            "total_clients": int,
            "total_campaigns": int,
            "spam_campaigns": int,
            "clients": [
                {
                    "client_name": str,
                    "campaigns": [...]
                }
            ]
        }
    """
    # Load Bison clients from sheets
    clients = sheets_client.load_bison_workspaces_from_sheet()

    # Filter by client name if specified
    if client_name:
        from rapidfuzz import process, fuzz
        client_names = [c["client_name"] for c in clients]
        result = process.extractOne(
            client_name,
            client_names,
            scorer=fuzz.WRatio,
            score_cutoff=60
        )
        if result:
            matched_name, score, index = result
            clients = [clients[index]]
        else:
            return {
                "error": f"Client '{client_name}' not found",
                "total_clients": 0,
                "total_campaigns": 0,
                "spam_campaigns": 0,
                "clients": []
            }

    results = {
        "total_clients": len(clients),
        "total_campaigns": 0,
        "spam_campaigns": 0,
        "clients": []
    }

    # Check each client
    for client in clients:
        api_key = client["api_key"]
        name = client["client_name"]

        print(f"[INFO] Checking campaigns for client: {name}")

        try:
            # List campaigns for this client
            campaigns_response = bison_client.list_bison_campaigns(
                api_key,
                status=status
            )
            campaigns = campaigns_response.get("data", [])

            client_result = {
                "client_name": name,
                "total_campaigns": len(campaigns),
                "spam_campaigns": 0,
                "campaigns": []
            }

            # Check each campaign
            for campaign in campaigns:
                campaign_id = campaign["id"]
                campaign_name = campaign["name"]

                print(f"[INFO]   Checking campaign: {campaign_name}")

                spam_check = check_bison_campaign_spam(
                    api_key,
                    emailguard_key,
                    campaign_id,
                    campaign_name
                )

                if spam_check["spam_steps"] > 0:
                    client_result["spam_campaigns"] += 1
                    results["spam_campaigns"] += 1

                client_result["campaigns"].append(spam_check)
                results["total_campaigns"] += 1

            results["clients"].append(client_result)

        except Exception as e:
            print(f"[ERROR] Failed to check client {name}: {e}")
            results["clients"].append({
                "client_name": name,
                "error": str(e)
            })

    return results
