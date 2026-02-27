import { Hono } from 'hono';

const SIDECAR_URL = (process.env.TINYORACLAW_SERVICE_URL || 'http://localhost:8100').replace(/\/$/, '');
const SIDECAR_TOKEN = process.env.TINYORACLAW_SERVICE_TOKEN || '';

function sidecarHeaders(): Record<string, string> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (SIDECAR_TOKEN) {
        headers['Authorization'] = `Bearer ${SIDECAR_TOKEN}`;
    }
    return headers;
}

const app = new Hono();

// GET /api/chats — list all sessions from Oracle (replaces filesystem scan)
app.get('/api/chats', async (c) => {
    try {
        const res = await fetch(`${SIDECAR_URL}/api/sessions`, {
            headers: sidecarHeaders(),
        });

        if (!res.ok) {
            return c.json([]);
        }

        const data = await res.json() as { sessions?: any[] };
        const sessions = data.sessions || [];

        // Map to the format TinyOffice expects
        return c.json(sessions.map((s: any) => ({
            teamId: s.team_id || s.teamId || 'unknown',
            file: s.session_key || s.label || 'session',
            time: s.created_at ? new Date(s.created_at).getTime() : Date.now(),
            sessionKey: s.session_key,
            label: s.label,
            channel: s.channel,
        })));
    } catch {
        return c.json([]);
    }
});

// GET /api/chats/:teamId — get sessions for a specific team
app.get('/api/chats/:teamId', async (c) => {
    try {
        const teamId = c.req.param('teamId');
        const res = await fetch(`${SIDECAR_URL}/api/sessions/${encodeURIComponent(teamId)}`, {
            headers: sidecarHeaders(),
        });

        if (!res.ok) {
            return c.json([]);
        }

        const data = await res.json() as { sessions?: any[] };
        return c.json(data.sessions || []);
    } catch {
        return c.json([]);
    }
});

export default app;
