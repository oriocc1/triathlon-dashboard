/**
 * Cloudflare Worker — Claude API proxy for the triathlon dashboard.
 *
 * Deploy steps:
 *   1. Create a free Cloudflare account at cloudflare.com
 *   2. Go to Workers & Pages → Create → Worker
 *   3. Paste this file, click Deploy
 *   4. Go to your Worker → Settings → Variables → Add Secret:
 *      Name: CLAUDE_API_KEY  Value: your Anthropic API key (sk-ant-...)
 *   5. Copy the Worker URL (e.g. https://dashboard-coach.YOUR.workers.dev)
 *   6. Paste it into CLAUDE_PROXY_URL in index.html
 *
 * The worker keeps your API key secret — it never appears in the browser.
 */

const ALLOWED_ORIGIN = '*'; // Restrict to your GitHub Pages domain if you want, e.g.:
// const ALLOWED_ORIGIN = 'https://yourusername.github.io';

export default {
  async fetch(request, env) {
    const corsHeaders = {
      'Access-Control-Allow-Origin': ALLOWED_ORIGIN,
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    };

    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders });
    }

    if (request.method !== 'POST') {
      return new Response('Method not allowed', { status: 405, headers: corsHeaders });
    }

    if (!env.CLAUDE_API_KEY) {
      return new Response(
        JSON.stringify({ error: { message: 'CLAUDE_API_KEY secret not set in Cloudflare Worker' } }),
        { status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      );
    }

    try {
      const body = await request.json();

      const upstream = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-api-key': env.CLAUDE_API_KEY,
          'anthropic-version': '2023-06-01',
        },
        body: JSON.stringify(body),
      });

      const data = await upstream.json();

      return new Response(JSON.stringify(data), {
        status: upstream.status,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      });
    } catch (err) {
      return new Response(
        JSON.stringify({ error: { message: err.message } }),
        { status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      );
    }
  },
};
