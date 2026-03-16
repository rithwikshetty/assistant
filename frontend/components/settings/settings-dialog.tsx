
import * as React from "react"
import { createPortal } from "react-dom"
import {
  X,
  Gear,
  User,
  Bug,
  Moon,
  Sun,
  SpinnerGap,
  Lightning,
  CaretLeft,
  EyeSlash,
  Plus,
  Trash,
  Pencil,
  SpeakerHigh,
} from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { Button } from "@/components/ui/button"
import { useTheme } from "@/components/theme-provider"
import { usePreferences } from "@/contexts/preferences-context"
import { useAuth } from "@/contexts/auth-context"
import { useToast } from "@/components/ui/toast"
import { submitBugReport, BugSeverity } from "@/lib/api/feedback"
import {
  getRedactionList,
  addRedactionEntry,
  updateRedactionEntry,
  deleteRedactionEntry,
  type RedactionEntry,
} from "@/lib/api/redaction-list"

type SettingsSection = "general" | "personalisation" | "redaction" | "support"

interface SettingsDialogProps {
  open: boolean
  onClose: () => void
  defaultSection?: SettingsSection
  userName?: string
  userEmail?: string
  userTier?: string
}

const SECTIONS = [
  { id: "general" as const, label: "General", icon: Gear },
  { id: "personalisation" as const, label: "Personalisation", icon: User },
  { id: "redaction" as const, label: "Redaction List", icon: EyeSlash },
  { id: "support" as const, label: "Report a Bug", icon: Bug },
]

