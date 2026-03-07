Vagrant.configure("2") do |config|
  config.vm.box = "cloud-image/fedora-43"
  config.vm.hostname = "ai-notes-fedora43"

  config.vm.provider :libvirt do |libvirt|
    libvirt.driver = "kvm"
    libvirt.cpus = 2
    libvirt.memory = 4096
  end
end
