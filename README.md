# UrlShort

A tiny five-digit URL service intended for family members who find long links
difficult to open. It uses one JSON file per code and has no third-party Python
dependencies.

The page is available in Russian and English. It initially follows the
browser/operating-system language preference, and visitors can override it with
the `RU | EN` switch. The selected language remains active while submitting a
code or correcting an error.

## Try it locally

Python 3.10 or newer is recommended.

```bash
python3 urlshort.py add --code 12345 https://example.com
python3 urlshort.py serve
```

Open `http://127.0.0.1:8080`, enter `12345`, and select **Open link**.
The management page is available at `http://127.0.0.1:8080/admin`.

Codes expire after seven days unless another lifetime is provided:

```bash
python3 urlshort.py add --days 30 "https://example.com/a/long/link"
```

The command prints the randomly generated code to send by SMS.

## Manage codes

```bash
python3 urlshort.py list
python3 urlshort.py remove 12345
python3 urlshort.py cleanup
```

By default, JSON files are kept in `./data`. Choose another location with the
global `--data-dir` option:

```bash
python3 urlshort.py --data-dir /var/lib/urlshort add "https://example.com"
```

A code file is intentionally straightforward:

```json
{
  "url": "https://example.com",
  "created_at": "2026-07-27T20:00:00Z",
  "expires_at": "2026-08-03T20:00:00Z"
}
```

Only `http` and `https` URLs are accepted. Codes are convenience identifiers,
not passwords; do not use them as the only protection for sensitive content.

## Admin panel

`/admin` uses the same JSON directory as the command-line tools. It can:

- create random or custom five-digit codes;
- select a 1, 7, 30, or 90-day lifetime;
- copy codes;
- list active and expired codes;
- delete individual codes; and
- remove all expired codes.

The panel is bilingual and protects create/delete operations against cross-site
form submissions. Authentication is intentionally delegated to the HTTPS
reverse proxy. **Never expose the Python server directly to the internet**:
keep it bound to `127.0.0.1` and protect every `/admin` path in Caddy.

## Install on a fresh Debian VPS

These instructions start from the first terminal session on a newly installed
Debian server. They assume:

- you have root access;
- the server has a public IPv4 address;
- you own a domain name;
- you will use a hostname such as `links.example.com`; and
- SSH currently works.

Commands in this section are run as `root`. If you log in as a regular
sudo-enabled user, prefix administrative commands with `sudo`.

### 1. Update Debian and install the basic tools

```bash
apt update
apt full-upgrade -y
apt install -y git python3 ca-certificates curl gnupg \
  debian-keyring debian-archive-keyring apt-transport-https nano
```

If Debian reports that a reboot is required, reboot and reconnect:

```bash
reboot
```

### 2. Download UrlShort

Create the dedicated service account first:

```bash
useradd --system --home-dir /var/lib/urlshort \
  --shell /usr/sbin/nologin urlshort
```

Download the application into its permanent location:

```bash
git clone https://github.com/SergeyMakeev/UrlShort.git /opt/urlshort
```

The application has no third-party Python dependencies, so there is no virtual
environment or `pip install` step.

### 3. Install and start the UrlShort service

Install the included systemd unit:

```bash
install -m 0644 /opt/urlshort/systemd/urlshort.service \
  /etc/systemd/system/urlshort.service
systemctl daemon-reload
systemctl enable --now urlshort
```

The service automatically creates `/var/lib/urlshort` for its JSON files and
listens only on `127.0.0.1:8080`.

Check that it started:

```bash
systemctl status urlshort --no-pager
curl http://127.0.0.1:8080/healthz
```

The final command must print:

```text
ok
```

If it does not, inspect the service log:

```bash
journalctl -u urlshort -n 100 --no-pager
```

### 4. Point the domain at the VPS

In your DNS provider's control panel, create:

```text
Type: A
Name: links
Value: YOUR_VPS_IPV4_ADDRESS
```

This example produces `links.example.com`. Use `@` as the name instead if you
want to use the root domain.

Create an `AAAA` record only when the VPS has working public IPv6. An incorrect
AAAA record can make the site fail for visitors whose networks prefer IPv6.

Check DNS from the VPS, replacing the example hostname:

```bash
getent ahostsv4 links.example.com
```

The displayed address should be the VPS public IPv4 address. DNS changes can
take time to propagate.

### 5. Allow the required network ports

In the VPS provider's firewall, security-group, or network-firewall page, allow
incoming TCP connections to:

```text
22    SSH
80    HTTP and certificate validation
443   HTTPS
```

If SSH uses a port other than 22, allow that port instead. Do this before
enabling a restrictive firewall so you do not lock yourself out.

Do **not** expose port `8080`; it must remain reachable only through
`127.0.0.1`.

An optional host firewall can be enabled with UFW. Confirm the SSH port first:

