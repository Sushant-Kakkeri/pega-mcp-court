"""
pega_client.py — Pega AgentX API client.

Handles:
  - OAuth client_credentials grant against Pega
  - Token caching and pre-emptive refresh
  - Creating new conversations with the configured AI agent
  - Sending messages and receiving structured responses
  - Capturing call metadata (URLs, payloads, timings) for the protocol panel

Designed to be testable without Streamlit. The client holds its own
token state in-memory; the Streamlit app stores a PegaClient instance
in st.session_state and reuses it across reruns.
"""

import time
from dataclasses import dataclass, field
from typing import Optional, Any
import requests

from config import (
    PEGA_OAUTH_TOKEN_URL,
    PEGA_CREATE_CONVERSATION_URL,
    pega_send_message_url,
    TOKEN_REFRESH_MARGIN_SECONDS,
    PEGA_REQUEST_TIMEOUT_SECONDS,
    PEGA_AGENT_ID,
    get_pega_client_id,
    get_pega_client_secret,
)


# ---------------------------------------------------------------------------
# Data classes — structured returns so callers can render protocol details
# ---------------------------------------------------------------------------

@dataclass
class CallRecord:
    """Captures one HTTP call to Pega, for display in the protocol panel."""
    method: str
    url: str
    request_body: Optional[dict]
    response_status: int
    response_body: Any
    latency_seconds: float
    error: Optional[str] = None


@dataclass
class AgentResponse:
    """The structured result of sending a message to the Pega agent."""
    conversation_id: str
    response_text: str
    message_id: Optional[str]
    raw_response: dict
    call_record: CallRecord
    # Routing info parsed from the response, if present
    routed_case_type: Optional[str] = None


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------

@dataclass
class _CachedToken:
    access_token: str
    expires_at_epoch: float  # absolute unix timestamp

    def needs_refresh(self) -> bool:
        return time.time() >= (self.expires_at_epoch - TOKEN_REFRESH_MARGIN_SECONDS)


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------

