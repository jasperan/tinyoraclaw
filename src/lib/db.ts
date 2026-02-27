/**
 * Oracle-backed message queue via TinyOraClaw sidecar HTTP API.
 *
 * Replaces the upstream SQLite (better-sqlite3) module with async HTTP calls
 * to the Python FastAPI sidecar running on TINYORACLAW_SERVICE_URL.
 *
 * All functions are async. The interfaces (DbMessage, DbResponse, etc.) remain
 * compatible with upstream TinyClaw so channel clients and the queue processor
 * work without structural changes — only await insertion is needed at call sites.
 */

import { EventEmitter } from 'events';

// ── Sidecar config ──────────────────────────────────────────────────────────

const SIDECAR_URL = (process.env.TINYORACLAW_SERVICE_URL || 'http://localhost:8100').replace(/\/$/, '');
const SIDECAR_TOKEN = process.env.TINYORACLAW_SERVICE_TOKEN || '';

function sidecarHeaders(): Record<string, string> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (SIDECAR_TOKEN) {
        headers['Authorization'] = `Bearer ${SIDECAR_TOKEN}`;
    }
    return headers;
}

async function sidecarFetch(path: string, opts: RequestInit = {}): Promise<any> {
    const url = `${SIDECAR_URL}${path}`;
    const res = await fetch(url, {
        ...opts,
        headers: { ...sidecarHeaders(), ...(opts.headers as Record<string, string> || {}) },
    });
    if (!res.ok) {
        const text = await res.text().catch(() => '');
        throw new Error(`Sidecar ${opts.method || 'GET'} ${path} failed (${res.status}): ${text}`);
    }
    return res.json();
}

// ── Types ────────────────────────────────────────────────────────────────────

export interface DbMessage {
    id: number;
    message_id: string;
    channel: string;
    sender: string;
    sender_id: string | null;
    message: string;
    agent: string | null;
    files: string | null;         // JSON array
    conversation_id: string | null;
    from_agent: string | null;
    status: 'pending' | 'processing' | 'completed' | 'dead';
    retry_count: number;
    last_error: string | null;
    created_at: number;
    updated_at: number;
    claimed_by: string | null;
}

export interface DbResponse {
    id: number;
    message_id: string;
    channel: string;
    sender: string;
    sender_id: string | null;
    message: string;
    original_message: string;
    agent: string | null;
    files: string | null;         // JSON array
    status: 'pending' | 'acked';
    created_at: number;
    acked_at: number | null;
}

export interface EnqueueMessageData {
    channel: string;
    sender: string;
    senderId?: string;
    message: string;
    messageId: string;
    agent?: string;
    files?: string[];
    conversationId?: string;
    fromAgent?: string;
}

export interface EnqueueResponseData {
    channel: string;
    sender: string;
    senderId?: string;
    message: string;
    originalMessage: string;
    messageId: string;
    agent?: string;
    files?: string[];
}

// ── Singleton ────────────────────────────────────────────────────────────────

export const queueEvents = new EventEmitter();

let _initialized = false;

// ── Init ─────────────────────────────────────────────────────────────────────

/**
 * Check that the sidecar is reachable and healthy.
 * Replaces the upstream initQueueDb() that created SQLite tables.
 */
export async function initQueueDb(): Promise<void> {
    if (_initialized) return;

    try {
        const health = await sidecarFetch('/api/health');
        if (health.status === 'ok' || health.status === 'healthy') {
            _initialized = true;
            console.log(`[TinyOraClaw] Sidecar connected at ${SIDECAR_URL}`);
        } else {
            console.warn(`[TinyOraClaw] Sidecar health check returned: ${JSON.stringify(health)}`);
            _initialized = true; // allow operation even if DB is degraded
        }
    } catch (e) {
        console.error(`[TinyOraClaw] Sidecar not reachable at ${SIDECAR_URL}: ${(e as Error).message}`);
        console.error(`[TinyOraClaw] Make sure the sidecar is running: docker compose up tinyoraclaw-service -d`);
        throw e;
    }
}

// ── Messages (incoming queue) ────────────────────────────────────────────────

export async function enqueueMessage(data: EnqueueMessageData): Promise<number> {
    const body = {
        messageId: data.messageId,
        channel: data.channel,
        sender: data.sender,
        senderId: data.senderId || null,
        message: data.message,
        agent: data.agent || null,
        files: data.files || null,
        conversationId: data.conversationId || null,
        fromAgent: data.fromAgent || null,
    };

    const result = await sidecarFetch('/api/queue/enqueue', {
        method: 'POST',
        body: JSON.stringify(body),
    });

    const rowId = result.id as number;
    queueEvents.emit('message:enqueued', { id: rowId, agent: data.agent });
    return rowId;
}

