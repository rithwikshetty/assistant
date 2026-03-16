
import { QueryClientProvider } from "@tanstack/react-query"
import { IconContext } from "@phosphor-icons/react"
import { AuthProvider } from "@/contexts/auth-context"
import { PreferencesProvider } from "@/contexts/preferences-context"
import { ThemeProvider } from "@/components/theme-provider"
import { PreferencesBootstrap } from "@/components/settings/preferences-bootstrap"
import { ToastProvider } from "@/components/ui/toast"
import { ActiveStreamsProvider } from "@/contexts/active-streams-context"
import { getQueryClient } from "@/lib/query/query-client"

const PHOSPHOR_DEFAULTS = { weight: "regular" as const, mirrored: false }

export function Providers({ children }: { children: React.ReactNode }) {
  const queryClient = getQueryClient()

  return (
    <IconContext.Provider value={PHOSPHOR_DEFAULTS}>
      <AuthProvider>
        <PreferencesProvider>
          <ThemeProvider>
            <PreferencesBootstrap />
            <ToastProvider>
              <QueryClientProvider client={queryClient}>
                <ActiveStreamsProvider>
                  {children}
                </ActiveStreamsProvider>
              </QueryClientProvider>
            </ToastProvider>
          </ThemeProvider>
        </PreferencesProvider>
      </AuthProvider>
    </IconContext.Provider>
  )
}