export function SettingsDialog({
  open,
  onClose,
  defaultSection = "general",
  userName,
  userEmail,
  userTier,
}: SettingsDialogProps) {
  const [mounted, setMounted] = React.useState(false)
  const [animateMounted, setAnimateMounted] = React.useState(false)
  const [activeSection, setActiveSection] = React.useState<SettingsSection>(defaultSection)
  const [showMobileSidebar, setShowMobileSidebar] = React.useState(true)

  // Reset to default section when dialog opens
  React.useEffect(() => {
    if (open) {
      setActiveSection(defaultSection)
      setShowMobileSidebar(true)
    }
  }, [open, defaultSection])

  React.useEffect(() => {
    setMounted(true)
    return () => setMounted(false)
  }, [])

  React.useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose()
    }
    if (open) document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [open, onClose])

  React.useEffect(() => {
    if (open) {
      const id = requestAnimationFrame(() => setAnimateMounted(true))
      return () => cancelAnimationFrame(id)
    } else {
      setAnimateMounted(false)
    }
  }, [open])

  const handleSectionClick = (section: SettingsSection) => {
    setActiveSection(section)
    setShowMobileSidebar(false)
  }

  if (!open || !mounted) return null

  return createPortal(
    <div
      className="fixed inset-0 z-[60] pointer-events-auto"
      role="dialog"
      aria-modal="true"
      aria-label="Settings"
    >
      {/* Backdrop */}
      <div
        className={cn(
          "absolute inset-0 bg-black/80 backdrop-blur-md transition-opacity duration-150 ease-out pointer-events-none",
          animateMounted ? "opacity-100" : "opacity-0"
        )}
        aria-hidden="true"
      />

      {/* Dialog container */}
      <div
        className="absolute inset-0 flex justify-center items-end sm:items-center p-0 sm:p-4"
        onClick={(e) => {
          if (e.target === e.currentTarget) onClose()
        }}
      >
        <div
          className={cn(
            "z-[61] w-full h-[100dvh] sm:h-[85vh] sm:max-h-[680px] sm:max-w-3xl sm:rounded-2xl rounded-none",
            "border bg-background shadow-xl flex flex-col overflow-hidden",
            "transition-transform transition-opacity duration-150 ease-out",
            animateMounted
              ? "opacity-100 translate-y-0 sm:scale-100"
              : "opacity-0 translate-y-2 sm:translate-y-0 sm:scale-[0.98]"
          )}
          onClick={(e) => e.stopPropagation()}
          onTouchStart={(e) => e.stopPropagation()}
        >
          {/* Mobile Header - only show when viewing content (not sidebar) */}
          <div className="sm:hidden flex items-center justify-between px-4 py-3 border-b">
            {!showMobileSidebar ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowMobileSidebar(true)}
                className="inline-flex items-center gap-1 type-size-14 text-muted-foreground hover:text-foreground h-auto px-2 py-1"
              >
                <CaretLeft className="size-4" />
                Back
              </Button>
            ) : (
              <h3 className="type-size-16 font-semibold">Settings</h3>
            )}
            <Button
              variant="ghost"
              size="icon"
              aria-label="Close"
              onClick={onClose}
              className="size-8 rounded-lg hover:bg-muted"
            >
              <X className="size-4" />
            </Button>
          </div>

          <div className="flex flex-1 overflow-hidden">
            {/* Sidebar */}
            <aside
              className={cn(
                "w-full sm:w-56 shrink-0 border-r bg-muted/30 overflow-y-auto",
                "sm:block",
                showMobileSidebar ? "block" : "hidden"
              )}
            >
              {/* Desktop close button */}
              <div className="hidden sm:flex items-center justify-between p-4 pb-2">
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="Close"
                  onClick={onClose}
                  className="size-8 rounded-lg hover:bg-muted"
                >
                  <X className="size-4" />
                </Button>
              </div>

              <nav className="p-3 sm:pt-1">
                {SECTIONS.map((section) => {
                  const Icon = section.icon
                  const isActive = activeSection === section.id
                  return (
                    <Button
                      key={section.id}
                      variant="ghost"
                      onClick={() => handleSectionClick(section.id)}
                      className={cn(
                        "w-full flex items-center justify-start gap-3 px-3 py-2.5 rounded-lg type-size-14 font-medium transition-colors h-auto",
                        isActive
                          ? "bg-primary/10 text-primary dark:bg-primary/15"
                          : "text-muted-foreground hover:bg-muted hover:text-foreground"
                      )}
                    >
                      <Icon className="size-[18px]" />
                      {section.label}
                    </Button>
                  )
                })}
              </nav>
            </aside>

            {/* Content area */}
            <main
              className={cn(
                "flex-1 overflow-y-auto",
                "sm:block",
                showMobileSidebar ? "hidden sm:block" : "block"
              )}
            >
              <div className="p-5 sm:p-6">
                {activeSection === "general" && (
                  <GeneralSection
                    userName={userName}
                    userEmail={userEmail}
                  />
                )}
                {activeSection === "personalisation" && (
                  <PersonalisationSection />
                )}
                {activeSection === "redaction" && <RedactionListSection isPowerUser={userTier === "power"} />}
                {activeSection === "support" && (
                  <SupportSection
                    userName={userName}
                    userEmail={userEmail}
                    onSuccess={onClose}
                  />
                )}
              </div>
            </main>
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}

// ============================================================================
// General Section
// ============================================================================

