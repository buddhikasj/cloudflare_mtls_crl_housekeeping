# CRL Housekeeping Cron Container

A Cloudflare Workers application that automatically maintains Certificate Revocation Lists (CRLs) using a scheduled container. This project runs a Python script inside a container on a configurable cron schedule to fetch, validate, and store CRLs in Cloudflare Workers KV.

## Features

- **Automated CRL Updates**: Periodically fetches and refreshes CRLs from configured sources
- **Health Monitoring**: Tracks CRL freshness and reports stale or missing CRLs
- **Automatic Cleanup**: Removes expired/inactive CRL data beyond retention period
- **Container-based**: Uses Cloudflare Containers for reliable execution
- **KV Storage**: Stores CRL data and metadata in Cloudflare Workers KV
- **Flexible Configuration**: Environment-based configuration for multiple CRL sources
- **Comprehensive Logging**: Detailed logs for monitoring and debugging

## What It Does

This container performs three main tasks:

1. **CRL Updates**: Fetches CRLs from configured sources and stores them in KV with metadata
2. **Health Checks**: Monitors CRL age and status, alerting on stale or missing CRLs
3. **Cleanup**: Removes old CRL data for inactive sources beyond the retention period

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Cloudflare Workers (TypeScript)                │
│  - Scheduled Trigger (Cron)                     │
│  - Durable Object Container Management          │
└────────────────┬────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────┐
│  Container (Python)                             │
│  - Fetch CRLs from sources                      │
│  - Parse and validate CRL data                  │
│  - Health monitoring                            │
│  - Cleanup old data                             │
└────────────────┬────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────┐
│  Cloudflare Workers KV                          │
│  - CRL data storage                             │
│  - Metadata and health status                   │
└─────────────────────────────────────────────────┘
```

## Prerequisites

- Cloudflare account with Workers, Durable Objects, Containers, and KV enabled
- Node.js and npm installed
- Wrangler CLI installed (`npm install -g wrangler`)
- Python 3.11+ (for local testing)

## Technology Stack

- **TypeScript**: Worker orchestration and cron scheduling
- **Python**: CRL fetching and processing
- **cryptography**: Industry-standard library for parsing X.509 CRLs
- **aiohttp**: Async HTTP client for fetching CRLs
- **Cloudflare Workers KV**: Persistent storage for CRL data

## Setup Instructions

### 1. Install Dependencies

```bash
npm install
```

### 2. Create KV Namespace

Create a KV namespace for storing CRL data:

```bash
wrangler kv:namespace create "CRL_NAMESPACE"
```

Note the namespace ID returned - you'll need it for configuration.

### 3. Configure Environment Variables

Copy the template configuration file:

```bash
cp wrangler.jsonc.template wrangler.jsonc
```

Edit `wrangler.jsonc` and replace the placeholder values:

```jsonc
"vars": {
  "CLOUDFLARE_ACCOUNT_ID": "your-account-id",
  "KV_NAMESPACE_ID": "your-kv-namespace-id",
  "CRL_URLS": "",  // Optional: comma-separated additional CRL URLs
  "MAX_CRL_AGE_HOURS": "24",
  "RETENTION_DAYS": "7",
  "ENABLE_HEALTH_CHECK": "true",
  "ENABLE_CLEANUP": "false"
}
```

Also update the KV namespace binding:

```jsonc
"kv_namespaces": [
  {
    "binding": "CRL_NAMESPACE",
    "id": "your-kv-namespace-id"
  }
]
```

### 4. Create API Token

Create a Cloudflare API token with the following permissions:

1. Go to [Cloudflare API Tokens](https://dash.cloudflare.com/profile/api-tokens)
2. Click "Create Token"
3. Configure permissions:
   - **Account** - `Workers KV Storage:Edit`
4. Set appropriate TTL and conditions
5. Click "Continue to summary" and "Create Token"
6. Copy the token (you won't see it again)

### 5. Set Up Secret

Configure the API token as a secret:

```bash
wrangler secret put WS_CLOUDFLARE_API_TOKEN
```

Paste your API token when prompted.

### 6. Deploy the Application

Deploy your Worker and Container to Cloudflare:

```bash
npm run deploy
```

## Configuration

### Cron Schedule

Configure your execution schedule by editing `triggers.crons` in `wrangler.jsonc`:

```jsonc
"triggers": {
  "crons": ["0 */6 * * *"]
}
```

**Common cron schedule examples:**
- `"0 */6 * * *"` - Every 6 hours (default)
- `"0 */4 * * *"` - Every 4 hours
- `"0 */2 * * *"` - Every 2 hours
- `"0 2 * * *"` - Daily at 2 AM UTC
- `"0 0 * * 0"` - Weekly on Sunday at midnight



### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `CLOUDFLARE_ACCOUNT_ID` | Your Cloudflare account ID | Required |
| `KV_NAMESPACE_ID` | KV namespace ID for storage | Required |
| `WS_CLOUDFLARE_API_TOKEN` | API token (secret) | Required |


## Usage

### Manual Trigger

You can manually trigger the cron job using the Cloudflare dashboard or via Wrangler:

```bash
wrangler dev
```

Then trigger the scheduled event from the dashboard.

### Check Health Status

Access the health endpoint:

```bash
curl https://your-worker.workers.dev/health
```

Response:
```json
{
  "status": "ok",
  "service": "CRL Housekeeping Cron Container",
  "timestamp": "2025-11-12T04:00:00.000Z"
}
```

## Monitoring

### View Logs

Monitor Worker execution logs:

```bash
wrangler tail
```

### Check CRL Status

CRL metadata is stored in KV with keys prefixed by `CRL_META_`. You can inspect this data:

```bash
wrangler kv:key get --namespace-id=YOUR_KV_NAMESPACE_ID "CRL_META_..."
```

### Log Format

The container provides structured logging:

```
[FETCH] Fetching CRL: DigiCert Global G2 TLS RSA SHA256 2020 CA1
[FETCH] Downloaded 12345 bytes in 0.45s
[UPDATE] Stored metadata for DigiCert Global G2 TLS RSA SHA256 2020 CA1
[HEALTH] DigiCert Global G2 TLS RSA SHA256 2020 CA1: healthy (age: 2.3 hours)
```

## Troubleshooting

### Common Issues

**Missing API Token**
- Error: `❌ WS_CLOUDFLARE_API_TOKEN not set`
- Solution: Set the secret using `wrangler secret put WS_CLOUDFLARE_API_TOKEN`

**KV Access Issues**
- Error: `KV GET/PUT failed`
- Solution: Verify KV namespace ID and API token permissions

**CRL Fetch Failures**
- Error: `HTTP 404` or timeout errors
- Solution: Verify CRL URLs are accessible and correct

**Container Not Starting**
- Solution: Check container logs in Cloudflare dashboard, verify Dockerfile builds successfully

### Useful Commands

```bash
# View Worker logs
wrangler tail

