# Website Reader MCP

A small production-ready [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server built with Python and FastAPI. It exposes **Website Reader** tools over **Streamable HTTP** so an AI chat backend can fetch public webpages and receive cleaned, readable text.

## What it does

- Runs as a FastAPI app locally with uvicorn over HTTPS
- Deploys to Vercel as a Python serverless app (HTTPS provided by Vercel)
- Exposes MCP at `/mcp` (Streamable HTTP transport)
- Protects the MCP endpoint with a static API key
- Provides a small content extraction pipeline: raw fetch, Markdown, article extraction, metadata and summary preparation
- Caches successful URL fetches (opt-in via `CACHE_ENABLED`; in-memory or Redis backend) to avoid duplicate downloads across tools
- Rate-limits outbound URL fetches per client (opt-in via `RATE_LIMIT_ENABLED`; API key + IP composite key; in-memory or Redis backend)
- Validates DNS-resolved IPs across multiple resolvers and pins the connection to the vetted IP (on by default via `SSRF_DNS_VALIDATION_ENABLED`) to block SSRF and DNS rebinding

## Tools

The server exposes five MCP tools so the AI Chat backend can pick the right extraction layer for the task:

| Tool | Best for | Output |
| --- | --- | --- |
| `fetch_url` | Raw/simple fetch for debugging or fallback when you also need HTTP status, final URL and content type | Cleaned page text plus basic title/description from HTML |
| `fetch_markdown` | RAG ingestion and LLM context | Clean, LLM-friendly Markdown with headings, paragraphs, links, lists and code blocks; boilerplate removed |
| `extract_article` | Summaries, blog posts, news, docs and long-form pages | Main article text **and** Markdown, plus author, published date, description, site name and language |
| `extract_metadata` | Link previews and routing | Title, description, author, published date, site name, language, image and canonical URL (Open Graph, Twitter card, JSON-LD, meta tags) |
| `summarize_article` | Preparing an article summary without coupling the server to an LLM | Article text plus a ready-to-use `summary_prompt` the chat backend passes to its own model |

Markdown and article extraction are powered by [`trafilatura`](https://trafilatura.readthedocs.io/), with a lightweight BeautifulSoup fallback when trafilatura cannot find usable content. All tools return **structured error messages** instead of crashing on invalid URLs, timeouts, unsupported content types, empty pages or extraction failures.

### `summarize_article` and LLMs

`summarize_article` deliberately does **not** call OpenAI or any other model from inside the MCP server. It returns the extracted `text` together with a `summary_prompt` string. The AI Chat backend can send `summary_prompt` to its existing model pipeline to produce the actual summary. This keeps the MCP server provider-agnostic.

## Local setup

Requirements: Python 3.11+ and OpenSSL (for local dev certs)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set a real value for `MCP_API_KEY`.

## Environment variables

Copy `.env.example` to `.env`:

```env
MCP_API_KEY=change-me
APP_ENV=local
REQUEST_TIMEOUT_SECONDS=12
MAX_RESPONSE_CHARS=12000
MAX_HTML_BYTES=2000000
ALLOWED_SCHEMES=https,http

# MCP client host allowlist (see .env.example)
MCP_ALLOWED_HOSTS=
MCP_ALLOWED_ORIGINS=

# URL fetch cache (disabled by default)
CACHE_ENABLED=false
CACHE_BACKEND=memory
CACHE_TTL_SECONDS=300
CACHE_MAX_ENTRIES=100
REDIS_URL=

# Fetch rate limiting (disabled by default)
RATE_LIMIT_ENABLED=false
RATE_LIMIT_BACKEND=memory
RATE_LIMIT_PER_MINUTE=15
RATE_LIMIT_PER_HOUR=120

# DNS-based SSRF protection (enabled by default)
SSRF_DNS_VALIDATION_ENABLED=true
SSRF_DNS_TIMEOUT_SECONDS=2
SSRF_DNS_RESOLVERS=system,1.1.1.1,1.0.0.1,8.8.8.8,8.8.4.4

HOST=0.0.0.0
PORT=8001
DEV_HTTPS=true
SSL_CERTFILE=certs/localhost.pem
SSL_KEYFILE=certs/localhost-key.pem
```

The real `.env` file is gitignored and should not be committed.

### URL fetch cache

Caching is **off by default**. Set `CACHE_ENABLED=true` to cache successful HTTP responses at the fetch layer (shared by all tools).

| Variable | Default | Description |
| --- | --- | --- |
| `CACHE_ENABLED` | `false` | Enable or disable URL fetch caching |
| `CACHE_BACKEND` | `memory` | `memory` for local/single-instance; `redis` for shared cache on Vercel |
| `CACHE_TTL_SECONDS` | `300` | How long cached responses are kept |
| `CACHE_MAX_ENTRIES` | `100` | Max in-memory entries (ignored for Redis) |
| `REDIS_URL` | *(empty)* | Required when `CACHE_BACKEND=redis` (e.g. Upstash) |

Only successful fetches are cached; errors and validation failures are not. Tests run with caching disabled.

### Fetch rate limiting

Rate limiting is **off by default**. Set `RATE_LIMIT_ENABLED=true` to cap how many outbound URL fetches each client can perform in a time window. Limits apply at the fetch layer (shared by all tools) and only count **cache misses** — cached responses do not consume quota.

Each client is identified by a composite key of **hashed API key + client IP** (the raw key is never stored in Redis). On Vercel, the client IP is taken from `x-vercel-forwarded-for` or `x-forwarded-for` when present.

| Variable | Default | Description |
| --- | --- | --- |
| `RATE_LIMIT_ENABLED` | `false` | Enable or disable fetch rate limiting |
| `RATE_LIMIT_BACKEND` | `memory` | `memory` for local/single-instance; `redis` for shared limits on Vercel |
| `RATE_LIMIT_PER_MINUTE` | `15` | Max URL fetches per client per minute (burst protection) |
| `RATE_LIMIT_PER_HOUR` | `120` | Max URL fetches per client per hour (sustained cap) |
| `REDIS_URL` | *(empty)* | Required when `RATE_LIMIT_BACKEND=redis` (e.g. Upstash; can be shared with the URL cache) |

When a client exceeds a limit, tools return a structured error such as `Rate limit exceeded. Retry after N seconds.` instead of fetching the URL.

### DNS-based SSRF protection

Beyond the synchronous checks on URL schemes, blocked hostnames and IP literals, the server performs **DNS-level validation** before every fetch. This is **on by default** and defends against Server-Side Request Forgery (SSRF), including DNS-rebinding attacks.

How it works:

1. **Multi-resolver resolution.** The hostname is resolved concurrently across several independent resolvers — the system resolver plus public resolvers (Cloudflare `1.1.1.1`/`1.0.0.1` and Google `8.8.8.8`/`8.8.4.4`). The union of all A/AAAA answers is validated, so if **any** resolver returns a private/internal address the request is rejected.
2. **Hardened IP classification.** Resolved IPs are rejected if they fall into loopback, private (RFC1918), link-local (incl. the `169.254.169.254` cloud metadata address), carrier-grade NAT, multicast, reserved, benchmarking or test ranges. IPv6-embedded IPv4 (IPv4-mapped, NAT64, 6to4) is unwrapped and checked too, so a private target cannot be smuggled through an IPv6 encoding.
3. **Connection pinning (anti-rebinding).** The vetted IP is pinned for the actual connection, so the name cannot resolve to a safe IP during validation and to an internal IP a moment later. The original `Host` header and TLS SNI/certificate verification are preserved against the real hostname.
4. **Redirects are validated too.** Every redirect hop flows through the same validation and pinning.

**Very low per-query timeouts** are used and resolvers are queried concurrently, so total added latency is bounded by a single timeout window regardless of how many resolvers are configured.

| Variable | Default | Description |
| --- | --- | --- |
| `SSRF_DNS_VALIDATION_ENABLED` | `true` | Enable DNS resolution + IP validation + connection pinning |
| `SSRF_DNS_TIMEOUT_SECONDS` | `2` | Low per-query timeout; resolvers are queried concurrently |
| `SSRF_DNS_RESOLVERS` | `system,1.1.1.1,1.0.0.1,8.8.8.8,8.8.4.4` | Comma-separated resolvers. `system` uses `/etc/resolv.conf`; others are public resolver IPs |

When a host resolves to a blocked IP (or cannot be resolved), tools return a structured error instead of fetching the URL.

## Create local HTTPS certs

Local development uses self-signed TLS certs. Generate them once:

```bash
chmod +x scripts/dev.sh scripts/generate_dev_certs.sh
./scripts/generate_dev_certs.sh
```

This creates:

```text
certs/localhost.pem
certs/localhost-key.pem
```

These files are gitignored and are for local dev only.

You do not need to run this manually if you use `./scripts/dev.sh` — it auto-generates missing certs on first start.

### Optional: trusted local certs with mkcert

If you prefer browser- and client-trusted local certs instead of self-signed ones:

```bash
brew install mkcert
mkcert -install
mkdir -p certs
mkcert -cert-file certs/localhost.pem -key-file certs/localhost-key.pem localhost 127.0.0.1
```

Then use `./scripts/dev.sh` as usual.

## Run locally

```bash
./scripts/dev.sh
```

This starts uvicorn with reload on:

```text
https://localhost:8001
```

Useful overrides:

```bash
# HTTP instead of HTTPS
DEV_HTTPS=false ./scripts/dev.sh

# Bind only to localhost
HOST=127.0.0.1 ./scripts/dev.sh
```

## Health check

Self-signed certs require `-k` with curl:

```bash
curl -k https://localhost:8001/health
```

Example response:

```json
{
  "status": "ok",
  "service": "website-reader-mcp"
}
```

## MCP endpoint

The MCP Streamable HTTP endpoint is:

```text
https://localhost:8001/mcp
```

Authentication is required. Use either header:

```http
Authorization: Bearer <MCP_API_KEY>
```

or:

```http
X-API-Key: <MCP_API_KEY>
```

### Quick MCP test with curl

Initialize a session (stateless mode):

```bash
curl -k -sS -X POST "https://localhost:8001/mcp/" \
  -H "Authorization: Bearer change-me" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "capabilities": {},
      "clientInfo": {"name": "curl-test", "version": "0.1"}
    }
  }'
```

List tools:

```bash
curl -k -sS -X POST "https://localhost:8001/mcp/" \
  -H "Authorization: Bearer change-me" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list",
    "params": {}
  }'
```

Call `fetch_url`:

```bash
curl -k -sS -X POST "https://localhost:8001/mcp/" \
  -H "Authorization: Bearer change-me" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "fetch_url",
      "arguments": {"url": "https://example.com"}
    }
  }'
```

Replace `change-me` with your configured `MCP_API_KEY`.

### Call `fetch_markdown`

```bash
curl -k -sS -X POST "https://localhost:8001/mcp/" \
  -H "Authorization: Bearer change-me" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 4,
    "method": "tools/call",
    "params": {
      "name": "fetch_markdown",
      "arguments": {
        "url": "https://example.com/blog/my-article",
        "max_chars": 12000
      }
    }
  }'
```

Example structured output:

```json
{
  "url": "https://example.com/blog/my-article",
  "final_url": "https://example.com/blog/my-article",
  "title": "My Article",
  "markdown": "# My Article\n\nClean readable content...\n\n- point one\n- point two",
  "content_length": 842,
  "truncated": false,
  "extraction_method": "trafilatura",
  "error": null
}
```

### Call `extract_article`

```bash
curl -k -sS -X POST "https://localhost:8001/mcp/" \
  -H "Authorization: Bearer change-me" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 5,
    "method": "tools/call",
    "params": {
      "name": "extract_article",
      "arguments": {
        "url": "https://example.com/blog/my-article",
        "max_chars": 12000,
        "include_metadata": true,
        "include_markdown": true
      }
    }
  }'
```

Example structured output:

```json
{
  "url": "https://example.com/blog/my-article",
  "final_url": "https://example.com/blog/my-article",
  "title": "My Article",
  "author": "Jane Doe",
  "published_date": "2024-05-01T10:00:00Z",
  "description": "Short article description",
  "site_name": "Example",
  "language": "en",
  "text": "Clean readable article text...",
  "markdown": "# My Article\n\nClean readable article text...",
  "content_length": 8452,
  "truncated": false,
  "extraction_method": "trafilatura",
  "error": null
}
```

If extraction fails, the tool returns a structured error instead of crashing:

```json
{
  "url": "https://example.com/article",
  "final_url": "https://example.com/article",
  "error": "Could not extract readable article content from this page.",
  "text": null,
  "markdown": null,
  "extraction_method": "trafilatura"
}
```

### Call `extract_metadata`

```bash
curl -k -sS -X POST "https://localhost:8001/mcp/" \
  -H "Authorization: Bearer change-me" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 6,
    "method": "tools/call",
    "params": {
      "name": "extract_metadata",
      "arguments": {"url": "https://example.com/blog/my-article"}
    }
  }'
```

Example structured output:

```json
{
  "url": "https://example.com/blog/my-article",
  "final_url": "https://example.com/blog/my-article",
  "title": "My Article",
  "description": "Short article description",
  "author": "Jane Doe",
  "published_date": "2024-05-01T10:00:00Z",
  "site_name": "Example",
  "language": "en",
  "image": "https://example.com/images/cover.png",
  "canonical_url": "https://example.com/blog/my-article",
  "error": null
}
```

### Call `summarize_article`

```bash
curl -k -sS -X POST "https://localhost:8001/mcp/" \
  -H "Authorization: Bearer change-me" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 7,
    "method": "tools/call",
    "params": {
      "name": "summarize_article",
      "arguments": {
        "url": "https://example.com/blog/my-article",
        "max_chars": 12000,
        "max_words": 150
      }
    }
  }'
```

Example structured output:

```json
{
  "url": "https://example.com/blog/my-article",
  "final_url": "https://example.com/blog/my-article",
  "title": "My Article",
  "author": "Jane Doe",
  "published_date": "2024-05-01T10:00:00Z",
  "description": "Short article description",
  "text": "Clean readable article text...",
  "content_length": 8452,
  "truncated": false,
  "summary_prompt": "Summarize My Article in at most 150 words. Focus on the key points...\n\nArticle content:\nClean readable article text...",
  "extraction_method": "trafilatura",
  "error": null
}
```

The chat backend passes `summary_prompt` to its own LLM to generate the final summary.

You can also connect with the [MCP Inspector](https://github.com/modelcontextprotocol/inspector) using Streamable HTTP transport, the HTTPS URL above, and the same API key. You may need to accept the self-signed certificate in your client.

## Tests

```bash
pytest
```

## Vercel deployment

1. Push this repository to GitHub.
2. Import the project in Vercel.
3. Set environment variables in the Vercel dashboard (at minimum `MCP_API_KEY`; for production, also consider `RATE_LIMIT_ENABLED=true`, `RATE_LIMIT_BACKEND=redis`, and `REDIS_URL`).
4. Deploy.

The included `vercel.json` routes all requests to `app/main.py`, which exports the ASGI `app` object required by `@vercel/python`. Vercel terminates HTTPS for you in production; the local cert files are not used there.

After deployment, your MCP endpoint will be:

```text
https://<your-project>.vercel.app/mcp
```

Use the same API key headers as in local development.

## Security notes and limitations

- The MCP endpoint is protected by a single static API key. Rotate the key if it is exposed.
- Local HTTPS uses self-signed certificates. Do not reuse them outside local development.
- SSRF protection blocks localhost, common internal hostnames, and private/link-local/multicast IP literals before fetching.
- **DNS-based SSRF protection** (`SSRF_DNS_VALIDATION_ENABLED`, on by default): hostnames are resolved across multiple resolvers and rejected if any resolved IP is private/internal (including IPv6-embedded IPv4). The connection is then pinned to the vetted IP to block DNS rebinding, while preserving `Host` and TLS SNI. See [DNS-based SSRF protection](#dns-based-ssrf-protection).
- **MCP host allowlist** (`MCP_ALLOWED_HOSTS`): optional restriction on which `Host` header values may access `/mcp` (in addition to the API key). Leave empty to disable. Set `*` to allow any host, list exact hosts (`example.com`), subdomain wildcards (`*.example.com`), or port wildcards for local dev (`localhost:*`). Optional `MCP_ALLOWED_ORIGINS` restricts browser `Origin` headers when set.
- Only `http` and `https` URLs are allowed.
- Responses are capped by `MAX_HTML_BYTES` while downloading and `MAX_RESPONSE_CHARS` (or `max_chars`) for returned text.
- **Fetch rate limiting** (`RATE_LIMIT_ENABLED`): optional per-client caps on outbound URL fetches (API key hash + IP). Use Redis on Vercel so limits are shared across serverless instances. Cached responses do not count toward the limit.
- No JavaScript rendering: pages that require a browser will not be fully readable.
- No crawling: each tool fetches a single URL per call.

## Project structure

```text
app/
  main.py              FastAPI app, health routes, MCP mount
  config.py            Environment settings
  auth.py              API key and MCP host allowlist middleware
  schemas.py           Response models
  cache/               URL fetch cache (noop, memory, Redis backends)
  ratelimit/           Fetch rate limiting (noop, memory, Redis backends)
  ssrf/                DNS SSRF protection (IP rules, multi-resolver, pinning transport)
  tools/
    website_reader.py  MCP tool registration (all five tools)
  services/
    fetcher.py             HTTP fetch + URL validation (SSRF checks)
    host_allowlist.py      MCP_ALLOWED_HOSTS parsing and Host-header matching
    extractor.py           HTML to readable text (BeautifulSoup, used by fetch_url)
    markdown_extractor.py  HTML to Markdown (trafilatura + BeautifulSoup fallback)
    metadata_extractor.py  Metadata (Open Graph, Twitter, JSON-LD, meta tags)
    article_extractor.py   Article extraction and summary prompt preparation
scripts/
  generate_dev_certs.sh  Create local self-signed TLS certs
  dev.sh                 Run uvicorn with HTTPS locally
tests/
  test_fetcher.py
  test_ssrf.py
  test_cache.py
  test_ratelimit.py
  test_extractor.py
  test_extract_article.py
  test_markdown.py
  test_metadata.py
  test_summarize.py
```

## Next steps

Possible follow-ups:

- add logging and request IDs
- add an MCP client inside the existing AI Chat backend
- add tools for `search_web` and `read_url`

## License

Licensed under the MIT License. See [LICENSE](LICENSE).