function GeneralSection({
  userName,
  userEmail,
}: {
  userName?: string
  userEmail?: string
}) {
  const { theme, setTheme } = useTheme()
  const { preferences, updateTheme, updatePreferences } = usePreferences()
  const { user } = useAuth()

  const handleThemeToggle = (checked: boolean) => {
    const next = checked ? "dark" : "light"
    setTheme(next)
    updateTheme(next)
  }

  // Get initials for avatar fallback
  const getInitials = (name: string) => {
    return name
      .split(" ")
      .map((word) => word.charAt(0))
      .join("")
      .toUpperCase()
      .slice(0, 2)
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="type-size-20 font-semibold text-foreground mb-1">General</h2>
        <p className="type-size-14 text-muted-foreground">
          Your profile and display preferences
        </p>
      </div>

      {/* Profile Section */}
      <section className="space-y-3">
        <h3 className="type-size-14 font-medium text-foreground">Profile</h3>
        <div className="rounded-xl border border-border/60 bg-muted/20 p-4">
          <div className="flex items-start gap-4">
            {/* Profile Image */}
            <div className="shrink-0">
              {user?.image ? (
                <img
                  src={user.image}
                  alt={userName || "User"}
                  width={64}
                  height={64}
                  className="size-16 rounded-full object-cover border-2 border-border/40"
                />
              ) : (
                <div className="size-16 rounded-full bg-primary/10 text-primary flex items-center justify-center type-size-20 font-semibold border-2 border-border/40">
                  {getInitials(userName || "U")}
                </div>
              )}
            </div>
            {/* Profile Details */}
            <div className="flex-1 min-w-0 space-y-3">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="type-size-12 font-medium text-muted-foreground">Name</label>
                  <p className="type-size-14 font-medium truncate">{userName || "User"}</p>
                </div>
                <div className="space-y-1">
                  <label className="type-size-12 font-medium text-muted-foreground">Email</label>
                  <p className="type-size-14 truncate">{userEmail || "user@example.com"}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Appearance Section */}
      <section className="space-y-3">
        <h3 className="type-size-14 font-medium text-foreground">Appearance</h3>
        <div className="flex items-center justify-between rounded-xl border border-border/60 bg-muted/20 px-4 py-3">
          <div className="flex items-center gap-3">
            {theme === "dark" ? (
              <Moon className="size-5 text-muted-foreground" />
            ) : (
              <Sun className="size-5 text-muted-foreground" />
            )}
            <div>
              <p className="type-size-14 font-medium">Dark Mode</p>
              <p className="type-size-12 text-muted-foreground">
                {theme === "dark" ? "Currently using dark theme" : "Currently using light theme"}
              </p>
            </div>
          </div>
          <Switch checked={theme === "dark"} onCheckedChange={handleThemeToggle} />
        </div>
      </section>

      {/* Notifications Section */}
      <section className="space-y-3">
        <h3 className="type-size-14 font-medium text-foreground">Notifications</h3>
        <div className="flex items-center justify-between rounded-xl border border-border/60 bg-muted/20 px-4 py-3">
          <div className="flex items-center gap-3">
            <SpeakerHigh className="size-5 text-muted-foreground" />
            <div>
              <p className="type-size-14 font-medium">Notification Sound</p>
              <p className="type-size-12 text-muted-foreground">
                Play a chime when a response completes in the background
              </p>
            </div>
          </div>
          <Switch
            checked={preferences?.notification_sound !== false}
            onCheckedChange={(checked) => updatePreferences({ notification_sound: checked })}
          />
        </div>
      </section>
    </div>
  )
}

// ============================================================================
// Personalisation Section
// ============================================================================

function PersonalisationSection() {
  const { preferences, updatePreferences: savePreferences } = usePreferences()
  const { user, refreshUser } = useAuth()

  const [customInstructions, setCustomInstructions] = React.useState(
    preferences?.custom_instructions || ""
  )
  const [status, setStatus] = React.useState<"idle" | "saving" | "saved" | "error">("idle")
  const lastSaved = React.useRef<string>(preferences?.custom_instructions || "")

  React.useEffect(() => {
    setCustomInstructions(preferences?.custom_instructions || "")
    lastSaved.current = preferences?.custom_instructions || ""
  }, [preferences?.custom_instructions])

  React.useEffect(() => {
    refreshUser()
  }, [refreshUser])

  const savePersonalisation = React.useCallback(async () => {
    const trimmed = customInstructions.trim()
    const hasChanges = trimmed !== lastSaved.current.trim()
    if (!hasChanges) return

    setStatus("saving")
    try {
      await savePreferences({ custom_instructions: trimmed || null })
      lastSaved.current = trimmed
      setStatus("saved")
    } catch {
      setStatus("error")
    }
  }, [customInstructions, savePreferences])

  // Debounced auto-save
  React.useEffect(() => {
    const timer = setTimeout(() => {
      void savePersonalisation()
    }, 900)
    return () => clearTimeout(timer)
  }, [customInstructions, savePersonalisation])

  return (
    <div className="space-y-6">
      <div>
        <h2 className="type-size-20 font-semibold text-foreground mb-1">Personalisation</h2>
        <p className="type-size-14 text-muted-foreground">
          Customize how assistant responds to you
        </p>
      </div>

      {/* Custom instructions */}
      <section className="space-y-3">
        <div className="flex items-center justify-between gap-2">
          <div>
            <h3 className="type-size-14 font-medium text-foreground">Custom Instructions</h3>
            <p className="type-size-12 text-muted-foreground">Optional guidance for the assistant</p>
          </div>
          <div className="flex items-center gap-2 type-size-12 text-muted-foreground">
            {status === "saving" && (
              <>
                <SpinnerGap className="size-3 animate-spin" />
                <span>Saving…</span>
              </>
            )}
            {status === "saved" && <span className="text-foreground/80">Saved</span>}
            {status === "error" && <span className="text-red-500">Save failed</span>}
          </div>
        </div>
        <Textarea
          rows={5}
          value={customInstructions}
          onChange={(e) => {
            const value = e.target.value
            if (value.length <= 2000) {
              setCustomInstructions(value)
            }
          }}
          className="resize-y min-h-[100px]"
          placeholder="For example:&#10;- Always summarise with 3 bullet points&#10;- Focus on project management implications"
        />
        <div className="flex justify-end type-size-12 text-muted-foreground">
          <span>{customInstructions.length} / 2000</span>
        </div>
      </section>

      {/* Usage tier */}
      <section className="space-y-3">
        <h3 className="type-size-14 font-medium text-foreground">Usage Tier</h3>
        <div className="rounded-xl border border-border/60 bg-muted/20 px-4 py-3">
          <div className="flex items-center gap-2 mb-2">
            {user?.user_tier === "power" && (
              <Lightning className="size-4 text-orange-600 dark:text-accent-yellow" />
            )}
            <span className="type-size-14 font-medium">
              {user?.user_tier === "power" ? "Power User" : "Default"}
            </span>
          </div>
          <p className="type-size-12 text-muted-foreground leading-relaxed">
            {user?.user_tier === "power"
              ? "You have access to more powerful AI models for complex tasks. "
              : "Standard tier provides cost-effective AI for most use cases. "}
            Tier changes are managed by the local deployment owner.
          </p>
        </div>
      </section>
    </div>
  )
}

