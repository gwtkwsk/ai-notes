# Using GitHub Copilot CLI in the Vagrant VM via Host mitmproxy

This document explains how to use the GitHub Copilot CLI inside the repo's
libvirt Vagrant VM without ever storing your real GitHub token inside the VM.

The real token lives in **GNOME Keyring** on the Fedora host. A host-side
**mitmproxy** terminates HTTPS for traffic coming from the VM and injects the
real `Authorization` header only for the GitHub hosts Copilot CLI needs. The VM
only holds a harmless placeholder token and trusts the mitmproxy CA certificate
so TLS works transparently.

---

## Prerequisites

- Fedora Workstation 43 host with GNOME Keyring available
- `uv` available on the host
- `mitmproxy` launched via `uvx` only. For the add-on in this guide, use:

  ```bash
  uvx --with keyring --from mitmproxy mitmdump --version
  ```

  This downloads the tool on demand and avoids any separate global installation.
  Fedora 43 does not currently ship a `mitmproxy` package in the default `dnf`
  repositories, so this guide does not rely on `dnf install mitmproxy`.
- The Vagrant + libvirt setup already working (see README)
- A **fine-grained GitHub Personal Access Token** with at least the
  **Copilot Requests** permission enabled (no other permissions required).
  Store it in GNOME Keyring, for example:

  ```bash
  keyring set github-copilot-proxy <your-gh-username>
  ```

---

## Host-side setup

### 1. Generate the mitmproxy CA certificate

Run `mitmproxy` once via `uvx` to generate its CA:

```bash
uvx --from mitmproxy mitmproxy   # Ctrl-C immediately after it starts
```

The CA certificate is written to `~/.mitmproxy/mitmproxy-ca-cert.pem`.

### 2. Write the token-injection script

**Keep this script outside the shared `/vagrant` mount** (i.e. outside the
repository) so the real token is never accessible inside the VM.

A suggested location is `~/.local/share/copilot-proxy/inject_token.py`. Below is
a sample snippet -- adapt it to your setup:

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

`api.individual.githubcopilot.com` is required for current Copilot CLI traffic:
the CLI uses it for model discovery and MCP endpoints such as `/models` and
`/mcp/readonly`. If mitmdump logs show another GitHub/Copilot host returning
`401`, add that hostname to `AUTH_HOSTS` and restart mitmdump.

Start mitmdump with that add-on:

```bash
mkdir -p ~/.local/share/copilot-proxy
$EDITOR ~/.local/share/copilot-proxy/inject_token.py
uvx --with keyring --from mitmproxy mitmdump \
  --listen-host "${VAGRANT_PROXY_HOST:-192.168.122.1}" \
  --listen-port "${VAGRANT_PROXY_PORT:-8080}" \
  -s ~/.local/share/copilot-proxy/inject_token.py
```

### 3. Bind mitmproxy to the libvirt bridge IP

The default libvirt bridge is `virbr0` with IP `192.168.122.1`. The script
above binds to `VAGRANT_PROXY_HOST` (default `192.168.122.1`) so the VM can
reach the proxy over the bridge without any firewall changes.

Confirm the bridge exists and has the expected address:

```bash
ip addr show virbr0
```

If `uvx ... mitmdump` fails with `could not bind on any address`, the host does
not currently own that IP. On Fedora/libvirt that usually means the default
network is not running yet. Start it, then verify `virbr0` again:

```bash
sudo virsh net-start default || true
sudo virsh net-autostart default
ip -4 addr show virbr0
```

If you use a different libvirt network, bind mitmdump to the actual host-side
address of that network and export the same value before running `vagrant up`.

If `curl` from inside the VM reaches the host IP but ends with `Connection
refused`, the network path is correct and the problem is on the host side:
`mitmdump` is either not running, bound to a different address, or listening on
a different port. Verify the listener on the host:

```bash
ss -ltn sport = :8080
```

You should see the exact address from `VAGRANT_PROXY_HOST` in the `Local
Address:Port` column. If not, restart `mitmdump` with the same host/port values
used by the VM.

On Fedora with firewalld, the `virbr0` interface usually lives in the `libvirt`
zone, which ends with a catch-all `reject` rule for ports that are not
explicitly allowed. If `ss` shows `mitmdump` listening correctly but the VM
still gets `Connection refused`, open the proxy port in that zone on the host:

```bash
sudo firewall-cmd --zone=libvirt --add-port=8080/tcp
```

To keep the rule across reboots:

```bash
sudo firewall-cmd --permanent --zone=libvirt --add-port=8080/tcp
sudo firewall-cmd --reload
```

If you use a different `VAGRANT_PROXY_PORT`, substitute that port number in the
commands above.

