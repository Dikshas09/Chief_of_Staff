import json


def load_tone_profile(path="tone_profile.json") -> dict:
    """Reads and returns the tone profile dict from a JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_past_replies(path="past_replies.json") -> list:
    """Reads and returns a list of past reply examples from a JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def format_thread_history(thread: dict) -> str:
    """
    Takes a thread dict with "subject" and "messages"
    (list of {from, date, body}) and formats it as a
    readable string showing who said what in order.
    """
    lines = [f"Subject: {thread['subject']}", ""]
    for msg in thread["messages"]:
        lines.append(f"From: {msg['from']}")
        lines.append(f"Date: {msg['date']}")
        lines.append(f"---")
        lines.append(msg["body"])
        lines.append("")
    return "\n".join(lines).strip()


def build_persona_block(tone_profile: dict) -> str:
    """
    Builds a structured persona block with name, role, tone, formality, and voice description.
    """
    name = tone_profile["name"]
    role = tone_profile["role"]
    tone = tone_profile["tone"]
    formality = tone_profile["formality"]
    voice = tone_profile.get("voice", "")

    parts = [
        f"[PERSONA]",
        f"Name: {name}",
        f"Role: {role}",
        f"Tone: {tone}",
        f"Formality: {formality}",
    ]
    if voice:
        parts.append(f"Voice: {voice}")

    return "\n".join(parts) + "\n"


def build_system_prompt(tone_profile: dict, past_replies: list) -> str:
    """
    Builds the system prompt that includes:
    - The persona block (name, role, tone, formality)
    - Writing rules from the quirks list
    - 2-3 past reply examples formatted as "Here's how {name} writes:"
    """
    name = tone_profile["name"]
    quirks = tone_profile["quirks"]

    persona_block = build_persona_block(tone_profile)

    lines = [
        persona_block,
        "[WRITING RULES]",
    ]
    for i, quirk in enumerate(quirks, 1):
        lines.append(f"{i}. {quirk}")

    lines.append("")
    lines.append("[STYLE REFERENCE]")
    lines.append(f"Here's how {name} writes:")
    lines.append("")

    # Show up to 3 past reply examples
    for reply in past_replies[:3]:
        lines.append(f"--- Example: Re: {reply['subject']} ---")
        lines.append(reply["body"])
        lines.append("")

    lines.append(
        "---\n"
        "Now write the email reply using the same voice and style "
        "shown above. Keep it concise, natural, and on-brand."
    )

    return "\n".join(lines).strip()


def build_user_prompt(thread_formatted: str) -> str:
    """
    Builds the user message asking for a reply draft.
    """
    return (
        "Please draft a reply to the following email thread. "
        "Write in your usual voice and style.\n\n"
        f"{thread_formatted}\n\n"
        "Reply:"
    )


def assemble_context(
    thread: dict,
    tone_path: str = "tone_profile.json",
    replies_path: str = "past_replies.json",
) -> dict:
    """
    The main function that loads everything and returns a dict:
    {"system": system_prompt, "user": user_prompt}
    """
    tone_profile = load_tone_profile(tone_path)
    past_replies = load_past_replies(replies_path)
    thread_formatted = format_thread_history(thread)

    system_prompt = build_system_prompt(tone_profile, past_replies)
    user_prompt = build_user_prompt(thread_formatted)

    return {"system": system_prompt, "user": user_prompt}


# -------------------------------------------------------------------
# Demo / smoke test — run this file to see the assembled context
# -------------------------------------------------------------------
if __name__ == "__main__":
    sample_thread = {
        "subject": "Launch date for v2.5 dashboard",
        "messages": [
            {
                "from": "Ananya (Design Lead)",
                "date": "2026-06-15",
                "body": "Hey Diksha, the design team has finalized the v2.5 dashboard mockups. "
                        "We're aiming for a July 10 launch. Can you review and confirm on your end?",
            },
            {
                "from": "Vikram (Engineering Lead)",
                "date": "2026-06-16",
                "body": "Engineering can make July 10 work, but we need the final specs by "
                        "June 25 to hit that date. Also, the new analytics widget will need "
                        "a backend endpoint we haven't scoped yet.",
            },
        ],
    }

    context = assemble_context(sample_thread)

    print("=" * 72)
    print("SYSTEM PROMPT")
    print("=" * 72)
    print(context["system"])
    print()
    print("=" * 72)
    print("USER PROMPT")
    print("=" * 72)
    print(context["user"])
    print()
    print("=" * 72)
    print("FULL ASSEMBLED CONTEXT DICT")
    print("=" * 72)
    print(json.dumps(context, indent=2))