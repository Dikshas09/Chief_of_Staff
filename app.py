"""
The Draft Desk — Unified Streamlit App
==========================================
A 4-phase email workflow tool: Inbox & Triage → Draft Generation → Approval Gate →`Export Proof
"""

import json
import os
import re
from datetime import date
from dotenv import load_dotenv
load_dotenv()

import streamlit as st

# ── Local imports ──────────────────────────────────────────────────────────
from triage import fetch_threads, triage_inbox
from draft_machine import draft_reply
from task_logger import log_action, get_action_log

# ─────────────────────────────────────────────────────────────────────────────
# Page config — MUST be first Streamlit command
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="The Draft Desk",
    page_icon="✍️",
    layout="wide",
)

# ── send_reply — imported after page config so Streamlit is fully initialised ──
from engine import send_reply as _send_reply_fn  # noqa: E402

def _get_send_reply():
    """Return the send_reply callable."""
    return _send_reply_fn


# ── calendar_engine — imported after page config ───────────────────────────
from calendar_engine import (  # noqa: E402
    parse_meeting_request as _parse_meeting_request,
    find_free_slot as _find_free_slot,
    create_event as _create_event,
)

def _get_calendar_engine():
    """Return the calendar engine callables as a tuple."""
    return _parse_meeting_request, _find_free_slot, _create_event

