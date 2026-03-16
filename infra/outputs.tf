output "instances" {
  description = "Block name -> public IP"
  value = {
    for name, inst in aws_instance.block :
    name => inst.public_ip
  }
}

output "ssh_commands" {
  description = "SSH commands for each block instance"
  value = {
    for name, inst in aws_instance.block :
    name => "ssh -i ~/.ssh/${var.key_name}.pem ubuntu@${inst.public_ip}"
  }
}

output "ami_id" {
  value       = data.aws_ami.ubuntu.id
  description = "AMI used"
}
