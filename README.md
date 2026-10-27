<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <img src="assets/logo.svg" alt="ocmanager" height="64">
  </picture>
</p>

<p align="center"><b>English</b> · <a href="README.ru.md">Русский</a></p>

<p align="center">
  <b>Your own VPN service in one command</b><br>
  Telegram Mini App, subscriptions, keys and an admin panel on top of ocserv (OpenConnect / AnyConnect)
</p>

<p align="center">
  <a href="https://github.com/sontiago/ocmanager/actions/workflows/backend.yml"><img src="https://github.com/sontiago/ocmanager/actions/workflows/backend.yml/badge.svg" alt="backend"></a>
  <a href="https://github.com/sontiago/ocmanager/actions/workflows/admin.yml"><img src="https://github.com/sontiago/ocmanager/actions/workflows/admin.yml/badge.svg" alt="admin"></a>
  <a href="https://github.com/sontiago/ocmanager/actions/workflows/tma.yml"><img src="https://github.com/sontiago/ocmanager/actions/workflows/tma.yml/badge.svg" alt="tma"></a>
  <a href="https://github.com/sontiago/ocmanager/actions/workflows/installer.yml"><img src="https://github.com/sontiago/ocmanager/actions/workflows/installer.yml/badge.svg" alt="installer"></a>
  <br>
  <img src="https://img.shields.io/badge/version-1.0.0-blue" alt="version 1.0.0">
  <img src="https://img.shields.io/badge/Python-3.12-3776ab?logo=python&logoColor=white" alt="Python 3.12">
  <img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/React-19-61dafb?logo=react&logoColor=black" alt="React 19">
  <img src="https://img.shields.io/badge/PostgreSQL-16-4169e1?logo=postgresql&logoColor=white" alt="PostgreSQL 16">
  <img src="https://img.shields.io/badge/Docker-compose-2496ed?logo=docker&logoColor=white" alt="Docker Compose">
  <img src="https://img.shields.io/badge/Debian%2012%2B%20%7C%20Ubuntu%2022.04%2B-supported-a81d33?logo=debian&logoColor=white" alt="OS">
</p>

## Features

- **Telegram Mini App:** plans, payments (Tribute), device keys, promo codes and referrals.
- **Admin panel:** clients, subscriptions, payments, statistics, traffic quotas, abuse alerts, node management.
- **Certificate authentication:** its own CA and CRL, one key per device.
- **Routes that bypass the VPN:** addresses clients open directly are configured in the admin panel.
- **Wizard installation:** `./install.sh` asks the questions and sets everything up, including Let's Encrypt certificates.
- **One-command maintenance:** `ocm` for status, backup and restore (optional), update and rollback.

## Quick start

You need: a Debian 12+ or Ubuntu 22.04+ server, two domains with A records pointing to its IP, open ports 80/tcp, 443/tcp and 443/udp, and a bot token from [@BotFather](https://t.me/BotFather).

```bash
git clone https://github.com/sontiago/ocmanager.git && cd ocmanager
sudo ./install.sh
```

The wizard asks everything it needs (English by default; add `--lang ru` for Russian, the choice is remembered for `ocm`). Details and what to do after the installation: **[deploy/INSTALL.md](deploy/INSTALL.md)**.

## The `ocm` command

| Command | What it does |
|---|---|
| `ocm status` | health check of all components |
| `ocm logs [service] [-f]` | logs |
| `ocm update` / `ocm rollback` | update and return to the previous version |
| `ocm backup-enable` / `ocm backup` / `ocm restore` | encrypted backups |
| `ocm admin-chat <id>` / `ocm admin-password <login>` | Telegram alerts and the admin password |

## How it works

```mermaid
flowchart LR
    C([VPN client]) -- 443 TCP/UDP --> N[nginx] --> O[ocserv]
    T([Telegram]) --> W[Caddy] --> P[api-public]
    P --> DB[(PostgreSQL)]
    A[api-admin<br/>127.0.0.1:8080] --> DB
    WK[worker] --> DB
    WK -- allowed.list, CRL, routes --> O
    B[bot] --> DB
```

One server, one set of services in Docker Compose. There is no multi-tenancy: every installation is independent.
The admin panel is reachable only through an SSH tunnel.

## Development

```bash
cd backend && make dev-up && make check     # Postgres + Redis, linter, mypy, tests
cd frontend/admin && npm ci && npm test     # admin panel (same for frontend/tma)
```

## Layout

| Directory | Contents |
|---|---|
| `backend/` | FastAPI, bot, worker, CLI, migrations |
| `frontend/tma/` | Telegram Mini App (React) |
| `frontend/admin/` | web admin panel (React) |
| `ocserv/` | ocserv node image |
| `deploy/` | Docker Compose, installer, `ocm`, [guide](deploy/INSTALL.md), [technical reference](deploy/README.md) |
| `scripts/` | `doctor.sh` and config checks |

Documentation (architecture, data flows, per-project details) is in [docs/](docs/README.md) and is written in Russian.