# ─────────────────────────────────────────────────────────────────────────────
# Custom CSS — dark theme
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(
    """
<style>
    .stApp {
        background-color: #1a1a2e;
        color: #e0e0e0;
    }
    section[data-testid="stSidebar"] {
        background-color: #16213e;
    }
    section[data-testid="stSidebar"] .stMarkdown {
        color: #e0e0e0;
    }
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
    .status-badge {
        display: inline-block;
        padding: 4px 14px;
        border-radius: 20px;
        font-weight: 600;
        font-size: 0.85rem;
        margin-right: 6px;
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
    .section-divider {
        border: none;
        border-top: 1px solid #333;
        margin: 20px 0;
    }
    .approval-thread {
        background-color: #0f3460;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 16px;
    }
    .approval-thread .subject-line {
        font-size: 1.1rem;
        font-weight: 600;
        margin-bottom: 8px;
    }
</style>
""",
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helper: resolve API key
# ─────────────────────────────────────────────────────────────────────────────
def resolve_api_key() -> str | None:
    try:
        return st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    except Exception:
        return os.environ.get("GEMINI_API_KEY")


# ─────────────────────────────────────────────────────────────────────────────
# Thread conversion helpers
# ─────────────────────────────────────────────────────────────────────────────
def triage_entry_to_thread(entry: dict) -> dict:
    """
    Convert a triage result entry (from triage_inbox) into a thread dict
    with the format expected by draft_machine / context_builder:
      {id, subject, messages: [{from, date, body}]}
    The original triage entry has: thread_id, sender, subject, snippet, date.
    """
    messages = entry.get("_messages", [])
    if not messages:
        messages = [
            {
                "from": entry.get("sender", "Unknown"),
                "date": entry.get("date", ""),
                "body": entry.get("snippet", "(No content)"),
            }
        ]
    return {
        "id": entry.get("thread_id", ""),
        "subject": entry.get("subject", "(No subject)"),
        "messages": messages,
    }


def load_sample_threads() -> list[dict]:
    """Load sample threads from sample_threads.json."""
    path = "sample_threads.json"
    if not os.path.exists(path):
        st.error(f"Sample threads file not found: {path}")
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline helpers (UI-free wrappers used by run_full_pipeline)
# ─────────────────────────────────────────────────────────────────────────────
def fetch_threads_via_engine(max_results: int = 10) -> list[dict]:
    """Fetch raw threads from Gmail and return them in triage-ready format."""
    return fetch_threads(max_results=max_results)


def triage_threads(raw_threads: list[dict], samples: list[dict] = None) -> list[dict]:
    """
    Run triage_inbox on raw_threads and, if samples are provided, merge
    full message bodies back into the triage results (_messages key).

    Returns the triaged list (same format as st.session_state.triaged).
    """
    triaged = triage_inbox(raw_threads)
    if samples:
        for t in triaged:
            tid = t.get("thread_id", "")
            orig = next((s for s in samples if s.get("id") == tid), None)
            if orig:
                t["_messages"] = orig.get("messages", [])
    return triaged


def _get_draft_reply():
    """Return the draft_reply callable."""
    return draft_reply


# ─────────────────────────────────────────────────────────────────────────────
# run_full_pipeline — fetch → triage → draft, no UI side-effects
# ─────────────────────────────────────────────────────────────────────────────
def run_full_pipeline() -> list[str]:
    """
    Execute the full end-to-end pipeline without rendering any UI.

    Steps:
      1. Determine source from st.session_state.source_selector.
      2. Fetch threads (Gmail or sample file).
      3. Triage fetched threads.
      4. Reset all downstream session state.
      5. Draft replies for every urgent / needs-reply thread.
      6. Set current_phase to "approval".

    Returns:
        A list of log strings describing each step's outcome.
    """
    log: list[str] = []

    # ── 1. Determine source ────────────────────────────────────────────────
    source = st.session_state.get("source_selector", "Sample File")
    log.append(f"Source: {source}")

    # ── 2. Fetch threads ───────────────────────────────────────────────────
    raw_threads: list[dict] = []
    samples: list[dict] = []

    if source == "Gmail":
        try:
            raw_threads = fetch_threads_via_engine(max_results=10)
            log.append(f"Fetched {len(raw_threads)} thread(s) from Gmail.")
        except Exception as exc:
            log.append(f"ERROR fetching Gmail threads: {exc}")
            return log
    else:
        try:
            samples = load_sample_threads()
            if not samples:
                log.append("ERROR: sample_threads.json is empty or missing.")
                return log
            # Convert samples to triage-ready format
            for s in samples:
                body_parts = [m["body"] for m in s.get("messages", [])]
                snippet = " | ".join(body_parts) if body_parts else ""
                raw_threads.append({
                    "thread_id": s.get("id", ""),
                    "sender": s["messages"][0]["from"] if s.get("messages") else "Unknown",
                    "subject": s.get("subject", "(No subject)"),
                    "snippet": snippet,
                    "date": s["messages"][-1]["date"] if s.get("messages") else "",
                })
            log.append(f"Loaded {len(raw_threads)} thread(s) from sample file.")
        except Exception as exc:
            log.append(f"ERROR loading sample threads: {exc}")
            return log

    # ── 3. Triage ──────────────────────────────────────────────────────────
    try:
        triaged = triage_threads(raw_threads, samples=samples or None)
        st.session_state.threads = samples if samples else raw_threads
        st.session_state.triaged = triaged
        actionable_count = sum(
            1 for t in triaged
            if t.get("priority", "").lower() in ("urgent", "needs-reply")
        )
        log.append(f"Triaged {len(triaged)} thread(s); {actionable_count} actionable.")
    except Exception as exc:
        log.append(f"ERROR during triage: {exc}")
        return log

    # ── 4. Reset downstream state ──────────────────────────────────────────
    st.session_state.drafts = {}
    st.session_state.approved = {}
    st.session_state.rejected = set()
    st.session_state.sent = set()
    st.session_state.booked = {}
    st.session_state.actionable_threads = []
    log.append("Reset drafts, approvals, rejections, sent, booked.")

    # ── 5. Draft actionable threads ────────────────────────────────────────
    actionable = [
        t for t in triaged
        if t.get("priority", "").lower() in ("urgent", "needs-reply")
    ]
    actionable_threads = [triage_entry_to_thread(t) for t in actionable]
    st.session_state.actionable_threads = actionable_threads

    draft_fn = _get_draft_reply()
    for thread in actionable_threads:
        thread_id = thread.get("id", "")
        subject = thread.get("subject", "(No subject)")
        try:
            draft = draft_fn(thread)
            st.session_state.drafts[thread_id] = draft
            log.append(f"Drafted: {subject}")
        except Exception as exc:
            st.session_state.drafts[thread_id] = f"[Draft generation failed: {exc}]"
            log.append(f"ERROR drafting '{subject}': {exc}")
            # Continue to next thread — don't abort the pipeline

    log.append(f"Generated {len(st.session_state.drafts)} draft(s).")

    # ── 6. Advance to Approval Gate ────────────────────────────────────────
    st.session_state.current_phase = "approval"
    log.append("Pipeline complete — navigating to Approval Gate.")

    return log


# ─────────────────────────────────────────────────────────────────────────────
# _render_pipeline_execution — full pipeline with live st.status UI
# ─────────────────────────────────────────────────────────────────────────────
def _render_pipeline_execution() -> None:
    """
    Run the full fetch → triage → draft pipeline with live progress UI.

    Uses st.status() to stream step-by-step updates to the user.
    On completion (or fatal error), stores the log, advances the phase,
    clears the running flag, and reruns.
    """
    log: list[str] = []
    source = st.session_state.get("source_selector", "Sample File")

    with st.status("Running full pipeline...", expanded=True) as status:

        # ── Step 1: Fetch ──────────────────────────────────────────────────
        raw_threads: list[dict] = []
        samples: list[dict] = []

        status.update(label="Step 1/3 — Fetching threads...")

        if source == "Gmail":
            try:
                raw_threads = fetch_threads_via_engine(max_results=10)
                msg = f"Fetched {len(raw_threads)} thread(s) from Gmail."
                st.write(f"✅ {msg}")
                log.append(msg)
            except Exception as exc:
                msg = f"Failed to fetch Gmail threads: {exc}"
                st.write(f"❌ {msg}")
                log.append(f"ERROR: {msg}")
                status.update(label="Pipeline failed at fetch step.", state="error")
                st.session_state.pipeline_log = log
                st.session_state.pipeline_running = False
                return
        else:
            try:
                samples = load_sample_threads()
                if not samples:
                    msg = "sample_threads.json is empty or missing."
                    st.write(f"❌ {msg}")
                    log.append(f"ERROR: {msg}")
                    status.update(label="Pipeline failed — no sample data.", state="error")
                    st.session_state.pipeline_log = log
                    st.session_state.pipeline_running = False
                    return
                for s in samples:
                    body_parts = [m["body"] for m in s.get("messages", [])]
                    snippet = " | ".join(body_parts) if body_parts else ""
                    raw_threads.append({
                        "thread_id": s.get("id", ""),
                        "sender": s["messages"][0]["from"] if s.get("messages") else "Unknown",
                        "subject": s.get("subject", "(No subject)"),
                        "snippet": snippet,
                        "date": s["messages"][-1]["date"] if s.get("messages") else "",
                    })
                msg = f"Loaded {len(raw_threads)} thread(s) from sample file."
                st.write(f"✅ {msg}")
                log.append(msg)
            except Exception as exc:
                msg = f"Failed to load sample threads: {exc}"
                st.write(f"❌ {msg}")
                log.append(f"ERROR: {msg}")
                status.update(label="Pipeline failed at fetch step.", state="error")
                st.session_state.pipeline_log = log
                st.session_state.pipeline_running = False
                return

        # ── Step 2: Triage ─────────────────────────────────────────────────
        status.update(label="Step 2/3 — Triaging threads...")

        try:
            triaged = triage_threads(raw_threads, samples=samples or None)
            st.session_state.threads = samples if samples else raw_threads
            st.session_state.triaged = triaged

            actionable_count = sum(
                1 for t in triaged
                if t.get("priority", "").lower() in ("urgent", "needs-reply")
            )
            msg = f"Triaged {len(triaged)} thread(s); {actionable_count} actionable."
            st.write(f"✅ {msg}")
            log.append(msg)
        except Exception as exc:
            msg = f"Triage failed: {exc}"
            st.write(f"❌ {msg}")
            log.append(f"ERROR: {msg}")
            status.update(label="Pipeline failed at triage step.", state="error")
            st.session_state.pipeline_log = log
            st.session_state.pipeline_running = False
            return

        # Reset downstream state now that we have fresh triage data
        st.session_state.drafts = {}
        st.session_state.approved = {}
        st.session_state.rejected = set()
        st.session_state.sent = set()
        st.session_state.booked = {}
        st.session_state.actionable_threads = []

        # ── Step 3: Draft loop ─────────────────────────────────────────────
        actionable = [
            t for t in triaged
            if t.get("priority", "").lower() in ("urgent", "needs-reply")
        ]
        actionable_threads = [triage_entry_to_thread(t) for t in actionable]
        st.session_state.actionable_threads = actionable_threads

        status.update(
            label=f"Step 3/3 — Drafting {len(actionable_threads)} reply/replies..."
        )

        draft_fn = _get_draft_reply()
        for thread in actionable_threads:
            thread_id = thread.get("id", "")
            subject = thread.get("subject", "(No subject)")
            try:
                draft = draft_fn(thread)
                st.session_state.drafts[thread_id] = draft
                msg = f"Drafted reply for: {subject}"
                st.write(f"✅ {msg}")
                log.append(msg)
            except Exception as exc:
                st.session_state.drafts[thread_id] = f"[Draft generation failed: {exc}]"
                msg = f"Draft failed for '{subject}': {exc}"
                st.write(f"❌ {msg}")
                log.append(f"ERROR: {msg}")
                # Continue — one failed draft doesn't abort the pipeline

        done_msg = (
            f"Pipeline complete — {len(st.session_state.drafts)} draft(s) ready."
        )
        st.write(f"✅ {done_msg}")
        log.append(done_msg)
        status.update(label=done_msg, state="complete")

    # ── Outside status block: finalise state and rerun ─────────────────────
    st.session_state.pipeline_log = log
    st.session_state.current_phase = "approval"
    st.session_state.pipeline_running = False
    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Priority emoji helper
# ─────────────────────────────────────────────────────────────────────────────
def priority_emoji(priority: str) -> str:
    return {
        "urgent": "🔴",
        "needs-reply": "🟠",
        "fyi": "🟢",
        "ignore": "⚪",
    }.get(priority.lower(), "❓")


# ─────────────────────────────────────────────────────────────────────────────
# Render a thread message as a styled card
# ─────────────────────────────────────────────────────────────────────────────
def render_thread_message(msg: dict) -> None:
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


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1: Inbox & Triage
# ─────────────────────────────────────────────────────────────────────────────
def phase_inbox_triage():
    st.markdown("## 📬 Inbox & Triage")

    col1, col2 = st.columns([2, 1])

    with col1:
        if st.button(
            "🔍 Fetch & Triage",
            type="primary",
            use_container_width=True,
        ):
            source = st.session_state.source_selector
            with st.spinner("Fetching and triaging threads..."):
                if source == "Gmail":
                    try:
                        raw_threads = fetch_threads(max_results=10)
                        if not raw_threads:
                            st.warning("No threads found in inbox.")
                            st.session_state.threads = []
                            st.session_state.triaged = []
                        else:
                            # triage_inbox expects [{thread_id, sender, subject, snippet, date}]
                            # and returns the same list with priority/category/reason added
                            triaged = triage_inbox(raw_threads)
                            st.session_state.threads = raw_threads
                            st.session_state.triaged = triaged
                            st.success(f"Fetched and triaged {len(triaged)} threads.")
                            st.rerun()
                    except Exception as e:
                        st.error(f"Failed to fetch/triage Gmail threads: {e}")
                else:
                    # Sample File
                    samples = load_sample_threads()
                    if not samples:
                        st.error("Could not load sample_threads.json")
                        st.session_state.threads = []
                        st.session_state.triaged = []
                    else:
                        # Convert sample threads to the format triage_inbox expects:
                        # {thread_id, sender, subject, snippet, date}
                        threads_for_triage = []
                        for s in samples:
                            body_parts = [m["body"] for m in s.get("messages", [])]
                            snippet = " | ".join(body_parts) if body_parts else ""
                            threads_for_triage.append({
                                "thread_id": s.get("id", ""),
                                "sender": s["messages"][0]["from"] if s.get("messages") else "Unknown",
                                "subject": s.get("subject", "(No subject)"),
                                "snippet": snippet,
                                "date": s["messages"][-1]["date"] if s.get("messages") else "",
                            })

                        # Call triage_inbox to classify priorities using AI
                        triaged = triage_inbox(threads_for_triage)

                        # Merge original full message data back into triage results for display
                        for t in triaged:
                            tid = t.get("thread_id", "")
                            orig = next((s for s in samples if s.get("id") == tid), None)
                            if orig:
                                t["_messages"] = orig.get("messages", [])

                        st.session_state.threads = samples
                        st.session_state.triaged = triaged
                        st.success(f"Loaded and triaged {len(triaged)} sample threads.")
                        st.rerun()

    with col2:
        triaged: list[dict] = st.session_state.get("triaged", [])
        if triaged:
            actionable = [
                t for t in triaged
                if t.get("priority", "").lower() in ("urgent", "needs-reply")
            ]
            st.metric("Actionable Threads", len(actionable))

    st.markdown("<hr class='section-divider' />", unsafe_allow_html=True)

    # ── Display triaged threads grouped by priority ──
    triaged = st.session_state.get("triaged", [])
    if not triaged:
        st.info(
            "👈 Click **Fetch & Triage** to get started. "
            "Choose **Sample File** in the sidebar to try without a real Gmail connection."
        )
        return

    priority_order = ["urgent", "needs-reply", "fyi", "ignore"]
    priority_headers = {
        "urgent": "🚨 Urgent",
        "needs-reply": "💬 Needs-Reply",
        "fyi": "📌 FYI",
        "ignore": "🗑️ Ignore",
    }

    for p in priority_order:
        group = [t for t in triaged if t.get("priority", "").lower() == p]
        if not group:
            continue

        with st.expander(f"{priority_headers[p]} — {len(group)} thread(s)", expanded=(p in ("urgent", "needs-reply"))):
            for t in group:
                subject = t.get("subject", "(No subject)")
                st.markdown(f"**{subject}**")

                # Get messages - use _messages (from sample threads) or construct from snippet
                messages = t.get("_messages", [])
                if not messages:
                    # For Gmail threads, construct a single message from available data
                    messages = [{
                        "from": t.get("sender", "Unknown"),
                        "date": t.get("date", ""),
                        "body": t.get("snippet", ""),
                    }]

                for msg in messages:
                    render_thread_message(msg)

    # ── Summary count ──
    st.markdown("<hr class='section-divider' />", unsafe_allow_html=True)
    actionable_count = len([t for t in triaged if t.get("priority", "").lower() in ("urgent", "needs-reply")])
    st.markdown(
        f"**📊 {actionable_count} threads need a reply → go to Draft Generation**"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2: Draft Generation
# ─────────────────────────────────────────────────────────────────────────────
def phase_draft_generation():
    st.markdown("## ✍️ Draft Generation")

    triaged: list[dict] = st.session_state.get("triaged", [])
    if not triaged:
        st.warning("No triaged threads. Please run **Inbox & Triage** first.")
        return

    # Get actionable threads (urgent + needs-reply)
    actionable = [
        t for t in triaged
        if t.get("priority", "").lower() in ("urgent", "needs-reply")
    ]

    if not actionable:
        st.info("No actionable threads (urgent or needs-reply) found.")
        return

    st.markdown(f"Found **{len(actionable)}** actionable thread(s).")

    # Convert actionable triage entries to thread dicts for draft_machine
    actionable_threads = [triage_entry_to_thread(t) for t in actionable]

    # Store these for the pipeline
    st.session_state.actionable_threads = actionable_threads

    # Generate All Drafts button
    if st.button(
        "🚀 Generate All Drafts",
        type="primary",
        use_container_width=True,
    ):
        api_key = resolve_api_key()
        if not api_key:
            st.error("GEMINI_API_KEY not found. Please add it to your .env file or Streamlit secrets.")
        else:
            # Initialize drafts dict
            st.session_state.drafts = {}
            progress_bar = st.progress(0, text="Generating drafts...")
            status_text = st.empty()

            for i, thread in enumerate(actionable_threads):
                thread_id = thread.get("id", f"thread_{i}")
                subject = thread.get("subject", "(No subject)")
                status_text.text(f"Generating draft {i+1}/{len(actionable_threads)}: {subject}")

                try:
                    draft = draft_reply(thread)
                    st.session_state.drafts[thread_id] = draft
                except Exception as e:
                    st.session_state.drafts[thread_id] = f"[Error generating draft: {e}]"
                    st.warning(f"Draft generation failed for '{subject}': {e}")

                progress_bar.progress((i + 1) / len(actionable_threads))

            status_text.text("✅ All drafts generated!")
            st.success(f"Generated {len(st.session_state.drafts)} draft(s). Proceed to **Approval Gate** →")
            st.rerun()

    st.markdown("<hr class='section-divider' />", unsafe_allow_html=True)

    # ── Display existing drafts ──
    drafts: dict = st.session_state.get("drafts", {})
    if not drafts:
        st.info("No drafts generated yet. Click **Generate All Drafts** above.")
        return

    st.markdown(f"### 📝 {len(drafts)} Draft(s) Generated")

    for thread in actionable_threads:
        thread_id = thread.get("id", "")
        subject = thread.get("subject", "(No subject)")
        draft_text = drafts.get(thread_id, "")

        if not draft_text:
            continue

        # Find original triage entry for priority badge
        orig = next(
            (t for t in actionable if t.get("thread_id", "") == thread_id),
            None,
        )
        priority = orig.get("priority", "").lower() if orig else ""
        badge = f'<span class="status-badge priority-{priority}">{priority.upper()}</span>' if priority in ("urgent", "needs-reply") else ""

        with st.expander(f"{badge} {subject}", expanded=True):
            col_left, col_right = st.columns(2)

            with col_left:
                st.markdown("**📧 Latest Message**")
                if thread.get("messages"):
                    latest = thread["messages"][-1]
                    st.markdown(
                        f"""
                        <div class="thread-msg">
                            <div class="sender">{latest['from']}</div>
                            <div class="date">{latest.get('date', '')}</div>
                            <div class="body">{latest['body']}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

            with col_right:
                st.markdown("**✍️ Draft Reply**")
                st.markdown(
                    f'<div class="draft-box">{draft_text}</div>',
                    unsafe_allow_html=True,
                )

    if drafts:
        st.info("👉 Head over to **Approval Gate** to review and approve each draft.")


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3: Approval Gate
# ─────────────────────────────────────────────────────────────────────────────
def phase_approval_gate():
    st.markdown("## ✅ Approval Gate")

    drafts: dict = st.session_state.get("drafts", {})
    if not drafts:
        st.warning("No drafts to review. Please run **Draft Generation** first.")
        return

    actionable_threads: list[dict] = st.session_state.get("actionable_threads", [])
    if not actionable_threads:
        st.warning("No actionable threads available. Please run **Inbox & Triage** first.")
        return

    # Ensure session state tracking
    if "approved" not in st.session_state:
        st.session_state.approved = {}
    if "rejected" not in st.session_state:
        st.session_state.rejected = set()
    if "current_phase" not in st.session_state:
        st.session_state.current_phase = "approval"

    # ── Running count ──
    approved_count = len(st.session_state.approved)
    rejected_count = len(st.session_state.rejected)
    pending_count = len(drafts) - approved_count - rejected_count

    col1, col2, col3 = st.columns(3)
    col1.metric("✅ Approved", approved_count)
    col2.metric("✖ Rejected", rejected_count)
    col3.metric("⏳ Pending", max(0, pending_count))

    st.markdown("<hr class='section-divider' />", unsafe_allow_html=True)

    # ── Pipeline execution log ─────────────────────────────────────────────
    pipeline_log: list = st.session_state.get("pipeline_log", [])
    if pipeline_log:
        with st.expander("🪵 Pipeline Execution Log", expanded=False):
            for entry in pipeline_log:
                upper = entry.upper()
                if "ERROR" in upper or "FAILED" in upper:
                    st.write(f"❌ {entry}")
                else:
                    st.write(f"✅ {entry}")
            if st.button("🗑️ Clear log", key="btn_clear_pipeline_log"):
                st.session_state.pipeline_log = []
                st.rerun()
        st.markdown("<hr class='section-divider' />", unsafe_allow_html=True)

    # ── Review each draft ──
    all_reviewed = True

    for thread in actionable_threads:
        thread_id = thread.get("id", "")
        subject = thread.get("subject", "(No subject)")
        draft_text = drafts.get(thread_id, "")

        if not draft_text:
            continue

        # Skip if already approved or rejected
        is_approved = thread_id in st.session_state.approved
        is_rejected = thread_id in st.session_state.rejected
        is_sent = thread_id in st.session_state.get("sent", set())

        if is_approved:
            is_booked = thread_id in st.session_state.get("booked", {})

            # Look up the triage category for this thread
            triaged_list: list[dict] = st.session_state.get("triaged", [])
            triage_entry = next(
                (t for t in triaged_list if t.get("thread_id", "") == thread_id),
                None,
            )
            category = triage_entry.get("category", "") if triage_entry else ""
            is_meeting_request = category == "meeting-request"

            # Status badges
            sent_badge = (
                '<span class="status-badge" style="background:#1565c0;color:#fff;">📨 Sent</span>'
                if is_sent else ""
            )
            booked_badge = (
                '<span class="status-badge" style="background:#6a1b9a;color:#fff;">📅 Booked</span>'
                if is_booked else ""
            )
            status_text = "Sent ✓" if is_sent else ("Booked ✓" if is_booked else "Approved — ready to send")

            st.markdown(
                f"""
                <div class="approval-thread" style="border-left: 4px solid #00c853;">
                    <div class="subject-line">✅ {subject} {sent_badge} {booked_badge}</div>
                    <div style="color:#a0a0b0;">{status_text}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # ── Action buttons ─────────────────────────────────────────────
            if not is_sent and not is_booked:
                if is_meeting_request:
                    btn_col_send, btn_col_book = st.columns(2)
                else:
                    btn_col_send = st.container()
                    btn_col_book = None

                # Send Reply button
                with btn_col_send:
                    if st.button(
                        "📨 Send Reply",
                        use_container_width=is_meeting_request,
                        key=f"send_{thread_id}",
                    ):
                        messages = thread.get("messages", [])
                        last_from = messages[-1]["from"] if messages else ""
                        match = re.search(r"<([^>]+)>", last_from)
                        recipient = match.group(1) if match else last_from.strip()

                        approved_body = st.session_state.approved[thread_id]
                        send_reply_fn = _get_send_reply()
                        try:
                            result = send_reply_fn(
                                thread_id=thread_id,
                                to=recipient,
                                subject=subject,
                                body=approved_body,
                            )
                            st.session_state.sent.add(thread_id)
                            if result.get("message_id"):
                                log_action(
                                    action_type="sent",
                                    thread_subject=thread.get("subject", subject),
                                    detail=recipient,
                                    action_id=result["message_id"],
                                )
                            st.success(f"✅ Reply sent to {recipient}! (message id: {result.get('message_id')})")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Failed to send reply: {exc}")

                # Book Meeting button — only for meeting-request threads
                if is_meeting_request and btn_col_book is not None:
                    with btn_col_book:
                        if st.button(
                            "📅 Book Meeting",
                            use_container_width=True,
                            key=f"book_{thread_id}",
                        ):
                            parse_fn, find_slot_fn, create_fn = _get_calendar_engine()

                            with st.spinner("Extracting meeting details…"):
                                meeting = parse_fn(thread)

                            if "parsing_error" in meeting:
                                st.error(f"Could not parse meeting details: {meeting['parsing_error']}")
                            else:
                                st.info(
                                    f"**Topic:** {meeting.get('topic', subject)}  \n"
                                    f"**Duration:** {meeting.get('duration_minutes', 30)} min  \n"
                                    f"**Proposed times:** {', '.join(meeting.get('proposed_times', [])) or 'none found'}  \n"
                                    f"**Attendees:** {', '.join(meeting.get('attendees', [])) or 'none found'}"
                                )

                                with st.spinner("Checking calendar availability…"):
                                    free_slot = find_slot_fn(
                                        meeting.get("proposed_times", []),
                                        meeting.get("duration_minutes", 30),
                                    )

                                if free_slot is None:
                                    st.warning("No free slot found among the proposed times. Please book manually.")
                                else:
                                    with st.spinner(f"Creating event at {free_slot}…"):
                                        try:
                                            event = create_fn(
                                                summary=meeting.get("topic", subject),
                                                start_time=free_slot,
                                                duration_minutes=meeting.get("duration_minutes", 30),
                                                attendees=meeting.get("attendees", []),
                                                description=st.session_state.approved.get(thread_id, ""),
                                            )
                                            st.session_state.booked[thread_id] = event
                                            event_link = event.get("htmlLink", "")
                                            if event.get("id"):
                                                log_action(
                                                    action_type="booked",
                                                    thread_subject=thread.get("subject", subject),
                                                    detail=meeting.get("topic", subject),
                                                    action_id=event["id"],
                                                )
                                            st.success(
                                                f"📅 Meeting booked at {free_slot}! "
                                                f"[Open in Google Calendar]({event_link})"
                                            )
                                            st.rerun()
                                        except Exception as exc:
                                            st.error(f"Failed to create calendar event: {exc}")

            elif is_booked:
                event = st.session_state.booked[thread_id]
                event_link = event.get("htmlLink", "")
                if event_link:
                    st.markdown(f"📅 [Open booked event in Google Calendar]({event_link})")

            continue

        if is_rejected:
            st.markdown(
                f"""
                <div class="approval-thread" style="border-left: 4px solid #ff1744;">
                    <div class="subject-line">✖ {subject}</div>
                    <div style="color:#a0a0b0;">Rejected</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            continue

        all_reviewed = False

        # Find priority for badge
        triaged: list[dict] = st.session_state.get("triaged", [])
        orig = next(
            (t for t in triaged if t.get("thread_id", "") == thread_id),
            None,
        )
        priority = orig.get("priority", "").lower() if orig else ""
        emoji = priority_emoji(priority)

        st.markdown(
            f"""
            <div class="approval-thread">
                <div class="subject-line">{emoji} {subject}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        left_col, right_col = st.columns(2)

        with left_col:
            st.markdown("**📧 Full Thread**")
            for msg in thread.get("messages", []):
                render_thread_message(msg)

        with right_col:
            st.markdown("**✍️ Draft (editable)**")
            # Unique key per thread for the text_area
            edit_key = f"edit_{thread_id}"
            edited_draft = st.text_area(
                "Edit the draft before approving:",
                value=draft_text,
                height=200,
                key=edit_key,
                label_visibility="collapsed",
            )

            col_a, col_b, col_c = st.columns(3)

            with col_a:
                if st.button(
                    "✅ Approve",
                    type="primary",
                    use_container_width=True,
                    key=f"approve_{thread_id}",
                ):
                    st.session_state.approved[thread_id] = edited_draft
                    st.rerun()

            with col_b:
                if st.button(
                    "🔄 Regenerate",
                    use_container_width=True,
                    key=f"regenerate_{thread_id}",
                ):
                    api_key = resolve_api_key()
                    if not api_key:
                        st.error("GEMINI_API_KEY not found.")
                    else:
                        with st.spinner("Regenerating draft..."):
                            try:
                                new_draft = draft_reply(thread)
                                st.session_state.drafts[thread_id] = new_draft
                                st.rerun()
                            except Exception as e:
                                st.error(f"Regeneration failed: {e}")

            with col_c:
                if st.button(
                    "✖ Reject",
                    use_container_width=True,
                    key=f"reject_{thread_id}",
                ):
                    st.session_state.rejected.add(thread_id)
                    st.rerun()

        st.markdown("<hr class='section-divider' />", unsafe_allow_html=True)

    # ── All reviewed? ──
    if all_reviewed and drafts:
        st.balloons()
        st.success(
            "🎉 All drafts reviewed! "
            f"**{approved_count} approved**, **{rejected_count} rejected**. "
            "Proceed to **Export Proof** to download your work."
        )
    elif not drafts:
        st.info("No drafts to review.")


# ─────────────────────────────────────────────────────────────────────────────
# Phase 4: Export Proof
# ─────────────────────────────────────────────────────────────────────────────
def generate_proof_markdown(approved_drafts: dict, threads: list[dict]) -> str:
    """Generate a Markdown proof-of-work document."""
    lines = []
    lines.append("# The Draft Desk — Proof of Work")
    lines.append(f"**Date:** {date.today().isoformat()}")
    lines.append(f"**Total Approved:** {len(approved_drafts)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for thread in threads:
        thread_id = thread.get("id", "")
        if thread_id not in approved_drafts:
            continue
        subject = thread.get("subject", "(No subject)")
        draft_text = approved_drafts[thread_id]

        lines.append(f"## {subject}")
        lines.append("")
        lines.append("### Original Thread")
        lines.append("")
        for msg in thread.get("messages", []):
            lines.append(f"> **From:** {msg['from']}  ")
            lines.append(f"> **Date:** {msg.get('date', '')}  ")
            lines.append(f">  ")
            for line in msg["body"].split("\n"):
                lines.append(f"> {line}")
            lines.append(f">  ")
        lines.append("")
        lines.append("### Draft Reply")
        lines.append("")
        lines.append("```")
        lines.append(draft_text)
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def generate_proof_html(approved_drafts: dict, threads: list[dict], action_log: list = None) -> str:
    """Generate a styled HTML proof-of-work document."""
    cards_html = ""

    for thread in threads:
        thread_id = thread.get("id", "")
        if thread_id not in approved_drafts:
            continue
        subject = thread.get("subject", "(No subject)")
        draft_text = approved_drafts[thread_id]

        # Build original messages HTML
        messages_html = ""
        for msg in thread.get("messages", []):
            messages_html += f"""
            <div style="background:#0f3460;border-left:3px solid #e94560;border-radius:4px;padding:10px 14px;margin-bottom:10px;">
                <div style="color:#e94560;font-weight:600;font-size:0.9rem;">{msg['from']}</div>
                <div style="color:#a0a0b0;font-size:0.75rem;margin-bottom:4px;">{msg.get('date', '')}</div>
                <div style="color:#e0e0e0;font-size:0.9rem;line-height:1.5;">{msg['body']}</div>
            </div>
            """

        cards_html += f"""
        <div style="margin-bottom:32px;">
            <h3 style="color:#e94560;margin-bottom:16px;">{subject}</h3>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;">
                <div style="background:#16213e;border:2px solid #e94560;border-radius:8px;padding:16px;">
                    <h4 style="color:#e94560;margin-top:0;margin-bottom:12px;">📧 Original Thread</h4>
                    {messages_html}
                </div>
                <div style="background:#16213e;border:2px solid #00c853;border-radius:8px;padding:16px;">
                    <h4 style="color:#00c853;margin-top:0;margin-bottom:12px;">✍️ Draft Reply</h4>
                    <div style="background:#0f3460;border-radius:4px;padding:14px;color:#e0e0e0;font-size:0.9rem;line-height:1.6;white-space:pre-wrap;">{draft_text}</div>
                </div>
            </div>
        </div>
        """

    # ── Action log section ─────────────────────────────────────────────────
    log_rows_html = ""
    if action_log:
        for entry in action_log:
            a_type = entry.get("action_type", "")
            icon = "📨" if a_type == "sent" else "📅"
            badge_color = "#1565c0" if a_type == "sent" else "#6a1b9a"

            raw_ts = entry.get("timestamp", "")
            try:
                from datetime import datetime, timezone as _tz
                ts = datetime.fromisoformat(raw_ts.rstrip("Z")).replace(tzinfo=_tz.utc)
                formatted_ts = ts.strftime("%b %d %I:%M %p")
            except Exception:
                formatted_ts = raw_ts

            log_rows_html += f"""
            <tr>
                <td style="padding:10px 12px;">
                    <span style="background:{badge_color};color:#fff;padding:3px 10px;border-radius:12px;font-size:0.78rem;font-weight:600;">
                        {icon} {a_type.upper()}
                    </span>
                </td>
                <td style="padding:10px 12px;color:#e0e0e0;font-weight:600;">{entry.get('thread_subject', '')}</td>
                <td style="padding:10px 12px;"><code style="background:#0f3460;padding:2px 8px;border-radius:4px;font-size:0.85rem;color:#a0d8ef;">{entry.get('detail', '')}</code></td>
                <td style="padding:10px 12px;color:#a0a0b0;font-size:0.82rem;">{formatted_ts}</td>
            </tr>
            """

    action_log_html = ""
    if log_rows_html:
        action_log_html = f"""
    <hr>
    <h2 style="color:#e0e0e0;font-size:1.3rem;margin-bottom:16px;">📋 Action Log</h2>
    <div style="overflow-x:auto;">
        <table style="width:100%;border-collapse:collapse;background:#16213e;border-radius:8px;overflow:hidden;">
            <thead>
                <tr style="background:#0f3460;">
                    <th style="padding:10px 12px;text-align:left;color:#a0a0b0;font-size:0.82rem;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;">Action</th>
                    <th style="padding:10px 12px;text-align:left;color:#a0a0b0;font-size:0.82rem;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;">Thread</th>
                    <th style="padding:10px 12px;text-align:left;color:#a0a0b0;font-size:0.82rem;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;">Detail</th>
                    <th style="padding:10px 12px;text-align:left;color:#a0a0b0;font-size:0.82rem;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;">Time</th>
                </tr>
            </thead>
            <tbody>
                {log_rows_html}
            </tbody>
        </table>
    </div>
        """
    else:
        action_log_html = """
    <hr>
    <h2 style="color:#e0e0e0;font-size:1.3rem;margin-bottom:16px;">📋 Action Log</h2>
    <p style="color:#a0a0b0;font-style:italic;">No actions logged yet.</p>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>The Draft Desk — Proof of Work</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background-color: #1a1a2e;
            color: #e0e0e0;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            padding: 40px;
            max-width: 1200px;
            margin: 0 auto;
        }}
        h1 {{ color: #e94560; font-size: 2rem; margin-bottom: 8px; }}
        h2 {{ color: #a0a0b0; font-weight: 400; font-size: 1rem; margin-bottom: 32px; }}
        hr {{ border: none; border-top: 1px solid #333; margin: 24px 0; }}
        tbody tr:nth-child(even) {{ background: #1a2744; }}
        .footer {{ text-align: center; color: #555; font-size: 0.8rem; margin-top: 48px; }}
    </style>
</head>
<body>
    <h1>✍️ The Draft Desk — Proof of Work</h1>
    <h2>Date: {date.today().isoformat()} · Total Approved: {len(approved_drafts)}</h2>
    <hr>
    {cards_html}
    {action_log_html}
    <hr>
    <div class="footer">
        Generated by The Draft Desk · All drafts were human-approved before export
    </div>
</body>
</html>"""
    return html


def phase_export_proof():
    st.markdown("## 📄 Export Proof")

    approved_drafts: dict = st.session_state.get("approved", {})
    if not approved_drafts:
        st.warning("No approved drafts yet. Please review and approve drafts in **Approval Gate** first.")
        return

    actionable_threads: list[dict] = st.session_state.get("actionable_threads", [])
    if not actionable_threads:
        st.warning("No thread data available.")
        return

    # Filter to only threads that have approved drafts
    approved_threads = [t for t in actionable_threads if t.get("id", "") in approved_drafts]

    st.success(f"🎉 **{len(approved_drafts)} approved draft(s)** ready for export!")

    # ── Preview ──
    st.markdown("### 📋 Preview")
    for thread in approved_threads:
        thread_id = thread.get("id", "")
        subject = thread.get("subject", "(No subject)")
        draft_text = approved_drafts[thread_id]

        col_left, col_right = st.columns(2)

        with col_left:
            st.markdown(f"**📧 {subject}**")
            for msg in thread.get("messages", []):
                render_thread_message(msg)

        with col_right:
            st.markdown("**✍️ Approved Draft**")
            st.markdown(
                f'<div class="draft-box">{draft_text}</div>',
                unsafe_allow_html=True,
            )

        st.markdown("<hr class='section-divider' />", unsafe_allow_html=True)

    # ── Action Log ────────────────────────────────────────────────────────
    st.markdown("### 📋 Action Log")
    action_log = get_action_log()
    if not action_log:
        st.info("No actions logged yet.")
    else:
        for entry in action_log:
            a_type = entry.get("action_type", "")
            icon = "📨" if a_type == "sent" else "📅"
            label = f"{icon} {a_type.upper()}"

            # Format timestamp: "Jan 01 02:30 PM"
            raw_ts = entry.get("timestamp", "")
            try:
                from datetime import datetime, timezone
                ts = datetime.fromisoformat(raw_ts.rstrip("Z")).replace(tzinfo=timezone.utc)
                formatted_ts = ts.strftime("%b %d %I:%M %p")
            except Exception:
                formatted_ts = raw_ts

            c1, c2, c3, c4 = st.columns([1, 3, 3, 2])
            c1.markdown(label)
            c2.markdown(f"**{entry.get('thread_subject', '')}**")
            c3.markdown(f"`{entry.get('detail', '')}`")
            c4.caption(formatted_ts)

    st.markdown("<hr class='section-divider' />", unsafe_allow_html=True)

    # ── Generate and offer downloads ──
    st.markdown("### 💾 Download")
    md_content = generate_proof_markdown(approved_drafts, approved_threads)
    html_content = generate_proof_html(approved_drafts, approved_threads, action_log=get_action_log())

    col1, col2 = st.columns(2)

    with col1:
        st.download_button(
            label="📥 Download Proof (Markdown)",
            data=md_content,
            file_name=f"draft_desk_proof_{date.today().isoformat()}.md",
            mime="text/markdown",
            use_container_width=True,
        )

    with col2:
        st.download_button(
            label="📥 Download Proof (HTML)",
            data=html_content,
            file_name=f"draft_desk_proof_{date.today().isoformat()}.html",
            mime="text/html",
            use_container_width=True,
        )

    st.markdown(
        """
        <div style="text-align:center;margin-top:32px;color:#a0a0b0;">
            ✅ All approved drafts are saved. The HTML file is styled and ready to share on social media.
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Share note ──
    st.markdown(
        """
        <div style="text-align:center;margin-top:24px;padding:20px;background:#16213e;border-radius:8px;border:1px solid #533483;">
            <p style="color:#e94560;font-size:1.1rem;font-weight:600;margin-bottom:8px;">
                🏆 Share your work!
            </p>
            <p style="color:#e0e0e0;font-size:0.95rem;">
                Post your proof with <strong style="color:#00c853;">#MyAIChiefOfStaff</strong> 
                to earn your <strong style="color:#ffd700;">Ghostwriter badge</strong>! 🖊️✨
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────
def render_sidebar():
    st.sidebar.title("✍️ The Draft Desk")
    st.sidebar.markdown("AI-powered email workflow — from inbox to approved draft.")
    st.sidebar.markdown("<hr class='section-divider' />", unsafe_allow_html=True)

    # ── Run Full Pipeline button ───────────────────────────────────────────
    if st.sidebar.button(
        "⚡ Run Full Pipeline",
        type="primary",
        use_container_width=True,
        key="btn_run_pipeline",
    ):
        st.session_state.pipeline_running = True
        st.rerun()
    st.sidebar.caption("Fetches, triages, and drafts — stops at Approval Gate.")
    st.sidebar.markdown("<hr class='section-divider' />", unsafe_allow_html=True)

    # ── Source selector ──
    st.sidebar.markdown("### 📡 Source")
    st.sidebar.radio(
        "Select email source:",
        ["Gmail", "Sample File"],
        key="source_selector",
        label_visibility="collapsed",
    )

    st.sidebar.markdown("<hr class='section-divider' />", unsafe_allow_html=True)

    # ── Workflow navigation ──
    st.sidebar.markdown("### 📋 Workflow")

    phases = {
        "Inbox & Triage": "inbox_triage",
        "Draft Generation": "draft_gen",
        "Approval Gate": "approval",
        "Export Proof": "export",
    }

    for label, phase_key in phases.items():
        # Check if this phase is accessible
        disabled = False
        help_text = ""

        if phase_key == "draft_gen" and not st.session_state.get("triaged"):
            disabled = True
            help_text = "Complete Inbox & Triage first"
        elif phase_key == "approval" and not st.session_state.get("drafts"):
            disabled = True
            help_text = "Complete Draft Generation first"
        elif phase_key == "export" and not st.session_state.get("approved"):
            disabled = True
            help_text = "Complete Approval Gate first"

        if disabled:
            st.sidebar.button(
                label,
                disabled=True,
                use_container_width=True,
                help=help_text,
                key=f"disabled_btn_{phase_key}"
            )
        else:
            if st.sidebar.button(
                label,
                use_container_width=True,
                type="primary" if st.session_state.current_phase == phase_key else "secondary",
                key=f"nav_btn_{phase_key}"
            ):
                st.session_state.current_phase = phase_key
                st.rerun()

    st.sidebar.markdown("<hr class='section-divider' />", unsafe_allow_html=True)

    # ── Status summary ──
    st.sidebar.markdown("### 📊 Status")
    triaged = st.session_state.get("triaged", [])
    drafts = st.session_state.get("drafts", {})
    approved = st.session_state.get("approved", {})

    if triaged:
        st.sidebar.markdown(f"**Triaged:** {len(triaged)} threads")
    if drafts:
        st.sidebar.markdown(f"**Drafts:** {len(drafts)}")
    if approved:
        st.sidebar.markdown(f"**Approved:** {len(approved)}")


# ─────────────────────────────────────────────────────────────────────────────
# Main app
# ─────────────────────────────────────────────────────────────────────────────
def main():
    # ── Initialise session state ──
    if "threads" not in st.session_state:
        st.session_state.threads = []
    if "triaged" not in st.session_state:
        st.session_state.triaged = []
    if "drafts" not in st.session_state:
        st.session_state.drafts = {}
    if "approved" not in st.session_state:
        st.session_state.approved = {}
    if "rejected" not in st.session_state:
        st.session_state.rejected = set()
    if "current_phase" not in st.session_state:
        st.session_state.current_phase = "inbox_triage"
    if "source_selector" not in st.session_state:
        st.session_state.source_selector = "Sample File"
    if "actionable_threads" not in st.session_state:
        st.session_state.actionable_threads = []
    if "sent" not in st.session_state:
        st.session_state.sent = set()
    if "booked" not in st.session_state:
        st.session_state.booked = {}
    if "pipeline_running" not in st.session_state:
        st.session_state.pipeline_running = False
    if "pipeline_log" not in st.session_state:
        st.session_state.pipeline_log = []

    # ── Render sidebar ──
    render_sidebar()

    # ── Pipeline in progress: hand off to progress UI ──
    if st.session_state.get("pipeline_running", False):
        _render_pipeline_execution()
        return

    # ── Render current phase ──
    phase = st.session_state.current_phase

    if phase == "inbox_triage":
        phase_inbox_triage()
    elif phase == "draft_gen":
        phase_draft_generation()
    elif phase == "approval":
        phase_approval_gate()
    elif phase == "export":
        phase_export_proof()


if __name__ == "__main__":
    main()