# Vagrantfile for ai-first-pipeline K3s deployment
# -*- mode: ruby -*-
# vi: set ft=ruby :

Vagrant.configure("2") do |config|
  # Ubuntu 22.04 LTS (Jammy)
  #config.vm.box = "ubuntu/jammy64"
  config.vm.box = "cloud-image/ubuntu-24.04"
  config.vm.box_check_update = false

  # VM naming
  config.vm.hostname = "ai-pipeline-k3s"

  # Network configuration
  # Private network required for NFS with libvirt
  # config.vm.network "private_network", ip: "192.168.56.10"

  # Optional: Forward specific ports to host
  # Dashboard
  config.vm.network "forwarded_port", guest: 5000, host: 5000, host_ip: "127.0.0.1"

  # Emulator NodePorts (forwarding k3s NodePorts to host)
  # Note: NodePorts are dynamically assigned. Check with:
  #   vagrant ssh -c "kubectl get services -n ai-pipeline"
  # GitHub Emulator - HTTPS NodePort (check actual port)
  config.vm.network "forwarded_port", guest: 30783, host: 8443, host_ip: "127.0.0.1"
  # GitHub Emulator - HTTP NodePort
  config.vm.network "forwarded_port", guest: 32661, host: 8080, host_ip: "127.0.0.1"
  # Jira Emulator - HTTPS NodePort
  config.vm.network "forwarded_port", guest: 30872, host: 9443, host_ip: "127.0.0.1"
  # Jira Emulator - HTTP NodePort
  config.vm.network "forwarded_port", guest: 32359, host: 9080, host_ip: "127.0.0.1"
  # Jira Emulator - MCP Server NodePort
  config.vm.network "forwarded_port", guest: 30961, host: 8081, host_ip: "127.0.0.1"

  # Provider-specific configuration
  #config.vm.provider "virtualbox" do |vb|
  #  vb.name = "ai-pipeline-k3s"
  #  vb.memory = "8192"
  #  vb.cpus = 8

  #  # Enable nested virtualization if needed
  #  vb.customize ["modifyvm", :id, "--nested-hw-virt", "on"]
  #end

  #config.vm.provider "vmware_desktop" do |v|
  #  v.vmx["displayname"] = "ai-pipeline-k3s"
  #  v.vmx["memsize"] = "8192"
  #  v.vmx["numvcpus"] = "8"
  #end

  config.vm.provider "libvirt" do |lv|
    lv.memory = 8192
    lv.cpus = 8
    lv.nested = true
    lv.machine_virtual_size = 100  # 100GB disk
  end

  # Synced folder - the entire project
  # For libvirt, use NFS with NFSv4 and TCP (or rsync for one-way sync)
  config.vm.synced_folder ".", "/vagrant",
    type: "nfs",
    nfs_version: 4,
    nfs_udp: false

  # Auto-resize disk on every boot
  config.vm.provision "shell", run: "always", inline: <<-SHELL
    set -e
    echo "==> Checking and resizing disk if needed..."

    # Find the root partition device
    ROOT_PART=$(findmnt -n -o SOURCE /)
    ROOT_DISK=$(lsblk -no pkname $ROOT_PART)

    # Resize partition (if growpart is available, otherwise use parted)
    if command -v growpart >/dev/null 2>&1; then
      growpart /dev/$ROOT_DISK $(echo $ROOT_PART | grep -o '[0-9]*$') 2>/dev/null || true
    else
      # Install cloud-guest-utils for growpart if not present
      apt-get update -qq && apt-get install -y -qq cloud-guest-utils 2>/dev/null || true
      growpart /dev/$ROOT_DISK $(echo $ROOT_PART | grep -o '[0-9]*$') 2>/dev/null || true
    fi

    # Resize filesystem
    resize2fs $ROOT_PART 2>/dev/null || true

    echo "==> Disk resize check complete"
    df -h /
  SHELL

  # Provision: Update system and install prerequisites
  config.vm.provision "shell", inline: <<-SHELL
    set -e

    echo "==> Updating system packages..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get upgrade -y -qq

    echo "==> Installing prerequisites..."
    apt-get install -y -qq \
      curl \
      wget \
      git \
      vim \
      jq \
      ca-certificates \
      gnupg \
      lsb-release \
      net-tools \
      dnsutils \
      iputils-ping \
      python3-pip \
      python3-venv \
      build-essential \
      docker.io

    echo "==> Starting and enabling docker..."
    systemctl start docker
    systemctl enable docker
    usermod -aG docker vagrant

    # Install uv for Python package management
    echo "==> Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh

    echo "==> Setting bash as default shell for vagrant user..."
    chsh -s /bin/bash vagrant

    echo "==> Configuring PATH for vagrant user..."
    # Create ~/bin directory if it doesn't exist
    sudo -u vagrant mkdir -p /home/vagrant/bin

    # Add ~/bin to PATH in .bashrc if not already present
    if ! grep -q 'export PATH="$HOME/bin:$PATH"' /home/vagrant/.bashrc; then
      echo 'export PATH="$HOME/bin:$PATH"' >> /home/vagrant/.bashrc
    fi

    echo "==> System preparation complete"
    echo "VM IP: 192.168.56.10"
    echo "Next: Run /vagrant/deploy/scripts/01-install-k3s.sh"
  SHELL
end
