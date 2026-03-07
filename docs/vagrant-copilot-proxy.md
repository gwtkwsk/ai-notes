# Using GitHub Copilot CLI in the Vagrant VM via Host mitmproxy

The real GitHub token lives in **GNOME Keyring** on the host. A host-side
**mitmproxy** injects it into Copilot traffic; the VM only holds a harmless
placeholder token and trusts the mitmproxy CA so TLS works transparently.

---

## Prerequisites

- Fedora Workstation 43 host with GNOME Keyring
- `uv` available on the host
- Vagrant + libvirt already working (see README)
- A fine-grained GitHub PAT with **Copilot Requests** permission stored in
  keyring:

  ```bash
  keyring set github-copilot-proxy <your-gh-username>
  ```

---

## Setup

### 1. Generate the mitmproxy CA

```bash
uvx --from mitmproxy mitmproxy   # Ctrl-C immediately after it starts
```

The CA is written to `~/.mitmproxy/mitmproxy-ca-cert.pem`.

### 2. Create the token-injection script

Save this **outside the repo** (e.g. `~/.local/share/copilot-proxy/inject_token.py`)
so the token never touches the VM's shared `/vagrant` folder:

```bash
mkdir -p ~/.local/share/copilot-proxy
```

```python
import os

import keyring
from mitmproxy import http

KEYRING_SERVICE = "github-copilot-proxy"
KEYRING_ACCOUNT = os.environ.get("COPILOT_KEYRING_ACCOUNT", "<your-gh-username>")
REAL_TOKEN = keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
AUTH_HOSTS = {
    "api.github.com",
    "api.individual.githubcopilot.com",
    "copilot-proxy.githubusercontent.com",
}

if not REAL_TOKEN:
    raise RuntimeError(
        f"No token found in keyring service={KEYRING_SERVICE!r} account={KEYRING_ACCOUNT!r}"
    )


def request(flow: http.HTTPFlow) -> None:
    if flow.request.pretty_host in AUTH_HOSTS:
        flow.request.headers["Authorization"] = f"Bearer {REAL_TOKEN}"
```

### 3. Start mitmproxy (host terminal)

```bash
uvx --with keyring --from mitmproxy mitmdump \
  --listen-host "${VAGRANT_PROXY_HOST:-192.168.122.1}" \
  --listen-port "${VAGRANT_PROXY_PORT:-8080}" \
  -s ~/.local/share/copilot-proxy/inject_token.py
```

### 4. Start the VM

```bash
vagrant up --provider=libvirt
```

`vagrant up` copies the mitmproxy CA into the VM and installs it automatically
when `~/.mitmproxy/mitmproxy-ca-cert.pem` exists on the host.

### 5. SSH and use Copilot

```bash
vagrant ssh
copilot   # placeholder token + proxy are pre-configured
```

---

## Vagrantfile environment variables

All are optional; defaults are shown.

| Variable | Default | Purpose |
|---|---|---|
| `VAGRANT_PROXY_HOST` | `192.168.122.1` | IP mitmproxy listens on (host side) |
| `VAGRANT_PROXY_PORT` | `8080` | Port mitmproxy listens on |
| `VAGRANT_MITM_CA` | `~/.mitmproxy/mitmproxy-ca-cert.pem` | Host path to mitmproxy CA cert |
| `VAGRANT_COPILOT_TOKEN` | `ghu_placeholder` | Fake token stored in the VM |

If the CA file is absent at provision time, the CA step is skipped. Re-run
after generating the cert:

```bash
vagrant provision
```

---

## Manual validation (inside the VM)

```bash
# CA trusted?
curl -s https://api.github.com | head -5

# Proxy reachable and certificate issuer correct?
curl -sv --proxy "$HTTPS_PROXY" https://api.github.com 2>&1 | grep -E "Connected|issuer"

# Env vars set correctly?
env | grep -E 'HTTPS_PROXY|GH_TOKEN|COPILOT_GITHUB_TOKEN'
```

---

## Troubleshooting

**mitmdump won't bind to 192.168.122.1** — the libvirt default network is not
running:

```bash
sudo virsh net-start default && sudo virsh net-autostart default
```

**VM gets `Connection refused` on the proxy port** — verify mitmdump is
listening on the host:

```bash
ss -ltn sport = :8080
```

If it is listening but the VM still can't connect, open the port in the
libvirt firewalld zone:

```bash
sudo firewall-cmd --zone=libvirt --add-port=8080/tcp
# Make permanent:
sudo firewall-cmd --permanent --zone=libvirt --add-port=8080/tcp
sudo firewall-cmd --reload
```

**Copilot API returns 401** — a GitHub/Copilot host is not covered by
`AUTH_HOSTS` in `inject_token.py`. Add the hostname that mitmdump logs show
returning 401, then restart mitmdump.

---

## Security notes

- The real token is **never written inside the VM** or the `/vagrant` folder;
  it lives only in GNOME Keyring and mitmproxy process memory on the host.
- If you rotate the token, restart mitmdump.
- The mitmproxy CA can intercept all HTTPS traffic from the VM. Do not import
  it into your host browser or other applications.
- The placeholder token `ghu_placeholder` is intentionally invalid and cannot
  be used against the GitHub API.
