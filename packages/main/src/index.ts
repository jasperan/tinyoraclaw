#!/usr/bin/env node
/**
 * TinyAGI Queue Processor — Entry point.
 *
 * Initializes the SQLite queue, starts the API server, processes messages,
 * and manages lifecycle. This is the only file that should be run directly.
 */

import fs from 'fs';
import path from 'path';
import {
    MessageJobData,
    getSettings, getAgents, getTeams, LOG_FILE, FILES_DIR, TINYAGI_HOME,
    log, emitEvent,
    parseAgentRouting, getAgentResetFlag,
    invokeAgent, killAgentProcess,
    loadPlugins, runIncomingHooks,
    streamResponse,
    initQueueDb, getPendingAgents, claimAllPendingMessages,
    markProcessing, completeMessage, failMessage,
    recoverStaleMessages, pruneAckedResponses, pruneCompletedMessages,
    closeQueueDb, queueEvents,
    insertAgentMessage,
    startScheduler, stopScheduler,
} from '@tinyagi/core';
import { startApiServer } from '@tinyagi/server';
import { startChannels, stopChannels, startChannel, stopChannel, restartChannel, getChannelStatus } from './channels';
import { startHeartbeat, stopHeartbeat, getHeartbeatStatus } from './heartbeat';
import {
    groupChatroomMessages,
    conversations,
    MAX_CONVERSATION_MESSAGES,
    enqueueInternalMessage,
    completeConversation,
    withConversationLock,
    incrementPending,
    decrementPending,
    resolveTeamContext,
    postToChatRoom,
    extractTeammateMentions,
    extractChatRoomMessages,
    loadConversationState,
    persistConversationState,
} from '@tinyagi/teams';

// Ensure directories exist
[FILES_DIR, path.dirname(LOG_FILE)].forEach(dir => {
    if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
    }
});

// ── Message Processing ──────────────────────────────────────────────────────