// ============================================================================
// Redaction List Section
// ============================================================================

function RedactionListSection({ isPowerUser: _isPowerUser }: { isPowerUser: boolean }) {
  const { addToast } = useToast()
  const [entries, setEntries] = React.useState<RedactionEntry[]>([])
  const [loading, setLoading] = React.useState(true)
  const [newName, setNewName] = React.useState("")
  const [adding, setAdding] = React.useState(false)
  const [editingId, setEditingId] = React.useState<string | null>(null)
  const [editValue, setEditValue] = React.useState("")

  // Fetch entries on mount
  React.useEffect(() => {
    getRedactionList()
      .then((data) => {
        setEntries(data || [])
      })
      .catch(() => {
        addToast({ type: "error", title: "Failed to load redaction list" })
      })
      .finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleAdd = async () => {
    const trimmed = newName.trim()
    if (!trimmed || adding) return

    setAdding(true)
    try {
      const entry = await addRedactionEntry({ name: trimmed, is_active: true })
      setEntries((prev) => [entry, ...prev])
      setNewName("")
      addToast({ type: "success", title: "Name added to redaction list" })
    } catch {
      addToast({ type: "error", title: "Failed to add name" })
    } finally {
      setAdding(false)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteRedactionEntry(id)
      setEntries((prev) => prev.filter((e) => e.id !== id))
      addToast({ type: "success", title: "Name removed from list" })
    } catch {
      addToast({ type: "error", title: "Failed to remove name" })
    }
  }

  const handleToggleActive = async (entry: RedactionEntry) => {
    try {
      const updated = await updateRedactionEntry(entry.id, {
        is_active: !entry.is_active,
      })
      setEntries((prev) => prev.map((e) => (e.id === entry.id ? updated : e)))
    } catch {
      addToast({ type: "error", title: "Failed to update entry" })
    }
  }

  const handleStartEdit = (entry: RedactionEntry) => {
    setEditingId(entry.id)
    setEditValue(entry.name)
  }

  const handleSaveEdit = async () => {
    if (!editingId) return
    const trimmed = editValue.trim()
    if (!trimmed) {
      addToast({ type: "error", title: "Name cannot be empty" })
      return
    }

    try {
      const updated = await updateRedactionEntry(editingId, { name: trimmed })
      setEntries((prev) => prev.map((e) => (e.id === editingId ? updated : e)))
      setEditingId(null)
      setEditValue("")
    } catch {
      addToast({ type: "error", title: "Failed to update name" })
    }
  }

  const handleCancelEdit = () => {
    setEditingId(null)
    setEditValue("")
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="type-size-20 font-semibold text-foreground mb-1">
          Redaction List
        </h2>
        <p className="type-size-14 text-muted-foreground">
          Names added here will be automatically redacted when uploading files
          with PII protection enabled.
        </p>
      </div>

      {/* Add new entry */}
      <div className="flex gap-2">
        <Input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder="Enter a name to redact..."
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault()
              handleAdd()
            }
          }}
          disabled={adding}
          className="flex-1"
        />
        <Button onClick={handleAdd} disabled={!newName.trim() || adding} size="sm">
          <Plus className="size-4 mr-1" />
          Add
        </Button>
      </div>

      {/* List of entries */}
      <div className="space-y-2 max-h-[280px] overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <SpinnerGap className="size-5 animate-spin text-muted-foreground" />
          </div>
        ) : entries.length === 0 ? (
          <div className="text-center py-8 type-size-14 text-muted-foreground">
            <EyeSlash className="size-8 mx-auto mb-2 opacity-40" />
            <p>No names in your redaction list yet.</p>
            <p className="type-size-12 mt-1">Add names above to protect them during file uploads.</p>
          </div>
        ) : (
          entries.map((entry) => (
            <div
              key={entry.id}
              className={cn(
                "flex items-center justify-between rounded-lg border px-3 py-2.5 transition-colors",
                entry.is_active
                  ? "border-border/60 bg-muted/20"
                  : "border-border/30 bg-muted/10 opacity-60"
              )}
            >
              {editingId === entry.id ? (
                <div className="flex items-center gap-2 flex-1 mr-2">
                  <Input
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault()
                        handleSaveEdit()
                      } else if (e.key === "Escape") {
                        handleCancelEdit()
                      }
                    }}
                    className="h-8 type-size-14"
                    autoFocus
                  />
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 shrink-0"
                    onClick={handleSaveEdit}
                  >
                    <Check className="size-4 text-green-600" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 shrink-0"
                    onClick={handleCancelEdit}
                  >
                    <X className="size-4" />
                  </Button>
                </div>
              ) : (
                <>
                  <div className="flex items-center gap-3 min-w-0 flex-1">
                    <Switch
                      checked={entry.is_active}
                      onCheckedChange={() => handleToggleActive(entry)}
                      className="shrink-0"
                    />
                    <span
                      className={cn(
                        "type-size-14 truncate",
                        !entry.is_active && "line-through"
                      )}
                    >
                      {entry.name}
                    </span>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={() => handleStartEdit(entry)}
                    >
                      <Pencil className="size-3.5 text-muted-foreground" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-destructive hover:text-destructive"
                      onClick={() => handleDelete(entry.id)}
                    >
                      <Trash className="size-3.5" />
                    </Button>
                  </div>
                </>
              )}
            </div>
          ))
        )}
      </div>

      {/* Info box */}
      <div className="rounded-xl bg-muted/40 px-4 py-3 type-size-12 text-muted-foreground">
        <p className="font-medium mb-1.5 text-foreground/80">How it works:</p>
        <ul className="list-disc list-inside space-y-1 leading-relaxed">
          <li>Names are matched case-insensitively across your uploaded files</li>
          <li>Variations like initials, spaced letters, and reversed order are also caught</li>
          <li>Toggle entries off to temporarily disable them without deleting</li>
        </ul>
      </div>
    </div>
  )
}

