# OrderTogether

A lightweight self-hosted web app for coordinating group orders. Create an order with a vendor link and deadline, share the URL, and let participants add their items — with live updates for everyone via WebSocket.

## Features

- **No account required** — participants join via a shared URL and pick a display name
- **Invite-only orders** — restrict participation to named guests via signed invite links
- **Privacy mode** — participants only see their own items (requires invite-only)
- **Real-time updates** — item list refreshes live across all open tabs via WebSocket
- **Dynamic deadline** — the add-item form disappears client-side when the deadline passes; admins can extend it and all connected clients update instantly
- **Admin panel** — secret URL grants admin rights in any browser; admins can add/edit/delete items and generate invite links even after the deadline
- **CSV export** — download the order grouped by person or by product (with quantity aggregation)
- **i18n** — English and German, auto-detected from the browser's `Accept-Language` header
- **Optional OIDC login** — enables user identity across browsers and privacy mode

## Quick Start (Docker)

```bash
cp .env.example .env
# Edit .env — at minimum set SECRET_KEY
docker compose up --build
```

App is available at <http://localhost:8000>. The SQLite database is stored in `./data/` (volume-mounted).

## Local Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
uvicorn app.main:app --reload
```

## Configuration

All configuration is via environment variables (`.env` file):

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | `changeme-…` | Session signing key — **change in production** |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/ordertogether.db` | SQLAlchemy async DB URL |
| `TIMEZONE` | `Europe/Berlin` | Timezone for deadline display and input parsing |
| `OIDC_CLIENT_ID` | — | Enables OIDC login when set together with the other two |
| `OIDC_CLIENT_SECRET` | — | OIDC client secret |
| `OIDC_DISCOVERY_URL` | — | OIDC discovery endpoint (e.g. `https://accounts.google.com/.well-known/openid-configuration`) |
| `OIDC_REDIRECT_URI` | `http://localhost:8000/auth/callback` | Must match the redirect URI registered with your OIDC provider |
| `OIDC_SSL_VERIFY` | `true` | Set to `false` to disable TLS verification (self-signed certs), or to an absolute path to a CA-bundle PEM file |

## How It Works

1. **Create an order** — enter vendor name, menu URL, and deadline. You are redirected to a secret admin URL — bookmark it.
2. **Share the link** — copy the regular order URL and send it to participants (or use invite links for invite-only orders).
3. **Participants add items** — name, product, quantity, optional SKU/URL/note.
4. **Export** — download a CSV grouped by person (for placing the order) or by product (to see totals).

### Identity Modes

| Mode | When | Can edit |
|---|---|---|
| Anonymous | No OIDC configured, no invite | Own items (open mode: any item) |
| Token | Joined via invite link | Own items only |
| OIDC | Logged in | Own items only |

### Admin Access

Admin rights are granted to the browser session that visits the secret admin URL (`/orders/{id}/admin/{token}`). The URL is shown in the admin panel and can be shared to grant admin rights in another browser. There is no password.

## OIDC Setup

Set the three `OIDC_*` variables to enable login. Any OpenID Connect provider works (Google, Keycloak, Authentik, …). With OIDC enabled:
- A login button appears in the nav
- OIDC users are identified by their `sub` claim across sessions
- Invite-only + privacy mode becomes available
