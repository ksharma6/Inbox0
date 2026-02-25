## Inbox0 — AI Email Assistant

An AI assistant that reads your Gmail, summarizes your day’s to‑dos, and drafts responses for human review in Slack. Runs a Flask server with Slack actions and a LangGraph workflow that orchestrates Gmail + OpenAI. At this time, the project only supports calls to OpenAI's API. 

### Quick start

1) Prerequisites
- Python 3.11+
- Google OAuth setup (Gmail)
  - In Google Cloud Console: enable Gmail API
  - Create OAuth client credentials and download `credentials.json`
  - Place `credentials.json` in the directory pointed to by `TOKENS_PATH`
  - First run will perform OAuth and create `token.json` in the same folder
- A Slack App (Bot) installed to your workspace
- An OpenAI API key

2) Clone and install
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# If anything is missing, also install:
pip install flask slack_bolt slack_sdk python-dotenv langgraph bs4 openai pydantic
```

3) Configure environment
- Create a `.env` file in the project root with the following keys:
```
OPENAI_API_KEY=your-openai-key
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
# Absolute path to the tokens folder that contains Gmail OAuth files (must end with a trailing slash)
TOKENS_PATH=/absolute/path/to/inbox_zero/tokens/
```

4) Slack App setup
- Create a Slack App (from scratch) and add a Bot user
- OAuth scopes (typical):
  - chat:write
  - im:write
  - users:read
- Interactivity & Shortcuts: enable and set Request URL to `<your-public-url>/slack/actions`
- Event Subscriptions: enable and set Request URL to `<your-public-url>/slack/events`
- Install the app to your workspace and copy the Bot Token and Signing Secret into `.env`
- For local development, use a tunneling tool (e.g., ngrok) to expose `http://localhost:5002`

5) Run the server
```bash
python main.py
# Server listens on http://localhost:5002
```

### What it does
- Reads recent Gmail messages via the Gmail API
- Generates a concise summary and identifies emails needing responses (OpenAI)
- Creates draft replies (OpenAI + Gmail)
- Sends each draft to Slack for approve/reject/save via interactive buttons
- Resumes the workflow after each Slack action until done, then posts a final summary

### API endpoints
- POST `/start_workflow`
  - Body: `{ "user_id": "U123ABC" }` (Slack user ID to DM approval requests)
  - Starts the LangGraph workflow. Returns `{"status": "paused", "awaiting_approval": true}` when waiting on Slack approval, or `{"status": "completed", ...}` when it finishes in one pass.

- POST `/resume_workflow`
  - Body: `{ "user_id": "U123ABC", "action": "approve_draft"|"reject_draft"|"save_draft" }`
  - Resumes the workflow after a Slack action when needed.

Slack endpoints used by the app
- `/slack/events` — Slack Events API entrypoint
- `/slack/actions` — Interactivity actions (buttons) entrypoint

### Configuration notes
- `.env` is loaded at runtime. Ensure it exists at the project root before starting the app.
- `TOKENS_PATH` must be an absolute path and end with a trailing slash. It should contain `credentials.json` and will be where `token.json` is created.
- The Flask server defaults to port `5002`.

### Project structure (high level)
```
inbox_zero/
  main.py                    # Flask + Slack app bootstrap
  src/  
    agent/  
      OpenAIAgent.py         # OpenAI tool-calling agent
    gmail/  
      GmailAuthenticator.py  # OAuth flow (credentials.json/token.json)
      GmailReader.py         # Read/search Gmail
      GmailWriter.py         # Create/send/save drafts, decode for Slack
      GCalendar.py           # Google Calendar integration helpers
    LangGraph/  
      factory.py             # Helper factory utilities
      workflow.py            # EmailProcessingWorkflow (LangGraph graph)
      workflow_factory.py    # get_workflow() wiring Gmail, Slack, OpenAI
      state_manager.py       # Persist/restore workflow state
    models/  
      agent.py               # Pydantic state and schemas
      gmail.py               # Gmail-related models
      slack.py               # Slack-related models
      toolfunction.py        # Tool/function schema models
    routes/  
      flask/  
        flask_routes.py      # /start_workflow, /resume_workflow
      slack/  
        slack_routes.py      # /slack/events, /slack/actions
    slack/  
      DraftApprovalHandler.py   # Slack interactive approvals
      SlackAuthenticator.py     # Slack auth helpers (if needed)
      workflow_bridge.py        # Resume workflow after Slack action
    utils/  
      load_env.py            # .env loader
      tests/                 # Utility tests
```

### How it works (architecture)
1. Client calls `/start_workflow` with a Slack `user_id`
2. `EmailProcessingWorkflow`:
   - reads unread emails
   - summarizes and analyzes which need responses (OpenAI)
   - generates drafts (OpenAI) and builds Gmail drafts
   - sends each draft to Slack via `DraftApprovalHandler` with Approve/Reject/Save buttons
   - pauses while waiting for user action (state is saved)
3. When the user clicks a Slack button, the app resumes via `/slack/actions` → internal resume logic → `/resume_workflow`
4. After all drafts are handled, a final summary is posted and the workflow completes

### Example requests
Start workflow
```bash
curl -X POST http://localhost:5002/start_workflow \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"U123ABC"}'
```

Resume after an approval (usually triggered internally from Slack)
```bash
curl -X POST http://localhost:5002/resume_workflow \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"U123ABC","action":"approve_draft"}'
```

### Troubleshooting
- Slack 401/invalid signature: verify `SLACK_SIGNING_SECRET` and external URLs for `/slack/actions` and `/slack/events`
- Cannot DM the user: ensure the bot is installed and has `im:write`; use a valid Slack user ID (e.g., starts with `U`)
- Gmail errors: confirm `credentials.json` exists at `TOKENS_PATH` and re‑run to regenerate `token.json` if needed
- No .env loaded: ensure `.env` exists at project root and environment variable keys are set before `python main.py`
- `TOKENS_PATH` must end with `/` so the app finds `token.json` and `credentials.json`

### Security
- Do not commit `credentials.json` or `token.json`
- Keep API keys in `.env` or your secret manager
