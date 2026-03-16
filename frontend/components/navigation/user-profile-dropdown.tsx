import * as React from "react"
import { useState, useEffect } from "react"
import { Moon, Sun, Bug, Gear as SettingsIcon, ListChecks, EyeSlash } from "@phosphor-icons/react"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Switch } from "@/components/ui/switch"
import { useTheme } from "@/components/theme-provider"
import { useAuth } from "@/contexts/auth-context"
import { SettingsDialog } from "@/components/settings/settings-dialog"
import { updatePreferences } from "@/lib/api/preferences"
import { useNavigate } from "react-router-dom"
import { SidebarMenuButton, useSidebar } from "@/components/ui/sidebar"

type SettingsSection = "general" | "personalisation" | "redaction" | "support"

export function UserProfileDropdown() {
  const { state } = useSidebar()
  const isCollapsed = state === "collapsed"
  const [open, setOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [settingsSection, setSettingsSection] = useState<SettingsSection>("general")
  const { theme, setTheme } = useTheme()
  const { user, isAuthenticated, isBackendAuthenticated } = useAuth()
  const navigate = useNavigate()

  // Listen for open-settings events (e.g., from file upload dialog)
  useEffect(() => {
    const handleOpenSettings = (e: CustomEvent<{ section?: SettingsSection }>) => {
      if (e.detail?.section) {
        setSettingsSection(e.detail.section)
      }
      setSettingsOpen(true)
    }
    window.addEventListener("open-settings", handleOpenSettings as EventListener)
    return () => window.removeEventListener("open-settings", handleOpenSettings as EventListener)
  }, [])

  // Loading state — CSS-driven collapsed/expanded
  if (!isAuthenticated || !isBackendAuthenticated || !user) {
    return (
      <div className="flex h-10 w-full items-center overflow-hidden rounded-sm px-3 py-1.5 gap-2 group-data-[collapsible=icon]:gap-0">
        <div className="shrink-0">
          <Avatar className="h-8 w-8 transition-[width,height] duration-200 ease-md-standard group-data-[collapsible=icon]:h-7 group-data-[collapsible=icon]:w-7">
            <AvatarFallback className="type-size-14 font-medium leading-none px-0.5 bg-sidebar-accent text-sidebar-foreground">
              U
            </AvatarFallback>
          </Avatar>
        </div>
        <span className="min-w-0 flex-1 truncate type-size-14 font-medium text-sidebar-foreground/50 transition-[opacity,width] duration-200 ease-md-standard group-data-[collapsible=icon]:w-0 group-data-[collapsible=icon]:opacity-0">
          Loading...
        </span>
      </div>
    )
  }

  const userName = user.name || "User"
  const userEmail = user.email || "user@example.com"
  const userAvatar = user?.image

  const getInitials = (name: string) => {
    return name
      .split(' ')
      .map(word => word.charAt(0))
      .join('')
      .toUpperCase()
      .slice(0, 2)
  }

  const handleThemeToggle = async (checked: boolean) => {
    const newTheme = checked ? 'dark' : 'light'
    setTheme(newTheme)
    try {
      await updatePreferences({ theme: newTheme })
    } catch { }
  }

  const handleOpenTasks = () => {
    setOpen(false)
    navigate('/tasks')
  }

  const handleReportBug = () => {
    setSettingsSection("support")
    setSettingsOpen(true)
    setOpen(false)
  }

  const handleOpenPersonalisation = () => {
    setSettingsSection("personalisation")
    setSettingsOpen(true)
    setOpen(false)
  }

  const handleOpenRedactionList = () => {
    setSettingsSection("redaction")
    setSettingsOpen(true)
    setOpen(false)
  }

  return (
    <>
      <DropdownMenu open={open} onOpenChange={setOpen}>
        <DropdownMenuTrigger asChild>
          <SidebarMenuButton className="h-auto py-2 hover:bg-sidebar-accent/60 group-data-[collapsible=icon]:px-2">
            <div className="shrink-0">
              <Avatar className="h-8 w-8 transition-[width,height] duration-200 ease-md-standard group-data-[collapsible=icon]:h-7 group-data-[collapsible=icon]:w-7">
                <AvatarImage src={userAvatar} alt={userName} />
                <AvatarFallback className="bg-sidebar-primary/15 text-sidebar-primary type-size-14 font-medium leading-none px-0.5">
                  {getInitials(userName)}
                </AvatarFallback>
              </Avatar>
            </div>
            <span className="flex min-w-0 flex-col items-start gap-0.5 text-left leading-none">
              <span className="w-full truncate type-size-14 font-medium text-sidebar-foreground">
                {userName}
              </span>
              <span className="w-full truncate type-size-12 text-sidebar-foreground/50">
                {userEmail}
              </span>
            </span>
          </SidebarMenuButton>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          className="w-60 p-2 bg-background/80 backdrop-blur-xl border-border/40 shadow-xl data-[state=open]:!zoom-in-100 data-[state=open]:!slide-in-from-bottom-0 data-[state=open]:!slide-in-from-top-0"
          align={isCollapsed ? "center" : "start"}
          side={isCollapsed ? "right" : "top"}
          sideOffset={8}
        >
          <div className="flex items-center justify-between px-3 py-2">
            <div className="flex items-center gap-3">
              {theme === "dark" ? (
                <Moon className="size-4 text-muted-foreground" />
              ) : (
                <Sun className="size-4 text-muted-foreground" />
              )}
              <span className="type-size-14">Dark Mode</span>
            </div>
            <Switch
              checked={theme === "dark"}
              onCheckedChange={handleThemeToggle}
            />
          </div>
          <DropdownMenuSeparator className="my-2" />
          <DropdownMenuItem onClick={handleReportBug} className="px-3 py-2">
            <div className="flex items-center gap-3 flex-1">
              <Bug className="size-4 text-rose-600 dark:text-rose-400" />
              <span className="type-size-14">Report a bug</span>
            </div>
          </DropdownMenuItem>
          <DropdownMenuItem onClick={handleOpenTasks} className="px-3 py-2">
            <div className="flex items-center gap-3 flex-1">
              <ListChecks className="size-4 text-amber-600 dark:text-amber-400" />
              <span className="type-size-14">Tasks</span>
            </div>
          </DropdownMenuItem>
          <DropdownMenuItem onClick={handleOpenRedactionList} className="px-3 py-2">
            <div className="flex items-center gap-3 flex-1">
              <EyeSlash className="size-4 text-red-600 dark:text-red-400" />
              <span className="type-size-14">Redaction List</span>
            </div>
          </DropdownMenuItem>
          <DropdownMenuItem onClick={handleOpenPersonalisation} className="px-3 py-2">
            <div className="flex items-center gap-3 flex-1">
              <SettingsIcon className="size-4 text-muted-foreground" />
              <span className="type-size-14">Personalisation</span>
            </div>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <SettingsDialog
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        defaultSection={settingsSection}
        userName={userName}
        userEmail={userEmail}
        userTier={user?.user_tier}
      />
    </>
  )
}
