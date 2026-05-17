# Pega MCP Court Assistant — Streamlit App

A Streamlit demo app that exposes the Pega Municipal Court Case
Management Agent as an MCP-compatible interface, with a side panel
visualizing the protocol layer.

## Status

**Step 1 of build (Saturday session):** OAuth + Pega client + smoke
test. Streamlit UI not yet implemented.

## Local setup

1. Create a virtual environment and install dependencies:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1   # PowerShell
   pip install -r requirements.txt
   ```

2. Set Pega OAuth credentials as environment variables:

   ```powershell
   $env:PEGA_CLIENT_ID = "<your-client-id>"
   $env:PEGA_CLIENT_SECRET = "<your-client-secret>"
   ```

   Never commit these to Git. They will be moved to Streamlit's
   `secrets.toml` mechanism when we deploy.

3. Run the smoke test to verify end-to-end connectivity:

   ```powershell
   python test_pega_client.py
   ```

   Expected output: three checks pass (OAuth, conversation creation,
   message send) and the Pega agent's response prints to the terminal.

## What's in this directory

- `config.py` — central configuration; reads credentials from Streamlit
  secrets or environment variables.
- `pega_client.py` — Pega AgentX API client; OAuth handling,
  conversation management, structured responses with call metadata.
- `test_pega_client.py` — standalone smoke test, runs without Streamlit.
- `requirements.txt` — pinned dependency ranges.

## What's coming next

- `mcp_wrapper.py` — MCP-style framing around the Pega client
- `protocol_log.py` — log structure for the right-panel display
- `ui_chat.py` — left-side chat rendering
- `ui_protocol.py` — right-side protocol panel
- `app.py` — Streamlit entry point and page layout
- `.streamlit/secrets.toml` — credentials (gitignored)
- Streamlit Community Cloud deployment
