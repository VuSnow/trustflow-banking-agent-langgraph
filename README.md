# TrustFlow Guardian — LangGraph Edition

> Natural-language banking assistant with adversarial safety built in.  
> Powered by **LangGraph** for state management, agent orchestration, and FSM control.

## Architecture (LangGraph)

```text
┌─────────────────────────────────────────────────────────┐
│                    StateGraph                            │
│                                                         │
│  entry → [FSM check] ─┬→ classify_intent → route ──┐   │
│                        ├→ confirmation_node          │   │
│                        └→ otp_node                   │   │
│                                                      │   │
│         ┌────────────────────────────────────────────┘   │
│         ▼                                                │
│  ┌─────────────────────────────────────────────┐        │
│  │ Domain Agents (LangGraph ReAct)             │        │
│  │ • transaction_agent (tools: text2sql,       │        │
│  │   verify_recipient, check_fraud_risk)       │        │
│  │ • card_agent (tools: get_cards, lock, etc.) │        │
│  │ • qa_agent (direct LLM)                     │        │
│  │ • data_query_agent (text2sql-service)       │        │
│  └──────────────────────┬──────────────────────┘        │
│                         ▼                                │
│  guardrails → [waiting_confirmation] → [waiting_otp]    │
│             → executed / blocked                         │
└─────────────────────────────────────────────────────────┘
```

## Key Differences from Original

| Aspect | Original (from scratch) | LangGraph Edition |
|--------|------------------------|-------------------|
| Agent loop | Manual `for` iteration + tool dispatch | `create_react_agent()` prebuilt |
| FSM | Manual if/else in `*_fsm.py` files | Graph conditional edges + state |
| Orchestration | Custom pipeline planner | StateGraph with conditional routing |
| State persistence | Manual PostgreSQL JSON | LangGraph state + session store |
| Routing | Manual intent → agent map | Conditional edges |
| Boilerplate | ~300 LOC per agent | ~50 LOC per agent |

## Quick Start

```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000
```

- Backend: http://localhost:8000
- Frontend: http://localhost:8000/web_ui

## API

```text
POST /chat              → Main conversation endpoint
GET  /sessions          → List sessions for user
POST /sessions          → Create new session
GET  /sessions/{id}     → Get session details
GET  /sessions/{id}/messages → Get messages
GET  /health            → Health check
```

## Project Structure

```
backend/
├── main.py                    # FastAPI app entrypoint
├── config.py                  # Environment config
├── state.py                   # LangGraph state definitions (TypedDict)
├── graphs/
│   └── orchestrator.py        # Main StateGraph (intent → agent → guardrails → FSM)
├── agents/
│   ├── transaction.py         # Transaction agent (LangGraph ReAct)
│   ├── card_operation.py      # Card agent (LangGraph ReAct)
│   ├── qa.py                  # QA agent (direct LLM)
│   └── data_query.py          # Data query agent (text2sql service)
├── tools/
│   ├── transaction_tools.py   # @tool: text2sql_query, verify_recipient, check_fraud_risk
│   ├── card_tools.py          # @tool: get_user_cards, lock_card, unlock_card, etc.
│   └── account_tools.py       # @tool: get_user_accounts, get_account_detail
├── services/
│   ├── chat_session_store.py  # PostgreSQL session/message persistence
│   ├── guardrails.py          # Deterministic safety checks
│   ├── confirmation_classifier.py  # LLM-based confirm/cancel/modify
│   └── audit_log.py           # Immutable audit trail
├── prompts/
│   ├── intent.py              # Intent classification prompts
│   ├── transaction.py         # Transaction agent system prompt
│   ├── card_operation.py      # Card agent system prompt
│   ├── qa.py                  # QA agent prompt
│   └── confirmation.py        # Confirmation classifier prompt
└── routes/
    ├── chat.py                # POST /chat endpoint
    └── sessions.py            # Session CRUD endpoints
data/                          # SQL schemas, seed data
docs/                          # Architecture docs
frontend/                      # Static HTML + Preact UI
```

## Guardian Matrix (unchanged)

| Risk Tier | Condition | Action |
|-----------|-----------|--------|
| 🟢 GREEN | Known recipient, low amount | Confirm → OTP |
| 🟡 YELLOW | Unknown recipient or large | Warning + OTP |
| 🔴 RED | Fraud CRITICAL | Hard block |

## Core Principles (unchanged)

1. **LLM prepares, never executes.** Agents create drafts only.
2. **Guardian is external and final.** No agent can bypass.
3. **Hard rules first, model second.** Deterministic before probabilistic.
4. **Immutable audit trail.** Every decision logged.
