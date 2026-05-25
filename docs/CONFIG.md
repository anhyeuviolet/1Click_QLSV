# Config Reference — `/root/.quanlyserver.json`

This document is the single source of truth for the v3 nested config schema
used by the `qlsv` web admin. The file is JSON (UTF-8) and lives at
`/root/.quanlyserver.json` on the game server.

> **Heads-up:** All values that contain Vietnamese diacritics are stored as
> UTF-8 — keep the file in UTF-8 (no BOM) when editing.

---

## First-time setup

1. Copy the example file shipped in the repo:

   ```bash
   sudo cp configs/quanlyserver.example.json /root/.quanlyserver.json
   sudo chmod 0600 /root/.quanlyserver.json
   ```

2. Edit and replace the three `REPLACE_ME` placeholders:
   - `admin.username` — the single admin account used to log into the web UI
   - `admin.password` — plaintext today (Phase 1); hashed storage tracked for v3.1
   - `session.secret_key` — see "Generate `session.secret_key`" below

3. (Optional) Set `db.mysql.password` and `db.mssql.password` if you intend
   to use Phase 3 account management. The web app does **not** require DB
   credentials to start — they are only consumed once the account manager
   ships.

---

## Generate `session.secret_key`

Run on the server (any 48-byte URL-safe random string works):

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Copy the output into `session.secret_key`. **Do not commit this value to
git.** Rotating it logs every open session out — that is intentional.

---

## Schema

### `game`

Game-server file tree + network identity used by `jx.sh`.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `directory` | string | `/home/jxser` | Absolute path to the JX1 game-server root (`$GAMEPATH`). |
| `server_ip` | string | `""` | IPv4 the game services bind to and advertise; empty = auto-detect first non-lo/non-docker iface. |
| `server_mac` | string | `""` | MAC of `server_ip`'s interface, formatted `AA-BB-CC-DD-EE-FF`; empty = auto-derive. |

### `web`

How the FastAPI web admin binds and serves traffic.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `bind_addr` | string | `0.0.0.0` | Interface to listen on. Keep as `0.0.0.0` for LAN access; the firewall (not the bind addr) is the access control — see `docs/RUNNING.md`. |
| `port` | integer | `8080` | TCP port for the web UI. |
| `idle_timeout_seconds` | integer | `2592000` | Session cookie max age (30 days). Lowering this forces more frequent re-logins. |
| `cookie_secure` | boolean | `false` | `true` only if you front the app with HTTPS (out of Phase 1 scope; reverse-proxy required). |

### `admin`

The single admin account. There is no signup flow — the admin sets these
by editing the file (D-02 in `01-CONTEXT.md`).

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `username` | string | `REPLACE_ME` | Login name shown in the header bar after authentication. |
| `password` | string | `REPLACE_ME` | Plaintext in v3.0; comparison is constant-time. Hashed storage is tracked for v3.1. |

If either is left as `REPLACE_ME` (or empty), the web app refuses to start
with the message *Chưa cấu hình admin*.

### `session`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `secret_key` | string | `REPLACE_ME` | URL-safe random string (≥ 32 bytes). See "Generate `session.secret_key`" above. The app refuses to start if missing or left as the placeholder. |

### `db.mysql`

Used by Phase 3 (account manager) — Phase 1 ignores this section.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `host` | string | `127.0.0.1` | MySQL host. |
| `port` | integer | `3306` | MySQL port. |
| `user` | string | `root` | MySQL user. |
| `password` | string | `REPLACE_ME` | MySQL password. Used by Phase 3 with **parameterized** queries (ACCT-05) — no string interpolation into SQL. |

### `db.mssql`

Used by Phase 3 (account manager) — Phase 1 ignores this section.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `host` | string | `127.0.0.1` | MSSQL host. |
| `port` | integer | `1433` | MSSQL port. |
| `user` | string | `SA` | MSSQL user. |
| `password` | string | `REPLACE_ME` | MSSQL `SA` password. Used by Phase 3 with **parameterized** queries (ACCT-05). |

---

## Migration from v2.x (flat → nested)

The v2.x file had a flat shape (`directory`, `server_ip`, `server_mac` at
the top level — see legacy `2.3.2/app.py:35`). On first launch under v3
the loader auto-migrates the file in place:

1. Reads the flat keys.
2. Re-emits them under the new `game.*` namespace.
3. Adds empty `web`, `admin`, `session`, `db` sections (with `REPLACE_ME`
   placeholders so the start-up guard prompts the admin to configure them).
4. Writes a backup at `/root/.quanlyserver.json.pre-v3.bak` before
   overwriting the original.

The migration is idempotent — re-running on an already-nested file is a
no-op (per D-13 in `01-CONTEXT.md`).

---

## Vendored assets

The web admin ships its JS/CSS dependencies inside the package — no CDN
calls at runtime — so the host stays usable on air-gapped LAN deployments.

- htmx.min.js: SHA-256 = e209dda5c8235479f3166defc7750e1dbcd5a5c1808b7792fc2e6733768fb447

  Upstream source: https://htmx.org/ . The digest above mirrors the
  ground-truth file `src/qlsv/web/static/htmx.min.js.sha256` written when
  the asset was vendored — if the JS is ever upgraded, regenerate the
  sidecar (`sha256sum htmx.min.js > htmx.min.js.sha256`) and update this
  line in lock-step.

### HTMX SSE extension

- htmx-ext-sse.min.js: SHA-256 = 83eca6fa0611fe2b0bf1700b424b88b5eced38ef448ef9760a2ea08fbc875611

  Version: 2.2.2 (matches htmx 2.x major). Upstream source:
  https://unpkg.com/htmx-ext-sse@2.2.2/sse.js (npm package
  `htmx-ext-sse`, GitHub
  `bigskysoftware/htmx-extensions/src/sse/sse.js`). Vendored verbatim
  as `src/qlsv/web/static/htmx-ext-sse.min.js`; the sidecar
  `htmx-ext-sse.min.js.sha256` is the ground truth — regenerate
  with `sha256sum htmx-ext-sse.min.js > htmx-ext-sse.min.js.sha256` and
  update this line in lock-step on any version bump.

  Loaded after `htmx.min.js` in `base.html`. Powers the live tail-pane on
  the dashboard (Plan 02-03 DASH-04): `<pre hx-ext="sse"
  sse-connect="/api/jobs/log?job_id=...&mode=stream" sse-swap="message"
  hx-swap="beforeend">`.
