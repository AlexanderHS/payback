# Payback

A personal-life decision journal. Each entry is forced into a target, a strategy, an alternatives section, costs and benefits, then ranked by payback period in months. The discipline of filling in those fields is most of the value; the ranking is the visible mechanism that makes you do it.

Live at https://payback.2ho.me. The root URL serves a public marketing landing page; the app proper is at `/dashboard` and requires Google sign-in.

In-app framework reference at `/docs` (public). Contributor / AI-tooling onboarding lives in [`CLAUDE.md`](CLAUDE.md). This README is just enough to run it.

## What it is

- Projects with: `target`, `strategy`, `pros_cons`, `alternatives`, `notes`, costs and benefits as line items
- Costs/benefits in dollars (`once` / `pcm` / `py`) or hours (`hours` / `hours_pcm`, multiplied by your configured hourly rate)
- Ranked by payback period: `upfront_cost / (monthly_benefit − monthly_recurring_cost)`
- Statuses: `active` / `done` / `dropped` / `archived` (soft delete; permanent delete requires archived first)
- Open Google sign-in by default; per-user data isolation; read-only sharing between users
- REST API with per-user keys, mirrors the web UI

## Stack

Flask + SQLite + HTMX + waitress, all running in one ~128MB container behind an oauth2-proxy sidecar. Frontend is server-rendered Jinja with a small amount of vanilla JS.

## Run it

```sh
cp oauth2-proxy.cfg.example oauth2-proxy.cfg
cp .env.example .env
# edit:
#   oauth2-proxy.cfg     real Google OAuth client_id/secret, cookie_secret
#   .env                 SECRET_KEY (CSRF tokens), ANALYTICS_TOKEN (admin endpoint)

docker compose up -d --build
# app on 127.0.0.1:8104 (Flask), oauth2-proxy on 127.0.0.1:4181
```

By default any Google account can sign in. Each user only sees their own projects. To restrict to a specific list of emails, see the comments in `oauth2-proxy.cfg.example`.

Put nginx (or any reverse proxy) in front of `127.0.0.1:4181` with TLS. The Flask container is not exposed publicly — all traffic must go through oauth2-proxy.

For local development without auth, just run `python app.py` and the app falls back to a `dev` user.

## Configuration

- `SERVICE_PORT` env var sets the Flask container's host-side port (default `8104`)
- `instance/payback.db` is the SQLite database — back it up
- Hourly rate is per-user (default `$80`, set on the in-app `/settings` page); time-based costs and benefits are multiplied by it
- Per-user caps: max 1000 projects, ~5–10k chars per text field, 100 line items per type. See `db.py` for exact values.

## Analytics

`GET /api/analytics` returns aggregate, privacy-preserving stats (user counts, project counts, distribution buckets, storage size). No emails or project content. Authenticated by `ANALYTICS_TOKEN` (set in `.env`), separate from per-user API keys — there is no admin user tier in the app itself.

```sh
curl -H "Authorization: Bearer $ANALYTICS_TOKEN" https://your.domain/api/analytics
```

## Lineage

Forked from a private internal tool (PBP) used at work for engineering project prioritisation. Same shape; this version generalises to personal-life decisions by letting time costs convert via a configurable hourly rate, and by encouraging willingness-to-pay framing for non-monetary benefits. See `/docs` in-app for techniques and worked examples.
