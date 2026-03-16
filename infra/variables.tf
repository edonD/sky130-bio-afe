variable "project_name" {
  default = "bio-afe"
}

variable "region" {
  default = "us-east-1"
}

variable "instance_type" {
  description = "CPU instance for SPICE simulation (no GPU needed)"
  default     = "c6a.4xlarge"
}

variable "volume_size" {
  description = "Root EBS volume size in GB"
  default     = 50
}

variable "key_name" {
  description = "Name of the EC2 key pair for SSH access"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID to deploy into"
  type        = string
}

variable "subnet_id" {
  description = "Subnet ID to deploy into"
  type        = string
}

variable "security_group_id" {
  description = "Security group ID (SSH + outbound)"
  type        = string
}

variable "blocks" {
  description = "Block names to create instances for"
  type        = list(string)
  default     = ["bandgap", "inamp", "pga", "filter", "adc"]
}
