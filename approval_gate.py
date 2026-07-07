import os
import json
from datetime import datetime
from typing import Any

import streamlit as st  # type: ignore[import]

# Local imports — these live in the same directory
from draft_machine import SAMPLE_THREADS, draft_reply_with_metadata
from triage import fetch_threads, triage_inbox

# ---------------------------------------------------------------------------
# Page config — must be the first Streamlit command
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="AI Email Ghostwriter — Approval Gate",
    page_icon="✉️",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Custom CSS — dark theme with thread boxes and status indicators
# ---------------------------------------------------------------------------
st.markdown(
    """
<style>
    /* Overall background */
    .stApp {
        background-color: #1a1a2e;
        color: #e0e0e0;
    }

    /* Sidebar */
    section[data-testid="stSidebar"] {
        background-color: #16213e;
    }
    section[data-testid="stSidebar"] .stMarkdown {
        color: #e0e0e0;
    }

    /* Thread message box */
    .thread-msg {
        background-color: #0f3460;
        border-left: 4px solid #e94560;
        border-radius: 6px;
        padding: 12px 16px;
        margin-bottom: 12px;
        color: #e0e0e0;
    }
    .thread-msg .sender {
        font-weight: 600;
        color: #e94560;
        font-size: 0.95rem;
    }
    .thread-msg .date {
        font-size: 0.8rem;
        color: #a0a0b0;
    }
    .thread-msg .body {
        margin-top: 6px;
        line-height: 1.5;
    }

    /* Draft display box */
    .draft-box {
        background-color: #0f3460;
        border: 1px solid #533483;
        border-radius: 8px;
        padding: 20px 24px;
        min-height: 120px;
        color: #e0e0e0;
        font-size: 1rem;
        line-height: 1.6;
        white-space: pre-wrap;
    }

    /* Status badges */
    .status-badge {
        display: inline-block;
        padding: 4px 14px;
        border-radius: 20px;
        font-weight: 600;
        font-size: 0.85rem;
    }
    .status-approved {
        background-color: #00c853;
        color: #ffffff;
    }
    .status-rejected {
        background-color: #ff1744;
        color: #ffffff;
    }
    .status-pending {
        background-color: #ff9100;
        color: #ffffff;
    }
    /* Triage priority badges */
    .priority-urgent {
        background-color: #d32f2f;
        color: #ffffff;
    }
    .priority-needs-reply {
        background-color: #f57c00;
        color: #ffffff;
    }
    .priority-fyi {
        background-color: #388e3c;
        color: #ffffff;
    }
    .priority-ignore {
        background-color: #616161;
        color: #ffffff;
    }

    /* Divider */
    .section-divider {
        border: none;
        border-top: 1px solid #333;
        margin: 20px 0;
    }

    /* Thread entry in sidebar */
    .thread-entry {
        background-color: #0f3460;
        border-radius: 6px;
        padding: 8px 12px;
        margin-bottom: 6px;
        cursor: pointer;
        font-size: 0.85rem;
    }
    .thread-entry:hover {
        border: 1px solid #533483;
    }

    /* Approved draft history entry */
    .history-entry {
        background-color: #0f3460;
        border-left: 3px solid #00c853;
        border-radius: 4px;
        padding: 8px 12px;
        margin-bottom: 8px;
        font-size: 0.85rem;
    }
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
APPROVED_FILE = "approved_drafts.json"

# ---------------------------------------------------------------------------
# Helper: resolve API key
# ---------------------------------------------------------------------------
def resolve_api_key() -> str | None:
    """Return GEMINI_API_KEY from st.secrets, then os.environ, else None."""
    try:
        return st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    except Exception:
        return os.environ.get("GEMINI_API_KEY")


# ---------------------------------------------------------------------------
# Helper: save / load approved drafts
# ---------------------------------------------------------------------------
def save_approved_draft(thread: dict, draft_text: str, edited: bool = False) -> None:
    """Append an approved draft to the approved_drafts.json file."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "source": thread.get("source", "unknown"),
        "subject": thread.get("subject", ""),
        "replying_to": thread["messages"][-1]["from"] if thread.get("messages") else "",
        "draft": draft_text,
        "edited": edited,
    }
    records = []
    if os.path.exists(APPROVED_FILE):
        with open(APPROVED_FILE, "r", encoding="utf-8") as f:
            try:
                records = json.load(f)
            except json.JSONDecodeError:
                records = []
    records.append(entry)
    with open(APPROVED_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


def load_approved_drafts() -> list[dict]:
    """Load the full list of approved drafts."""
    if not os.path.exists(APPROVED_FILE):
        return []
    with open(APPROVED_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


# ---------------------------------------------------------------------------
# Helper: render a thread message card
# ---------------------------------------------------------------------------
def render_thread_message(msg: dict) -> None:
    """Display a single message as a styled card."""
    st.markdown(
        f"""
        <div class="thread-msg">
            <div class="sender">{msg['from']}</div>
            <div class="date">{msg.get('date', '')}</div>
            <div class="body">{msg['body']}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Helper: render the thread column (left side)
# ---------------------------------------------------------------------------
def render_thread_column(thread: dict, triage_info: dict | None = None) -> None:
    """Show the full email thread on the left side."""
    st.markdown("### 📧 Email Thread")

    # Optional triage badge
    if triage_info:
        priority = triage_info.get("priority", "").lower()
        priority_class = f"priority-{priority}" if priority in ("urgent", "needs-reply", "fyi", "ignore") else ""
        category = triage_info.get("category", "")
        reason = triage_info.get("reason", "")
        badge_html = f'<span class="status-badge {priority_class}">{priority.upper()}</span>' if priority_class else ""
        st.markdown(
            f"""{badge_html} <strong>{category}</strong> — {reason}""",
            unsafe_allow_html=True,
        )

    st.markdown(f"**Subject:** {thread.get('subject', '(No subject)')}")
    st.markdown(f"**Messages:** {len(thread['messages'])}")
    st.markdown("<hr class='section-divider' />", unsafe_allow_html=True)

    for msg in thread["messages"]:
        render_thread_message(msg)


# ---------------------------------------------------------------------------
# Helper: render the draft column (right side) with action buttons
# ---------------------------------------------------------------------------
def render_draft_column(thread: dict) -> None:
    """Show the AI-generated draft and the three action buttons."""
    st.markdown("### ✍️ Draft Reply")
    status = st.session_state.status

    # --- No draft yet ---
    if status == "none":
        st.info("Click **Generate Draft** in the sidebar to create a reply.")
        return

    # --- Rejected ---
    if status == "rejected":
        st.markdown(
            '<div class="status-badge status-rejected">✖ REJECTED</div>',
            unsafe_allow_html=True,
        )
        st.warning("The draft was discarded. Click **Generate Draft** to try again.")
        st.markdown(
            f'<div class="draft-box" style="opacity:0.5;">{st.session_state.current_draft}</div>',
            unsafe_allow_html=True,
        )
        return

    # --- Editing mode ---
    if status == "editing":
        st.markdown(
            '<div class="status-badge status-pending">✎ EDITING</div>',
            unsafe_allow_html=True,
        )
        edited_text = st.text_area(
            "Edit the draft below, then click **Approve Edited Version**:",
            value=st.session_state.current_draft,
            height=200,
            key="edit_area",
        )
        col_a, col_b = st.columns([1, 3])
        with col_a:
            if st.button("✅ Approve Edited Version", type="primary"):
                st.session_state.current_draft = edited_text
                st.session_state.status = "approved"
                save_approved_draft(thread, edited_text, edited=True)
                st.rerun()
        with col_b:
            if st.button("↩ Cancel Edit"):
                st.session_state.status = "draft_ready"
                st.rerun()
        return

    # --- Approved ---
    if status == "approved":
        st.markdown(
            '<div class="status-badge status-approved">✓ APPROVED — Ready to send</div>',
            unsafe_allow_html=True,
        )
        st.success("This draft has been saved to `approved_drafts.json`.")
        st.markdown(
            f'<div class="draft-box">{st.session_state.current_draft}</div>',
            unsafe_allow_html=True,
        )
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 Generate Another Draft", use_container_width=True):
                st.session_state.status = "none"
                st.session_state.current_draft = ""
                st.rerun()
        with col2:
            if st.button("📋 View History", use_container_width=True):
                st.session_state.show_history = True
                st.rerun()
        return

    # --- Draft ready — show draft + action buttons ---
    st.markdown(
        f'<div class="draft-box">{st.session_state.current_draft}</div>',
        unsafe_allow_html=True,
    )

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("**Actions:**", unsafe_allow_html=True)

    action_cols = st.columns(3)
    with action_cols[0]:
        if st.button("✅ Approve", type="primary", use_container_width=True):
            st.session_state.status = "approved"
            save_approved_draft(thread, st.session_state.current_draft, edited=False)
            st.rerun()

    with action_cols[1]:
        if st.button("✎ Edit", use_container_width=True):
            st.session_state.status = "editing"
            st.rerun()

    with action_cols[2]:
        if st.button("✖ Reject", use_container_width=True):
            st.session_state.status = "rejected"
            st.rerun()


# ---------------------------------------------------------------------------
# Helper: parse custom thread JSON
# ---------------------------------------------------------------------------
def parse_custom_thread(raw: str) -> dict | None:
    """Try to parse a JSON thread from the text area. Return None on failure."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        st.error("Invalid JSON — please check the format and try again.")
        return None

    if not isinstance(data, dict):
        st.error("Custom thread must be a JSON object with 'subject' and 'messages'.")
        return None
    if "subject" not in data or "messages" not in data:
        st.error("Custom thread must contain both 'subject' and 'messages' fields.")
        return None
    if not isinstance(data["messages"], list) or len(data["messages"]) == 0:
        st.error("'messages' must be a non-empty array.")
        return None
    for i, msg in enumerate(data["messages"]):
        if not all(k in msg for k in ("from", "date", "body")):
            st.error(f"Message {i+1} is missing one of: 'from', 'date', 'body'.")
            return None
    data.setdefault("source", "custom")
    return data


# ---------------------------------------------------------------------------
# Helper: convert a triage thread (from Gmail) into a thread dict with messages
# ---------------------------------------------------------------------------
def build_thread_from_triage(triage_entry: dict) -> dict:
    """Convert a triage output entry into a full thread dict with a messages list."""
    return {
        "source": "gmail",
        "subject": triage_entry.get("subject", "(No subject)"),
        "thread_id": triage_entry.get("thread_id", ""),
        "messages": [
            {
                "from": triage_entry.get("sender", "Unknown"),
                "date": triage_entry.get("date", ""),
                "body": triage_entry.get("snippet", "(No content)"),
            }
        ],
    }


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
def render_sidebar():
    """Build the sidebar UI."""
    st.sidebar.title("✉️ AI Email Ghostwriter")
    st.sidebar.markdown("### Approval Gate — Human in the Loop")
    st.sidebar.markdown("<hr class='section-divider' />", unsafe_allow_html=True)

    # --- API Key ---
    api_key = resolve_api_key()
    if not api_key:
        st.sidebar.error("GEMINI_API_KEY not found.")
        api_key = st.sidebar.text_input(
            "Enter your GEMINI_API_KEY:",
            type="password",
            help="Your key is used only for this session and is not stored.",
        )
        if api_key:
            os.environ["GEMINI_API_KEY"] = api_key

    st.sidebar.markdown("<hr class='section-divider' />", unsafe_allow_html=True)

    # --- Fetch Live Inbox ---
    st.sidebar.markdown("### 📬 Live Inbox")
    if st.sidebar.button("📥 Fetch Inbox from Gmail", use_container_width=True):
        if not api_key:
            st.sidebar.error("Please provide a GEMINI_API_KEY first.")
        else:
            with st.spinner("Fetching threads from Gmail via MCP..."):
                try:
                    threads = fetch_threads(max_results=10)
                    if not threads:
                        st.sidebar.warning("No threads found in inbox.")
                    else:
                        st.sidebar.success(f"Fetched {len(threads)} threads. Triaging...")
                        triaged = triage_inbox(threads)
                        st.session_state.live_threads = triaged
                        st.session_state.show_live = True
                        st.rerun()
                except Exception as e:
                    st.sidebar.error(f"Failed to fetch inbox: {e}")

    # Show live threads if we have them
    live_threads: list[dict] = st.session_state.get("live_threads", [])
    if live_threads:
        st.sidebar.markdown("**Inbox threads (triaged):**")
        for i, t in enumerate(live_threads):
            priority = t.get("priority", "").upper()
            subject = t.get("subject", "(No subject)")
            sender = t.get("sender", "Unknown")
            p_short = priority[:4]
            label = f"[{p_short}] {sender[:20]} — {subject[:30]}"
            if st.sidebar.button(
                label,
                key=f"live_{i}",
                use_container_width=True,
                help=f"Priority: {priority} | Category: {t.get('category', '')}",
            ):
                thread_dict = build_thread_from_triage(t)
                st.session_state.selected_thread = thread_dict
                st.session_state.current_draft = ""
                st.session_state.status = "none"
                st.session_state.triage_info = t
                st.rerun()

        st.sidebar.markdown("---")

    st.sidebar.markdown("<hr class='section-divider' />", unsafe_allow_html=True)

    # --- Sample Threads ---
    st.sidebar.markdown("### 📥 Sample Threads")
    thread_labels = [t["subject"] for t in SAMPLE_THREADS]
    selected_label = st.sidebar.selectbox(
        "Choose a sample thread:",
        thread_labels,
        index=0,
        key="thread_selector",
    )

    st.sidebar.markdown("— or —")
    custom_json = st.sidebar.text_area(
        "Paste custom thread JSON:",
        height=120,
        placeholder='{"subject": "...", "messages": [{"from": "...", "date": "...", "body": "..."}]}',
        key="custom_thread_input",
    )

    # Resolve sample/custom thread
    if custom_json.strip():
        parsed = parse_custom_thread(custom_json)
        if parsed is not None:
            selected_thread = parsed
            # If user pastes custom, we clear the live flag
            st.session_state.show_live = False
            st.sidebar.success("Custom thread loaded.")
        else:
            idx = thread_labels.index(selected_label)
            selected_thread = dict(SAMPLE_THREADS[idx])
            selected_thread["source"] = "sample"
    else:
        idx = thread_labels.index(selected_label)
        selected_thread = dict(SAMPLE_THREADS[idx])
        selected_thread["source"] = "sample"

    # Only overwrite selected_thread if we're not currently showing a live thread
    if not st.session_state.get("show_live", False) or not live_threads:
        if st.session_state.get("selected_thread") != selected_thread:
            st.session_state.selected_thread = selected_thread
            st.session_state.current_draft = ""
            st.session_state.status = "none"
            st.session_state.triage_info = None

    st.sidebar.markdown("<hr class='section-divider' />", unsafe_allow_html=True)

    # --- Generate Draft button ---
    thread = st.session_state.get("selected_thread")
    if thread:
        st.sidebar.markdown(f"**Active thread:** {thread.get('subject', '')[:50]}")
    if st.sidebar.button("🚀 Generate Draft", type="primary", use_container_width=True):
        if not api_key:
            st.sidebar.error("Please provide a GEMINI_API_KEY first.")
        elif not thread:
            st.sidebar.error("No thread selected.")
        else:
            with st.spinner("Generating draft with Gemini..."):
                try:
                    result = draft_reply_with_metadata(thread)
                    st.session_state.current_draft = result["draft"]
                    st.session_state.status = "draft_ready"
                    st.session_state.generation_count += 1
                    st.rerun()
                except Exception as e:
                    st.sidebar.error(f"Draft generation failed: {e}")

    if st.session_state.generation_count > 0:
        st.sidebar.markdown(
            f"**Generations this session:** {st.session_state.generation_count}"
        )

    st.sidebar.markdown("<hr class='section-divider' />", unsafe_allow_html=True)

    # --- Approved Drafts History ---
    with st.sidebar.expander("📋 Approved Drafts History", expanded=False):
        approved = load_approved_drafts()
        if not approved:
            st.caption("No approved drafts yet.")
        else:
            for entry in reversed(approved[-10:]):  # show last 10
                ts = entry.get("timestamp", "")[:16]
                subj = entry.get("subject", "(No subject)")
                draft_preview = entry.get("draft", "")[:80]
                st.markdown(
                    f"""
                    <div class="history-entry">
                        <div style="color:#00c853;font-weight:600;">{ts}</div>
                        <div style="font-weight:500;">{subj}</div>
                        <div style="color:#a0a0b0;">{draft_preview}…</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------
def main():
    # --- Initialise session state ---
    if "current_draft" not in st.session_state:
        st.session_state.current_draft = ""
    if "status" not in st.session_state:
        st.session_state.status = "none"
    if "selected_thread" not in st.session_state:
        st.session_state.selected_thread = dict(SAMPLE_THREADS[0])
        st.session_state.selected_thread["source"] = "sample"
    if "generation_count" not in st.session_state:
        st.session_state.generation_count = 0
    if "live_threads" not in st.session_state:
        st.session_state.live_threads = []
    if "show_live" not in st.session_state:
        st.session_state.show_live = False
    if "triage_info" not in st.session_state:
        st.session_state.triage_info = None
    if "show_history" not in st.session_state:
        st.session_state.show_history = False

    # --- Render sidebar ---
    render_sidebar()

    # --- Render main area ---
    thread = st.session_state.get("selected_thread")
    triage_info = st.session_state.get("triage_info")

    if thread is None:
        st.info("Select a thread from the sidebar and click **Generate Draft**.")
        return

    # Show history view if requested
    if st.session_state.get("show_history"):
        st.markdown("### 📋 Approved Drafts History")
        approved = load_approved_drafts()
        if not approved:
            st.info("No approved drafts yet.")
        else:
            for entry in reversed(approved):
                ts = entry.get("timestamp", "")[:19]
                subj = entry.get("subject", "(No subject)")
                edited = "✎" if entry.get("edited") else "✓"
                st.markdown(
                    f"""
                    <div class="history-entry">
                        <div><strong>{ts}</strong> {edited} <em>{subj}</em></div>
                        <div style="color:#a0a0b0;white-space:pre-wrap;">{entry.get('draft', '')}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        if st.button("← Back to Approval Gate"):
            st.session_state.show_history = False
            st.rerun()
        return

    # --- Two-column layout ---
    left_col, right_col = st.columns(2, gap="large")

    with left_col:
        # If this is a live Gmail thread, we only have a snippet — show source info
        if thread.get("source") == "gmail":
            render_thread_column(thread, triage_info)
            st.info(
                "💡 **Gmail thread** — only snippet available. "
                "Use a sample thread or paste custom JSON for the full conversation."
            )
        else:
            render_thread_column(thread, triage_info)

    with right_col:
        render_draft_column(thread)

    # --- Footer ---
    st.markdown("---")
    st.caption(
        "🧠 **Guardrail active:** No email is ever sent without your explicit approval. "
        "Approve ✓ | Edit ✎ | Reject ✖"
    )


if __name__ == "__main__":
    main()