"""
test_mcp_wrapper.py — second smoke test.

Verifies the MCP wrapper (mcp_wrapper.py) produces well-shaped
ProtocolEntry records when talking to the real Pega agent.

We exercise three different agent response types:
  1. Capability self-report (no Pega-internal operations expected)
  2. Refused lookup (the new guardrail should fire and be detected)
  3. Hearing scheduling attempt (will trigger slot-fill or confirmation)

Run after test_pega_client.py passes. Credentials via the same
PEGA_CLIENT_ID / PEGA_CLIENT_SECRET environment variables.

  python test_mcp_wrapper.py
"""

import sys
import time

from mcp_wrapper import MCPCourtAgent
from protocol_log import ProtocolLog


def print_entry(entry):
    """Pretty-print a ProtocolEntry to the terminal."""
    print(f"  [{entry.timestamp}] {entry.mcp_tool_name}")
    print(f"    inputs: {entry.mcp_tool_inputs}")
    print(f"    HTTP {entry.http_method} -> {entry.http_response_status}")
    print(f"    latency: {entry.latency_seconds:.2f}s")
    if entry.transport_error:
        print(f"    TRANSPORT ERROR: {entry.transport_error}")
    if entry.detected_operations:
        print(f"    detected operations:")
        for op in entry.detected_operations:
            line = f"      - {op.kind}: {op.detail}"
            if op.case_reference:
                line += f"  [case_ref={op.case_reference}]"
            if op.case_type:
                line += f"  [case_type={op.case_type}]"
            print(line)
    else:
        print(f"    detected operations: (none)")


def turn(agent, log, label, message):
    print()
    print(f"--- {label} ---")
    print(f"  > {message}")
    start = time.time()
    try:
        wrapped, create_entry = agent.invoke(message)
    except Exception as e:
        print(f"  FAILED: {e}")
        sys.exit(1)
    elapsed = time.time() - start
    print(f"  (round-trip {elapsed:.2f}s)")

    if create_entry is not None:
        # First turn — capture the conversation-creation record too
        log.append(create_entry)
        print("  Recorded conversation creation:")
        print_entry(create_entry)

    log.append(wrapped.protocol_entry)
    print()
    print("  Response (first 240 chars):")
    snippet = wrapped.response_text.replace("\n", " ")[:240]
    print(f"    | {snippet}{'...' if len(wrapped.response_text) > 240 else ''}")
    print()
    print("  Protocol entry:")
    print_entry(wrapped.protocol_entry)


def main():
    print("=" * 72)
    print("MCP wrapper smoke test")
    print("=" * 72)

    agent = MCPCourtAgent()
    log = ProtocolLog()

    # Turn 1: capability self-report — no Pega-internal ops expected
    turn(
        agent, log,
        "Turn 1 (capability self-report)",
        "I got a ticket, what can you help me with?",
    )

    # Turn 2: refused lookup — guardrail should fire and be detected
    turn(
        agent, log,
        "Turn 2 (refused lookup)",
        "Look up ticket 1214 MUN 001242.",
    )

    # Turn 3: hearing scheduling — should trigger slot-fill or confirmation
    turn(
        agent, log,
        "Turn 3 (hearing scheduling)",
        "Schedule a hearing for ticket 1214 MUN 001242 on June 20 at 2pm with Judge Sarah Chen.",
    )

    print()
    print("=" * 72)
    print(f"Wrapper produced {log.turn_count()} protocol entries across 3 turns.")
    print("=" * 72)
    print()
    print("What to look for in the output above:")
    print("  Turn 1: no detected operations (or just 'routed' if agent self-reported)")
    print("  Turn 2: detected operation kind = 'refused_lookup'")
    print("  Turn 3: detected operation kind = 'confirmation_request' or 'slot_fill_request'")
    print()
    print("If those line up, the wrapper is producing sensible records.")


if __name__ == "__main__":
    main()