/**
 * Atomically claim the oldest pending message for a given agent.
 * The sidecar uses SELECT FOR UPDATE SKIP LOCKED for concurrency safety.
 */
export async function claimNextMessage(agentId: string): Promise<DbMessage | null> {
    const result = await sidecarFetch(`/api/queue/next/${encodeURIComponent(agentId)}`);
    return result.message || null;
}

export async function completeMessage(rowId: number): Promise<void> {
    await sidecarFetch(`/api/queue/${rowId}/complete`, { method: 'PATCH' });
}

export async function failMessage(rowId: number, error: string): Promise<void> {
    await sidecarFetch(`/api/queue/${rowId}/fail`, {
        method: 'PATCH',
        body: JSON.stringify({ error }),
    });
}

// ── Responses (outgoing queue) ───────────────────────────────────────────────

export async function enqueueResponse(data: EnqueueResponseData): Promise<number> {
    const body = {
        messageId: data.messageId,
        channel: data.channel,
        sender: data.sender,
        senderId: data.senderId || null,
        message: data.message,
        originalMessage: data.originalMessage,
        agent: data.agent || null,
        files: data.files || null,
    };

    const result = await sidecarFetch('/api/responses/enqueue', {
        method: 'POST',
        body: JSON.stringify(body),
    });

    return result.id as number;
}

export async function getResponsesForChannel(channel: string): Promise<DbResponse[]> {
    const result = await sidecarFetch(`/api/responses/pending?channel=${encodeURIComponent(channel)}`);
    return result.responses || [];
}

export async function ackResponse(responseId: number): Promise<void> {
    await sidecarFetch(`/api/responses/${responseId}/ack`, { method: 'POST' });
}

export async function getRecentResponses(limit: number): Promise<DbResponse[]> {
    const result = await sidecarFetch(`/api/responses/recent?limit=${limit}`);
    return result.responses || [];
}

// ── Queue status & management ────────────────────────────────────────────────

export async function getQueueStatus(): Promise<{
    pending: number; processing: number; completed: number; dead: number;
    responsesPending: number;
}> {
    const result = await sidecarFetch('/api/queue/status');
    return {
        pending: result.pending ?? 0,
        processing: result.processing ?? 0,
        completed: result.completed ?? 0,
        dead: result.dead ?? 0,
        responsesPending: result.responsesPending ?? 0,
    };
}

export async function getDeadMessages(): Promise<DbMessage[]> {
    const result = await sidecarFetch('/api/queue/dead');
    return result.messages || [];
}

export async function retryDeadMessage(rowId: number): Promise<boolean> {
    try {
        await sidecarFetch(`/api/queue/dead/${rowId}/retry`, { method: 'POST' });
        return true;
    } catch {
        return false;
    }
}

export async function deleteDeadMessage(rowId: number): Promise<boolean> {
    try {
        await sidecarFetch(`/api/queue/dead/${rowId}`, { method: 'DELETE' });
        return true;
    } catch {
        return false;
    }
}

/**
 * Recover messages stuck in 'processing' for longer than threshold.
 */
export async function recoverStaleMessages(): Promise<number> {
    const result = await sidecarFetch('/api/queue/recover-stale', { method: 'POST' });
    return result.recovered ?? 0;
}

/**
 * Clean up acked responses older than the given threshold.
 */
export async function pruneAckedResponses(): Promise<number> {
    const result = await sidecarFetch('/api/queue/prune/responses', { method: 'DELETE' });
    return result.pruned ?? 0;
}

/**
 * Clean up completed messages older than the given threshold.
 */
export async function pruneCompletedMessages(): Promise<number> {
    const result = await sidecarFetch('/api/queue/prune/messages', { method: 'DELETE' });
    return result.pruned ?? 0;
}

/**
 * Get all distinct agent values from pending messages.
 */
export async function getPendingAgents(): Promise<string[]> {
    const result = await sidecarFetch('/api/queue/pending-agents');
    return result.agents || [];
}

// ── Lifecycle ────────────────────────────────────────────────────────────────

/**
 * No-op — the sidecar manages its own Oracle connection pool.
 * Kept for API compatibility with upstream TinyClaw.
 */
export async function closeQueueDb(): Promise<void> {
    _initialized = false;
}
