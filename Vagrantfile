################################################################
# Host-configurable values (all have safe defaults)
#
#   VAGRANT_PROXY_HOST   - libvirt gateway seen from the VM
#                          default: 192.168.122.1
#   VAGRANT_PROXY_PORT   - mitmproxy listen port on the host
#                          default: 8080
#   VAGRANT_MITM_CA      - absolute path to the mitmproxy CA cert
#                          on the HOST filesystem
#                          default: ~/.mitmproxy/mitmproxy-ca-cert.pem
#   VAGRANT_FEDORA_BOX   - local Vagrant box name
#                          default: fedora/43-cloud-base
#   VAGRANT_FEDORA_BOX_URL - official Fedora Cloud Base libvirt box URL
#                          default: Fedora 43 Cloud Base libvirt box
#   VAGRANT_COPILOT_TOKEN - placeholder token stored inside the VM;
#                          the real token is injected by the host proxy
#                          default: ghu_placeholder
################################################################

FEDORA_BOX = ENV.fetch("VAGRANT_FEDORA_BOX", "fedora/43-cloud-base")
FEDORA_BOX_URL = ENV.fetch(
  "VAGRANT_FEDORA_BOX_URL",
  "https://download.fedoraproject.org/pub/fedora/linux/releases/43/Cloud/x86_64/images/" \
  "Fedora-Cloud-Base-Vagrant-libvirt-43-1.6.x86_64.vagrant.libvirt.box"
)
PROXY_HOST  = ENV.fetch("VAGRANT_PROXY_HOST",  "192.168.122.1")
PROXY_PORT  = ENV.fetch("VAGRANT_PROXY_PORT",  "8080")
PROXY_URL   = "http://#{PROXY_HOST}:#{PROXY_PORT}"
MITM_CA     = ENV.fetch("VAGRANT_MITM_CA",
                File.expand_path("~/.mitmproxy/mitmproxy-ca-cert.pem"))
COPILOT_TOK = ENV.fetch("VAGRANT_COPILOT_TOKEN", "ghu_placeholder")

Vagrant.configure("2") do |config|
  config.vm.box = FEDORA_BOX
  config.vm.box_url = FEDORA_BOX_URL
  config.vm.hostname = "ai-notes-fedora43"

  config.vm.provider :libvirt do |libvirt|
    libvirt.driver = "kvm"
    libvirt.cpus = 2
    libvirt.memory = 4096
  end

  # ---- mitmproxy CA certificate ----------------------------------------
  # Only provision when the cert exists on the host so that `vagrant up`
  # works without mitmproxy installed.
  if File.exist?(MITM_CA)
    config.vm.provision "file",
      source:      MITM_CA,
      destination: "/tmp/mitmproxy-ca-cert.pem"

    config.vm.provision "shell",
      name: "install-mitmproxy-ca",
      inline: <<~SHELL
        set -euo pipefail
        if [ ! -f /tmp/mitmproxy-ca-cert.pem ]; then
          echo "mitmproxy CA file provisioning failed: /tmp/mitmproxy-ca-cert.pem is missing." >&2
          exit 1
        fi
        cp /tmp/mitmproxy-ca-cert.pem \
           /etc/pki/ca-trust/source/anchors/mitmproxy-ca-cert.pem
        update-ca-trust extract
        echo "mitmproxy CA installed into system trust store."
      SHELL
  else
    warn("Skipping mitmproxy CA provisioning because #{MITM_CA} was not found on the host.")
  end

  # ---- Proxy and token environment variables ---------------------------
  # Written to /etc/profile.d/ so they are available in every interactive
  # login shell (ssh, vagrant ssh, sudo -i, etc.).
  config.vm.provision "shell",
    name: "configure-proxy-env",
    env: {
      "PROXY_URL"   => PROXY_URL,
      "COPILOT_TOK" => COPILOT_TOK,
    },
    inline: <<~SHELL
      set -euo pipefail
      cat > /etc/profile.d/copilot-proxy.sh << EOF
# Injected by Vagrantfile - copilot-via-mitmproxy setup
export HTTP_PROXY="${PROXY_URL}"
export HTTPS_PROXY="${PROXY_URL}"
export ALL_PROXY="${PROXY_URL}"
export NO_PROXY="localhost,127.0.0.1,::1"

# Placeholder token; the real token is injected by the host mitmproxy.
export COPILOT_GITHUB_TOKEN="${COPILOT_TOK}"
export GH_TOKEN="${COPILOT_TOK}"
export GITHUB_TOKEN="${COPILOT_TOK}"
EOF
      chmod 644 /etc/profile.d/copilot-proxy.sh
      echo "Proxy environment written to /etc/profile.d/copilot-proxy.sh"
    SHELL
end
