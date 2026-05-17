"""
app.py — Streamlit entry point for the Pega MCP Court Assistant.

Page structure:
  - Header bar: app title, OAuth status indicator, reset button
  - Body: two columns — chat (65%) on the left, protocol panel (35%) on the right
  - Footer: small disclaimer / version

Run locally:
    streamlit run app.py

Required environment:
  - Pega credentials in .streamlit/secrets.toml (or PEGA_CLIENT_ID /
    PEGA_CLIENT_SECRET env vars for non-Streamlit testing)
  - Optional demo password in secrets.toml under [app] demo_password
"""

import time
import streamlit as st

from config import (
    get_demo_password,
    PEGA_AGENT_ID,
    PEGA_BASE_URL,
)
from mcp_wrapper import MCPCourtAgent
from protocol_log import ProtocolLog
from ui_chat import (
    render_chat_history,
    render_chat_input,
    append_user_message,
    append_assistant_message,
    clear_chat_history,
)
from ui_protocol import (
    inject_protocol_css,
    render_protocol_panel,
)


# ---------------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Pega MCP Court Assistant",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ---------------------------------------------------------------------------
# Custom CSS for the overall page layout
# ---------------------------------------------------------------------------

def _inject_global_css() -> None:
    st.markdown(
        """
        <style>
        /* Tighten the top of the page — Streamlit's default padding is excessive */
        .block-container {
            padding-top: 1.5rem;
            padding-bottom: 2rem;
            max-width: 1400px;
        }
        /* Header bar */
        .app-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 0 14px 0;
            border-bottom: 1px solid #e5e7eb;
            margin-bottom: 18px;
        }
        .app-title {
            font-size: 1.35rem;
            font-weight: 700;
            color: #111827;
            letter-spacing: -0.01em;
        }
        .app-subtitle {
            font-size: 0.82rem;
            color: #6b7280;
            margin-top: 2px;
        }
        .status-pill {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 10px;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 500;
            font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
        }
        .status-pill.ok {
            background: #f0fdf4;
            color: #166534;
            border: 1px solid #bbf7d0;
        }
        .status-pill.idle {
            background: #f9fafb;
            color: #6b7280;
            border: 1px solid #e5e7eb;
        }
        .status-pill.warn {
            background: #fef3c7;
            color: #92400e;
            border: 1px solid #fde68a;
        }
        .status-pill.bad {
            background: #fee2e2;
            color: #991b1b;
            border: 1px solid #fecaca;
        }
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: currentColor;
        }
        /* Section labels above each column */
        .col-label {
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-size: 0.72rem;
            font-weight: 600;
            color: #6b7280;
            margin-bottom: 10px;
            padding-bottom: 6px;
            border-bottom: 1px solid #f3f4f6;
        }
        /* Footer */
        .app-footer {
            margin-top: 32px;
            padding-top: 16px;
            border-top: 1px solid #f3f4f6;
            color: #9ca3af;
            font-size: 0.72rem;
            font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Password gate
# ---------------------------------------------------------------------------

def password_gate() -> bool:
    """
    Render a password gate if a demo password is configured.

    Returns True if access is granted (no password required or password
    matched). Returns False if a password is configured but not yet
    correctly entered.
    """
    configured = get_demo_password()
    if not configured:
        # No password configured — open access. This is fine for local
        # development but a warning at deployment time (see footer).
        return True

    if st.session_state.get("password_ok"):
        return True

    st.markdown(
        '<div class="app-header">'
        '<div><div class="app-title">Pega MCP Court Assistant</div>'
        '<div class="app-subtitle">Demo access requires password</div></div>'
        '</div>',
        unsafe_allow_html=True,
    )

    entered = st.text_input(
        "Demo password",
        type="password",
        placeholder="Enter the demo password to continue",
    )
    if entered:
        if entered == configured:
            st.session_state.password_ok = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False


# ---------------------------------------------------------------------------
# Session-state initialization
# ---------------------------------------------------------------------------

def _ensure_state() -> None:
    if "mcp_agent" not in st.session_state:
        st.session_state.mcp_agent = MCPCourtAgent()
    if "protocol_log" not in st.session_state:
        st.session_state.protocol_log = ProtocolLog()
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "pending_user_message" not in st.session_state:
        st.session_state.pending_user_message = None


# ---------------------------------------------------------------------------
# Header bar
# ---------------------------------------------------------------------------

def _render_header() -> None:
    agent: MCPCourtAgent = st.session_state.mcp_agent
    log: ProtocolLog = st.session_state.protocol_log

    # Authentication status
    if agent.client.is_authenticated():
        remaining = agent.client.token_seconds_remaining() or 0
        status_class = "ok"
        status_text = f"Pega OAuth · {int(remaining // 60)}m remaining"
    elif agent.client._token is not None:  # noqa: SLF001 — read-only access
        status_class = "warn"
        status_text = "Pega OAuth · refreshing"
    else:
        status_class = "idle"
        status_text = "Pega OAuth · not yet authenticated"

    conv_id = agent.conversation_id or "—"
    turn_count = log.turn_count()

    # Render header HTML
    st.markdown(
        f"""
        <div class="app-header">
            <div>
                <div class="app-title">Pega MCP Court Assistant</div>
                <div class="app-subtitle">
                    Streamlit · MCP-style interface · Pega AgentX agent
                    <code>{PEGA_AGENT_ID}</code>
                </div>
            </div>
            <div style="display: flex; gap: 10px; align-items: center;">
                <span class="status-pill {status_class}">
                    <span class="status-dot"></span>{status_text}
                </span>
                <span class="status-pill idle">
                    conv <code>{conv_id}</code>
                </span>
                <span class="status-pill idle">
                    turns <code>{turn_count}</code>
                </span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Reset button — separate from the header HTML so Streamlit can wire it
    col_a, col_b, col_c = st.columns([6, 6, 1])
    with col_c:
        if st.button("Reset", help="Start a new Pega conversation", use_container_width=True):
            _reset_conversation()


def _reset_conversation() -> None:
    """Discard the current conversation, chat history, and protocol log."""
    agent: MCPCourtAgent = st.session_state.mcp_agent
    agent.reset_conversation()
    st.session_state.protocol_log = ProtocolLog()
    clear_chat_history()
    st.rerun()


# ---------------------------------------------------------------------------
# Body — two-column layout
# ---------------------------------------------------------------------------

def _render_body() -> None:
    left, right = st.columns([13, 7], gap="large")

    with left:
        st.markdown(
            '<div class="col-label">Conversation</div>',
            unsafe_allow_html=True,
        )
        render_chat_history()

    with right:
        st.markdown(
            '<div class="col-label">MCP Protocol</div>',
            unsafe_allow_html=True,
        )
        render_protocol_panel(st.session_state.protocol_log)


# ---------------------------------------------------------------------------
# Turn handling — submit a message, wait, append response
# ---------------------------------------------------------------------------

def _handle_user_turn(message: str) -> None:
    """
    Process a single user turn: send the message via the MCP wrapper,
    show a live latency counter while waiting, then append the
    response to the chat history and the protocol log.
    """
    append_user_message(message)

    agent: MCPCourtAgent = st.session_state.mcp_agent
    log: ProtocolLog = st.session_state.protocol_log

    # Live latency counter during the wait. Streamlit doesn't give us
    # background threads, so we fake "live" by polling-style updates
    # while the actual HTTP call is in flight on a worker thread.
    #
    # For simplicity and to avoid threading complexity, we use a single
    # st.status block that updates after the call returns. The visible
    # behavior: spinner spins, label says "Agent is thinking...", and
    # once the call returns we report the elapsed time. Honest, simple,
    # works reliably.
    start = time.time()
    error_message = None
    wrapped = None
    create_entry = None

    with st.status("Agent is thinking...", expanded=False) as status:
        try:
            wrapped, create_entry = agent.invoke(message)
            elapsed = time.time() - start
            status.update(
                label=f"Agent responded in {elapsed:.2f}s",
                state="complete",
                expanded=False,
            )
        except Exception as e:
            elapsed = time.time() - start
            error_message = str(e)
            status.update(
                label=f"Pega request failed after {elapsed:.2f}s",
                state="error",
                expanded=True,
            )
            st.error(f"Error: {error_message}")

    if error_message:
        append_assistant_message(
            f"_The request to Pega failed: `{error_message}`_\n\n"
            "Check the OAuth status pill in the header — if it isn't green, "
            "the credentials may be wrong or the Pega instance may be "
            "unavailable. Click Reset to start over."
        )
        return

    # Record the conversation-creation entry (first turn only)
    if create_entry is not None:
        log.append(create_entry)

    # Record the message entry
    log.append(wrapped.protocol_entry)

    # Append the agent's text response to the chat
    append_assistant_message(wrapped.response_text)


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

def _render_footer() -> None:
    pw_configured = bool(get_demo_password())
    pw_note = "" if pw_configured else " · password gate not configured"
    st.markdown(
        f'<div class="app-footer">'
        f'Pega instance: <code>{PEGA_BASE_URL}</code> · '
        f'Agent: <code>{PEGA_AGENT_ID}</code>'
        f'{pw_note}'
        f'</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    _inject_global_css()
    inject_protocol_css()

    if not password_gate():
        return

    _ensure_state()
    _render_header()
    _render_body()

    # Chat input at the bottom — outside the columns so it sits across the page
    submitted = render_chat_input()
    if submitted:
        _handle_user_turn(submitted)
        st.rerun()

    _render_footer()


if __name__ == "__main__":
    main()
else:
    # Streamlit imports the module and runs it; the __name__ check above
    # doesn't trigger because Streamlit doesn't set __name__ to "__main__".
    main()