To derive the address from `virbr0` without manual lookup:

```bash
export VAGRANT_PROXY_HOST="$(ip -4 -o addr show virbr0 | awk '{print $4}' | cut -d/ -f1)"
```

If your libvirt network uses a different subnet, export the variable before
starting both the proxy and `vagrant up`:

```bash
export VAGRANT_PROXY_HOST=192.168.122.1   # example alternate address
```

---

## Vagrantfile environment variables

The `Vagrantfile` reads the following host environment variables (all
optional -- sensible defaults are shown):

| Variable | Default | Purpose |
|---|---|---|
| `VAGRANT_PROXY_HOST` | `192.168.122.1` | IP the mitmproxy listens on (host side) |
| `VAGRANT_PROXY_PORT` | `8080` | Port mitmproxy listens on |
| `VAGRANT_MITM_CA` | `~/.mitmproxy/mitmproxy-ca-cert.pem` | Host path to the mitmproxy CA cert |
| `VAGRANT_COPILOT_TOKEN` | `ghu_placeholder` | Fake token stored in the VM |

When `VAGRANT_MITM_CA` points to an existing file, `vagrant up` copies it
into the VM and installs it into Fedora's system CA trust store
(`/etc/pki/ca-trust/source/anchors/`) automatically.

If the cert file does not exist at provision time, the CA step is skipped and
you must re-provision later with:

```bash
VAGRANT_MITM_CA=~/.mitmproxy/mitmproxy-ca-cert.pem vagrant provision
```

---

## Starting the workflow

1. **Start mitmproxy** on the host (in a separate terminal):

    ```bash
    export VAGRANT_PROXY_HOST="${VAGRANT_PROXY_HOST:-192.168.122.1}"
    uvx --with keyring --from mitmproxy mitmdump \
      --listen-host "$VAGRANT_PROXY_HOST" \
      --listen-port "${VAGRANT_PROXY_PORT:-8080}" \
      -s ~/.local/share/copilot-proxy/inject_token.py
    ```

2. **Start (or re-provision) the VM**:

   ```bash
   vagrant up --provider=libvirt
   # or, if the VM already exists:
   vagrant provision
   ```

3. **SSH into the VM**:

   ```bash
   vagrant ssh
   ```

4. The shell will have these environment variables set automatically via
   `/etc/profile.d/copilot-proxy.sh`:

   ```text
    HTTP_PROXY=http://192.168.122.1:8080
    HTTPS_PROXY=http://192.168.122.1:8080
    ALL_PROXY=http://192.168.122.1:8080
   NO_PROXY=localhost,127.0.0.1,::1
   COPILOT_GITHUB_TOKEN=ghu_placeholder
   GH_TOKEN=ghu_placeholder
   GITHUB_TOKEN=ghu_placeholder
   ```

---

## Manual validation

Run each step inside the VM (`vagrant ssh`) to confirm the whole chain works.

### Check that the CA is trusted

```bash
curl -s https://api.github.com | head -5
# Should return JSON, not an SSL error.
```

### Check that the proxy is reachable

```bash
curl -sv --proxy "$HTTPS_PROXY" https://api.github.com 2>&1 | grep -E "Connected|issuer"
# The issuer should mention "mitmproxy".
```

### Check that Copilot CLI can use the placeholder token

```bash
env | grep -E 'HTTPS_PROXY|GH_TOKEN|COPILOT_GITHUB_TOKEN'
# You should see the proxy URL plus the placeholder token values from
# /etc/profile.d/copilot-proxy.sh.
```

### Check that the Copilot API host is covered by the add-on

```bash
curl -sv --proxy "$HTTPS_PROXY" https://api.individual.githubcopilot.com/models 2>&1 \
  | grep -E "HTTP/[0-9.]+|unauthorized"
# A 401 here usually means inject_token.py is not rewriting requests for
# api.individual.githubcopilot.com.
```

### Check Copilot CLI

```bash
copilot
# The CLI should not force you through /login if the placeholder token and
# proxy are wired correctly. Ask a trivial prompt, then confirm the request
# appears in the host-side mitmdump log.
```

---

## Security notes

- The **real token is never written inside the VM** or the `/vagrant`
  shared folder. It lives only in GNOME Keyring and in the mitmproxy
  process memory on the host.
- The injection script reads the token from GNOME Keyring when mitmdump
  starts. If you rotate the token, restart mitmdump.
- The mitmproxy CA gives the proxy the ability to read all HTTPS traffic
  from the VM. Only use this CA for the dedicated mitmproxy instance --
  do not import it into your host browser or other applications.
- The placeholder token `ghu_placeholder` is intentionally invalid.
  Even if someone obtains it, it cannot be used against the GitHub API.
