"""
ui_protocol.py — right-side protocol panel rendering.

Renders ProtocolEntry records from the ProtocolLog into a scrollable
panel. Each entry becomes a card showing:

  - Tool name and timestamp
  - HTTP method, status, and latency
  - Detected Pega-internal operations as colored badges
  - The MCP-level inputs
  - An expandable section with the raw HTTP request/response

The most recent entry's expandable section is opened by default;
earlier entries collapse to save vertical space.

Some focused CSS is injected for badge styling and card spacing —
restrained, not decorative.
"""

import json
import streamlit as st

from protocol_log import ProtocolLog, ProtocolEntry, DetectedOperation


# ---------------------------------------------------------------------------
# Badge styling — one color per operation kind. Restrained palette,
# muted backgrounds, clear semantic meaning.
# ---------------------------------------------------------------------------

_OPERATION_STYLES = {
    "conversation_created":  {"bg": "#eef2ff", "fg": "#3730a3", "label": "Conversation opened"},
    "capability_self_report":{"bg": "#f0fdf4", "fg": "#166534", "label": "Capability self-report"},
    "refused_lookup":        {"bg": "#fef3c7", "fg": "#92400e", "label": "Lookup refused (guardrail)"},
    "validation_failed":     {"bg": "#fee2e2", "fg": "#991b1b", "label": "Platform validation failed"},
    "confirmation_request":  {"bg": "#e0e7ff", "fg": "#3730a3", "label": "Confirmation requested"},
    "slot_fill_request":     {"bg": "#e0f2fe", "fg": "#075985", "label": "Slot-fill in progress"},
    "case_created":          {"bg": "#dcfce7", "fg": "#14532d", "label": "Case created"},
    "routed":                {"bg": "#f3e8ff", "fg": "#6b21a8", "label": "Routed"},
}

_DEFAULT_STYLE = {"bg": "#f3f4f6", "fg": "#374151", "label": "Operation"}


