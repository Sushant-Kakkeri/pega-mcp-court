"""
test_pega_client.py — smoke test for the Pega API client.

Run this from a terminal BEFORE wiring up Streamlit, to verify:
  1. OAuth works against your Pega instance
  2. A new conversation can be created
  3. A message can be sent and a response received

Set credentials via environment variables before running:

  Windows PowerShell:
    $env:PEGA_CLIENT_ID = "<your-client-id>"
    $env:PEGA_CLIENT_SECRET = "<your-client-secret>"
    python test_pega_client.py

  Bash:
    export PEGA_CLIENT_ID="<your-client-id>"
    export PEGA_CLIENT_SECRET="<your-client-secret>"
    python test_pega_client.py

DO NOT paste credentials into this file. They belong in environment
variables locally, and in Streamlit's secrets.toml when deployed.
"""

import sys
import time

from pega_client import PegaClient


def main():
    print("=" * 70)
    print("Pega AgentX smoke test")
    print("=" * 70)

    client = PegaClient()

    # ----- Step 1: OAuth -----
    print("\n[1/3] Performing OAuth client_credentials grant...")
    start = time.time()
    try:
        client._ensure_token()  # type: ignore[attr-defined]
    except Exception as e:
        print(f"  FAILED: {e}")
        sys.exit(1)
    elapsed = time.time() - start
    remaining = client.token_seconds_remaining()
    print(f"  OK ({elapsed:.2f}s). Token valid for ~{remaining:.0f}s.")

    # ----- Step 2: Create conversation -----
    print("\n[2/3] Creating a new conversation with the Pega agent...")
    start = time.time()
    try:
        conv_id, _ = client.create_conversation()
    except Exception as e:
        print(f"  FAILED: {e}")
        sys.exit(1)
    elapsed = time.time() - start
    print(f"  OK ({elapsed:.2f}s). Conversation ID: {conv_id}")

    # ----- Step 3: Send a test message -----
    test_message = "I got a ticket, what can you help me with?"
    print(f"\n[3/3] Sending test message:")
    print(f"  > {test_message}")
    start = time.time()
    try:
        result = client.send_message(conv_id, test_message)
    except Exception as e:
        print(f"  FAILED: {e}")
        sys.exit(1)
    elapsed = time.time() - start
    print(f"  OK ({elapsed:.2f}s). Response:")
    print("  " + "-" * 66)
    for line in result.response_text.splitlines():
        print(f"  | {line}")
    print("  " + "-" * 66)
    if result.routed_case_type:
        print(f"  Detected routing: {result.routed_case_type}")
    if result.message_id:
        print(f"  Message ID: {result.message_id}")

    print("\n" + "=" * 70)
    print("All checks passed. Pega connectivity is working end-to-end.")
    print("=" * 70)


if __name__ == "__main__":
    main()
