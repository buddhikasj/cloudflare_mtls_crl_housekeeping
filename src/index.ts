import { Container, getContainer } from '@cloudflare/containers';
import { env } from "cloudflare:workers";

export class CRLHousekeepingContainer extends Container {
  sleepAfter = "5m";
  manualStart = true;

  envVars = {
    KV_NAMESPACE_ID: env.KV_NAMESPACE_ID,
    LARGE_CRL_QUEUE_ID: env.LARGE_CRL_QUEUE_ID,
    CLOUDFLARE_ACCOUNT_ID: env.CLOUDFLARE_ACCOUNT_ID,
    WS_CLOUDFLARE_API_TOKEN: env.WS_CLOUDFLARE_API_TOKEN_CRL,
    ENABLE_QUEUE_PROCESSING: env.ENABLE_QUEUE_PROCESSING || "true"
  };

  override onStart() {
    console.log('[CONTAINER] Starting CRL Housekeeping Container');
    console.log('[CONTAINER] Container initialized at:', new Date().toISOString());
  }

  override onStop() {
    console.log('[CONTAINER] CRL Housekeeping Container Stopped');
    console.log('[CONTAINER] Container stopped at:', new Date().toISOString());
  }
}

export default {
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    
    if (url.pathname === '/health') {
      return new Response(JSON.stringify({
        status: 'ok',
        service: 'CRL Housekeeping Cron Container',
        timestamp: new Date().toISOString()
      }, null, 2), {
        headers: { 'Content-Type': 'application/json' }
      });
    }
    
    return new Response('CRL Housekeeping Cron Container\n\nThis Worker runs scheduled tasks to maintain Certificate Revocation Lists (CRLs).\n\nEndpoints:\n  GET /health - Health check\n', {
      headers: { 'Content-Type': 'text/plain' }
    });
  },

  async scheduled(
    _controller: any,
    env: { CRL_HOUSEKEEPING_CONTAINER: DurableObjectNamespace<CRLHousekeepingContainer> }
  ) {
    console.log('[CRON] Scheduled trigger received at:', new Date().toISOString());
    console.log('[CRON] Starting CRL Housekeeping Container...');
    
    try {
      let container = getContainer(env.CRL_HOUSEKEEPING_CONTAINER);
      await container.start({});
      console.log('[CRON] Container started successfully');
    } catch (error) {
      console.error('[CRON] Failed to start container:', error);
      throw error;
    }
  },
};
