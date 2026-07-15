# Vagrantfile for ai-first-pipeline K3s deployment
# -*- mode: ruby -*-
# vi: set ft=ruby :

Vagrant.configure("2") do |config|

  # ── Primary VM: ai-pipeline-k3s ──────────────────────────────────────
  config.vm.define "ai-pipeline", primary: true do |pipeline|
    pipeline.vm.box = "cloud-image/ubuntu-24.04"
    pipeline.vm.box_check_update = false
    pipeline.vm.hostname = "ai-pipeline-k3s"


    pipeline.vm.provider "libvirt" do |lv|
      lv.memory = 32768
      lv.cpus = 8
      lv.nested = true
      lv.machine_virtual_size = 100  # 100GB disk
    end

    # Synced folder - the entire project
    pipeline.vm.synced_folder ".", "/vagrant",
      type: "nfs",
      nfs_version: 4,
      nfs_udp: false

    # Auto-resize disk on every boot
    pipeline.vm.provision "shell", run: "always", inline: <<-SHELL
      set -e
      echo "==> Checking and resizing disk if needed..."

      ROOT_PART=$(findmnt -n -o SOURCE /)
      ROOT_DISK=$(lsblk -no pkname $ROOT_PART)

      if command -v growpart >/dev/null 2>&1; then
        growpart /dev/$ROOT_DISK $(echo $ROOT_PART | grep -o '[0-9]*$') 2>/dev/null || true
      else
        apt-get update -qq && apt-get install -y -qq cloud-guest-utils 2>/dev/null || true
        growpart /dev/$ROOT_DISK $(echo $ROOT_PART | grep -o '[0-9]*$') 2>/dev/null || true
      fi

      resize2fs $ROOT_PART 2>/dev/null || true

      echo "==> Disk resize check complete"
      df -h /
    SHELL

    # Provision: Update system and install prerequisites
    pipeline.vm.provision "shell", inline: <<-SHELL
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

      echo "==> Installing uv..."
      curl -LsSf https://astral.sh/uv/install.sh | sh

      echo "==> Setting bash as default shell for vagrant user..."
      chsh -s /bin/bash vagrant

      echo "==> Configuring PATH for vagrant user..."
      sudo -u vagrant mkdir -p /home/vagrant/bin

      if ! grep -q 'export PATH="$HOME/bin:$PATH"' /home/vagrant/.bashrc; then
        echo 'export PATH="$HOME/bin:$PATH"' >> /home/vagrant/.bashrc
      fi

      echo "==> System preparation complete"
      echo "Next: Run /vagrant/deploy/scripts/01-install-k3s.sh"
    SHELL

    # Install interactive agent and cluster-debugging tools. This named
    # provisioner can also be rerun with:
    # vagrant provision --provision-with development-tools
    pipeline.vm.provision "development-tools", type: "shell",
      path: "deploy/scripts/00-install-vagrant-tools.sh",
      args: ["vagrant"]
  end

end
