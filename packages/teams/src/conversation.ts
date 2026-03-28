import {
    MessageJobData,
    AgentConfig,
    TeamConfig,
    Conversation,
    log,
    emitEvent,
    findTeamForAgent,
    insertChatMessage,
    enqueueMessage,
    genId,
    collectFiles,
    streamResponse,
} from '@tinyagi/core';
import { stripBracketTags } from './routing';

const SIDECAR_URL = (process.env.TINYORACLAW_SERVICE_URL || '').replace(/\/$/, '');
const SIDECAR_TOKEN = process.env.TINYORACLAW_SERVICE_TOKEN || '';

function sidecarHeaders(): Record<string, string> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (SIDECAR_TOKEN) headers['Authorization'] = `Bearer ${SIDECAR_TOKEN}`;
    return headers;
}

async function sidecarFetch(pathname: string, opts: RequestInit = {}): Promise<any> {
    if (!SIDECAR_URL) {
        throw new Error('TinyOraClaw sidecar is not configured');
    }

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

function stateKey(conversationId: string): string {
    return `conversation:${conversationId}`;
}

function serializeConversation(conv: Conversation): Record<string, unknown> {
    return {
        id: conv.id,
        channel: conv.channel,
        sender: conv.sender,
        senderId: conv.senderId,
        originalMessage: conv.originalMessage,
        messageId: conv.messageId,
        pending: conv.pending,
        responses: conv.responses,
        files: Array.from(conv.files),
        totalMessages: conv.totalMessages,
        maxMessages: conv.maxMessages,
        teamContext: conv.teamContext,
        startTime: conv.startTime,
        outgoingMentions: Object.fromEntries(conv.outgoingMentions),
    };
}

function hydrateConversation(raw: any): Conversation {
    return {
        id: raw.id,
        channel: raw.channel,
        sender: raw.sender,
        senderId: raw.senderId ?? undefined,
        originalMessage: raw.originalMessage,
        messageId: raw.messageId,
        pending: raw.pending,
        responses: Array.isArray(raw.responses) ? raw.responses : [],
        files: new Set<string>(Array.isArray(raw.files) ? raw.files : []),
        totalMessages: raw.totalMessages,
        maxMessages: raw.maxMessages,
        teamContext: raw.teamContext,
        startTime: raw.startTime,
        outgoingMentions: new Map<string, number>(Object.entries(raw.outgoingMentions || {}).map(([k, v]) => [k, Number(v)])),
    };
}

export async function persistConversationState(conv: Conversation): Promise<void> {
    if (!SIDECAR_URL) return;
    await sidecarFetch(`/api/state/${encodeURIComponent(stateKey(conv.id))}`, {
        method: 'PUT',
        body: JSON.stringify({
            agentId: 'default',
            value: serializeConversation(conv),
        }),
    });
}

export async function loadConversationState(
    conversationId: string
): Promise<Conversation | null> {
    if (!SIDECAR_URL) return null;

    const res = await fetch(
        `${SIDECAR_URL}/api/state/${encodeURIComponent(stateKey(conversationId))}?agentId=default`,
        { headers: sidecarHeaders() }
    );
    if (res.status === 404) return null;
    if (!res.ok) {
        const text = await res.text().catch(() => '');
        throw new Error(`Sidecar GET /api/state failed (${res.status}): ${text}`);
    }
    const body = await res.json() as { value?: any };
    return body.value ? hydrateConversation(body.value) : null;
}

export async function deleteConversationState(conv: Conversation): Promise<void> {
    if (!SIDECAR_URL) return;
    await sidecarFetch(
        `/api/state/${encodeURIComponent(stateKey(conv.id))}?agentId=default`,
        { method: 'DELETE' }
    );
}

export const conversations = new Map<string, Conversation>();
export const MAX_CONVERSATION_MESSAGES = 50;

const conversationLocks = new Map<string, Promise<void>>();

export async function withConversationLock<T>(convId: string, fn: () => Promise<T>): Promise<T> {
    const currentLock = conversationLocks.get(convId) || Promise.resolve();

    let resolveLock!: () => void;
    const lockPromise = new Promise<void>((resolve) => {
        resolveLock = resolve;
    });

    const newLock = currentLock.then(async () => {
        try {
            return await fn();
        } finally {
            resolveLock();
        }
    });

    conversationLocks.set(convId, lockPromise);

    newLock.finally(() => {
        if (conversationLocks.get(convId) === lockPromise) {
            conversationLocks.delete(convId);
        }
    });

    return newLock;
}

export function incrementPending(conv: Conversation, count: number): void {
    conv.pending += count;
    log('DEBUG', `Conversation ${conv.id}: pending incremented to ${conv.pending} (+${count})`);
}

export function decrementPending(conv: Conversation): boolean {
    conv.pending--;
    log('DEBUG', `Conversation ${conv.id}: pending decremented to ${conv.pending}`);

    if (conv.pending < 0) {
        log('WARN', `Conversation ${conv.id}: pending went negative (${conv.pending}), resetting to 0`);
        conv.pending = 0;
    }

    return conv.pending === 0;
}

export async function enqueueInternalMessage(
    conversationId: string,
    fromAgent: string,
    targetAgent: string,
    message: string,
    originalData: { channel: string; sender: string; senderId?: string | null; messageId: string }
): Promise<void> {
    const messageId = `internal_${conversationId}_${targetAgent}_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
    await enqueueMessage({
        channel: originalData.channel,
        sender: originalData.sender,
        senderId: originalData.senderId ?? undefined,
        message,
        messageId,
        agent: targetAgent,
        conversationId,
        fromAgent,
    });
    log('INFO', `Enqueued internal message: @${fromAgent} → @${targetAgent}`);
}

export async function postToChatRoom(
    teamId: string,
    fromAgent: string,
    message: string,
    teamAgents: string[],
    originalData: { channel: string; sender: string; senderId?: string | null; messageId: string }
): Promise<number> {
    const chatMsg = `[Chat room #${teamId} — @${fromAgent}]:\n${message}`;
    const id = insertChatMessage(teamId, fromAgent, message);
    for (const agentId of teamAgents) {
        if (agentId === fromAgent) continue;
        await enqueueMessage({
            channel: 'chatroom',
            sender: originalData.sender,
            senderId: originalData.senderId ?? undefined,
            message: chatMsg,
            messageId: genId('chat'),
            agent: agentId,
            fromAgent,
        });
    }
    return id;
}

export function resolveTeamContext(
    agentId: string,
    isTeamRouted: boolean,
    teams: Record<string, TeamConfig>
): { teamId: string; team: TeamConfig } | null {
    if (isTeamRouted) {
        for (const [tid, t] of Object.entries(teams)) {
            if (t.leader_agent === agentId && t.agents.includes(agentId)) {
                return { teamId: tid, team: t };
            }
        }
    }
    return findTeamForAgent(agentId, teams);
}

async function saveSessionToOracle(conv: Conversation, agents: Record<string, AgentConfig>): Promise<void> {
    if (!SIDECAR_URL) return;

    try {
        const chatLines: string[] = [];
        chatLines.push(`# Team Conversation: ${conv.teamContext.team.name} (@${conv.teamContext.teamId})`);
        chatLines.push(`**Date:** ${new Date().toISOString()}`);
        chatLines.push(`**Channel:** ${conv.channel} | **Sender:** ${conv.sender}`);
        chatLines.push(`**Messages:** ${conv.totalMessages}`);
        chatLines.push('');
        chatLines.push('------');
        chatLines.push('');
        chatLines.push('## User Message');
        chatLines.push('');
        chatLines.push(conv.originalMessage);
        chatLines.push('');
        for (const step of conv.responses) {
            const stepAgent = agents[step.agentId];
            const stepLabel = stepAgent ? `${stepAgent.name} (@${step.agentId})` : `@${step.agentId}`;
            chatLines.push('------');
            chatLines.push('');
            chatLines.push(`## ${stepLabel}`);
            chatLines.push('');
            chatLines.push(step.response);
            chatLines.push('');
        }

        const history = chatLines.join('\n');

        await sidecarFetch('/api/sessions/save', {
            method: 'POST',
            body: JSON.stringify({
                teamId: conv.teamContext.teamId,
                agentId: conv.teamContext.team.leader_agent,
                sessionId: conv.id,
                history,
                channel: conv.channel,
                label: `${conv.teamContext.team.name} — ${new Date().toISOString()}`,
            }),
        });

        log('INFO', `Chat history saved to Oracle (team: ${conv.teamContext.teamId})`);
    } catch (e) {
        log('ERROR', `Failed to save chat history to Oracle: ${(e as Error).message}`);
    }
}

export async function completeConversation(
    conv: Conversation,
    agents: Record<string, AgentConfig>
): Promise<void> {
    log('INFO', `Conversation ${conv.id} complete — ${conv.responses.length} response(s), ${conv.totalMessages} total message(s)`);
    emitEvent('team_chain_end', {
        teamId: conv.teamContext.teamId,
        totalSteps: conv.responses.length,
        agents: conv.responses.map((s) => s.agentId),
    });

    let finalResponse: string;
    if (conv.responses.length === 1) {
        finalResponse = conv.responses[0].response;
    } else {
        finalResponse = conv.responses
            .map((step) => `@${step.agentId}: ${step.response}`)
            .join('\n\n------\n\n');
    }

    finalResponse = finalResponse.trim();
    const outboundFilesSet = new Set<string>(conv.files);
    collectFiles(finalResponse, outboundFilesSet);
    const outboundFiles = Array.from(outboundFilesSet);

    if (outboundFiles.length > 0) {
        finalResponse = finalResponse.replace(/\[send_file:\s*[^\]]+\]/g, '').trim();
    }

    finalResponse = stripBracketTags(stripBracketTags(finalResponse, '@'), '#').trim();

    await saveSessionToOracle(conv, agents);

    await streamResponse(finalResponse, {
        channel: conv.channel,
        sender: conv.sender,
        senderId: conv.senderId,
        messageId: conv.messageId,
        originalMessage: conv.originalMessage,
        agentId: conv.teamContext.team.leader_agent,
        existingFiles: outboundFiles,
        transform: (text) => stripBracketTags(stripBracketTags(text, '@'), '#').trim(),
    });

    log('INFO', `✓ Response ready [${conv.channel}] ${conv.sender} (${finalResponse.length} chars)`);
    emitEvent('response_ready', {
        channel: conv.channel,
        sender: conv.sender,
        responseLength: finalResponse.length,
        responseText: finalResponse,
        messageId: conv.messageId,
    });

    conversations.delete(conv.id);
    try {
        await deleteConversationState(conv);
    } catch (error) {
        log('WARN', `Conversation ${conv.id}: response delivered but state cleanup failed: ${(error as Error).message}`);
    }
}
