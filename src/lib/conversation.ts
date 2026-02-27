import { Conversation } from './types';
import { getSettings, getAgents } from './config';
import { log, emitEvent } from './logging';
import { enqueueMessage, enqueueResponse } from './db';
import { handleLongResponse, collectFiles } from './response';

// ── Sidecar config (for session saving) ─────────────────────────────────────

const SIDECAR_URL = (process.env.TINYORACLAW_SERVICE_URL || 'http://localhost:8100').replace(/\/$/, '');
const SIDECAR_TOKEN = process.env.TINYORACLAW_SERVICE_TOKEN || '';

function sidecarHeaders(): Record<string, string> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (SIDECAR_TOKEN) {
        headers['Authorization'] = `Bearer ${SIDECAR_TOKEN}`;
    }
    return headers;
}

// Active conversations — tracks in-flight team message passing
export const conversations = new Map<string, Conversation>();

export const MAX_CONVERSATION_MESSAGES = 50;

// Per-conversation locks to prevent race conditions
const conversationLocks = new Map<string, Promise<void>>();

/**
 * Execute a function with exclusive access to a conversation.
 * This prevents race conditions when multiple agents complete simultaneously.
 */
export async function withConversationLock<T>(
    convId: string,
    fn: () => Promise<T>
): Promise<T> {
    const currentLock = conversationLocks.get(convId) || Promise.resolve();

    let resolveLock: () => void;
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

/**
 * Safely increment the pending counter for a conversation.
 */
export function incrementPending(conv: Conversation, count: number): void {
    conv.pending += count;
    log('DEBUG', `Conversation ${conv.id}: pending incremented to ${conv.pending} (+${count})`);
}

/**
 * Safely decrement the pending counter and check if conversation should complete.
 * Returns true if pending reached 0 and conversation should complete.
 */
export function decrementPending(conv: Conversation): boolean {
    conv.pending--;
    log('DEBUG', `Conversation ${conv.id}: pending decremented to ${conv.pending}`);

    if (conv.pending < 0) {
        log('WARN', `Conversation ${conv.id}: pending went negative (${conv.pending}), resetting to 0`);
        conv.pending = 0;
    }

    return conv.pending === 0;
}

/**
 * Enqueue an internal (agent-to-agent) message into the Oracle queue via sidecar.
 */
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

/**
 * Save chat history to Oracle sessions via sidecar (replaces filesystem .md files).
 */
async function saveSessionToOracle(conv: Conversation, agents: Record<string, any>): Promise<void> {
    try {
        const chatLines: string[] = [];
        chatLines.push(`# Team Conversation: ${conv.teamContext.team.name} (@${conv.teamContext.teamId})`);
        chatLines.push(`**Date:** ${new Date().toISOString()}`);
        chatLines.push(`**Channel:** ${conv.channel} | **Sender:** ${conv.sender}`);
        chatLines.push(`**Messages:** ${conv.totalMessages}`);
        chatLines.push('');
        chatLines.push('------');
        chatLines.push('');
        chatLines.push(`## User Message`);
        chatLines.push('');
        chatLines.push(conv.originalMessage);
        chatLines.push('');
        for (let i = 0; i < conv.responses.length; i++) {
            const step = conv.responses[i];
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

        await fetch(`${SIDECAR_URL}/api/sessions/save`, {
            method: 'POST',
            headers: sidecarHeaders(),
            body: JSON.stringify({
                teamId: conv.teamContext.teamId,
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

/**
 * Complete a conversation: aggregate responses, write to outgoing queue, save chat history.
 */
export async function completeConversation(conv: Conversation): Promise<void> {
    const settings = getSettings();
    const agents = getAgents(settings);

    log('INFO', `Conversation ${conv.id} complete — ${conv.responses.length} response(s), ${conv.totalMessages} total message(s)`);
    emitEvent('team_chain_end', {
        teamId: conv.teamContext.teamId,
        totalSteps: conv.responses.length,
        agents: conv.responses.map(s => s.agentId),
    });

    // Aggregate responses
    let finalResponse: string;
    if (conv.responses.length === 1) {
        finalResponse = conv.responses[0].response;
    } else {
        finalResponse = conv.responses
            .map(step => `@${step.agentId}: ${step.response}`)
            .join('\n\n------\n\n');
    }

    // Save chat history to Oracle (non-blocking — don't fail the conversation)
    saveSessionToOracle(conv, agents).catch(e => {
        log('ERROR', `Background session save failed: ${(e as Error).message}`);
    });

    // Detect file references
    finalResponse = finalResponse.trim();
    const outboundFilesSet = new Set<string>(conv.files);
    collectFiles(finalResponse, outboundFilesSet);
    const outboundFiles = Array.from(outboundFilesSet);

    // Remove [send_file: ...] tags
    if (outboundFiles.length > 0) {
        finalResponse = finalResponse.replace(/\[send_file:\s*[^\]]+\]/g, '').trim();
    }

    // Remove [@agent: ...] tags from final response
    finalResponse = finalResponse.replace(/\[@\S+?:\s*[\s\S]*?\]/g, '').trim();

    // Handle long responses — send as file attachment
    const { message: responseMessage, files: allFiles } = handleLongResponse(finalResponse, outboundFiles);

    // Write to outgoing queue
    await enqueueResponse({
        channel: conv.channel,
        sender: conv.sender,
        message: responseMessage,
        originalMessage: conv.originalMessage,
        messageId: conv.messageId,
        files: allFiles.length > 0 ? allFiles : undefined,
    });

    log('INFO', `✓ Response ready [${conv.channel}] ${conv.sender} (${finalResponse.length} chars)`);
    emitEvent('response_ready', { channel: conv.channel, sender: conv.sender, responseLength: finalResponse.length, responseText: finalResponse, messageId: conv.messageId });

    // Clean up
    conversations.delete(conv.id);
}
