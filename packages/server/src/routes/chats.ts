import fs from 'fs';
import path from 'path';
import { Hono } from 'hono';
import { CHATS_DIR } from '@tinyagi/core';

const app = new Hono();
const SIDECAR_URL = (process.env.TINYORACLAW_SERVICE_URL || '').replace(/\/$/, '');
const SIDECAR_TOKEN = process.env.TINYORACLAW_SERVICE_TOKEN || '';

// GET /api/chats
app.get('/api/chats', async (c) => {
    if (SIDECAR_URL) {
        const headers: Record<string, string> = {};
        if (SIDECAR_TOKEN) headers['Authorization'] = `Bearer ${SIDECAR_TOKEN}`;

        try {
            const res = await fetch(`${SIDECAR_URL}/api/sessions`, { headers });
            if (res.ok) {
                const body = await res.json() as { sessions?: any[] };
                const chats = (body.sessions || []).map((s: any) => ({
                    teamId: s.team_id,
                    file: s.label || s.session_key,
                    time: s.updated_at,
                }));
                chats.sort((a, b) => b.time - a.time);
                return c.json(chats);
            }
        } catch (error) {
            console.warn(`Failed to fetch sidecar sessions from ${SIDECAR_URL}: ${error instanceof Error ? error.message : String(error)}`);
        }
    }

    const chats: { teamId: string; file: string; time: number }[] = [];
    if (fs.existsSync(CHATS_DIR)) {
        for (const teamDir of fs.readdirSync(CHATS_DIR)) {
            const teamPath = path.join(CHATS_DIR, teamDir);
            if (fs.statSync(teamPath).isDirectory()) {
                for (const file of fs.readdirSync(teamPath).filter(f => f.endsWith('.md'))) {
                    const time = fs.statSync(path.join(teamPath, file)).mtimeMs;
                    chats.push({ teamId: teamDir, file, time });
                }
            }
        }
    }
    chats.sort((a, b) => b.time - a.time);
    return c.json(chats);
});

export default app;
