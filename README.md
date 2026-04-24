# Payback

A project list where every entry is forced into a target, a strategy, an alternatives section, costs, and benefits, then ranked by payback period in months. The discipline of filling in those fields is most of the value; the ranking is the visible mechanism that makes you do it.

In-app docs at `/docs` — this README is just enough to run it.

## What it is

- Projects with: `target`, `strategy`, `pros_cons`, `alternatives`, `notes`, costs and benefits as line items
- Costs/benefits in dollars (`once` / `pcm` / `py`) or hours (`hours` / `hours_pcm`, multiplied by your configured hourly rate)
- Ranked by payback period: `upfront_cost / (monthly_benefit − monthly_recurring_cost)`
- Statuses: `active` / `done` / `dropped` / `archived` (soft delete; permanent delete requires archived first)
- Single-user via oauth2-proxy (Google by default); supports read-only sharing between users
- REST API with per-user keys, mirrors the web UI

## Stack

Flask + SQLite + HTMX + waitress, all running in one ~128MB container behind an oauth2-proxy sidecar. Frontend is server-rendered Jinja with a small amount of vanilla JS.

## Run it

```sh
cp oauth2-proxy.cfg.example oauth2-proxy.cfg
cp allowed-emails.txt.example allowed-emails.txt
# edit both: real Google OAuth client_id/secret, generated cookie_secret, your email(s)

docker compose up -d --build
# app on 127.0.0.1:8104 (Flask), oauth2-proxy on 127.0.0.1:4181
```

Put nginx (or any reverse proxy) in front of `127.0.0.1:4181` with TLS. The Flask container is not exposed publicly — all traffic must go through oauth2-proxy.

For local development without auth, just run `python app.py` and the app falls back to a `dev` user.

## Configuration

- `SERVICE_PORT` env var sets the Flask container's host-side port (default `8104`)
- `instance/payback.db` is the SQLite database — back it up
- Hourly rate is per-user, set on the in-app `/settings` page

## Lineage

Forked from a private internal tool (PBP) used at work for engineering project prioritisation. Same shape; this version generalises to personal-life decisions by letting time costs convert via a configurable hourly rate, and by encouraging willingness-to-pay framing for non-monetary benefits. See `/docs` in-app for techniques and worked examples.
