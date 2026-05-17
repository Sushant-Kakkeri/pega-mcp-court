"""
config.py — central configuration for the Pega MCP Court Assistant.

Reads credentials and endpoint config from either:
  - Streamlit secrets (when deployed on Streamlit Cloud), or
  - Environment variables (when running locally for testing).

This dual-mode reading lets the same code work in both environments
without changes.
"""

import os
from typing import Optional

# ---------------------------------------------------------------------------
# Static configuration — constants that don't change between environments
# ---------------------------------------------------------------------------

PEGA_BASE_URL = "https://oystohjs.pegace.net"
PEGA_AGENT_ID = "MYORG-MUNICIPAL-UIPAGES!MUNICIPALAGENT"

# OAuth token endpoint pattern for Pega Personal Edition
PEGA_OAUTH_TOKEN_URL = f"{PEGA_BASE_URL}/prweb/PRRestService/oauth2/v1/token"

# AgentX API endpoints
PEGA_CREATE_CONVERSATION_URL = (
    f"{PEGA_BASE_URL}/prweb/api/application/v2/ai-agents/{PEGA_AGENT_ID}/conversations"
)
def pega_send_message_url(conversation_id: str) -> str:
    return (
        f"{PEGA_BASE_URL}/prweb/api/application/v2/ai-agents/"
        f"{PEGA_AGENT_ID}/conversations/{conversation_id}"
    )

# Token refresh margin — refresh proactively when fewer than this many
# seconds remain on the current token. Pega tokens default to 3600s validity.
TOKEN_REFRESH_MARGIN_SECONDS = 600  # 10 minutes

# HTTP request timeout for Pega calls (seconds). Pega's AI agent can be slow
# when invoking case actions; give it generous headroom.
PEGA_REQUEST_TIMEOUT_SECONDS = 60


# ---------------------------------------------------------------------------
# Dynamic configuration — credentials read at runtime
# ---------------------------------------------------------------------------

def _read_secret(streamlit_path: tuple, env_var: str) -> Optional[str]:
    """
    Read a credential from Streamlit secrets if available, falling back
    to an environment variable.

    streamlit_path: tuple like ("pega", "client_id") meaning
                    st.secrets["pega"]["client_id"]
    env_var: environment variable name like "PEGA_CLIENT_ID"
    """
    # Try Streamlit secrets first (when running inside Streamlit)
    try:
        import streamlit as st
        node = st.secrets
        for key in streamlit_path:
            node = node[key]
        return node
    except Exception:
        pass

    # Fall back to environment variable (for local non-Streamlit testing)
    return os.environ.get(env_var)


def get_pega_client_id() -> str:
    value = _read_secret(("pega", "client_id"), "PEGA_CLIENT_ID")
    if not value:
        raise RuntimeError(
            "Pega client_id not configured. Set either "
            "st.secrets['pega']['client_id'] or the PEGA_CLIENT_ID "
            "environment variable."
        )
    return value


def get_pega_client_secret() -> str:
    value = _read_secret(("pega", "client_secret"), "PEGA_CLIENT_SECRET")
    if not value:
        raise RuntimeError(
            "Pega client_secret not configured. Set either "
            "st.secrets['pega']['client_secret'] or the PEGA_CLIENT_SECRET "
            "environment variable."
        )
    return value


def get_demo_password() -> Optional[str]:
    """
    Optional demo password gate. Returns None if not configured, in which
    case the password gate is disabled. The app should still recommend
    enabling it.
    """
    return _read_secret(("app", "demo_password"), "DEMO_PASSWORD")
