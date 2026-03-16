terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

# --- Ubuntu 24.04 LTS AMI (no GPU, just CPU) ---
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }

  filter {
    name   = "state"
    values = ["available"]
  }
}

# --- 5 EC2 instances, one per block ---
resource "aws_instance" "block" {
  for_each = toset(var.blocks)

  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  key_name               = var.key_name
  vpc_security_group_ids = [var.security_group_id]
  subnet_id              = var.subnet_id

  associate_public_ip_address = true

  root_block_device {
    volume_size = var.volume_size
    volume_type = "gp3"
    throughput  = 250
    iops        = 3000
  }

  user_data = templatefile("${path.module}/setup.sh", {
    block_name = each.key
  })

  tags = {
    Name    = "${var.project_name}-${each.key}"
    Project = var.project_name
    Block   = each.key
  }
}
