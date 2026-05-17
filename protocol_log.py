"""
protocol_log.py — in-memory log of MCP-style tool calls.

Used by the Streamlit app to render the right-side protocol panel.
Each entry describes one MCP tool invocation — including the inputs
the MCP layer received, the HTTP call made to Pega underneath, the
response, latency, and any Pega-internal routing detected.

This module is intentionally Streamlit-free. The Streamlit app
will hold a ProtocolLog in st.session_state and pass it into the
UI rendering layer.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Detected operations — best-effort interpretation of what Pega did internally
# ---------------------------------------------------------------------------

@dataclass
class DetectedOperation:
    """
    A best-effort interpretation of a Pega-internal operation, parsed
    from the agent's response text. May be wrong; never authoritative.
    Used purely to enrich the right-panel display.
    """
    kind: str          # e.g. "case_created", "refused_lookup", "validation_failed",
                       #      "slot_fill_request", "confirmation_request"
    detail: str        # human-readable detail for display
    case_reference: Optional[str] = None   # M-#### or C-#### if applicable
    case_type: Optional[str] = None        # "Case Intake", "Hearing Scheduling", etc.


# ---------------------------------------------------------------------------
# A single MCP tool call record
# ---------------------------------------------------------------------------

@dataclass
class ProtocolEntry:
    """
    One entry in the protocol log, corresponding to one MCP tool invocation.

    Each entry captures the full story of what happened on one user turn:
    MCP-level inputs, HTTP-level transport, response, and detected
    Pega-internal operations.
    """
    # When this turn happened (display only)
    timestamp: str

    # MCP-level
    mcp_tool_name: str
    mcp_tool_inputs: dict

    # HTTP-level transport to Pega
    http_method: str
    http_url: str
    http_request_body: Optional[dict]
    http_response_status: int
    http_response_body: Any
    latency_seconds: float
    transport_error: Optional[str] = None

    # Pega agent response (parsed from http_response_body when available)
    agent_response_text: Optional[str] = None
    pega_message_id: Optional[str] = None
    pega_conversation_id: Optional[str] = None

    # Best-effort interpretation of what Pega did internally on this turn
    detected_operations: list[DetectedOperation] = field(default_factory=list)

    def to_dict(self) -> dict:
        """For debugging / export. Streamlit doesn't need this but it's useful."""
        d = asdict(self)
        d["detected_operations"] = [asdict(op) for op in self.detected_operations]
        return d


# ---------------------------------------------------------------------------
# The log
# ---------------------------------------------------------------------------

class ProtocolLog:
    """
    A simple ordered list of ProtocolEntry. Lives in Streamlit session state
    and gets rendered into the right-panel UI on each rerun.

    Provides a small API rather than just exposing the list, so the UI
    layer doesn't need to know the internal structure.
    """

    def __init__(self):
        self._entries: list[ProtocolEntry] = []

    def append(self, entry: ProtocolEntry) -> None:
        self._entries.append(entry)

    def all(self) -> list[ProtocolEntry]:
        return list(self._entries)

    def latest(self) -> Optional[ProtocolEntry]:
        return self._entries[-1] if self._entries else None

    def clear(self) -> None:
        self._entries.clear()

    def turn_count(self) -> int:
        return len(self._entries)


# ---------------------------------------------------------------------------
# Factory helper — builds a ProtocolEntry from a Pega CallRecord + response
# ---------------------------------------------------------------------------

def make_entry(
    mcp_tool_name: str,
    mcp_tool_inputs: dict,
    call_record,  # pega_client.CallRecord — avoid circular import in typing
    agent_response_text: Optional[str] = None,
    pega_message_id: Optional[str] = None,
    pega_conversation_id: Optional[str] = None,
    detected_operations: Optional[list[DetectedOperation]] = None,
) -> ProtocolEntry:
    """
    Build a ProtocolEntry from a Pega CallRecord plus parsed response data.
    Centralizing this means the wrapper layer doesn't have to know the
    field layout of ProtocolEntry.
    """
    return ProtocolEntry(
        timestamp=datetime.now().strftime("%H:%M:%S"),
        mcp_tool_name=mcp_tool_name,
        mcp_tool_inputs=mcp_tool_inputs,
        http_method=call_record.method,
        http_url=call_record.url,
        http_request_body=call_record.request_body,
        http_response_status=call_record.response_status,
        http_response_body=call_record.response_body,
        latency_seconds=call_record.latency_seconds,
        transport_error=call_record.error,
        agent_response_text=agent_response_text,
        pega_message_id=pega_message_id,
        pega_conversation_id=pega_conversation_id,
        detected_operations=detected_operations or [],
    )
