<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="../assets/logo-dark.svg">
    <img src="../assets/logo.svg" alt="ocmanager" height="48">
  </picture>
</p>

<p align="center"><b>English</b> · <a href="INSTALL.ru.md">Русский</a></p>

# ocmanager: installation and operation

A guide for the server owner. Basic Linux skills are required: SSH, `sudo`, DNS.

## What you need beforehand

1. **A server** running Debian 12+ or Ubuntu 22.04+, a public IPv4 address, root or `sudo`. At least 1 GB of memory (on 1 GB the
   wizard offers to create swap) and 10 GB of disk.
2. **Two domains** (or subdomains): one for the Mini App, one for the VPN gateway. Both need an A record pointing to the server IP.
3. **Ports 80/tcp, 443/tcp and 443/udp** free and open at your provider. Docker publishes ports bypassing `ufw`,
   so close everything else in your provider's firewall: only 80, 443 and SSH should be reachable from outside.
4. **A bot** from @BotFather: you need its token.
5. **Access to the product repository** (a deploy key or a token) and an email for Let's Encrypt.

## Installation

```bash
git clone <repository> ocmanager && cd ocmanager
sudo ./install.sh
```

The wizard speaks English by default. Use `--lang ru` (or `OCM_LANG=ru`) for Russian; `ocm` keeps using the language you chose.

The wizard checks the server and then asks, in order:

| Question | What to answer |
|---|---|
| Mini App domain / VPN domain | Names without `https://`, different from each other. The wizard checks the A records against the server IP. |
| Let's Encrypt email | Your working email. |
| Bot token | From @BotFather. The wizard verifies it and picks up the bot name itself. |
| Tribute key | You can skip it (Enter) and add it later to `deploy/.env`. |
| Administrator login and password | The password must be at least 12 characters; you can let the wizard generate one (shown once). |
| Enable backups | Optional (default: no). If yes, the wizard asks where else to copy them: `user@server:/path` (over SSH key) or a directory. Enable later: `sudo ocm backup-enable`. |

The installation takes about 10 minutes. If it was interrupted, fix the cause and run `sudo ./install.sh` again: it continues from
the same step, secrets and `.env` are not recreated. To see the plan without changes: `sudo ./install.sh --dry-run`.

If you enabled backups, the wizard shows the **encryption key** at the end. Save it separately from the server (a password manager):
backups cannot be decrypted without it.

## After the installation

1. @BotFather → `/myapps` → your app → Edit Web App URL → `https://<Mini App domain>`.
2. Send `/whoami` to the bot, take the number it replies with and run `sudo ocm admin-chat <number>`: this is how you start receiving alerts.
3. The admin panel is reachable only through an SSH tunnel:
   ```bash
   ssh -L 8080:127.0.0.1:8080 user@server
   ```
   then open `http://localhost:8080/` in a browser.
4. Create plans in the admin panel. Tribute: in the author's account set the webhook `https://<Mini App domain>/webhooks/tribute`,
   put the API key into `deploy/.env` (`OCM_TRIBUTE_API_KEY`) and run `cd deploy && docker compose up -d`.

## Everyday use: the `ocm` command (as root)

| Command | What it does |
|---|---|
| `ocm status` | Health check: every line should be green |
| `ocm logs [service] [-f]` | Logs |
| `ocm backup-enable` | Enable daily backups |
| `ocm backup` | Take a backup now |
| `ocm restore <file> [--with-env]` | Restore |
| `ocm update` | Update, with a backup first |
| `ocm rollback` | Return to the version before the update |
| `ocm admin-chat <number>` | Who receives alerts |
| `ocm admin-password <login>` | Change the administrator password |

### `ocm` security

`ocm` runs as root and executes code from the directory where you cloned the repository. That directory (and everything above it)
must therefore not be writable by other users: `ocm` refuses to start otherwise and lists the offending paths (fix with
`chmod go-w`). Keep the clone in the home directory of root or of an administrator you already trust with `sudo`.

## Backups

Off by default. Enable them with `sudo ocm backup-enable` (creates the key and the timer). Without backups, losing the server means losing the
database and the CA, and `ocm update` asks for confirmation that updating without a backup is fine.

Once enabled, a file `/var/backups/ocmanager/ocmanager-<date>.tar.gz.enc` is created every night at 03:30: the database, the certificate
authority (CA) and `.env`, encrypted with the key from `/root/.ocmanager-backup-key`. The last 14 are kept. If a backup fails, the
admin receives a Telegram alert, and `ocm status` turns red when there has been no successful backup for more than 36 hours.

**Losing the CA means reissuing the keys of every client.** So: keep the encryption key outside the server and set a second
destination for the copies.

### Restoring on a new server

1. Install the product as usual (`sudo ./install.sh`) with the same domains and point DNS to the new IP.
2. Put the backup file on the server and the key into `/root/.ocmanager-backup-key` (`chmod 600`).
3. `sudo ocm restore /path/to/ocmanager-….tar.gz.enc` and type `YES`. Add `--with-env` if you need the previous `.env`
   (the old server's secrets). An emergency backup of the current state is taken before the restore.
4. `ocm status`: after the restore, the keys already issued to clients keep working.

A wrong key or a damaged file is detected before the services are stopped: nothing is overwritten.

## Update and rollback

```bash
sudo ocm update
```

The command refuses to work if the installation directory has local changes or the update would need a merge, and changes nothing
in that case. Otherwise: backup → `git pull --ff-only` → build → start → check. If the check is red, the command suggests
`sudo ocm rollback`: the code returns to the previous commit, and the database can (as a separate question) be restored from the
pre-update backup, losing the changes made after it. After a rollback, return to your branch: `git switch <branch>` (the name is
printed by `ocm rollback`).

## If something is wrong

| Symptom | Where to look |
|---|---|
| ocserv keeps restarting | `ocm logs ocserv`: no CA/CRL or certificate (Caddy is still issuing it) |
| The certificate is not issued | A records, port 80 reachable from outside, `ocm logs caddy` (Let's Encrypt allows 5 failures per hour) |
| Clients cannot connect after months | `ocm logs worker`: certificate renewal is picked up every 6 hours |
| The Mini App shows a white screen | Edit Web App URL in @BotFather; the site response must not contain `X-Frame-Options` |
| No notifications | `ocm logs worker`; `admin_chat_ids` is not set (`ocm admin-chat`) |
| `ocm status`: node reconcile is red | Normal during the first 5–6 minutes after start |
| `ocm status`: no fresh backup | `ocm backup` and read the error message; `systemctl status ocm-backup.timer` |

Technical reference (manual path, how the stack is built): [README.md](README.md).