async function processMessage(dbMsg: any): Promise<void> {
    const files: string[] = typeof dbMsg.files === 'string'
        ? (() => {
            try { return JSON.parse(dbMsg.files); } catch { return []; }
        })()
        : (Array.isArray(dbMsg.files) ? dbMsg.files : []);

    const data: MessageJobData = {
        channel: dbMsg.channel,
        sender: dbMsg.sender,
        senderId: dbMsg.sender_id,
        message: dbMsg.message,
        messageId: dbMsg.message_id,
        agent: dbMsg.agent ?? undefined,
        files: files.length > 0 ? files : undefined,
        conversationId: dbMsg.conversation_id ?? undefined,
        fromAgent: dbMsg.from_agent ?? undefined,
    };

    const { channel, sender, message: rawMessage, messageId, agent: preRoutedAgent } = data;
    const isInternal = !!data.conversationId;

    log('INFO', `Processing [${isInternal ? 'internal' : channel}] ${isInternal ? `@${data.fromAgent}→@${preRoutedAgent}` : `from ${sender}`}: ${rawMessage}`);

    const settings = getSettings();
    const agents = getAgents(settings);
    const teams = getTeams(settings);
    const workspacePath = settings?.workspace?.path || path.join(require('os').homedir(), 'tinyagi-workspace');

    // ── Route message to agent ──────────────────────────────────────────────
    let agentId: string;
    let message: string;
    let isTeamRouted = false;

    if (preRoutedAgent && agents[preRoutedAgent]) {
        agentId = preRoutedAgent;
        message = rawMessage;
    } else {
        const routing = parseAgentRouting(rawMessage, agents, teams);
        agentId = routing.agentId;
        message = routing.message;
        isTeamRouted = !!routing.isTeam;
    }

    if (!agents[agentId]) {
        agentId = 'tinyagi';
        message = rawMessage;
    }
    if (!agents[agentId]) {
        agentId = Object.keys(agents)[0];
    }

    const agent = agents[agentId];

    let teamContext: { teamId: string; team: any } | null = null;
    if (isInternal && data.conversationId) {
        let conv = conversations.get(data.conversationId);
        if (!conv) {
            conv = await loadConversationState(data.conversationId) || undefined;
            if (conv) conversations.set(conv.id, conv);
        }
        if (conv) {
            teamContext = conv.teamContext;
        } else {
            throw new Error(`Orphaned internal message for missing conversation ${data.conversationId}`);
        }
    } else {
        teamContext = resolveTeamContext(agentId, isTeamRouted, teams);
    }

    // ── Invoke agent ────────────────────────────────────────────────────────
    const agentResetFlag = getAgentResetFlag(agentId, workspacePath);
    const shouldReset = fs.existsSync(agentResetFlag);
    if (shouldReset) {
        fs.unlinkSync(agentResetFlag);
    }

    ({ text: message } = await runIncomingHooks(message, { channel, sender, messageId, originalMessage: rawMessage }));

    if (isInternal && data.conversationId) {
        const conv = conversations.get(data.conversationId);
        if (conv) {
            const othersPending = conv.pending - 1;
            if (othersPending > 0) {
                message += `\n\n------\n\n[${othersPending} other teammate response(s) are still being processed and will be delivered when ready. Do not re-mention teammates who haven't responded yet.]`;
            }
        }
    }

    emitEvent('agent:invoke', { agentId, agentName: agent.name, fromAgent: data.fromAgent || null });
    let response: string;
    try {
        response = await invokeAgent(agent, agentId, message, workspacePath, shouldReset, agents, teams, (text) => {
            log('INFO', `Agent ${agentId}: ${text}`);
            insertAgentMessage({ agentId, role: 'assistant', channel, sender: agentId, messageId, content: text });
            emitEvent('agent:progress', { agentId, agentName: agent.name, text, messageId });
            if (!teamContext) {
                void sendDirectResponse(text, {
                    channel, sender, senderId: data.senderId,
                    messageId, originalMessage: rawMessage, agentId,
                });
            }
        });
    } catch (error) {
        const provider = agent.provider || 'anthropic';
        const providerLabel = provider === 'openai' ? 'Codex' : provider === 'opencode' ? 'OpenCode' : 'Claude';
        log('ERROR', `${providerLabel} error (agent: ${agentId}): ${(error as Error).message}`);
        response = "Sorry, I encountered an error processing your request. Please check the queue logs.";
        const msgSender = isInternal ? data.fromAgent! : sender;
        insertAgentMessage({ agentId, role: 'assistant', channel, sender: msgSender, messageId, content: response });
        if (!teamContext) {
            await sendDirectResponse(response, {
                channel, sender, senderId: data.senderId,
                messageId, originalMessage: rawMessage, agentId,
            });
        }
    }

    emitEvent('agent:response', {
        agentId, agentName: agent.name, role: 'assistant',
        channel, sender, messageId,
        content: response,
        isTeamMessage: isInternal || isTeamRouted,
    });

    if (!teamContext) {
        return;
    }

    const chatRoomMsgs = extractChatRoomMessages(response, agentId, teams);
    if (chatRoomMsgs.length > 0) {
        log('INFO', `Chat room broadcasts from @${agentId}: ${chatRoomMsgs.map((m) => `#${m.teamId}`).join(', ')}`);
    }
    for (const crMsg of chatRoomMsgs) {
        await postToChatRoom(crMsg.teamId, agentId, crMsg.message, teams[crMsg.teamId].agents, {
            channel,
            sender,
            senderId: data.senderId,
            messageId,
        });
    }

    const conversationId = data.conversationId || messageId;

    await withConversationLock(conversationId, async () => {
        let conv = conversations.get(conversationId);
        if (!conv) {
            conv = await loadConversationState(conversationId) || undefined;
            if (conv) {
                conversations.set(conv.id, conv);
                log('INFO', `Conversation restored from Oracle state: ${conv.id}`);
            }
        }

        if (!conv) {
            conv = {
                id: conversationId,
                channel,
                sender,
                senderId: data.senderId,
                originalMessage: rawMessage,
                messageId,
                pending: 1,
                responses: [],
                files: new Set<string>(),
                totalMessages: 0,
                maxMessages: MAX_CONVERSATION_MESSAGES,
                teamContext,
                startTime: Date.now(),
                outgoingMentions: new Map<string, number>(),
            };
            conversations.set(conversationId, conv);
            log('INFO', `Conversation started: ${conversationId} (team: ${teamContext.team.name})`);
            emitEvent('team_chain_start', {
                teamId: teamContext.teamId,
                teamName: teamContext.team.name,
                agents: teamContext.team.agents,
                leader: teamContext.team.leader_agent,
            });
        }

        conv.responses.push({ agentId, response });
        conv.totalMessages++;

        if (data.files) {
            for (const file of data.files) conv.files.add(file);
        }

        await persistConversationState(conv);

        const teammateMentions = extractTeammateMentions(response, agentId, conv.teamContext.teamId, teams, agents);
        if (teammateMentions.length > 0 && conv.totalMessages < conv.maxMessages) {
            incrementPending(conv, teammateMentions.length);
            conv.outgoingMentions.set(agentId, teammateMentions.length);
            await persistConversationState(conv);
            for (const mention of teammateMentions) {
                log('INFO', `@${agentId} → @${mention.teammateId}`);
                emitEvent('chain_handoff', { teamId: conv.teamContext.teamId, fromAgent: agentId, toAgent: mention.teammateId });

                const internalMsg = `[Message from teammate @${agentId}]:\n${mention.message}`;
                await enqueueInternalMessage(conv.id, agentId, mention.teammateId, internalMsg, {
                    channel: data.channel,
                    sender: data.sender,
                    senderId: data.senderId,
                    messageId: data.messageId,
                });
            }
        } else if (teammateMentions.length > 0) {
            log('WARN', `Conversation ${conv.id} hit max messages (${conv.maxMessages}) — not enqueuing further mentions`);
        }

        const shouldComplete = decrementPending(conv);
        if (shouldComplete) {
            await completeConversation(conv, agents);
        } else {
            await persistConversationState(conv);
            log('INFO', `Conversation ${conv.id}: ${conv.pending} branch(es) still pending`);
        }
    });
}

// ── Helpers ──────────────────────────────────────────────────────────────────

async function sendDirectResponse(
    response: string,
    ctx: { channel: string; sender: string; senderId?: string | null; messageId: string; originalMessage: string; agentId: string }
): Promise<void> {
    const signed = `${response}\n\n- [${ctx.agentId}]`;
    await streamResponse(signed, {
        channel: ctx.channel,
        sender: ctx.sender,
        senderId: ctx.senderId ?? undefined,
        messageId: ctx.messageId,
        originalMessage: ctx.originalMessage,
        agentId: ctx.agentId,
    });
}

// ── Queue Processing ────────────────────────────────────────────────────────

const agentChains = new Map<string, Promise<void>>();

async function processQueue(): Promise<void> {
    const pendingAgents = await getPendingAgents();
    if (pendingAgents.length === 0) return;

    for (const agentId of pendingAgents) {
        const messages = await claimAllPendingMessages(agentId);
        if (messages.length === 0) continue;

        const currentChain = agentChains.get(agentId) || Promise.resolve();
        // .catch() prevents a rejected chain from blocking subsequent messages
        const newChain = currentChain.catch(() => {}).then(async () => {
            const { messages: groupedMessages, messageIds } = groupChatroomMessages(messages);
            for (let i = 0; i < groupedMessages.length; i++) {
                const msg = groupedMessages[i];
                const ids = messageIds[i];
                try {
                    for (const id of ids) await markProcessing(id);
                    await processMessage(msg);
                    for (const id of ids) {
                        await completeMessage(id);
                    }
                } catch (error) {
                    log('ERROR', `Failed to process message ${msg.id}: ${(error as Error).message}`);
                    for (const id of ids) {
                        await failMessage(id, (error as Error).message);
                    }
                }
            }
        });
        agentChains.set(agentId, newChain);
        newChain.finally(() => {
            if (agentChains.get(agentId) === newChain) {
                agentChains.delete(agentId);
            }
        });
    }
}

function logAgentConfig(): void {
    const settings = getSettings();
    const agents = getAgents(settings);
    const teams = getTeams(settings);

    const agentCount = Object.keys(agents).length;
    log('INFO', `Loaded ${agentCount} agent(s):`);
    for (const [id, agent] of Object.entries(agents)) {
        log('INFO', `  ${id}: ${agent.name} [${agent.provider}/${agent.model}] cwd=${agent.working_directory}`);
    }

    const teamCount = Object.keys(teams).length;
    if (teamCount > 0) {
        log('INFO', `Loaded ${teamCount} team(s):`);
        for (const [id, team] of Object.entries(teams)) {
            log('INFO', `  ${id}: ${team.name} [agents: ${team.agents.join(', ')}] leader=${team.leader_agent}`);
        }
    }
}

function runLogged(label: string, task: () => Promise<unknown>): void {
    void Promise.resolve()
        .then(task)
        .catch((error) => {
            log('ERROR', `${label} failed: ${error instanceof Error ? error.message : String(error)}`);
        });
}

// ─── Start ──────────────────────────────────────────────────────────────────

initQueueDb();

// Write PID file so the CLI can find this process
fs.writeFileSync(path.join(TINYAGI_HOME, 'tinyagi.pid'), String(process.pid));

// Recover any messages left in 'processing' from a previous run — they're
// guaranteed stale because the process just restarted.
runLogged('Startup stale recovery', async () => {
    const startupRecovered = await recoverStaleMessages(0);
    if (startupRecovered > 0) {
        log('INFO', `Startup: recovered ${startupRecovered} in-flight message(s) from previous run`);
    }
});

const apiServer = startApiServer({
    startChannel,
    stopChannel,
    restartChannel,
    getChannelStatus,
    getHeartbeatStatus,
    restart() {
        log('INFO', 'Restart requested via API');
        shutdown(75);
    },
});

// Event-driven: process queue when a new message arrives
queueEvents.on('message:enqueued', () => {
    runLogged('Queue processing (message:enqueued)', () => processQueue());
});

// When user manually kills an agent session, clear its promise chain
queueEvents.on('agent:killed', ({ agentId }: { agentId: string }) => {
    agentChains.delete(agentId);
    log('INFO', `Cleared agent chain for ${agentId}`);
});

// Also poll periodically in case events are missed
const pollInterval = setInterval(() => {
    runLogged('Queue polling', () => processQueue());
}, 5000);

// Periodic maintenance (prune old completed/acked records)
const maintenanceInterval = setInterval(() => {
    runLogged('Prune acked responses', () => pruneAckedResponses());
    runLogged('Prune completed messages', () => pruneCompletedMessages());
}, 60 * 1000);

// Load plugins
(async () => {
    await loadPlugins();
})();

// Start in-process cron scheduler
startScheduler();

// Start channels and heartbeat
startChannels();
startHeartbeat();

log('INFO', 'Queue processor started (TinyOraClaw hybrid queue: Oracle sidecar + local UI state)');
logAgentConfig();
log('INFO', `Agents: ${Object.keys(getAgents(getSettings())).join(', ')}, Teams: ${Object.keys(getTeams(getSettings())).join(', ')}`);

// Graceful shutdown. Exit code 75 signals "restart" to the Docker entrypoint loop.
function shutdown(exitCode = 0): void {
    log('INFO', exitCode === 75 ? 'Restarting queue processor...' : 'Shutting down queue processor...');
    stopHeartbeat();
    stopChannels();
    stopScheduler();
    clearInterval(pollInterval);
    clearInterval(maintenanceInterval);
    apiServer.close();
    closeQueueDb();
    // Clean up PID file on normal shutdown (not restart)
    if (exitCode !== 75) {
        try { fs.unlinkSync(path.join(TINYAGI_HOME, 'tinyagi.pid')); } catch {}
    }
    process.exit(exitCode);
}

process.on('SIGINT', () => { shutdown(); });
process.on('SIGTERM', () => { shutdown(); });
