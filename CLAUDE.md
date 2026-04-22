# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project Overview

**Involio Copytrading Agent** — A 24/7 automated system that monitors Involio notifications and replicates trades published by followed traders, using only parameters visible in the interface. No API access is available; automation is done via browser (Playwright).

---

## Core Philosophy

**Copy what exists. Never invent what does not.**

- Replicate only parameters visible in the trade notification or detail view.
- If a parameter (TP, SL, leverage, bank %) is absent, open the trade anyway without filling in defaults.
- Never infer, estimate, or assume missing values.
- Never copy the same trade more than once.
- Never follow traders or take any action outside the explicit set authorized by the user.

---

## System Architecture

Eight decoupled modules, each with a single responsibility:

```
SessionManager       → login, session persistence, expiry detection
NotificationMonitor  → polls the bell icon, detects new alerts, emits events
TradeParser          → opens notification/detail, extracts & normalizes visible fields
DeduplicationEngine  → assigns unique IDs per trade, blocks re-execution
ExecutionEngine      → opens / modifies / closes trades using only parsed fields
StateStore           → SQLite; persists session, trade history, errors, timestamps
AlertingModule       → Telegram/Discord/email for critical events and daily summaries
RecoveryManager      → restarts browser, restores session, detects missed notifications
```

Data flows one-way through the pipeline:

```
NotificationMonitor
    → TradeParser
        → DeduplicationEngine
            → ExecutionEngine
                → StateStore + AlertingModule

(parallel loop)
ExecutionEngine monitors active trades → syncs modifications → closes on source close
RecoveryManager watches all components → restarts on crash
```

---

## Tech Stack

| Layer | Choice |
|---|---|
| Browser automation | Playwright + Python (primary); Selenium (fallback) |
| State / deduplication | SQLite |
| Credentials | `.env` file, never hardcoded |
| Alerts | Telegram, Discord, or email (configurable) |
| Deployment target | Local PC first; VPS-ready design |

---

## Development Commands

> Commands will be added here as the project is scaffolded. Expected structure:

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Run the agent
python main.py

# Run tests
pytest

# Run a single test
pytest tests/test_parser.py::test_name -v

# Lint
ruff check .
```

---

## Operational Rules (non-negotiable)

| Rule | Behavior |
|---|---|
| Order failure | Pause entire system immediately, alert user, do not continue |
| Interface change detected | Pause execution engine, alert user, do not click blindly |
| Browser/session crash | Restart immediately, restore session, check for missed notifications, alert user |
| Session expiry | Pause bot, request human intervention |
| Duplicate trade detected | Skip silently, log it |
| Unauthorized trader notification | Skip, no copy |

**Forbidden actions — never implement:**
- Deposits or withdrawals
- Profile or account changes
- Following new traders automatically
- Filling missing trade fields with defaults
- Continuing to execute trades after a critical order failure

---

## Execution Priorities

1. **Speed** — minimum latency between detection and execution
2. **Precision** — replicate only what is visible
3. **No missed trades** — deduplication must be robust, not restrictive

The system is intentionally aggressive: no daily loss limits, no max simultaneous trades, no leverage cap. This is by user decision and must be respected in all implementations.

---

## Logging & Observability

Every critical action must be logged with:

```
timestamp | trader_id | trade_unique_id | parsed_fields | action_taken | result | errors
```

Screenshots must be saved before and after each execution attempt.

Alert triggers (send immediately):
- Login failure
- Order failure
- Interface change detected
- Browser closed
- Session expired
- System paused / resumed
- Trade detected but not copied
- Modification detected but not applied

Daily summary must include: trades detected, trades copied, failures, downtime, errors, approximate PnL.

---

## Phased Roadmap

| Phase | Goal |
|---|---|
| 1 | Stable login + session + notification reading + basic data extraction |
| 2 | Continuous polling + trader authorization filter + deduplication |
| 3 | Trade execution (open long/short with available params) |
| 4 | Sync modifications + auto-close on source close |
| 5 | Fault tolerance: auto-restart, session recovery, pause/resume controls |
| 6 | Dashboard, daily metrics, VPS deployment |

Build and validate each phase before moving to the next.

---

## Open Decisions (confirm before implementing)

- Credential storage location (`.env` path, secrets manager, etc.)
- Alert channel (Telegram bot token, Discord webhook, etc.)
- Slippage alert threshold (no blocking in v1; add in later phase)
- Polling frequency for the notification bell
- Strategy for stable unique trade ID (notification ID, timestamp+trader combo, etc.)
- Whether to validate trade data against the detail page before executing (tradeoff: accuracy vs. latency)
