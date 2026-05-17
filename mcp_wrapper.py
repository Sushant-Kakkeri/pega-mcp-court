"""
mcp_wrapper.py — MCP-style framing layer over the Pega client.

Exposes a single conceptual MCP tool — `pega_court_agent` — that
sends a natural-language message to the Pega Municipal Court Case
Management Agent. The Pega agent internally routes to one of four
case-type tools (Municipal Case, Case Intake, Hearing Scheduling,
Case Resolution); we surface that internal routing in the protocol
log as best-effort detected operations.

This is the layer the Streamlit app calls. It encapsulates:
  - Conversation lifecycle (start one on first call, reuse afterwards)
  - Pega request/response handling via PegaClient
  - Best-effort interpretation of what Pega did internally
  - Construction of ProtocolEntry records for the right-panel display

The "MCP" framing here is presentational. We are not running a
strict MCP server with stdio transport — we are wrapping Pega's
AgentX API in MCP-style tool semantics (named tool, input schema,
structured output, captured call metadata). The audience sees the
shape of an MCP integration; the implementation is direct HTTP.
"""

import re
from dataclasses import dataclass
from typing import Optional

from pega_client import PegaClient, AgentResponse
from protocol_log import (
    ProtocolEntry,
    DetectedOperation,
    make_entry,
)


# ---------------------------------------------------------------------------
# MCP tool definition — for display in the protocol panel
# ---------------------------------------------------------------------------

MCP_TOOL_NAME = "pega_court_agent"

MCP_TOOL_SCHEMA = {
    "name": MCP_TOOL_NAME,
    "description": (
        "Send a natural-language message to the Pega Municipal Court "
        "Case Management Agent. The Pega agent internally routes to "
        "its registered case-type tools (Municipal Case, Case Intake, "
        "Hearing Scheduling, Case Resolution) and performs platform "
        "operations such as creating cases, scheduling hearings, and "
        "recording dispositions."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "conversation_id": {
                "type": "string",
                "description": (
                    "Existing Pega conversation ID. Omit to start a new "
                    "conversation."
                ),
            },
            "message": {
                "type": "string",
                "description": "Natural-language message to the agent.",
            },
        },
        "required": ["message"],
    },
}


# ---------------------------------------------------------------------------
# Internal-routing detection — best-effort parsing of the agent's response
# ---------------------------------------------------------------------------

# Regex patterns for detecting Pega-internal operations in response text.
# These are best-effort heuristics, not authoritative. False positives are
# acceptable; false negatives just mean the panel shows less detail.

# Match Pega work object IDs like M-2001, C-1, MUNICIPALCASE-2001
_CASE_REF_PATTERN = re.compile(r"\b([A-Z]{1,15}-\d{1,8})\b")

# Match the agent's own case-type self-report
_CASE_TYPE_PATTERN = re.compile(
    r"Case Type:\s*(Municipal Case|Case Intake|Hearing Scheduling|Case Resolution)",
    re.IGNORECASE,
)

# Match lookup-refusal language. We want to detect an *active refusal*
# of a lookup request, not a *mention* of lookup limitations in a
# general capability self-report. The two responses share vocabulary but
# differ in shape: a refusal directly addresses the user's request
# ("I cannot retrieve..."), while a self-report describes the system in
# the abstract ("This system cannot look up...").
#
# Heuristic: require both (a) a refusal-shape verb phrase AND
# (b) the absence of capability-self-report framing.
_REFUSED_LOOKUP_DIRECT_MARKERS = [
    "i cannot retrieve",
    "i am not able to retrieve",
    "i cannot look up",
    "i am not able to look up",
    "i cannot display",
    "case lookup is not a capability available",
    "regardless of the identifier provided",
    "regardless of how the request is phrased",
]

# Phrases that indicate a capability self-report rather than a refusal.
# If any of these appear, suppress the refused_lookup detection.
_CAPABILITY_SELF_REPORT_MARKERS = [
    "what i can help with",
    "what this system can",
    "here is what this system",
    "current limitations you should be aware of",
    "what i cannot help with",
]

# Match Pega platform validation failures
_VALIDATION_FAILED_MARKERS = [
    "does not exist in the system",
    "system returned an error",
    "operator record",
    "not a valid",
]

# Match the agent's pre-submit confirmation pattern
_CONFIRMATION_MARKERS = [
    "do you confirm",
    "shall i proceed",
    "before proceeding",
    "before submitting",
    "can you confirm",
]

# Match the agent asking for more fields (slot-fill)
_SLOT_FILL_MARKERS = [
    "please provide the following",
    "i need a few additional details",
    "i need the following",
    "please share as many of these details",
    "to complete",
]


