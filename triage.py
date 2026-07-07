import os
import json
import subprocess
from typing import Optional
import time
import google.generativeai as genai  # type: ignore[import]
from dotenv import load_dotenv

# Use the direct Gmail API client instead of the MCP subprocess
from gmail_fetch import get_gmail_service

load_dotenv()
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.5-flash")


def fetch_threads(max_results: int = 2) -> list[dict]:
    """
    Fetch inbox threads directly from Gmail API using OAuth credentials.
    Returns a list of dicts with keys: thread_id, sender, subject, snippet, date.
    """
    service = get_gmail_service()

    # List threads from inbox
    threads_result = (
        service.users()
        .threads()
        .list(userId="me", maxResults=max_results, q="in:inbox")
        .execute()
    )

    thread_list = threads_result.get("threads", [])
    output = []

    for t in thread_list:
        # Get full thread data including all messages
        thread_data = (
            service.users()
            .threads()
            .get(userId="me", id=t["id"], format="full")
            .execute()
        )

        messages = thread_data.get("messages", [])
        if not messages:
            continue

        # Extract headers from the first message
        first_msg = messages[0]
        headers = first_msg.get("payload", {}).get("headers", [])
        sender = ""
        subject = ""
        date = ""
        for h in headers:
            if h["name"] == "From":
                sender = h["value"]
            elif h["name"] == "Subject":
                subject = h["value"]
            elif h["name"] == "Date":
                date = h["value"]

        # Build a full body snippet from all messages in the thread
        snippet_parts = []
        for msg in messages:
            payload = msg.get("payload", {})
            # Recursively extract text from message parts
            parts = payload.get("parts", [])
            text = _extract_text_from_parts(parts) or payload.get("body", {}).get("data", "")
            if text:
                import base64
                try:
                    decoded = base64.urlsafe_b64decode(text).decode("utf-8", errors="replace")
                except Exception:
                    decoded = text
                # Strip HTML
                import re
                decoded = re.sub(r"<[^>]+>", "", decoded)
                decoded = re.sub(r"\s+", " ", decoded).strip()
                if decoded:
                    snippet_parts.append(decoded)

        snippet = " | ".join(snippet_parts) if snippet_parts else first_msg.get("snippet", "")

        output.append({
            "thread_id": t["id"],
            "sender": sender,
            "subject": subject,
            "snippet": snippet[:500],  # keep a generous preview
            "date": date[:16] if len(date) > 16 else date,
        })

    return output


def _extract_text_from_parts(parts: list) -> str | None:
    """Recursively extract text/plain or text/html content from MIME parts."""
    for part in parts:
        mime = part.get("mimeType", "")
        if mime == "text/plain" or mime == "text/html":
            data = part.get("body", {}).get("data", "")
            if data:
                return data
        # Recurse into nested parts
        nested = part.get("parts", [])
        if nested:
            result = _extract_text_from_parts(nested)
            if result:
                return result
    return None


def triage_thread(sender: str, subject: str, snippet: str) -> dict:
    prompt = f"""
        you are an intelligent email assistant helping triage an inbox.
        Given this thread and metadata, classify it:

        Sender: {sender}
        subject: {subject}
        snippet: {snippet}
        Priority: 

        Response format:
        Priority: urgent | needs-reply | fyi | ignore
        Category: some short tag like: meeting-request, follow-up, newsletter, billing, job-app, social, admin, etc.
        Reason: some sentence explaining why?
        """
    response = model.generate_content(prompt)
    return parse_triage_response(response.text)


def parse_triage_response(text: str) -> dict:
    result = {"priority": "unknown", "category": "other", "reason": ""}
    for line in text.strip().split('\n'):
        if line.startswith("Priority:"):
            result["priority"] = line.replace("Priority:", "").strip().lower()
        elif line.startswith("Category:"):
            result["category"] = line.replace("Category:", "").strip().lower()
        elif line.startswith("Reason:"):
            result["reason"] = line.replace("Reason:", "").strip().lower()
    return result


def triage_inbox(threads: list) -> list:
    """
    Sends all threads to Gemini in a single batch request to avoid daily quota limits.
    """
    if not threads:
        return []

    print(f"Sending {len(threads)} threads to Gemini in a single batch request...")

    # 1. Prepare a clean, lightweight list of the emails for the prompt
    email_batch = []
    for t in threads:
        email_batch.append({
            "thread_id": t["thread_id"],
            "sender": t.get("sender", ""),
            "subject": t.get("subject", ""),
            "snippet": t.get("snippet", "")
        })

    # 2. Build a single structured prompt forcing a JSON array response
    prompt = f"""
    You are an intelligent email assistant. Analyze this array of emails and triage them.
    For each email, provide a classification object.

    Emails to triage:
    {json.dumps(email_batch, indent=2)}

    Your response MUST be a valid JSON array containing objects with exactly these keys:
    [
      {{
        "thread_id": "string",
        "priority": "urgent" | "needs-reply" | "fyi" | "ignore",
        "category": "meeting-request" | "follow-up" | "newsletter" | "billing" | "job-app" | "social" | "admin" | "other",
        "reason": "short sentence explaining why"
      }}
    ]
    Respond ONLY with the raw JSON array. Do not include markdown formatting or backticks.
    """

    try:
        # Send the entire batch in ONE request
        response = model.generate_content(prompt)
        text_response = response.text.strip()

        # Clean up markdown code blocks if the model mistakenly added them
        if text_response.startswith("```"):
            text_response = text_response.strip("```").replace("json", "", 1).strip()

        # Parse the batch results
        predictions = json.loads(text_response)

        # Map predictions back to the original threads using thread_id
        pred_map = {p["thread_id"]: p for p in predictions if "thread_id" in p}

        triaged = []
        for t in threads:
            labels = pred_map.get(t["thread_id"], {"priority": "unknown", "category": "other", "reason": "Failed to parse classification"})
            # Merge original thread data with the AI labels
            triaged.append({
                **t,
                "priority": labels.get("priority", "unknown").lower(),
                "category": labels.get("category", "other").lower(),
                "reason": labels.get("reason", "")
            })

        # Sort by priority
        priority_order = {"urgent": 0, "needs-reply": 1, "fyi": 2, "ignore": 3, "unknown": 4}
        triaged.sort(key=lambda x: priority_order.get(x['priority'], 4))
        return triaged

    except Exception as e:
        print(f"Error during batch classification: {e}")
        # Fallback: return untriaged data if the JSON parsing or API fails
        return [{**t, "priority": "unknown", "category": "other", "reason": "Error"} for t in threads]


if __name__ == '__main__':
    """Fetch the last 20 inbox threads, triage them, and print results."""
    print("Fetching inbox threads...")
    threads = fetch_threads(20)
    print(f"Fetched {len(threads)} threads. Classifying...\n")

    results = triage_inbox(threads)

    for r in results:
        print(f"[{r['priority'].upper()}] [{r['category']}] {r['subject']} - {r['reason']}")