"""
ui_chat.py — left-side chat rendering for the Streamlit app.

Pure rendering module. Reads from session state, renders Streamlit
components by side effect. Does not own the MCP agent or the protocol
log — those live in app.py.

The chat history is a list of (role, content) tuples in
st.session_state.chat_history. Roles are "user" or "assistant".
"""

import streamlit as st


def render_chat_history() -> None:
    """
    Render every message in the conversation history.

    Called on each Streamlit rerun. The most recent assistant message
    will appear at the bottom; the input box sits below this rendering.
    """
    history = st.session_state.get("chat_history", [])

    if not history:
        # Empty-state hint — shown only before the first message.
        st.markdown(
            """
            <div style="
                padding: 24px 0;
                color: #6b7280;
                font-style: italic;
                font-size: 0.95rem;
                line-height: 1.6;
            ">
            Ask the Pega Municipal Court Case Management Agent
            anything. The agent can open new cases, schedule
            hearings, and process pleas and resolutions. Case lookup
            by ticket number is not yet wired — try
            <em>"I got a ticket, what can you help me with?"</em>
            to see the agent describe its capabilities.
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    for role, content in history:
        with st.chat_message(role):
            st.markdown(content)


def render_chat_input(placeholder: str = "Ask about a municipal court case...") -> str | None:
    """
    Render the chat input box at the bottom of the page.

    Returns the user's typed message, or None if they haven't submitted
    anything on this rerun.
    """
    return st.chat_input(placeholder)


def append_user_message(content: str) -> None:
    """Append a user message to the chat history."""
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    st.session_state.chat_history.append(("user", content))


def append_assistant_message(content: str) -> None:
    """Append an assistant (agent) message to the chat history."""
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    st.session_state.chat_history.append(("assistant", content))


def clear_chat_history() -> None:
    """Clear the entire chat history."""
    st.session_state.chat_history = []
