"""
Campaign spam checker - scans Bison and Instantly campaigns for spam content.
"""

from typing import List, Dict, Any, Optional
from . import bison_client, instantly_client, emailguard_client, sheets_client


def check_text_spam(
    emailguard_key: str,
    subject: str = "",
    body: str = ""
) -> Dict[str, Any]:
    """
    Check arbitrary email text for spam (ad-hoc checking without campaign).

    Useful for:
    - Pre-writing campaign copy review
    - A/B testing subject line variations
    - Competitive analysis of forwarded emails

    Args:
        emailguard_key: EmailGuard API key
        subject: Email subject line (optional)
        body: Email body content (optional)

    Returns:
        {
            "is_spam": bool,
            "spam_score": float,
            "spam_words": list,
            "number_of_spam_words": int,
            "subject": str,
            "body": str
        }
    """
    # Combine subject and body
    content = ""
    if subject:
        content += f"Subject: {subject}\n\n"
    if body:
        content += body

    if not content.strip():
        return {
            "error": "No content provided to check",
            "is_spam": False,
            "spam_score": 0,
            "spam_words": []
        }

    try:
        # Check with EmailGuard
        spam_result = emailguard_client.check_content_spam(emailguard_key, content)
        message = spam_result.get("data", {}).get("message", {})

        return {
            "is_spam": message.get("is_spam", False),
            "spam_score": message.get("spam_score", 0),
            "spam_words": message.get("spam_words", []),
            "number_of_spam_words": message.get("number_of_spam_words", 0),
            "subject": subject,
            "body": body
        }

    except Exception as e:
        return {
            "error": str(e),
            "is_spam": False,
            "spam_score": 0,
            "spam_words": [],
            "subject": subject,
            "body": body
        }





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


def check_instantly_campaign_spam(
    api_key: str,
    emailguard_key: str,
    campaign_id: str,
    campaign_name: str
) -> Dict[str, Any]:
    """
    Check a single Instantly campaign for spam.

    Args:
        api_key: Instantly API key
        emailguard_key: EmailGuard API key
        campaign_id: Campaign ID (UUID)
        campaign_name: Campaign name

    Returns:
        {
            "campaign_id": str,
            "campaign_name": str,
            "total_steps": int,
            "spam_steps": int,
            "steps": [...]
        }
    """
    # Get campaign details with sequences
    campaign_details = instantly_client.get_instantly_campaign_details(api_key, campaign_id)
    sequences = campaign_details.get("sequences", [])

    results = {
        "campaign_id": campaign_id,
        "campaign_name": campaign_name,
        "total_steps": 0,
        "spam_steps": 0,
        "steps": []
    }

    # Process all sequences
    for sequence in sequences:
        steps = sequence.get("steps", [])

        for step_idx, step in enumerate(steps):
            # Instantly structure: each step has variants with subject/body
            variants = step.get("variants", [])

            for variant_idx, variant in enumerate(variants):
                results["total_steps"] += 1

                subject = variant.get("subject", "")
                body = variant.get("body", "")

                # Remove HTML tags for spam checking
                import re
                body_text = re.sub(r'<[^>]+>', '', body)
                body_text = re.sub(r'\s+', ' ', body_text).strip()

                # Combine subject and body for spam check
                content = f"Subject: {subject}\n\n{body_text}"

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
                        "step_order": step_idx + 1,
                        "variant": variant_idx + 1 if len(variants) > 1 else None,
                        "subject": subject,
                        "is_spam": is_spam,
                        "spam_score": spam_score,
                        "spam_words": spam_words
                    })

                except Exception as e:
                    print(f"[ERROR] Failed to check step {step_idx + 1}: {e}")
                    results["steps"].append({
                        "step_order": step_idx + 1,
                        "variant": variant_idx + 1 if len(variants) > 1 else None,
                        "subject": subject,
                        "error": str(e)
                    })

    return results


def check_all_instantly_campaigns_spam(
    emailguard_key: str,
    status: str = "active",
    client_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Check spam for all Instantly campaigns across all clients.

    Args:
        emailguard_key: EmailGuard API key
        status: Campaign status to filter (default: "active")
            Can be string: "draft", "active", "paused", "completed"
            Or number: 0 (Draft), 1 (Active), 2 (Paused), 3 (Completed)
        client_name: Optional specific client name to check

    Returns:
        {
            "total_clients": int,
            "total_campaigns": int,
            "spam_campaigns": int,
            "clients": [...]
        }
    """
    # Convert status string to number for Instantly API
    status_map = {
        "draft": 0,
        "active": 1,
        "paused": 2,
        "completed": 3,
        "running_subsequences": 4
    }

    if isinstance(status, str) and status.lower() in status_map:
        status_number = status_map[status.lower()]
    elif isinstance(status, int):
        status_number = status
    else:
        status_number = 1  # Default to active

    # Load Instantly clients from sheets
    clients = sheets_client.load_instantly_workspaces_from_sheet()

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
            campaigns = instantly_client.list_instantly_campaigns(api_key, status=status_number)

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

                spam_check = check_instantly_campaign_spam(
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
