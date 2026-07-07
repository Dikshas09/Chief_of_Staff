import os
import json
import google.generativeai as genai
from dotenv import load_dotenv
from context_builder import assemble_context

# Load environment variables
load_dotenv()

# Configure Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

# Model name constant
MODEL_NAME = "gemini-2.5-flash"

# -------------------------------------------------------------------
# Sample threads for the approval gate UI
# -------------------------------------------------------------------
SAMPLE_THREADS = [
    {
        "subject": "Q3 Budget Review — final approval needed",
        "messages": [
            {
                "from": "Priya (Finance)",
                "date": "2026-06-18",
                "body": "Hi Diksha, the Q3 budget allocations are finalized on our end. "
                        "We've incorporated the 15% buffer you requested for the analytics "
                        "migration. Can you give final approval by EOD Friday so we can "
                        "lock things in before the quarter starts?",
            },
            {
                "from": "Vikram (Engineering)",
                "date": "2026-06-19",
                "body": "From engineering's side, the numbers look good. Just flagging "
                        "that the infra line item (+$12K) is for the new Kubernetes cluster "
                        "we discussed — wanted to make sure that's still in scope.",
            },
        ],
    },
    {
        "subject": "Launch date for v2.5 dashboard",
        "messages": [
            {
                "from": "Ananya (Design Lead)",
                "date": "2026-06-15",
                "body": "Hey Diksha ,the design team has finalized the v2.5 dashboard mockups. "
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
    },
    {
        "subject": "Sprint retro — time and format",
        "messages": [
            {
                "from": "Meera (Agile Coach)",
                "date": "2026-06-20",
                "body": "Team — for this sprint's retro, I'm thinking we try a new format: "
                        "Start-Stop-Continue instead of the usual Glad-Sad-Mad. It's more "
                        "action-oriented. Thoughts? Also, please share your availability "
                        "for Thursday or Friday this week.",
            },
            {
                "from": "Arjun (Backend Dev)",
                "date": "2026-06-21",
                "body": "Fine with the format change. Thursday afternoon works for me — "
                        "after 2pm. Let's keep it to 45 mins max though, we have a "
                        "deployment window at 4pm.",
            },
        ],
    },
]


def _build_drafting_rules() -> str:
    """
    Returns a block of drafting constraints appended to the user prompt.
    """
    return (
        "\n\n[DRAFTING RULES — follow these strictly]\n"
        "1. ONE-ASK RULE: Every email has exactly ONE clear question or ONE clear response. "
        "Do not ask multiple things or bury the ask.\n"
        "2. LENGTH CONTROL: Match the thread's energy. Maximum 5 sentences. "
        "Use numbered points if listing multiple items.\n"
        "3. NO AI FILLER: Never use phrases like 'I hope this finds you well', "
        "'Thank you for reaching out', 'I'm writing to', or similar generic openers.\n"
        "4. STRUCTURE: Acknowledge the sender's message briefly -> give your response "
        "-> end with exactly ONE clear next step or question."
    )


def draft_reply(thread: dict) -> str:
    """
    Takes a thread dict, assembles context via assemble_context(),
    appends drafting rules, calls Gemini, and returns only the draft text.
    """
    context = assemble_context(thread)
    system_prompt = context["system"]
    user_prompt = context["user"] + _build_drafting_rules()

    model = genai.GenerativeModel(
        MODEL_NAME,
        system_instruction=system_prompt,
    )

    response = model.generate_content(user_prompt)
    return response.text.strip()


def draft_reply_with_metadata(thread: dict) -> dict:
    """
    Like draft_reply() but returns a dict with:
      - draft: the generated reply text
      - model: the model name used
      - subject: the thread subject
      - replying_to: the sender of the last message in the thread
    """
    draft = draft_reply(thread)
    last_message = thread["messages"][-1] if thread["messages"] else {}
    return {
        "draft": draft,
        "model": MODEL_NAME,
        "subject": thread.get("subject", ""),
        "replying_to": last_message.get("from", ""),
    }


# -------------------------------------------------------------------
# Demo
# -------------------------------------------------------------------
if __name__ == "__main__":
    if not GEMINI_API_KEY:
        print(
            "ERROR: GEMINI_API_KEY not found. "
            "Make sure you have a .env file with GEMINI_API_KEY set."
        )
        exit(1)

    sample_thread = SAMPLE_THREADS[0]
    result = draft_reply_with_metadata(sample_thread)

    print("=" * 72)
    print("DRAFT REPLY")
    print("=" * 72)
    print(result["draft"])
    print()
    print("=" * 72)
    print("METADATA")
    print("=" * 72)
    print(f"Model       : {result['model']}")
    print(f"Subject     : {result['subject']}")
    print(f"Replying to : {result['replying_to']}")