def inject_protocol_css() -> None:
    """
    Inject focused CSS for the protocol panel.
    Called once from app.py before rendering the panel.
    """
    st.markdown(
        """
        <style>
        .protocol-card {
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 6px;
            padding: 12px 14px;
            margin-bottom: 10px;
            font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
            font-size: 0.78rem;
            line-height: 1.5;
        }
        .protocol-card-header {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            font-weight: 600;
            color: #111827;
            margin-bottom: 6px;
        }
        .protocol-timestamp {
            color: #6b7280;
            font-weight: 400;
            font-size: 0.72rem;
        }
        .protocol-field {
            margin: 4px 0;
            color: #374151;
        }
        .protocol-field-label {
            color: #6b7280;
            display: inline-block;
            min-width: 72px;
        }
        .protocol-badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.7rem;
            font-weight: 600;
            margin-right: 6px;
            margin-top: 4px;
            font-family: ui-sans-serif, system-ui, sans-serif;
            letter-spacing: 0.01em;
        }
        .protocol-status-ok { color: #166534; font-weight: 600; }
        .protocol-status-bad { color: #991b1b; font-weight: 600; }
        .protocol-section-header {
            color: #111827;
            font-weight: 600;
            margin-top: 8px;
            margin-bottom: 2px;
        }
        .protocol-empty {
            color: #9ca3af;
            font-style: italic;
            padding: 24px 0;
            text-align: center;
            font-size: 0.85rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_protocol_panel(log: ProtocolLog) -> None:
    """
    Render the entire protocol log as a scrolling panel of cards.
    Most recent entry first.
    """
    entries = log.all()

    if not entries:
        st.markdown(
            '<div class="protocol-empty">'
            'MCP tool calls will appear here as you interact '
            'with the agent.</div>',
            unsafe_allow_html=True,
        )
        return

    # Most recent first
    reversed_entries = list(reversed(entries))
    latest_idx = 0  # in the reversed list

    for idx, entry in enumerate(reversed_entries):
        _render_entry_card(entry, is_latest=(idx == latest_idx))


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _render_entry_card(entry: ProtocolEntry, is_latest: bool) -> None:
    """Render a single ProtocolEntry as an inline HTML card + expander."""

    status_class = (
        "protocol-status-ok"
        if 200 <= entry.http_response_status < 300
        else "protocol-status-bad"
    )
    status_display = (
        str(entry.http_response_status) if entry.http_response_status else "—"
    )

    # Compact, structured top of the card — rendered as HTML for layout.
    badge_html = ""
    if entry.detected_operations:
        for op in entry.detected_operations:
            style = _OPERATION_STYLES.get(op.kind, _DEFAULT_STYLE)
            badge_html += (
                f'<span class="protocol-badge" '
                f'style="background:{style["bg"]};color:{style["fg"]};">'
                f'{style["label"]}'
                f'</span>'
            )

    inputs_html = _format_inputs(entry.mcp_tool_inputs)

    card_html = f"""
    <div class="protocol-card">
        <div class="protocol-card-header">
            <span>MCP: <code>{entry.mcp_tool_name}</code></span>
            <span class="protocol-timestamp">{entry.timestamp}</span>
        </div>
        <div class="protocol-field">
            <span class="protocol-field-label">HTTP:</span>
            {entry.http_method}
            <span class="{status_class}">{status_display}</span>
            &nbsp;&nbsp;<span class="protocol-field-label">latency:</span>
            {entry.latency_seconds:.2f}s
        </div>
        <div class="protocol-field">
            <span class="protocol-field-label">inputs:</span>
            {inputs_html}
        </div>
        {('<div>' + badge_html + '</div>') if badge_html else ''}
    </div>
    """
    st.markdown(card_html, unsafe_allow_html=True)

    # Expandable detail — operation details + raw HTTP request/response.
    with st.expander("Show transport detail", expanded=is_latest):
        _render_operation_details(entry.detected_operations)
        _render_http_detail(entry)


def _format_inputs(inputs: dict) -> str:
    """Format the MCP tool inputs compactly for the card header."""
    if not inputs:
        return "<em>(none)</em>"
    parts = []
    for k, v in inputs.items():
        if isinstance(v, str) and len(v) > 80:
            v = v[:77] + "..."
        v_str = json.dumps(v) if not isinstance(v, str) else v
        parts.append(f"<code>{k}</code>=<code>{_escape_html(str(v_str))}</code>")
    return ", ".join(parts)


def _render_operation_details(operations: list[DetectedOperation]) -> None:
    """Render the detected operations with their detail strings."""
    if not operations:
        return
    st.markdown(
        '<div class="protocol-section-header">Detected operations</div>',
        unsafe_allow_html=True,
    )
    for op in operations:
        extras = []
        if op.case_reference:
            extras.append(f"case_ref=`{op.case_reference}`")
        if op.case_type:
            extras.append(f"case_type=`{op.case_type}`")
        extras_str = " · " + " · ".join(extras) if extras else ""
        st.markdown(f"- **{op.kind}** — {op.detail}{extras_str}")


def _render_http_detail(entry: ProtocolEntry) -> None:
    """Render the raw HTTP request and response for the curious viewer."""
    st.markdown(
        '<div class="protocol-section-header">HTTP request</div>',
        unsafe_allow_html=True,
    )
    st.code(
        f"{entry.http_method} {entry.http_url}\n\n"
        + json.dumps(entry.http_request_body, indent=2)
        if entry.http_request_body else
        f"{entry.http_method} {entry.http_url}",
        language="http",
    )

    if entry.transport_error:
        st.markdown(
            '<div class="protocol-section-header">Transport error</div>',
            unsafe_allow_html=True,
        )
        st.code(entry.transport_error)
        return

    st.markdown(
        '<div class="protocol-section-header">HTTP response</div>',
        unsafe_allow_html=True,
    )
    if isinstance(entry.http_response_body, (dict, list)):
        st.code(json.dumps(entry.http_response_body, indent=2), language="json")
    else:
        st.code(str(entry.http_response_body))


def _escape_html(s: str) -> str:
    """Minimal HTML escaping for code snippets we put into inline HTML."""
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )
