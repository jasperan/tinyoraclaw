/**
 * Hybrid queue layer.
 *
 * - In normal upstream mode, uses local SQLite (`tinyagi.db`).
 * - When `TINYORACLAW_SERVICE_URL` is set, routes message/response queue
 *   operations through the TinyOraClaw Oracle sidecar while keeping newer
 *   upstream-only local tables (`chat_messages`, `agent_messages`) in SQLite.
 */

import Database from 'better-sqlite3';
import path from 'path';
import { EventEmitter } from 'events';
import { TINYAGI_HOME } from './config';
import { MessageJobData, ResponseJobData } from './types';

const QUEUE_DB_PATH = path.join(TINYAGI_HOME, 'tinyagi.db');
const MAX_RETRIES = 5;

const SIDECAR_URL = (process.env.TINYORACLAW_SERVICE_URL || '').replace(/\/$/, '');
const SIDECAR_TOKEN = process.env.TINYORACLAW_SERVICE_TOKEN || '';
const USE_SIDECAR = Boolean(SIDECAR_URL);

let db: Database.Database | null = null;
export const queueEvents = new EventEmitter();

function sidecarHeaders(): Record<string, string> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (SIDECAR_TOKEN) headers['Authorization'] = `Bearer ${SIDECAR_TOKEN}`;
    return headers;
}

async function sidecarFetch(pathname: string, opts: RequestInit = {}): Promise<any> {
    const res = await fetch(`${SIDECAR_URL}${pathname}`, {
        ...opts,
        headers: { ...sidecarHeaders(), ...(opts.headers as Record<string, string> || {}) },
    });
    if (!res.ok) {
        const text = await res.text().catch(() => '');
        throw new Error(`Sidecar ${opts.method || 'GET'} ${pathname} failed (${res.status}): ${text}`);
    }
    return res.json();
}

export function initQueueDb(): void {
    if (db) return;
    db = new Database(QUEUE_DB_PATH);
    db.pragma('journal_mode = WAL');
    db.pragma('busy_timeout = 5000');

    db.exec(`
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT NOT NULL UNIQUE,
            channel TEXT NOT NULL, sender TEXT NOT NULL, sender_id TEXT,
            message TEXT NOT NULL, agent TEXT,
            from_agent TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            retry_count INTEGER NOT NULL DEFAULT 0, last_error TEXT,
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT NOT NULL,
            channel TEXT NOT NULL, sender TEXT NOT NULL, sender_id TEXT,
            message TEXT NOT NULL, original_message TEXT NOT NULL,
            agent TEXT, files TEXT, metadata TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at INTEGER NOT NULL, acked_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id TEXT NOT NULL, from_agent TEXT NOT NULL,
            message TEXT NOT NULL, created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS agent_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id TEXT NOT NULL,
            role TEXT NOT NULL,
            channel TEXT NOT NULL,
            sender TEXT NOT NULL,
            message_id TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_msg_status ON messages(status, agent, created_at);
        CREATE INDEX IF NOT EXISTS idx_resp_channel ON responses(channel, status);
        CREATE INDEX IF NOT EXISTS idx_chat_team ON chat_messages(team_id, id);
        CREATE INDEX IF NOT EXISTS idx_agent_messages_agent ON agent_messages(agent_id, created_at);
    `);

    const respCols = db.prepare("PRAGMA table_info(responses)").all() as { name: string }[];
    if (!respCols.some(c => c.name === 'metadata')) {
        db.exec('ALTER TABLE responses ADD COLUMN metadata TEXT');
    }
    const msgCols = db.prepare("PRAGMA table_info(messages)").all() as { name: string }[];
    if (msgCols.some(c => c.name === 'files')) db.exec('ALTER TABLE messages DROP COLUMN files');
    if (msgCols.some(c => c.name === 'conversation_id')) db.exec('ALTER TABLE messages DROP COLUMN conversation_id');
}

function getDb(): Database.Database {
    if (!db) throw new Error('Queue DB not initialized — call initQueueDb() first');
    return db;
}

// ── Messages ────────────────────────────────────────────────────────────────

export async function enqueueMessage(data: MessageJobData): Promise<number | null> {
    if (USE_SIDECAR) {
        try {
            const result = await sidecarFetch('/api/queue/enqueue', {
                method: 'POST',
                body: JSON.stringify({
                    messageId: data.messageId,
                    channel: data.channel,
                    sender: data.sender,
                    senderId: data.senderId || null,
                    message: data.message,
                    agent: data.agent || null,
                    files: data.files || null,
                    conversationId: data.conversationId || null,
                    fromAgent: data.fromAgent || null,
                }),
            });
            queueEvents.emit('message:enqueued', { id: result.id, agent: data.agent });
            return result.id as number;
        } catch (err: any) {
            const msg = String(err?.message || err);
            if (msg.includes('ORA-00001') || msg.toLowerCase().includes('duplicate')) {
                return null;
            }
            throw err;
        }
    }

    const now = Date.now();
    try {
        const r = getDb().prepare(
            `INSERT INTO messages (message_id,channel,sender,sender_id,message,agent,from_agent,status,created_at,updated_at)
             VALUES (?,?,?,?,?,?,?,'pending',?,?)`
        ).run(data.messageId, data.channel, data.sender, data.senderId ?? null, data.message,
            data.agent ?? null, data.fromAgent ?? null, now, now);
        queueEvents.emit('message:enqueued', { id: r.lastInsertRowid, agent: data.agent });
        return r.lastInsertRowid as number;
    } catch (err: any) {
        if (err.code === 'SQLITE_CONSTRAINT_UNIQUE') return null;
        throw err;
    }
}

export async function getPendingAgents(): Promise<string[]> {
    if (USE_SIDECAR) {
        const result = await sidecarFetch('/api/queue/pending-agents');
        return result.agents || [];
    }
    return (getDb().prepare(
        `SELECT DISTINCT COALESCE(agent,'default') as agent FROM messages WHERE status='pending'`
    ).all() as { agent: string }[]).map(r => r.agent);
}

export async function claimAllPendingMessages(agentId: string): Promise<any[]> {
    if (USE_SIDECAR) {
        const messages: any[] = [];
        while (true) {
            const result = await sidecarFetch(`/api/queue/next/${encodeURIComponent(agentId)}`);
            if (!result.message) break;
            messages.push(result.message);
        }
        return messages;
    }

    const d = getDb();
    return d.transaction(() => {
        const rows = d.prepare(
            `SELECT * FROM messages WHERE status='pending' AND (agent=? OR (agent IS NULL AND ?='default')) ORDER BY created_at`
        ).all(agentId, agentId) as any[];
        if (rows.length === 0) return [];
        const now = Date.now();
        const ids = rows.map((r: any) => r.id);
        d.prepare(`UPDATE messages SET status='queued',updated_at=? WHERE id IN (${ids.map(() => '?').join(',')})`).run(now, ...ids);
        return rows.map((r: any) => ({ ...r, status: 'queued' }));
    }).immediate();
}

export async function markProcessing(rowId: number): Promise<void> {
    if (USE_SIDECAR) return;
    getDb().prepare(`UPDATE messages SET status='processing',updated_at=? WHERE id=?`).run(Date.now(), rowId);
}

export async function completeMessage(rowId: number): Promise<void> {
    if (USE_SIDECAR) {
        await sidecarFetch(`/api/queue/${rowId}/complete`, { method: 'PATCH' });
        return;
    }
    getDb().prepare(`UPDATE messages SET status='completed',updated_at=? WHERE id=?`).run(Date.now(), rowId);
}

export async function failMessage(rowId: number, error: string): Promise<void> {
    if (USE_SIDECAR) {
        await sidecarFetch(`/api/queue/${rowId}/fail`, {
            method: 'PATCH',
            body: JSON.stringify({ error }),
        });
        return;
    }

    const d = getDb();
    const msg = d.prepare('SELECT retry_count FROM messages WHERE id=?').get(rowId) as { retry_count: number } | undefined;
    if (!msg) return;
    const newStatus = msg.retry_count + 1 >= MAX_RETRIES ? 'dead' : 'pending';
    d.prepare(`UPDATE messages SET status=?,retry_count=?,last_error=?,updated_at=? WHERE id=?`)
        .run(newStatus, msg.retry_count + 1, error, Date.now(), rowId);
}

