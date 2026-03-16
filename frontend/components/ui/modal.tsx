
import * as React from 'react'
import { createPortal } from 'react-dom'
import { X } from '@phosphor-icons/react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

type ModalSize = 'sm' | 'md' | 'lg' | 'xl' | '2xl' | '3xl' | '4xl' | '5xl' | '6xl' | '7xl'

export function Modal({ open, onClose, title, children, className, actions, fullBleed = false, size = 'xl' }: {
  open: boolean
  onClose: () => void
  title?: string
  children: React.ReactNode
  className?: string
  actions?: React.ReactNode
  fullBleed?: boolean
  size?: ModalSize
}) {
  const [mounted, setMounted] = React.useState(false)

  React.useEffect(() => {
    setMounted(true)
    return () => setMounted(false)
  }, [])

  React.useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    if (open) document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  // Minimal mount animation (fade + slight scale). No animation when closed.
  const [animateMounted, setAnimateMounted] = React.useState(false)
  React.useEffect(() => {
    if (open) {
      const id = requestAnimationFrame(() => setAnimateMounted(true))
      return () => cancelAnimationFrame(id)
    } else {
      setAnimateMounted(false)
    }
  }, [open])

  if (!open || !mounted) return null

  return createPortal(
    <div className="fixed inset-0 z-[60] pointer-events-auto" role="dialog" aria-modal="true" aria-label={title || 'Dialog'}>
      {/* Backdrop */}
      <div
        className={`absolute inset-0 bg-black/70 backdrop-blur-lg transition-opacity duration-200 ease-out pointer-events-none ${animateMounted ? 'opacity-100' : 'opacity-0'}`}
        aria-hidden="true"
      />
      <div
        className={cn(
          "absolute inset-0 flex justify-center p-0 sm:p-4",
          fullBleed ? "items-stretch sm:p-0" : "items-end sm:items-center",
        )}
        onClick={(e) => {
          // Only close if clicking the container, not its children
          if (e.target === e.currentTarget) {
            onClose()
          }
        }}
      >
        <div className={cn(
          // Mobile: full-bleed sheet; Desktop: centered card, or fullBleed
          `z-[61] w-full h-[100dvh] sm:h-auto sm:max-h-[calc(100dvh-2rem)] sm:rounded-2xl rounded-none border bg-background shadow-xl flex flex-col \
           ${animateMounted ? 'opacity-100 translate-y-0 sm:scale-100 animate-spring-in' : 'opacity-0 translate-y-4 sm:translate-y-0 sm:scale-[0.92]'}`,
          // Panel width on desktop
          size === 'sm' && 'sm:max-w-sm',
          size === 'md' && 'sm:max-w-md',
          size === 'lg' && 'sm:max-w-lg',
          size === 'xl' && 'sm:max-w-xl',
          size === '2xl' && 'sm:max-w-2xl',
          size === '3xl' && 'sm:max-w-3xl',
          size === '4xl' && 'sm:max-w-4xl',
          size === '5xl' && 'sm:max-w-5xl',
          size === '6xl' && 'sm:max-w-6xl',
          size === '7xl' && 'sm:max-w-7xl',
          fullBleed && `sm:max-w-none sm:h-[100dvh] sm:rounded-none sm:border-0`,
          className
        )}
        id="app-modal-panel"
        role="document"
        onClick={(e) => e.stopPropagation()}
        onTouchStart={(e) => e.stopPropagation()}
        >
          <div className="flex items-center justify-between px-4 sm:px-5 py-3 border-b gap-3">
            <h3 className="type-size-16 font-semibold text-foreground truncate">{title}</h3>
            <div className="flex items-center gap-2">
              {actions}
              <Button variant="ghost" size="icon" aria-label="Close" onClick={onClose} className="size-7 rounded-lg hover:bg-muted">
                <X className="size-4" />
              </Button>
            </div>
          </div>
          <div className={cn(
            "overflow-y-auto flex-1 min-h-0",
            fullBleed ? "p-3 sm:p-4" : "p-4 sm:p-5",
          )}>
            {children}
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}