// ============================================================================
// Support Section (Bug Report)
// ============================================================================

function SupportSection({
  userName,
  userEmail,
  onSuccess,
}: {
  userName?: string
  userEmail?: string
  onSuccess: () => void
}) {
  const { addToast } = useToast()
  const [title, setTitle] = React.useState("")
  const [severity, setSeverity] = React.useState<BugSeverity>("medium")
  const [description, setDescription] = React.useState("")
  const [submitting, setSubmitting] = React.useState(false)

  const resetForm = React.useCallback(() => {
    setTitle("")
    setSeverity("medium")
    setDescription("")
  }, [])

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (submitting) return

    const trimmedTitle = title.trim()
    const trimmedDesc = description.trim()

    if (trimmedTitle.length < 3) {
      addToast({ type: "error", title: "Title too short", description: "Please provide at least 3 characters." })
      return
    }
    if (trimmedDesc.length === 0) {
      addToast({ type: "error", title: "Description required", description: "Please describe the issue." })
      return
    }

    setSubmitting(true)
    try {
      await submitBugReport({ title: trimmedTitle, description: trimmedDesc, severity })
      addToast({ type: "success", title: "Bug reported", description: "Thanks for the report!" })
      resetForm()
      onSuccess()
    } catch (err: unknown) {
      addToast({ type: "error", title: "Failed to submit", description: (err as Error)?.message || "Please try again." })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="type-size-20 font-semibold text-foreground mb-1">Report a Bug</h2>
        <p className="type-size-14 text-muted-foreground">
          Help us improve by reporting issues you encounter
        </p>
      </div>

      <form onSubmit={onSubmit} className="space-y-5">
        {(userName || userEmail) && (
          <div className="type-size-12 text-muted-foreground">
            Reporting as {userName || "User"} ({userEmail || "unknown"})
          </div>
        )}

        {/* Title */}
        <div className="space-y-2">
          <label className="type-size-14 font-medium text-foreground">Title</label>
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Short summary of the issue"
            maxLength={255}
          />
        </div>

        {/* Severity */}
        <fieldset className="space-y-2">
          <legend className="type-size-14 font-medium text-foreground">Severity</legend>
          <div
            role="radiogroup"
            aria-label="Severity"
            className="flex items-center rounded-xl border border-border/60 bg-muted/20 p-1 gap-1.5 w-max"
          >
            {(
              [
                { key: "low", label: "Low", color: "bg-success", ring: "ring-success/40" },
                { key: "medium", label: "Medium", color: "bg-warning text-warning-foreground", ring: "ring-warning/40" },
                { key: "high", label: "High", color: "bg-destructive", ring: "ring-destructive/40" },
              ] as const
            ).map((opt) => {
              const active = severity === opt.key
              return (
                <Button
                  key={opt.key}
                  type="button"
                  onClick={() => setSeverity(opt.key)}
                  aria-pressed={active}
                  className={cn(
                    "h-8 px-3 type-size-12",
                    active
                      ? `${opt.color} hover:opacity-90 focus-visible:ring-2 ${opt.ring}`
                      : "bg-transparent text-foreground hover:bg-muted/50"
                  )}
                  variant="ghost"
                  size="sm"
                >
                  {opt.label}
                </Button>
              )
            })}
          </div>
          <div className="type-size-12 leading-5 text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1 pt-1">
            <span className="whitespace-nowrap">
              <span className="inline-block size-2 rounded-full bg-destructive mr-1 align-middle" />
              High: blocks work
            </span>
            <span className="whitespace-nowrap">
              <span className="inline-block size-2 rounded-full bg-warning mr-1 align-middle" />
              Medium: degrades UX
            </span>
            <span className="whitespace-nowrap">
              <span className="inline-block size-2 rounded-full bg-success mr-1 align-middle" />
              Low: minor
            </span>
          </div>
        </fieldset>

        {/* Description */}
        <div className="space-y-2">
          <label className="type-size-14 font-medium text-foreground">Description</label>
          <Textarea
            className="min-h-32"
            placeholder="Steps to reproduce, expected vs actual behavior, any context."
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            maxLength={10000}
          />
          <div className="flex items-center justify-between">
            <p className="type-size-12 text-muted-foreground">
              Tip: Include steps to reproduce and any error text.
            </p>
            <span className="type-size-12 text-muted-foreground">{description.length}/10000</span>
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center justify-end gap-2 pt-2">
          <Button type="submit" disabled={submitting}>
            {submitting ? "Submitting…" : "Submit Report"}
          </Button>
        </div>

        {/* Contact fallback */}
        <div className="rounded-xl bg-muted/40 px-4 py-3 type-size-12 text-muted-foreground">
          If you self-host this app, route support requests to your deployment owner.
        </div>
      </form>
    </div>
  )
}