export async function getProcessingMessages(): Promise<any[]> {
    if (USE_SIDECAR) {
        const result = await sidecarFetch('/api/queue/processing');
        return result.messages || [];
    }
    return getDb().prepare(`SELECT * FROM messages WHERE status IN ('queued','processing') ORDER BY updated_at`).all();
}

export async function recoverStaleMessages(thresholdMs = 10 * 60 * 1000): Promise<number> {
    if (USE_SIDECAR) {
        const result = await sidecarFetch(`/api/queue/recover-stale?threshold_ms=${thresholdMs}`, { method: 'POST' });
        return result.recovered ?? 0;
    }
    return getDb().prepare(`UPDATE messages SET status='pending',updated_at=? WHERE status IN ('processing','queued') AND updated_at<?`)
        .run(Date.now(), Date.now() - thresholdMs).changes;
}

// ── Responses ───────────────────────────────────────────────────────────────

export async function enqueueResponse(data: ResponseJobData): Promise<number> {
    if (USE_SIDECAR) {
        const result = await sidecarFetch('/api/responses/enqueue', {
            method: 'POST',
            body: JSON.stringify({
                messageId: data.messageId,
                channel: data.channel,
                sender: data.sender,
                senderId: data.senderId || null,
                message: data.message,
                originalMessage: data.originalMessage,
                agent: data.agent || null,
                files: data.files || null,
                metadata: data.metadata || null,
            }),
        });
        return result.id as number;
    }

    const r = getDb().prepare(
        `INSERT INTO responses (message_id,channel,sender,sender_id,message,original_message,agent,files,metadata,status,created_at)
         VALUES (?,?,?,?,?,?,?,?,?,'pending',?)`
    ).run(data.messageId, data.channel, data.sender, data.senderId ?? null, data.message,
        data.originalMessage, data.agent ?? null, data.files ? JSON.stringify(data.files) : null,
        data.metadata ? JSON.stringify(data.metadata) : null, Date.now());
    return r.lastInsertRowid as number;
}

export async function getResponsesForChannel(channel: string): Promise<any[]> {
    if (USE_SIDECAR) {
        const result = await sidecarFetch(`/api/responses/pending?channel=${encodeURIComponent(channel)}`);
        return result.responses || [];
    }
    return getDb().prepare(`SELECT * FROM responses WHERE channel=? AND status='pending' ORDER BY created_at`).all(channel);
}

export async function ackResponse(responseId: number): Promise<void> {
    if (USE_SIDECAR) {
        await sidecarFetch(`/api/responses/${responseId}/ack`, { method: 'POST' });
        return;
    }
    getDb().prepare(`UPDATE responses SET status='acked',acked_at=? WHERE id=?`).run(Date.now(), responseId);
}

export async function getRecentResponses(limit: number): Promise<any[]> {
    if (USE_SIDECAR) {
        const result = await sidecarFetch(`/api/responses/recent?limit=${limit}`);
        return result.responses || [];
    }
    return getDb().prepare(`SELECT * FROM responses ORDER BY created_at DESC LIMIT ?`).all(limit);
}

// ── Queue status ────────────────────────────────────────────────────────────

export async function getQueueStatus(): Promise<any> {
    if (USE_SIDECAR) {
        const result = await sidecarFetch('/api/queue/status');
        return { queued: 0, ...result };
    }

    const d = getDb();
    const counts = d.prepare(`SELECT status, COUNT(*) as cnt FROM messages GROUP BY status`).all() as { status: string; cnt: number }[];
    const result: any = { pending: 0, queued: 0, processing: 0, completed: 0, dead: 0, responsesPending: 0 };
    for (const row of counts) if (row.status in result) result[row.status] = row.cnt;
    result.responsesPending = (d.prepare(`SELECT COUNT(*) as cnt FROM responses WHERE status='pending'`).get() as { cnt: number }).cnt;
    return result;
}

export async function getAgentQueueStatus(): Promise<{ agent: string; pending: number; queued: number; processing: number }[]> {
    if (USE_SIDECAR) {
        const result = await sidecarFetch('/api/queue/agents');
        return result.agents || [];
    }
    return getDb().prepare(
        `SELECT COALESCE(agent,'default') as agent,
                SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status='queued' THEN 1 ELSE 0 END) as queued,
                SUM(CASE WHEN status='processing' THEN 1 ELSE 0 END) as processing
         FROM messages WHERE status IN ('pending','queued','processing') GROUP BY agent`
    ).all() as { agent: string; pending: number; queued: number; processing: number }[];
}

export async function getDeadMessages(): Promise<any[]> {
    if (USE_SIDECAR) {
        const result = await sidecarFetch('/api/queue/dead');
        return result.messages || [];
    }
    return getDb().prepare(`SELECT * FROM messages WHERE status='dead' ORDER BY updated_at DESC`).all();
}

export async function retryDeadMessage(rowId: number): Promise<boolean> {
    if (USE_SIDECAR) {
        try {
            await sidecarFetch(`/api/queue/dead/${rowId}/retry`, { method: 'POST' });
            return true;
        } catch {
            return false;
        }
    }
    return getDb().prepare(`UPDATE messages SET status='pending',retry_count=0,updated_at=? WHERE id=? AND status='dead'`).run(Date.now(), rowId).changes > 0;
}

export async function deleteDeadMessage(rowId: number): Promise<boolean> {
    if (USE_SIDECAR) {
        try {
            await sidecarFetch(`/api/queue/dead/${rowId}`, { method: 'DELETE' });
            return true;
        } catch {
            return false;
        }
    }
    return getDb().prepare(`DELETE FROM messages WHERE id=? AND status='dead'`).run(rowId).changes > 0;
}

export async function pruneAckedResponses(olderThanMs = 86400000): Promise<number> {
    if (USE_SIDECAR) {
        const result = await sidecarFetch(`/api/queue/prune/responses?older_than_ms=${olderThanMs}`, { method: 'DELETE' });
        return result.pruned ?? 0;
    }
    return getDb().prepare(`DELETE FROM responses WHERE status='acked' AND acked_at<?`).run(Date.now() - olderThanMs).changes;
}

export async function pruneCompletedMessages(olderThanMs = 86400000): Promise<number> {
    if (USE_SIDECAR) {
        const result = await sidecarFetch(`/api/queue/prune/messages?older_than_ms=${olderThanMs}`, { method: 'DELETE' });
        return result.pruned ?? 0;
    }
    return getDb().prepare(`DELETE FROM messages WHERE status='completed' AND updated_at<?`).run(Date.now() - olderThanMs).changes;
}

// ── Agent messages (per-agent chat history, local-only for now) ────────────

export function insertAgentMessage(data: {
    agentId: string; role: 'user' | 'assistant';
    channel: string; sender: string; messageId: string; content: string;
}): number {
    return getDb().prepare(
        `INSERT INTO agent_messages (agent_id,role,channel,sender,message_id,content,created_at) VALUES (?,?,?,?,?,?,?)`
    ).run(data.agentId, data.role, data.channel, data.sender, data.messageId, data.content, Date.now()).lastInsertRowid as number;
}

export function getAgentMessages(agentId: string, limit = 100): any[] {
    return getDb().prepare(
        `SELECT * FROM agent_messages WHERE agent_id=? ORDER BY created_at DESC LIMIT ?`
    ).all(agentId, limit);
}

export function getAllAgentMessages(limit = 100): any[] {
    return getDb().prepare(
        `SELECT * FROM agent_messages ORDER BY created_at DESC LIMIT ?`
    ).all(limit);
}

// ── Chat messages (local-only for now) ─────────────────────────────────────

export function insertChatMessage(teamId: string, fromAgent: string, message: string): number {
    return getDb().prepare(`INSERT INTO chat_messages (team_id,from_agent,message,created_at) VALUES (?,?,?,?)`)
        .run(teamId, fromAgent, message, Date.now()).lastInsertRowid as number;
}

export function getChatMessages(teamId: string, limit = 100): any[] {
    return getDb().prepare(`SELECT * FROM chat_messages WHERE team_id=? ORDER BY created_at DESC LIMIT ?`).all(teamId, limit);
}

// ── Lifecycle ───────────────────────────────────────────────────────────────

export function closeQueueDb(): void {
    if (db) { db.close(); db = null; }
}
