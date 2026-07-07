import base64
import json
from datetime import date
from email.mime.text import MIMEText

from gmail_fetch import get_gmail_service
from triage import fetch_threads, triage_inbox

GMAIL_USER_ID = "me"


def send_reply(
    thread_id: str,
    to: str,
    subject: str,
    body: str,
    message_id: str = None,
) -> dict:
    """
    Send a reply to an existing Gmail thread.

    Args:
        thread_id:  The Gmail thread ID to reply into.
        to:         Recipient email address.
        subject:    Email subject (\"Re:\" prefix is added automatically if absent).
        body:       Plain-text message body.
        message_id: Original message-id header value for threading (optional).

    Returns:
        A dict with keys ``message_id``, ``thread_id``, and ``status``.
    """
    # Prepend "Re:" if not already present
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    # Build the MIME message
    mime_msg = MIMEText(body, "plain")
    mime_msg["To"] = to
    mime_msg["Subject"] = subject

    # Set threading headers when we know the original message-id
    if message_id:
        mime_msg["In-Reply-To"] = message_id
        mime_msg["References"] = message_id

    # base64url-encode the raw message
    raw = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("utf-8")

    # Call the Gmail send API
    service = get_gmail_service()
    sent = (
        service.users()
        .messages()
        .send(
            userId=GMAIL_USER_ID,
            body={"raw": raw, "threadId": thread_id},
        )
        .execute()
    )

    return {
        "message_id": sent.get("id"),
        "thread_id": sent.get("threadId", thread_id),
        "status": "sent",
    }


def run_pipeline(max_results: int = 2) -> list:
    """Pipeline: fetch -> triage"""
    print(f"--- Starting Pipeline (Fetching {max_results} threads) ---")
    threads = fetch_threads(max_results)
    results = triage_inbox(threads)
    return results


def format_digest(results: list) -> None:
    """
    Print a clean, readable digest of triaged emails to the terminal.

    Groups emails by priority (URGENT, NEEDS-REPLY, FYI, IGNORE),
    shows a header with today's date and total count, and adds
    separator lines between priority groups.
    """
    if not results:
        print("=== INBOX DIGEST ===")
        print("No threads to display.")
        return

    # --- Header ---
    today = date.today().isoformat()
    print(f"{'=' * 60}")
    print(f"  INBOX DIGEST — {today}  |  {len(results)} thread(s)")
    print(f"{'=' * 60}")

    # --- Priority-grouped output ---
    priority_order = ["urgent", "needs-reply", "fyi", "ignore"]
    priority_labels = {
        "urgent": "URGENT",
        "needs-reply": "NEEDS-REPLY",
        "fyi": "FYI",
        "ignore": "IGNORE",
    }

    first_group = True
    for p in priority_order:
        # Collect all threads with this priority
        group = [r for r in results if r.get("priority", "").lower() == p]
        if not group:
            continue

        # Separator between priority groups (skip before the first non-empty group)
        if not first_group:
            print(f"\n{'-' * 60}")
        first_group = False

        label = priority_labels[p]
        print(f"\n  [{label}]")
        for r in group:
            sender = r.get("sender", "unknown")
            subject = r.get("subject", "(no subject)")
            reason = r.get("reason", "")
            print(f"    [{label}] {sender} | {subject} — {reason}")

    # Catch any threads with an unrecognised priority
    unknown = [r for r in results if r.get("priority", "").lower() not in priority_order]
    if unknown:
        if not first_group:
            print(f"\n{'-' * 60}")
        print(f"\n  [OTHER]")
        for r in unknown:
            sender = r.get("sender", "unknown")
            subject = r.get("subject", "(no subject)")
            reason = r.get("reason", "")
            print(f"    [{r.get('priority', '?').upper()}] {sender} | {subject} — {reason}")

    print()


def main():
    """Execute the pipeline, print the digest, and save results to a JSON file."""
    # 1. Run the pipeline to get the triaged data
    results = run_pipeline(2)

    # 2. Print the formatted digest to the terminal
    format_digest(results)

    # 3. Specify the output filename
    output_filename = "triage_output.json"
    print(f"\nSaving results to {output_filename}...")

    # 4. Write the pretty-printed JSON directly to a file
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4)

    print("Done! You can now open triage_output.json in your editor.")


if __name__ == '__main__':
    main()
