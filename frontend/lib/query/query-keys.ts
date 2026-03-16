/**
 * Query key factory for React Query.
 * Using a factory pattern ensures consistent keys across the app.
 */
export const queryKeys = {
  // Conversations
  conversations: {
    all: ['conversations'] as const,
    list: (userId: string) => ['conversations', 'list', userId] as const,
  },

  // Messages by conversation
  messages: {
    all: ['messages'] as const,
  },

  // File helpers
  files: {
    all: ['files'] as const,
    downloadUrl: (fileId: string) => ['files', 'download-url', fileId] as const,
  },

  // Projects
  projects: {
    all: ['projects'] as const,
    list: (userId: string) => ['projects', 'list', userId] as const,
    detail: (projectId: string) => ['projects', 'detail', projectId] as const,
  },

  // Admin metrics
  admin: {
    all: ['admin'] as const,
    metrics: () => ['admin', 'metrics'] as const,
    toolsDistribution: () => ['admin', 'analytics', 'tools', 'distribution'] as const,
    sectors: () => ['admin', 'analytics', 'sectors'] as const,
  },
}
