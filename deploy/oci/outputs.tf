output "instance_public_ip" {
  description = "Public IP of the TinyOraClaw instance"
  value       = oci_core_instance.tinyoraclaw.public_ip
}

output "ssh_command" {
  description = "SSH into the instance"
  value       = "ssh opc@${oci_core_instance.tinyoraclaw.public_ip}"
}

output "api_url" {
  description = "TinyClaw API endpoint"
  value       = "http://${oci_core_instance.tinyoraclaw.public_ip}:3777/api/queue/status"
}

output "sidecar_url" {
  description = "TinyOraClaw sidecar health endpoint"
  value       = "http://${oci_core_instance.tinyoraclaw.public_ip}:8100/api/health"
}

output "setup_log" {
  description = "Watch the setup progress"
  value       = "ssh opc@${oci_core_instance.tinyoraclaw.public_ip} -t 'tail -f /var/log/tinyoraclaw-setup.log'"
}

output "oracle_password" {
  description = "Generated Oracle DB password (save this!)"
  value       = local.oracle_password
  sensitive   = true
}

output "database_mode" {
  description = "Oracle Database mode used"
  value       = local.oracle_mode
}
