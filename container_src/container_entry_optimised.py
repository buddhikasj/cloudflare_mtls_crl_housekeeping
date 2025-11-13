import os
import json
import logging
from datetime import datetime, timedelta
import asyncio
import aiohttp
from typing import Dict, List, Optional, Tuple
import base64
import hashlib
from cryptography import x509
from cryptography.hazmat.backends import default_backend

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration from environment variables
KV_NAMESPACE_ID = os.getenv('KV_NAMESPACE_ID')
LARGE_CRL_QUEUE_ID = os.getenv('LARGE_CRL_QUEUE_ID')  # Separate namespace for large CRL queue
CLOUDFLARE_ACCOUNT_ID = os.getenv('CLOUDFLARE_ACCOUNT_ID')
API_TOKEN = os.getenv('WS_CLOUDFLARE_API_TOKEN')
ENABLE_QUEUE_PROCESSING = os.getenv('ENABLE_QUEUE_PROCESSING', 'true').lower() == 'true'



def get_crl_key(crl_url: str) -> str:
    """Generate KV key for a CRL"""
    return f"CRL_{base64.b64encode(crl_url.encode()).decode()}"

def get_crl_metadata_key(crl_url: str) -> str:
    """Generate KV key for CRL metadata"""
    return f"CRL_{base64.b64encode(crl_url.encode()).decode()}"

async def kv_get(key: str, namespace_id: str = None) -> Optional[str]:
    """Get value from Cloudflare KV"""
    ns_id = namespace_id or KV_NAMESPACE_ID
    url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/storage/kv/namespaces/{ns_id}/values/{key}"
    headers = {'Authorization': f'Bearer {API_TOKEN}'}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    return await response.text()
                elif response.status == 404:
                    return None
                else:
                    logger.error(f"KV GET failed: {response.status}")
                    return None
    except Exception as e:
        logger.error(f"Error getting KV value: {e}")
        return None

async def kv_put(key: str, value: str, expiration_ttl: Optional[int] = None, namespace_id: str = None) -> bool:
    """Put value into Cloudflare KV"""
    ns_id = namespace_id or KV_NAMESPACE_ID
    url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/storage/kv/namespaces/{ns_id}/values/{key}"
    headers = {'Authorization': f'Bearer {API_TOKEN}', 'Content-Type': 'text/plain'}
    
    if expiration_ttl:
        url += f"?expiration_ttl={expiration_ttl}"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.put(url, headers=headers, data=value) as response:
                return response.status in [200, 201]
    except Exception as e:
        logger.error(f"Error putting KV value: {e}")
        return False

async def kv_delete(key: str, namespace_id: str = None) -> bool:
    """Delete value from Cloudflare KV"""
    ns_id = namespace_id or KV_NAMESPACE_ID
    url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/storage/kv/namespaces/{ns_id}/values/{key}"
    headers = {'Authorization': f'Bearer {API_TOKEN}'}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.delete(url, headers=headers) as response:
                return response.status == 200
    except Exception as e:
        logger.error(f"Error deleting KV value: {e}")
        return False

async def kv_list(prefix: str = None, namespace_id: str = None) -> List[Dict]:
    """List keys in Cloudflare KV"""
    ns_id = namespace_id or KV_NAMESPACE_ID
    url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/storage/kv/namespaces/{ns_id}/keys"
    if prefix:
        url += f"?prefix={prefix}"
    
    headers = {'Authorization': f'Bearer {API_TOKEN}'}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get('result', [])
                return []
    except Exception as e:
        logger.error(f"Error listing KV keys: {e}")
        return []