```bash
apt install -y ufw
ufw allow 22/tcp comment SSH
ufw allow 80/tcp comment HTTP
ufw allow 443/tcp comment HTTPS
ufw enable
ufw status verbose
```

Replace `22` before running these commands if SSH uses a custom port. Keep the
current SSH session open and verify that a second SSH session can connect before
closing the first one.

### 6. Install Caddy

Install Caddy from its official stable Debian repository:

```bash
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | tee /etc/apt/sources.list.d/caddy-stable.list
chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg
chmod o+r /etc/apt/sources.list.d/caddy-stable.list
apt update
apt install -y caddy
```

The package installs and starts Caddy as a systemd service.

### 7. Create the admin password

Generate a secure password hash:

```bash
caddy hash-password
```

Caddy asks for the password without displaying it and prints a hash beginning
with something similar to `$2a$...`. Copy the entire hash. The plaintext
password must not be placed in the Caddyfile.

### 8. Configure HTTPS and admin authentication

Open the Caddy configuration:

```bash
nano /etc/caddy/Caddyfile
```

Replace its contents with the following. Change `links.example.com` to your
real hostname and replace `YOUR_PASSWORD_HASH` with the hash from the previous
step:

```caddyfile
links.example.com {
    handle /admin* {
        basic_auth {
            admin YOUR_PASSWORD_HASH
        }

        reverse_proxy 127.0.0.1:8080
    }

    handle {
        reverse_proxy 127.0.0.1:8080
    }
}
```

Save in nano with `Ctrl+O`, press Enter, and exit with `Ctrl+X`.

Format and validate the configuration before loading it:

```bash
caddy fmt --overwrite /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy
systemctl status caddy --no-pager
```

Caddy automatically obtains the TLS certificate and redirects HTTP to HTTPS
when the domain resolves to this server and ports 80 and 443 are reachable.

If Caddy does not start, inspect its log:

```bash
journalctl -u caddy -n 100 --no-pager
```

### 9. Verify the finished installation

Open these addresses in a browser:

```text
https://links.example.com
https://links.example.com/admin
```

The first address should show the five-digit entry page. The second should ask
for username `admin` and the password selected earlier, then display the
management panel.

Command-line checks are also useful:

```bash
curl -I https://links.example.com
curl -I https://links.example.com/admin
```

The public page should return `200`. The unauthenticated admin request should
return `401`.

### 10. Create the first link

Open `/admin`, enter a destination URL, choose an expiration period, and select
**Create code**. The generated code is saved as an individual JSON file under:

```text
/var/lib/urlshort/
```

The command line remains available:

```bash
runuser -u urlshort -- /usr/bin/python3 /opt/urlshort/urlshort.py \
  --data-dir /var/lib/urlshort add "https://example.com"
```

### Updating the application

```bash
cd /opt/urlshort
git pull --ff-only
install -m 0644 systemd/urlshort.service /etc/systemd/system/urlshort.service
systemctl daemon-reload
systemctl restart urlshort
curl http://127.0.0.1:8080/healthz
```

### Backing up the links

All user data is contained in `/var/lib/urlshort`. A simple manual backup is:

```bash
tar -C /var/lib -czf /root/urlshort-backup.tar.gz urlshort
```

Copy the resulting archive off the VPS. Restoring it replaces the contents of
`/var/lib/urlshort`; stop the application before performing a restore and
ensure the restored files belong to the `urlshort` user.

### Useful operational commands

```bash
systemctl status urlshort --no-pager
systemctl status caddy --no-pager
journalctl -u urlshort -f
journalctl -u caddy -f
systemctl restart urlshort
systemctl reload caddy
```

Official references:

- [Caddy installation on Debian](https://caddyserver.com/docs/install)
- [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https)
- [Caddy basic authentication](https://caddyserver.com/docs/caddyfile/directives/basic_auth)

## Install on Armbian

Copy the repository to `/opt/urlshort`, then create a dedicated system user and
install the included service:

```bash
sudo useradd --system --home /var/lib/urlshort --shell /usr/sbin/nologin urlshort
sudo cp systemd/urlshort.service /etc/systemd/system/urlshort.service
sudo systemctl daemon-reload
sudo systemctl enable --now urlshort
```

The service listens only on `127.0.0.1:8080`. Configure Tailscale Funnel to
publish that local address over HTTPS. The exact Funnel command depends on the
Tailscale version installed, so verify it with:

```bash
tailscale funnel --help
```

Create codes as the service user so the JSON files retain the correct owner:

```bash
sudo -u urlshort /usr/bin/python3 /opt/urlshort/urlshort.py \
  --data-dir /var/lib/urlshort add "https://example.com"
```

Useful service checks:

```bash
systemctl status urlshort
curl http://127.0.0.1:8080/healthz
journalctl -u urlshort
```

## Test

```bash
python3 -m unittest discover -v
```
