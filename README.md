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