def parse_crl(crl_data: bytes) -> Tuple[Optional[datetime], Optional[datetime], List[str]]:
    """
    Parse CRL using cryptography library
    
    Returns:
        Tuple of (next_update, this_update, revoked_serials_list)
        revoked_serials_list: ["SERIAL_HEX", ...]
    """
    try:
        # Parse CRL using cryptography library
        crl = x509.load_der_x509_crl(crl_data, default_backend())
        
        # Extract dates
        this_update = crl.last_update
        next_update = crl.next_update
        
        # Get all revoked certificates as a list/set
        revoked_certs = list(crl)
        revoked_serials_list = [
            format(cert.serial_number, 'X')
            for cert in revoked_certs
        ]
        
        revoked_count = len(revoked_serials_list)
        logger.info(f"CRL parsed successfully: {revoked_count} revoked certificates")
        
        # Log sample for debugging
        sample_serials = revoked_serials_list[:3]
        if sample_serials:
            logger.info(f"Sample revoked serials: {', '.join(sample_serials)}...")
        
        return next_update, this_update, revoked_serials_list
        
    except Exception as e:
        logger.error(f"Failed to parse CRL: {e}")
        return None, None, []

async def fetch_and_parse_crl(crl_source: Dict) -> Dict:
    """Fetch and parse a CRL from the given source"""
    logger.info(f"[FETCH] Fetching CRL: {crl_source['name']}")
    start_time = datetime.now()
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(crl_source['url'], timeout=aiohttp.ClientTimeout(total=60)) as response:
                if response.status != 200:
                    raise Exception(f"HTTP {response.status}")
                
                crl_data = await response.read()
                fetch_duration = (datetime.now() - start_time).total_seconds()
                logger.info(f"[FETCH] Downloaded {len(crl_data)} bytes in {fetch_duration:.2f}s")
                
                # Calculate SHA-256 hash of the CRL data
                crl_hash = hashlib.sha256(crl_data).hexdigest().upper()
                
                next_update, this_update, revoked_serials_list = parse_crl(crl_data)
                
                return {
                    'success': True,
                    'fetched_at': datetime.now().isoformat(),
                    'bytes': len(crl_data),
                    'fetch_duration_ms': int(fetch_duration * 1000),
                    'revoked_count': len(revoked_serials_list),
                    'next_update': next_update.isoformat() if next_update else None,
                    'this_update': this_update.isoformat() if this_update else None,
                    'crl_hash': crl_hash,
                    'revoked_serials_list': revoked_serials_list
                }
    except Exception as e:
        fetch_duration = (datetime.now() - start_time).total_seconds()
        logger.error(f"[FETCH] Failed: {e}")
        return {
            'success': False,
            'error': str(e),
            'fetch_duration_ms': int(fetch_duration * 1000),
            'fetched_at': datetime.now().isoformat()
        }




