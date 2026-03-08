import fs from 'fs';
import { Hono } from 'hono';
import { Settings } from '../../lib/types';
import { SETTINGS_FILE, getSettings } from '../../lib/config';
import { log } from '../../lib/logging';

/** Read, mutate, and persist settings.json atomically. */
export function mutateSettings(fn: (settings: Settings) => void): Settings {
    const settings = getSettings();
    fn(settings);
    fs.writeFileSync(SETTINGS_FILE, JSON.stringify(settings, null, 2) + '\n');
    return settings;
}

/** Strip sensitive values (tokens, keys) from settings before returning via API. */
function redactSecrets(settings: Settings): Record<string, unknown> {
    const redacted = JSON.parse(JSON.stringify(settings));
    // Redact channel bot tokens
    if (redacted.channels) {
        for (const channel of Object.values(redacted.channels) as Record<string, unknown>[]) {
            if (channel && typeof channel === 'object') {
                for (const key of Object.keys(channel)) {
                    if (/token|key|secret|password/i.test(key)) {
                        channel[key] = '***REDACTED***';
                    }
                }
            }
        }
    }
    return redacted;
}

/** Keys that must NOT be set via the PUT API (require env vars or direct file edit). */
const PROTECTED_KEYS = new Set(['channels']);

const app = new Hono();

// GET /api/settings — returns settings with secrets redacted
app.get('/api/settings', (c) => {
    return c.json(redactSecrets(getSettings()));
});

// PUT /api/settings — shallow merge with protected key validation
app.put('/api/settings', async (c) => {
    const body = await c.req.json();
    if (typeof body !== 'object' || body === null || Array.isArray(body)) {
        return c.json({ error: 'Request body must be a JSON object' }, 400);
    }
    // Block writes to protected keys
    for (const key of Object.keys(body)) {
        if (PROTECTED_KEYS.has(key)) {
            return c.json({ error: `Cannot modify protected key: ${key}` }, 403);
        }
    }
    const current = getSettings();
    const merged = { ...current, ...body } as Settings;
    fs.writeFileSync(SETTINGS_FILE, JSON.stringify(merged, null, 2) + '\n');
    log('INFO', '[API] Settings updated');
    return c.json({ ok: true, settings: redactSecrets(merged) });
});

export default app;
