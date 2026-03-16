
import { useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { useAuth } from "@/contexts/auth-context"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ShieldWarning } from "@phosphor-icons/react"

interface AdminGuardProps {
  children: React.ReactNode
}

export function AdminGuard({ children }: AdminGuardProps) {
  const { user, isLoading } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (!isLoading && user?.role?.toUpperCase() !== 'ADMIN') {
      // Give a slight delay to show the unauthorized message
      const timer = setTimeout(() => {
        navigate('/')
      }, 2000)
      return () => clearTimeout(timer)
    }
  }, [user, isLoading, navigate])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    )
  }

  if (user?.role?.toUpperCase() !== 'ADMIN') {
    return (
      <div className="flex items-center justify-center min-h-screen p-4">
        <Card className="max-w-md">
          <CardHeader className="text-center">
            <ShieldWarning className="h-12 w-12 text-destructive mx-auto mb-4" />
            <CardTitle className="type-size-32">Access Denied</CardTitle>
          </CardHeader>
          <CardContent className="text-center">
            <p className="text-muted-foreground mb-4">
              You don&apos;t have permission to access this page. Admin privileges are required.
            </p>
            <p className="type-size-14 text-muted-foreground">
              Redirecting to home page...
            </p>
          </CardContent>
        </Card>
      </div>
    )
  }

  return <>{children}</>
}
