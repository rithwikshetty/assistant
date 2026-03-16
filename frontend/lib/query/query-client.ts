import { QueryClient, isServer } from '@tanstack/react-query'

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // 2 minutes - data considered fresh, no refetch
        staleTime: 2 * 60 * 1000,
        // 10 minutes - data kept in cache before garbage collection
        gcTime: 10 * 60 * 1000,
        // Disable refetch on window focus (messages update via live transport)
        refetchOnWindowFocus: false,
        // Refetch when network reconnects
        refetchOnReconnect: true,
        // Only retry once on failure
        retry: 1,
      },
    },
  })
}

let browserQueryClient: QueryClient | undefined = undefined

/**
 * Get the QueryClient singleton.
 * - On server: creates a new QueryClient per request (for SSR isolation)
 * - On browser: returns the same QueryClient instance (for caching)
 *
 * This function can be called from anywhere - React components, transport handlers, etc.
 */
export function getQueryClient(): QueryClient {
  if (isServer) {
    // Server: always create a new query client
    // This ensures data isolation between requests
    return makeQueryClient()
  }

  // Browser: use singleton pattern
  if (!browserQueryClient) {
    browserQueryClient = makeQueryClient()
  }
  return browserQueryClient
}