async def process_queued_crls() -> Dict:
    """Process CRLs from the LARGE_CRL_QUEUE"""
    logger.info('[QUEUE] Starting queued CRL processing')
    
    if not LARGE_CRL_QUEUE_ID:
        logger.warning('[QUEUE] LARGE_CRL_QUEUE_ID not configured, skipping queue processing')
        return {'processed_count': 0, 'failed_count': 0, 'skipped_count': 0}
    
    processed_count = 0
    failed_count = 0
    skipped_count = 0
    
    try:
        # List all queued CRLs with prefix "QUEUE_"
        queue_keys = await kv_list(prefix='QUEUE_', namespace_id=LARGE_CRL_QUEUE_ID)
        logger.info(f'[QUEUE] Found {len(queue_keys)} queued CRLs')
        
        for key_info in queue_keys:
            queue_key = key_info['name']
            
            try:
                # Get queue entry
                queue_entry_str = await kv_get(queue_key, namespace_id=LARGE_CRL_QUEUE_ID)
                if not queue_entry_str:
                    logger.warning(f'[QUEUE] Empty queue entry: {queue_key}')
                    skipped_count += 1
                    continue
                
                queue_entry = json.loads(queue_entry_str)
                
                # Check if already processed
                if queue_entry.get('processedByHousekeeping'):
                    logger.info(f'[QUEUE] Already processed: {queue_entry["url"]}')
                    skipped_count += 1
                    continue
                
                logger.info(f'[QUEUE] Processing: {queue_entry["url"]} ({queue_entry["sizeMB"]}MB)')
                
                # Fetch and parse the CRL
                crl_source = {
                    'name': f'Queued CRL - {queue_entry["url"].split("/")[-1]}',
                    'url': queue_entry['url']
                }
                
                result = await fetch_and_parse_crl(crl_source)
                
                if result['success'] and result.get('revoked_serials_list') is not None:
                    # Store parsed CRL in main namespace using the kvKey from queue entry
                    crl_payload = {
                        'next_update': result['next_update'],
                        'this_update': result['this_update'],
                        'crl_hash': result['crl_hash'],
                        'revokedSerialNumbers': result['revoked_serials_list']
                    }
                    
                    # Use the kvKey from queue entry (e.g., "CRL_aHR0cDo...")
                    crl_kv_key = queue_entry['kvKey']
                    await kv_put(crl_kv_key, json.dumps(crl_payload))
                    
                    logger.info(f'[QUEUE] ✓ Stored CRL: {crl_kv_key} ({result["revoked_count"]} revoked certs, hash: {result["crl_hash"][:16]}...)')
                    
                    # Update queue entry to mark as processed
                    queue_entry['processedByHousekeeping'] = True
                    queue_entry['processedAt'] = datetime.now().isoformat()
                    queue_entry['revoked_count'] = result['revoked_count']
                    queue_entry['crl_hash'] = result['crl_hash']
                    queue_entry['next_update'] = result['next_update']
                    queue_entry['this_update'] = result['this_update']
                    
                    await kv_put(queue_key, json.dumps(queue_entry), namespace_id=LARGE_CRL_QUEUE_ID)
                    
                    processed_count += 1
                else:
                    logger.error(f'[QUEUE] ✗ Failed to parse CRL: {queue_entry["url"]}')
                    failed_count += 1
                    
                    # Update queue entry with error
                    queue_entry['processedByHousekeeping'] = False
                    queue_entry['processedAt'] = datetime.now().isoformat()
                    queue_entry['error'] = result.get('error', 'Unknown error')
                    await kv_put(queue_key, json.dumps(queue_entry), namespace_id=LARGE_CRL_QUEUE_ID)
                    
            except Exception as e:
                logger.error(f'[QUEUE] Error processing {queue_key}: {e}')
                failed_count += 1
        
        logger.info(f'[QUEUE] Complete: {processed_count} processed, {failed_count} failed, {skipped_count} skipped')
        return {
            'processed_count': processed_count,
            'failed_count': failed_count,
            'skipped_count': skipped_count,
            'total_queued': len(queue_keys)
        }
        
    except Exception as e:
        logger.error(f'[QUEUE] Fatal error: {e}')
        return {
            'processed_count': processed_count,
            'failed_count': failed_count,
            'skipped_count': skipped_count,
            'error': str(e)
        }