def detect_operations(response_text: str) -> list[DetectedOperation]:
    """
    Best-effort interpretation of what Pega did internally on this turn.
    Returns a list of DetectedOperation objects for display in the
    protocol panel.
    """
    if not response_text:
        return []

    ops: list[DetectedOperation] = []
    lowered = response_text.lower()

    # Detect case-type routing (agent's own self-report)
    case_type = None
    m = _CASE_TYPE_PATTERN.search(response_text)
    if m:
        case_type = m.group(1).strip()

    # Detect case references (work object IDs)
    case_refs = list(set(_CASE_REF_PATTERN.findall(response_text)))
    # Filter out anything that looks like an N.J.S.A. reference or similar
    # by requiring at least one match looks like a Pega work object pattern
    # (e.g., short prefix + numeric sequence)
    pega_refs = [r for r in case_refs if _looks_like_pega_workobj(r)]

    # Detect capability self-report (no operation, but worth surfacing)
    is_capability_report = any(
        marker in lowered for marker in _CAPABILITY_SELF_REPORT_MARKERS
    )

    # Detect refused lookup — only if shape is a direct refusal, not a
    # capability self-report that happens to mention lookup limitations.
    is_refusal = (
        any(marker in lowered for marker in _REFUSED_LOOKUP_DIRECT_MARKERS)
        and not is_capability_report
    )

    if is_refusal:
        ops.append(DetectedOperation(
            kind="refused_lookup",
            detail="Agent honestly refused a lookup request (guardrail fired).",
        ))

    if is_capability_report and not is_refusal:
        ops.append(DetectedOperation(
            kind="capability_self_report",
            detail=(
                "Agent described its available capabilities and current "
                "limitations to the user."
            ),
        ))

    if any(marker in lowered for marker in _VALIDATION_FAILED_MARKERS):
        ops.append(DetectedOperation(
            kind="validation_failed",
            detail=(
                "Pega platform rejected the action. The agent surfaced "
                "the rejection rather than fabricating success."
            ),
            case_type=case_type,
        ))

    # Case creation / case reference returned
    if pega_refs and (
        "has been created" in lowered
        or "has been initiated" in lowered
        or "successfully created" in lowered
    ):
        for ref in pega_refs:
            ops.append(DetectedOperation(
                kind="case_created",
                detail=f"Pega created work object {ref}.",
                case_reference=ref,
                case_type=case_type,
            ))

    if any(marker in lowered for marker in _CONFIRMATION_MARKERS):
        ops.append(DetectedOperation(
            kind="confirmation_request",
            detail="Agent is requesting user confirmation before proceeding.",
            case_type=case_type,
        ))

    if any(marker in lowered for marker in _SLOT_FILL_MARKERS) and not ops:
        # Only mark slot-fill if nothing more specific was detected
        ops.append(DetectedOperation(
            kind="slot_fill_request",
            detail="Agent is collecting additional fields from the user.",
            case_type=case_type,
        ))

    # If we detected routing but nothing else, surface it on its own
    if case_type and not ops:
        ops.append(DetectedOperation(
            kind="routed",
            detail=f"Pega agent routed to case type: {case_type}",
            case_type=case_type,
        ))

    return ops


def _looks_like_pega_workobj(ref: str) -> bool:
    """
    Heuristic: a Pega work object ID is a short alpha prefix followed
    by a hyphen and a numeric sequence. N.J.S.A. statute references
    have colons and are not single hyphenated tokens; we filter those
    out at the regex level already.
    """
    if "-" not in ref:
        return False
    prefix, _, suffix = ref.partition("-")
    return (
        1 <= len(prefix) <= 15
        and prefix.isalpha()
        and suffix.isdigit()
    )


# ---------------------------------------------------------------------------
# The wrapper
# ---------------------------------------------------------------------------

@dataclass
class WrappedResponse:
    """
    The result of invoking the MCP tool. Carries everything the
    Streamlit UI needs to render both the chat turn and the protocol
    panel entry.
    """
    response_text: str
    conversation_id: str
    protocol_entry: ProtocolEntry


class MCPCourtAgent:
    """
    Single conceptual MCP tool wrapping the Pega court agent.

    Holds:
      - A PegaClient (for auth and transport)
      - The current conversation_id (created lazily on first invoke)

    Designed so the Streamlit app can construct one of these,
    store it in session state, and call .invoke() per user message.
    """

    def __init__(self, pega_client: Optional[PegaClient] = None):
        self.client = pega_client or PegaClient()
        self.conversation_id: Optional[str] = None

    def ensure_conversation(self) -> tuple[str, Optional[ProtocolEntry]]:
        """
        Make sure we have an active Pega conversation. Returns
        (conversation_id, optional_protocol_entry_for_creation).
        The entry is included so the protocol panel can show the
        conversation-creation call too, on the first turn only.
        """
        if self.conversation_id is not None:
            return self.conversation_id, None

        conv_id, call_record = self.client.create_conversation()
        self.conversation_id = conv_id

        entry = make_entry(
            mcp_tool_name=MCP_TOOL_NAME,
            mcp_tool_inputs={"operation": "create_conversation"},
            call_record=call_record,
            pega_conversation_id=conv_id,
            detected_operations=[
                DetectedOperation(
                    kind="conversation_created",
                    detail=f"New Pega conversation initiated: {conv_id}",
                ),
            ],
        )
        return conv_id, entry

    def invoke(self, message: str) -> tuple[WrappedResponse, Optional[ProtocolEntry]]:
        """
        Send a message via the MCP tool wrapper.

        Returns (WrappedResponse, optional_extra_entry).
        The extra entry, if present, is the conversation-creation entry
        from the first turn — the caller should append it to the
        protocol log first, then the WrappedResponse's protocol_entry.
        """
        conv_id, create_entry = self.ensure_conversation()

        agent_response: AgentResponse = self.client.send_message(conv_id, message)

        detected = detect_operations(agent_response.response_text)

        entry = make_entry(
            mcp_tool_name=MCP_TOOL_NAME,
            mcp_tool_inputs={
                "conversation_id": conv_id,
                "message": message,
            },
            call_record=agent_response.call_record,
            agent_response_text=agent_response.response_text,
            pega_message_id=agent_response.message_id,
            pega_conversation_id=conv_id,
            detected_operations=detected,
        )

        return (
            WrappedResponse(
                response_text=agent_response.response_text,
                conversation_id=conv_id,
                protocol_entry=entry,
            ),
            create_entry,
        )

    def reset_conversation(self) -> None:
        """Drop the current conversation. The next invoke() starts a new one."""
        self.conversation_id = None