class PegaClient:
    """
    A small, stateful Pega API client.

    Keeps a cached OAuth token. Reuses it across calls. Refreshes
    pre-emptively when nearing expiration.
    """

    def __init__(self):
        self._token: Optional[_CachedToken] = None
        # Accumulated call records — primarily useful for the auth flow
        # since message sends return their own record directly.
        self._auth_call_records: list[CallRecord] = []

    # -----------------------------------------------------------------
    # OAuth
    # -----------------------------------------------------------------

    def _fetch_new_token(self) -> _CachedToken:
        """Perform OAuth client_credentials grant against Pega."""
        client_id = get_pega_client_id()
        client_secret = get_pega_client_secret()

        start = time.time()
        try:
            resp = requests.post(
                PEGA_OAUTH_TOKEN_URL,
                data={"grant_type": "client_credentials"},
                auth=(client_id, client_secret),
                timeout=30,
            )
            latency = time.time() - start

            record = CallRecord(
                method="POST",
                url=PEGA_OAUTH_TOKEN_URL,
                request_body={"grant_type": "client_credentials"},
                response_status=resp.status_code,
                response_body=self._safe_json(resp),
                latency_seconds=latency,
            )
            self._auth_call_records.append(record)

            if resp.status_code != 200:
                raise RuntimeError(
                    f"Pega OAuth failed: status {resp.status_code}, "
                    f"body: {resp.text[:500]}"
                )

            data = resp.json()
            access_token = data["access_token"]
            # Pega returns expires_in in seconds
            expires_in = int(data.get("expires_in", 3600))
            expires_at = time.time() + expires_in

            return _CachedToken(
                access_token=access_token,
                expires_at_epoch=expires_at,
            )
        except requests.RequestException as e:
            latency = time.time() - start
            self._auth_call_records.append(CallRecord(
                method="POST",
                url=PEGA_OAUTH_TOKEN_URL,
                request_body={"grant_type": "client_credentials"},
                response_status=0,
                response_body=None,
                latency_seconds=latency,
                error=str(e),
            ))
            raise RuntimeError(f"Pega OAuth request failed: {e}") from e

    def _ensure_token(self) -> str:
        """Return a valid access token, refreshing if needed."""
        if self._token is None or self._token.needs_refresh():
            self._token = self._fetch_new_token()
        return self._token.access_token

    # -----------------------------------------------------------------
    # Conversation management
    # -----------------------------------------------------------------

    def create_conversation(self) -> tuple[str, CallRecord]:
        """
        Start a new conversation with the Pega agent.

        Returns (conversation_id, call_record).
        """
        token = self._ensure_token()
        url = PEGA_CREATE_CONVERSATION_URL

        start = time.time()
        try:
            resp = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={},
                timeout=PEGA_REQUEST_TIMEOUT_SECONDS,
            )
            latency = time.time() - start
        except requests.RequestException as e:
            latency = time.time() - start
            raise RuntimeError(f"Pega create_conversation failed: {e}") from e

        record = CallRecord(
            method="POST",
            url=url,
            request_body={},
            response_status=resp.status_code,
            response_body=self._safe_json(resp),
            latency_seconds=latency,
        )

        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Pega create_conversation returned {resp.status_code}: "
                f"{resp.text[:500]}"
            )

        body = resp.json()
        # The exact key varies between Pega versions. Try the common ones.
        conversation_id = (
            body.get("ID")
            or body.get("conversationID")
            or body.get("conversation_id")
        )
        if not conversation_id:
            raise RuntimeError(
                f"Pega create_conversation returned no conversation ID. "
                f"Response keys: {list(body.keys())}"
            )

        return conversation_id, record

    def send_message(
        self,
        conversation_id: str,
        message: str,
    ) -> AgentResponse:
        """
        Send a user message to an existing Pega conversation.

        Returns AgentResponse with structured data.
        """
        token = self._ensure_token()
        url = pega_send_message_url(conversation_id)
        body = {"request": message}

        start = time.time()
        try:
            resp = requests.patch(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=PEGA_REQUEST_TIMEOUT_SECONDS,
            )
            latency = time.time() - start
        except requests.RequestException as e:
            latency = time.time() - start
            raise RuntimeError(f"Pega send_message failed: {e}") from e

        record = CallRecord(
            method="PATCH",
            url=url,
            request_body=body,
            response_status=resp.status_code,
            response_body=self._safe_json(resp),
            latency_seconds=latency,
        )

        if resp.status_code != 200:
            raise RuntimeError(
                f"Pega send_message returned {resp.status_code}: "
                f"{resp.text[:500]}"
            )

        data = resp.json()
        response_text = data.get("response", "")
        message_id = data.get("messageID")

        # Best-effort routing detection — surface this in the protocol panel
        routed_case_type = self._detect_routing(response_text)

        return AgentResponse(
            conversation_id=conversation_id,
            response_text=response_text,
            message_id=message_id,
            raw_response=data,
            call_record=record,
            routed_case_type=routed_case_type,
        )

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    @staticmethod
    def _safe_json(resp: requests.Response) -> Any:
        """Try to parse JSON, fall back to text snippet."""
        try:
            return resp.json()
        except Exception:
            return {"_raw_text": resp.text[:1000]}

    @staticmethod
    def _detect_routing(response_text: str) -> Optional[str]:
        """
        Best-effort: look for the agent's own mention of which case type
        it routed to. The agent's responses commonly contain phrases
        like "Case Type: Case Intake" after a creation flow.
        """
        if not response_text:
            return None
        # Order matters — more specific matches first
        markers = [
            ("Case Type: Case Intake", "Case Intake"),
            ("Case Type: Hearing Scheduling", "Hearing Scheduling"),
            ("Case Type: Case Resolution", "Case Resolution"),
            ("Case Type: Municipal Case", "Municipal Case"),
        ]
        for marker, label in markers:
            if marker in response_text:
                return label
        return None

    # -----------------------------------------------------------------
    # Introspection — useful for debugging and the status indicator
    # -----------------------------------------------------------------

    def is_authenticated(self) -> bool:
        """Returns True if we currently hold a non-expired token."""
        return self._token is not None and not self._token.needs_refresh()

    def token_seconds_remaining(self) -> Optional[float]:
        """Returns seconds until the current token expires, or None."""
        if self._token is None:
            return None
        return max(0.0, self._token.expires_at_epoch - time.time())