async def refresh_existing_crls() -> Dict:
    """Refresh existing CRLs in the namespace by checking for updates"""
    logger.info('[REFRESH] Starting CRL refresh check')
    
    updated_count = 0
    unchanged_count = 0
    failed_count = 0
    
    try:
        # List all CRL keys from the main namespace
        crl_keys = await kv_list(prefix='CRL_', namespace_id=KV_NAMESPACE_ID)
        logger.info(f'[REFRESH] Found {len(crl_keys)} CRLs to check')
        
        for key_info in crl_keys:
            crl_key = key_info['name']
            
            try:
                # Decode the URL from the key (remove "CRL_" prefix and base64 decode)
                if not crl_key.startswith('CRL_'):
                    logger.warning(f'[REFRESH] Invalid key format: {crl_key}')
                    continue
                
                encoded_url = crl_key[4:]  # Remove "CRL_" prefix
                crl_url = base64.b64decode(encoded_url).decode('utf-8')
                
                logger.info(f'[REFRESH] Checking: {crl_url}')
                
                # Get current stored CRL data
                stored_crl_str = await kv_get(crl_key, namespace_id=KV_NAMESPACE_ID)
                if not stored_crl_str:
                    logger.warning(f'[REFRESH] No stored data for: {crl_url}')
                    failed_count += 1
                    continue
                
                stored_crl = json.loads(stored_crl_str)
                stored_hash = stored_crl.get('crl_hash')
                
                if not stored_hash:
                    logger.warning(f'[REFRESH] No hash in stored CRL: {crl_url}')
                    failed_count += 1
                    continue
                
                # Download the CRL
                async with aiohttp.ClientSession() as session:
                    async with session.get(crl_url, timeout=aiohttp.ClientTimeout(total=60)) as response:
                        if response.status != 200:
                            logger.error(f'[REFRESH] Failed to download CRL (HTTP {response.status}): {crl_url}')
                            failed_count += 1
                            continue
                        
                        crl_data = await response.read()
                        logger.info(f'[REFRESH] Downloaded {len(crl_data)} bytes from {crl_url}')
                
                # Calculate hash of downloaded CRL
                new_hash = hashlib.sha256(crl_data).hexdigest().upper()
                
                # Compare hashes
                if new_hash == stored_hash:
                    logger.info(f'[REFRESH] ✓ Unchanged: {crl_url} (hash: {new_hash[:16]}...)')
                    unchanged_count += 1
                else:
                    logger.info(f'[REFRESH] ⟳ Update detected: {crl_url}')
                    logger.info(f'[REFRESH]   Old hash: {stored_hash[:16]}...')
                    logger.info(f'[REFRESH]   New hash: {new_hash[:16]}...')
                    
                    # Parse the new CRL
                    next_update, this_update, revoked_serials_list = parse_crl(crl_data)
                    
                    # Update the stored CRL
                    crl_payload = {
                        'next_update': next_update.isoformat() if next_update else None,
                        'this_update': this_update.isoformat() if this_update else None,
                        'crl_hash': new_hash,
                        'revokedSerialNumbers': revoked_serials_list
                    }
                    
                    await kv_put(crl_key, json.dumps(crl_payload), namespace_id=KV_NAMESPACE_ID)
                    logger.info(f'[REFRESH] ✓ Updated: {crl_url} ({len(revoked_serials_list)} revoked certs)')
                    updated_count += 1
                    
            except Exception as e:
                logger.error(f'[REFRESH] Error processing {crl_key}: {e}')
                failed_count += 1
        
        logger.info(f'[REFRESH] Complete: {updated_count} updated, {unchanged_count} unchanged, {failed_count} failed')
        return {
            'updated_count': updated_count,
            'unchanged_count': unchanged_count,
            'failed_count': failed_count,
            'total_checked': len(crl_keys)
        }
        
    except Exception as e:
        logger.error(f'[REFRESH] Fatal error: {e}')
        return {
            'updated_count': updated_count,
            'unchanged_count': unchanged_count,
            'failed_count': failed_count,
            'error': str(e)
        }

async def main():
    """Main function"""
    logger.info("🚀 Starting CRL Housekeeping Container")
    logger.info(f"=== CRL HOUSEKEEPING STARTED at {datetime.now().isoformat()} ===")
    
    if not all([API_TOKEN, KV_NAMESPACE_ID, CLOUDFLARE_ACCOUNT_ID]):
        logger.error("❌ Missing required environment variables")
        return False
    
    results = {'timestamp': datetime.now().isoformat(), 'queue': None, 'refresh': None}
    
    try:
        # Process queued large CRLs first (priority)
        if ENABLE_QUEUE_PROCESSING:
            logger.info('[STEP 1] Processing queued large CRLs...')
            results['queue'] = await process_queued_crls()
            logger.info(f"[STEP 1] Complete: {results['queue']['processed_count']} processed, {results['queue']['failed_count']} failed")
        
        # Refresh existing CRLs
        logger.info('[STEP 2] Refreshing existing CRLs...')
        results['refresh'] = await refresh_existing_crls()
        logger.info(f"[STEP 2] Complete: {results['refresh']['updated_count']} updated, {results['refresh']['unchanged_count']} unchanged")
        
        logger.info("✅ CRL Housekeeping completed successfully")
        print("\n" + "="*60)
        print("📊 CRL HOUSEKEEPING SUMMARY")
        print("="*60)
        if ENABLE_QUEUE_PROCESSING and results['queue']:
            print(f"Queue:   {results['queue']['processed_count']}/{results['queue']['total_queued']} processed")
        if results['refresh']:
            print(f"Refresh: {results['refresh']['updated_count']} updated, {results['refresh']['unchanged_count']} unchanged (of {results['refresh']['total_checked']} checked)")
        print("="*60 + "\n")
        return True
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        logger.exception(e)
        return False

if __name__ == "__main__":
    asyncio.run(main())
