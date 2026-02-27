resource "oci_core_vcn" "tinyoraclaw" {
  compartment_id = var.compartment_ocid
  display_name   = "tinyoraclaw-vcn"
  cidr_blocks    = [var.vcn_cidr]
  dns_label      = "tinyvcn"
}

resource "oci_core_internet_gateway" "tinyoraclaw" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.tinyoraclaw.id
  display_name   = "tinyoraclaw-igw"
  enabled        = true
}

resource "oci_core_route_table" "tinyoraclaw" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.tinyoraclaw.id
  display_name   = "tinyoraclaw-rt"

  route_rules {
    destination       = "0.0.0.0/0"
    network_entity_id = oci_core_internet_gateway.tinyoraclaw.id
  }
}

resource "oci_core_security_list" "tinyoraclaw" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.tinyoraclaw.id
  display_name   = "tinyoraclaw-sl"

  # Allow all egress
  egress_security_rules {
    destination = "0.0.0.0/0"
    protocol    = "all"
    stateless   = false
  }

  # SSH
  ingress_security_rules {
    source    = "0.0.0.0/0"
    protocol  = "6"
    stateless = false
    tcp_options {
      min = 22
      max = 22
    }
  }

  # TinyClaw API (Hono)
  ingress_security_rules {
    source    = "0.0.0.0/0"
    protocol  = "6"
    stateless = false
    tcp_options {
      min = 3777
      max = 3777
    }
  }

  # TinyOraClaw Sidecar API
  ingress_security_rules {
    source    = "0.0.0.0/0"
    protocol  = "6"
    stateless = false
    tcp_options {
      min = 8100
      max = 8100
    }
  }

  # ICMP
  ingress_security_rules {
    source    = "0.0.0.0/0"
    protocol  = "1"
    stateless = false
    icmp_options {
      type = 3
      code = 4
    }
  }
}

resource "oci_core_subnet" "tinyoraclaw" {
  compartment_id             = var.compartment_ocid
  vcn_id                     = oci_core_vcn.tinyoraclaw.id
  display_name               = "tinyoraclaw-subnet"
  cidr_block                 = cidrsubnet(var.vcn_cidr, 8, 1)
  dns_label                  = "tinysub"
  route_table_id             = oci_core_route_table.tinyoraclaw.id
  security_list_ids          = [oci_core_security_list.tinyoraclaw.id]
  prohibit_public_ip_on_vnic = false
}
