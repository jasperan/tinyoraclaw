# OCI Generative AI Integration for TinyOraClaw

This directory provides **OCI Generative AI** integration for TinyOraClaw via the [`oci-openai`](https://pypi.org/project/oci-openai/) Python library. It exposes OCI GenAI as an OpenAI-compatible endpoint so TinyOraClaw (or any OpenAI-compatible client) can use OCI-hosted models without code changes.

## Prerequisites

- **Python 3.11+**
- **OCI CLI configured** with a valid profile in `~/.oci/config`
  - [OCI CLI installation guide](https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/cliinstall.htm)
- **OCI Compartment** with Generative AI service enabled

## Quick Start

```bash
# 1. Install dependencies
cd oci-genai
pip install -r requirements.txt

# 2. Set required environment variables
export OCI_COMPARTMENT_ID="ocid1.compartment.oc1..your-compartment-ocid"

# 3. Start the proxy
python proxy.py
# Proxy runs at http://localhost:9999/v1
```

Then configure TinyOraClaw (or any OpenAI-compatible client) to use `http://localhost:9999/v1` as the base URL with any API key value (e.g., `oci-genai`).

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OCI_PROFILE` | `DEFAULT` | OCI config profile name from `~/.oci/config` |
| `OCI_REGION` | `us-chicago-1` | OCI region for the GenAI service endpoint |
| `OCI_COMPARTMENT_ID` | *(required)* | OCI compartment OCID where GenAI is enabled |
| `OCI_PROXY_PORT` | `9999` | Port for the local OpenAI-compatible proxy |

## Files

| File | Purpose |
|------|---------|
| `oci_client.py` | OCI GenAI client wrapper — creates sync/async OpenAI-compatible clients authenticated via OCI User Principal Auth |
| `proxy.py` | Local HTTP proxy that accepts OpenAI API calls and forwards them to OCI GenAI |
| `requirements.txt` | Python dependencies (`oci-openai`) |

## Using with TinyOraClaw

The default LLM backend for TinyOraClaw remains **Anthropic/OpenAI** via API keys. OCI GenAI is an **optional** alternative. To use it:

1. Start the proxy (`python proxy.py`)
2. Configure the LLM provider in your agent settings to point to `http://localhost:9999/v1`
3. Use any OCI GenAI model (e.g., `meta.llama-3.3-70b-instruct`, `cohere.command-r-plus`)

## Available Models

OCI GenAI provides access to several model families. Check [OCI GenAI documentation](https://docs.oracle.com/en-us/iaas/Content/generative-ai/home.htm) for the latest list of supported models and regions.

## Further Reading

- [OCI Generative AI Documentation](https://docs.oracle.com/en-us/iaas/Content/generative-ai/home.htm)
- [oci-openai on PyPI](https://pypi.org/project/oci-openai/)
- [OCI CLI Configuration](https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/cliinstall.htm)
