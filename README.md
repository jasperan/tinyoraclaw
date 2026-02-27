<div align="center">
  <img src="./docs/images/tinyclaw.png" alt="TinyOraClaw" width="600" />

  <h1>TinyOraClaw</h1>

  <h3>Multi-Agent AI Assistant + Oracle AI Database for Persistent Memory</h3>

  <p>
    <img src="https://img.shields.io/badge/TypeScript-5.9-3178C6?style=for-the-badge&logo=typescript&logoColor=white" alt="TypeScript">
    <img src="https://img.shields.io/badge/Node.js-22+-339933?style=for-the-badge&logo=nodedotjs&logoColor=white" alt="Node.js">
    <img src="https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
    <a href="https://www.oracle.com/database/free/">
      <img src="https://img.shields.io/badge/Oracle_Database-Free-F80000?style=for-the-badge&logo=oracle&logoColor=white" alt="Oracle Database Free">
    </a>
    <a href="https://opensource.org/licenses/MIT">
      <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="MIT License">
    </a>
  </p>
</div>

---

## What is TinyOraClaw?

**TinyOraClaw** is a fork of [TinyClaw](https://github.com/TinyAGI/tinyclaw) that replaces all SQLite storage with **Oracle AI Database** as the exclusive persistence layer. Every message, conversation, and memory is stored in Oracle with in-database ONNX vector embeddings for semantic recall.

TinyClaw is a multi-agent, multi-team, multi-channel 24/7 AI assistant framework. TinyOraClaw preserves all of its capabilities while adding enterprise-grade persistence and vector search.

### Why Oracle AI Database?

| Feature | SQLite (upstream) | Oracle AI Database (TinyOraClaw) |
|---------|-------------------|----------------------------------|
| **Embeddings** | None | In-database ONNX (`VECTOR_EMBEDDING()`) |
| **Semantic Search** | None | `VECTOR_DISTANCE()` with COSINE similarity |
| **Crash Recovery** | WAL journal | Full ACID transactions |
| **Concurrent Access** | File-level locking | Connection pooling + row-level locking |
| **Scalability** | Single-file | Enterprise (FreePDB local or ADB cloud) |
| **Audit Trail** | None | Full transcript logging |

### Key Features

Everything from TinyClaw:
- **Multi-agent** — Run multiple isolated AI agents with specialized roles
- **Multi-team collaboration** — Agents hand off work via chain execution and fan-out
- **Multi-channel** — Discord, WhatsApp, and Telegram
- **Web portal (TinyOffice)** — Browser-based dashboard for chat, agents, teams, tasks, logs
- **Team Observation** — Observe agent team conversations in real-time

Plus Oracle AI Database:
- **Oracle AI Database** as exclusive storage backend (not SQLite, not files)
- **In-database ONNX embeddings** (ALL_MINILM_L12_V2) — zero external API calls
- **Semantic memory recall** — agents remember by meaning, not just keywords
- **Python FastAPI sidecar** for all Oracle operations
- **Docker Compose** with FreePDB (local) + ADB (cloud) modes
- **Full audit transcripts** with agent attribution

## Architecture

```
┌─────────────────────────────────────────────────┐
│  TinyClaw (TypeScript/Node.js)                  │
│  ├── Channels: Discord, Telegram, WhatsApp      │
│  ├── Hono API Server (:3777)                    │
│  ├── Queue Processor                            │
│  └── Agent Coordination                         │
│           │ HTTP/REST                            │
│           ▼                                      │
│  TinyOraClaw Service (Python FastAPI :8100)      │
│  ├── Message Queue API                          │
│  ├── Memory Service (VECTOR_EMBEDDING)          │
│  ├── Session Service                            │
│  ├── Transcript Service                         │
│  └── Connection Pool Manager                    │
│           │ oracledb (async)                     │
│           ▼                                      │
│  Oracle AI Database 26ai Free (:1521)           │
│  ├── TINY_MESSAGES   (queue lifecycle)           │
│  ├── TINY_RESPONSES  (delivery tracking)         │
│  ├── TINY_MEMORIES   (VECTOR(384) + COSINE)     │
│  ├── TINY_SESSIONS   (JSON CLOB history)         │
│  ├── TINY_TRANSCRIPTS (audit log)                │
│  ├── TINY_STATE      (agent K-V store)           │
│  └── TINY_META       (schema versioning)         │
└─────────────────────────────────────────────────┘
```

The **tinyoraclaw-service** sidecar handles all Oracle operations:
- Connection pooling and lifecycle management
- Schema initialization (auto-init on startup)
- Embedding generation via `VECTOR_EMBEDDING()`
- Memory store with vector similarity search
- Session persistence (JSON CLOB)
- Full audit transcripts

Upstream TinyClaw connects to the sidecar via HTTP/REST, replacing all SQLite calls.

## Quick Start

### 1. Clone

```bash
git clone https://github.com/jasperan/tinyoraclaw.git
cd tinyoraclaw
```

### 2. Start Oracle + Sidecar

```bash
cp .env.example .env
docker compose up oracle-db tinyoraclaw-service -d

# Wait for Oracle to become healthy (~2 minutes on first run)
docker compose logs -f oracle-db
```

### 3. Install TinyClaw

```bash
npm install
npm run build
```

### 4. Configure & Run

```bash
# Set up agents via the TinyClaw setup wizard
./tinyclaw.sh setup

# Start the queue processor (now Oracle-backed)
npm run queue
```

## Docker Compose

```bash
# Full stack: Oracle + Sidecar (default)
docker compose up -d

# Oracle only (for local dev against sidecar)
docker compose up oracle-db -d

# ADB cloud mode (no local Oracle needed)
docker compose --profile adb up tinyoraclaw-service-adb -d
```

## Oracle Schema

| Table | Purpose | Key Feature |
|-------|---------|-------------|
| `TINY_META` | Schema versioning | Single row per key |
| `TINY_MESSAGES` | Message queue | Full lifecycle: pending → processing → completed/dead |
| `TINY_RESPONSES` | Response tracking | Delivery status with ack timestamps |
| `TINY_MEMORIES` | Long-term memory | `VECTOR(384)` + COSINE index for semantic recall |
| `TINY_SESSIONS` | Chat history | JSON CLOB per team (replaces filesystem .md) |
| `TINY_TRANSCRIPTS` | Audit log | Full conversation record with agent attribution |
| `TINY_STATE` | Agent K-V store | Composite PK (agent_id, key) |

All tables support **multi-agent isolation** via `agent_id` column.

## Configuration

### FreePDB (Local Docker)

```bash
ORACLE_MODE=freepdb
ORACLE_HOST=localhost
ORACLE_PORT=1521
ORACLE_SERVICE=FREEPDB1
ORACLE_USER=tinyoraclaw
ORACLE_PASSWORD=TinyOraClaw2026
```

### ADB (Oracle Cloud)

```bash
ORACLE_MODE=adb
ORACLE_USER=ADMIN
ORACLE_PASSWORD=Welcome12345*
ORACLE_DSN=(description= (retry_count=20)(retry_delay=3)...)
```

See [.env.example](.env.example) for full configuration reference.

## Sidecar API

The Python FastAPI sidecar exposes these endpoints on port 8100:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/health` | GET | Readiness + DB connectivity |
| `/api/init` | POST | Manual schema initialization |
| `/api/queue/enqueue` | POST | Add message to queue |
| `/api/queue/next/{agent_id}` | GET | Claim next pending message |
| `/api/queue/status` | GET | Queue counts by status |
| `/api/memory/remember` | POST | Store memory with auto-embedding |
| `/api/memory/recall` | POST | Semantic vector search |
| `/api/sessions/save` | POST | Persist chat session |
| `/api/sessions/{team_id}` | GET | Load session history |
| `/api/transcripts/log` | POST | Write audit entry |

## Sister Projects

| Project | Upstream | Language | Description |
|---------|----------|----------|-------------|
| [OracLaw](https://github.com/jasperan/oraclaw) | OpenClaw | TypeScript + Python | Code-aware AI with Oracle memory |
| [PicoOraClaw](https://github.com/jasperan/picooraclaw) | PicoClaw | Go | Lightweight agent with Oracle storage |
| [ZeroOraClaw](https://github.com/jasperan/zerooraclaw) | ZeroClaw | Rust | High-performance agent with Oracle backend |
| **TinyOraClaw** | TinyClaw | TypeScript + Python | Multi-agent teams with Oracle persistence |

## License

MIT License — see [LICENSE](LICENSE) for details.

Based on [TinyClaw](https://github.com/TinyAGI/tinyclaw) by Jian Liao.

---

<div align="center">

[![GitHub](https://img.shields.io/badge/GitHub-jasperan-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/jasperan)&nbsp;
[![LinkedIn](https://img.shields.io/badge/LinkedIn-jasperan-0077B5?style=for-the-badge&logo=linkedin&logoColor=white)](https://www.linkedin.com/in/jasperan/)&nbsp;
[![Oracle](https://img.shields.io/badge/Oracle_Database-Free-F80000?style=for-the-badge&logo=oracle&logoColor=white)](https://www.oracle.com/database/free/)

</div>
