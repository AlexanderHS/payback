# CLAUDE.md

Onboarding for AI tooling (Claude Code, Codex, etc.) and human contributors picking up this repo. Read this before suggesting changes.

## What this is

Payback is a personal-life decision journal. Each entry has a target, a strategy, an alternatives section, costs and benefits; the app computes a payback period and ranks the list. The discipline of filling in the fields is most of the value — the ranking is the visible mechanism that makes you do it.

Live: https://payback.2ho.me. The root URL serves a public marketing landing page; the app proper is at `/dashboard` and requires Google sign-in.

## Stack & layout

Flask + SQLite + HTMX + waitress, all in one ~128MB container behind an oauth2-proxy sidecar. Server-rendered Jinja templates with a small amount of vanilla JS. nginx (TLS via certbot) terminates in front of oauth2-proxy on the VPS.

Key files:

- `app.py` — all routes
- `db.py` — schema, queries, validation
- `project_templates.py` — worked-example seed data for the dashboard's empty-state prompt chips (also referenced by the landing page's vegetable-garden example for visual consistency)
- `templates/` — Jinja templates; `landing.html` is standalone (does not extend `base.html`), `privacy.html` and the rest do extend `base.html`
- `static/css/styles.css` — main app styles
- `static/css/landing.css` — landing-page-only styles (editorial)
- `instance/payback.db` — SQLite, gitignored

## Run it

Local dev (no oauth2-proxy, falls back to a `dev` user):

```sh
python app.py
```

Full prod-equivalent (after copying `oauth2-proxy.cfg.example` and `.env.example`):

```sh
docker compose up -d --build
```

## Deploy

Live VPS at `72.11.130.174` (RackNerd), app dir `/opt/payback`. Standard deploy:

```sh
ssh root@72.11.130.174 'cd /opt/payback && git pull && docker compose up -d --build'
```

If you change `oauth2-proxy.cfg`, you also need `docker compose restart oauth2-proxy` — `up -d --build` does not recreate the proxy container when only the mounted cfg has changed (compose definition unchanged → compose sees no work to do).

The real `/opt/payback/oauth2-proxy.cfg`, `/opt/payback/.env`, and `/opt/payback/allowed-emails.txt` live on the VPS only. The repo only contains `.example` files. **When you change `oauth2-proxy.cfg.example` to add a public route or similar, you also need to mirror the change to the live cfg on the VPS.**

## What's deliberately NOT in scope

Don't propose these without a concrete trigger:

- **Currency picker.** `$` reads as universal-enough until someone in USD specifically asks for it. AUD label was dropped from the settings page for the same reason.
- **Client-side encryption / E2EE.** Incompatible with the AI-agent-via-API workflow (server has to read plaintext during requests). Privacy is operational, not cryptographic — see `/privacy` and the privacy section of the landing page.
- **Manual PBP override.** Removed; auto-calc handles 99% of cases, the override confused new users more than it helped.
- **Per-environment configs in git.** Real configs stay on the VPS; repo carries `.example` files only.

## Project disposition

Lean toward the simplest, honest implementation that solves the visible need. Active user count is ~1 (the project author). Most "should we also build X?" questions answer themselves: *not yet, here's the trigger that'd make it worth doing.* When suggesting options, name the simpler one as the recommendation up front; don't bury it.

Honesty over claim-inflation. The privacy page says explicitly what we can and can't see; the hourly-rate banner offers "accept this default" rather than pretending the default is the user's preference.

## Visual direction

Two distinct surfaces:

- **Public-facing pages** (`/`, eventually the empty-state, anything new visitors see): editorial. Newsreader serif headings, IBM Plex Mono numbers, system body, hairline rules, dark/green palette. Hard veto on gradient blobs, abstract glows, stock imagery, generic SaaS purple. See `static/css/landing.css` for the full vocabulary.
- **Internal/utility surfaces** (settings, sharing, API keys, the project form): functional. Match the existing dark-card style in `static/css/styles.css`. No editorial flourishes.

## oauth2-proxy gotchas

The sidecar is configured with `set_xauthrequest = true` and `pass_user_headers = true`, plus `skip_auth_routes = ["^/$", "^/privacy$", "^/static/", "^/api/", "^/docs$"]`.

- `skip_auth_routes` skips both the auth check AND header injection. So even when a visitor has a valid cookie, a route in the skip list will not see `X-Forwarded-Email` server-side. For in-page logged-in detection on a public route, use a client-side `fetch('/oauth2/auth', { credentials: 'same-origin' })` — returns 200/202 if signed in, 401 otherwise. See the small `<script>` at the top of `templates/landing.html`.
- Sign out: `<a href="/oauth2/sign_out?rd=/">` clears the cookie and lands the user back on the public landing page.

## Database conventions

- The `has_X_set` pattern (e.g. `has_hourly_rate_set`) uses **row existence** as the truth signal, not column value. So `set_X(0)` is meaningfully different from "never visited the settings page." Don't auto-upsert on empty form submissions; let the absence of a row carry meaning.
- Schema migrations go in `init_db()` in `db.py`, gated by a `PRAGMA table_info` check. SQLite 3.35+ supports `ALTER TABLE ... DROP COLUMN`, which the VPS has.
- API keys are SHA-256 hashed at rest. The plaintext is shown to the user once at creation and never stored. Never log plaintext keys.

## Don't do this

- **Don't pull `/opt/payback/oauth2-proxy.cfg` or `/opt/payback/.env` to your local machine to edit.** They contain the live Google OAuth `client_secret` and the oauth2-proxy `cookie_secret`. Edit them in place via SSH (`sed -i`, escaping `$` as `\\\$` inside a double-quoted ssh string), or write a small Python one-liner over SSH that does the precise edit. If you do pull them by accident: shred the local copy, flag it openly to the maintainer, and recommend rotating those secrets.
- **Don't `git push --force` without an explicit ask.** History was rewritten once already (April 2026, to fix author email); avoid further churn.
- **Don't commit secrets, DB files, or generated configs.** `.env`, `oauth2-proxy.cfg`, `allowed-emails.txt`, `instance/`, `__pycache__/` are gitignored — keep it that way.
- **Don't add features the user didn't ask for.** A bug fix doesn't need surrounding cleanup; a one-shot operation doesn't need a helper. The codebase intentionally avoids speculative abstraction.

## API

`/docs` (public, no auth — agents can `WebFetch` it pre-auth) is the canonical framework reference: fields, units, math, worked examples, full API surface. Hit it before asking the user to fill in fields. The REST API mirrors the web UI shape; per-user keys via `Authorization: Bearer <key>` or `X-API-Key` headers.