# List secrets
wrangler secret list

# List KV namespaces
wrangler kv:namespace list

# View KV keys
wrangler kv:key list --namespace-id=YOUR_KV_NAMESPACE_ID

# Get specific KV value
wrangler kv:key get --namespace-id=YOUR_KV_NAMESPACE_ID "CRL_META_..."

# Delete old data
wrangler kv:key delete --namespace-id=YOUR_KV_NAMESPACE_ID "KEY_NAME"
```

## Development

### Local Testing

Test the Python script locally:

```bash
cd container_src
python3 -m venv venv
source venv/bin/activate
pip install -r ../requirements.txt

# Set environment variables
export CLOUDFLARE_ACCOUNT_ID="your-account-id"
export KV_NAMESPACE_ID="your-kv-namespace-id"
export WS_CLOUDFLARE_API_TOKEN="your-token"

python container_entry.py
```

### Modifying CRL Sources

Edit `container_src/container_entry.py` to add or modify CRL sources:

```python
CRL_SOURCES.append({
    'name': 'Your CA Name',
    'url': 'http://example.com/your-ca.crl',
    'enabled': True
})
```

### CRL Parsing

The container uses the **cryptography** library for robust CRL parsing:

- **Accurate parsing**: Proper ASN.1/DER decoding of X.509 CRL structure
- **Date extraction**: Extracts `thisUpdate` and `nextUpdate` timestamps
- **Revoked certificates**: Counts and samples revoked certificate serial numbers
- **Error handling**: Graceful handling of malformed or invalid CRLs

The `parse_crl()` function returns:
- `next_update`: When the CRL should be refreshed
- `this_update`: When the CRL was last published
- `revoked_count`: Total number of revoked certificates
- `revoked_serials_sample`: Sample serial numbers for verification

## Integration with CRL Worker

This housekeeping container works alongside the CRL verification worker (in `../CRL worker/access-crl-worker-template/`):

1. **Housekeeping Container**: Periodically updates CRLs in KV
2. **CRL Worker**: Checks incoming requests against stored CRLs

Both components share the same KV namespace and key format for seamless integration.

## Security Considerations

- API tokens are stored as Wrangler secrets (encrypted)
- Container runs as non-root user
- CRL data stored in KV has configurable retention
- All communications use HTTPS/secure protocols
- Logs don't expose sensitive data

## Learn More

- [Cloudflare Workers Documentation](https://developers.cloudflare.com/workers/)
- [Cloudflare Containers Documentation](https://developers.cloudflare.com/containers/)
- [Cloudflare Workers KV Documentation](https://developers.cloudflare.com/kv/)
- [Cloudflare Durable Objects Documentation](https://developers.cloudflare.com/durable-objects/)
- [Wrangler CLI Documentation](https://developers.cloudflare.com/workers/wrangler/)

## License

This project follows the same license as the reference implementation.
