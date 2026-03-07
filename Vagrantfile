require "shellwords"

# Optional overrides:
#   VAGRANT_PROXY_HOST  - libvirt gateway IP mitmproxy listens on (default: 192.168.122.1)
#   VAGRANT_MITM_CA     - host path to the mitmproxy CA cert
#                         (default: ~/.mitmproxy/mitmproxy-ca-cert.pem)

PROXY_HOST      = ENV.fetch("VAGRANT_PROXY_HOST", "192.168.122.1")
PROXY_URL       = "http://#{PROXY_HOST}:8080"
MITM_CA         = ENV.fetch("VAGRANT_MITM_CA",
                    File.expand_path("~/.mitmproxy/mitmproxy-ca-cert.pem"))
SHELL_PROXY_URL = Shellwords.escape(PROXY_URL)

Vagrant.configure("2") do |config|
  config.vm.box     = "fedora/43-cloud-base"
  config.vm.box_url = "https://download.fedoraproject.org/pub/fedora/linux/releases/43/Cloud/x86_64/images/" \
                      "Fedora-Cloud-Base-Vagrant-libvirt-43-1.6.x86_64.vagrant.libvirt.box"
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
        SRC=/tmp/mitmproxy-ca-cert.pem
        DEST=/etc/pki/ca-trust/source/anchors/mitmproxy-ca-cert.pem

        if [ ! -f "$SRC" ]; then
          if [ -f "$DEST" ]; then
            echo "Source absent but CA already installed; skipping."
            exit 0
          fi
          echo "mitmproxy CA file not found at $SRC." >&2
          exit 1
        fi

        if [ -f "$DEST" ] && cmp -s "$SRC" "$DEST"; then
          echo "mitmproxy CA already up to date; skipping."
          exit 0
        fi

        cp "$SRC" "$DEST"
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
    inline: <<~SHELL
      set -euo pipefail
      cat > /etc/profile.d/copilot-proxy.sh <<'EOF'
# Injected by Vagrantfile - copilot-via-mitmproxy setup
export HTTP_PROXY=#{SHELL_PROXY_URL}
export HTTPS_PROXY=#{SHELL_PROXY_URL}
export ALL_PROXY=#{SHELL_PROXY_URL}
export NO_PROXY=localhost,127.0.0.1,::1

# Placeholder token; the real token is injected by the host mitmproxy.
export COPILOT_GITHUB_TOKEN=ghu_placeholder
export GH_TOKEN=ghu_placeholder
export GITHUB_TOKEN=ghu_placeholder
EOF
      chmod 644 /etc/profile.d/copilot-proxy.sh
      echo "Proxy environment written to /etc/profile.d/copilot-proxy.sh"
    SHELL
end
