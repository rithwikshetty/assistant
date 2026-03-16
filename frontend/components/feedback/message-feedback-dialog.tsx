
import * as React from 'react'
import { Modal } from '@/components/ui/modal'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { useToast } from '@/components/ui/toast'
import { submitMessageFeedback, type MessageFeedbackRating } from '@/lib/api/feedback'
import { Textarea } from '@/components/ui/textarea'

type TimeUnit = 'minutes' | 'hours' | 'days'

function convertToMinutes(value: number, unit: TimeUnit): number {
  switch (unit) {
    case 'minutes':
      return value
    case 'hours':
      return value * 60
    case 'days':
      return value * 60 * 24
  }
}

export function MessageFeedbackDialog({
  open,
  onClose,
  messageId,
  conversationId,
  rating,
  onSuccess,
}: {
  open: boolean
  onClose: () => void
  messageId: string
  conversationId?: string
  rating: MessageFeedbackRating
  onSuccess?: () => void
}) {
  const { addToast } = useToast()
  const [submitting, setSubmitting] = React.useState(false)

  // Thumbs up fields
  const [timeSavedValue, setTimeSavedValue] = React.useState('')
  const [timeSavedUnit, setTimeSavedUnit] = React.useState<TimeUnit>('minutes')
  const [improvementNotes, setImprovementNotes] = React.useState('')

  // Thumbs down fields
  const [issueDescription, setIssueDescription] = React.useState('')
  const [timeSpentValue, setTimeSpentValue] = React.useState('')
  const [timeSpentUnit, setTimeSpentUnit] = React.useState<TimeUnit>('minutes')

  React.useEffect(() => {
    if (!open) {
      setTimeSavedValue('')
      setTimeSavedUnit('minutes')
      setImprovementNotes('')
      setIssueDescription('')
      setTimeSpentValue('')
      setTimeSpentUnit('minutes')
      setSubmitting(false)
    }
  }, [open])

  async function handleSubmit() {
    if (submitting) return

    setSubmitting(true)
    try {
      const payload: {
        message_id: string
        rating: MessageFeedbackRating
        time_saved_minutes?: number
        improvement_notes?: string
        issue_description?: string
        time_spent_minutes?: number
      } = {
        message_id: messageId,
        rating,
      }

      if (rating === 'up') {
        const minutes = Number.parseFloat(timeSavedValue)
        if (!Number.isFinite(minutes) || minutes <= 0) {
          throw new Error('Please enter how many minutes this saved you (must be greater than zero).')
        }
        payload.time_saved_minutes = convertToMinutes(minutes, timeSavedUnit)
        const notes = improvementNotes.trim()
        if (notes) {
          payload.improvement_notes = notes
        }
      } else {
        const minutes = Number.parseFloat(timeSpentValue)
        if (!Number.isFinite(minutes) || minutes <= 0) {
          throw new Error('Please enter how many minutes you spent (must be greater than zero).')
        }
        payload.time_spent_minutes = convertToMinutes(minutes, timeSpentUnit)
        const issue = issueDescription.trim()
        if (issue) {
          payload.issue_description = issue
        }
      }

      const response = await submitMessageFeedback(payload)

      if (conversationId) {
        try {
          window.dispatchEvent(
            new CustomEvent("frontend:conversationFeedbackStatus", {
              detail: {
                conversationId,
                requiresFeedback: response.conversation_requires_feedback ?? false,
              },
            }),
          )
        } catch {}
      }

      addToast({
        type: 'success',
        title: 'Thanks for your feedback!',
        description: 'Your input helps us improve.',
      })
      onSuccess?.()
      onClose()
    } catch (err: unknown) {
      addToast({
        type: 'error',
        title: 'Failed to submit feedback',
        description: (err as Error)?.message || 'Please try again.',
      })
    } finally {
      setSubmitting(false)
    }
  }

  const isThumbsUp = rating === 'up'
  const title = isThumbsUp ? 'Thanks for the feedback!' : 'Help us improve'
  const parsedTimeSaved = Number.parseFloat(timeSavedValue)
  const parsedTimeSpent = Number.parseFloat(timeSpentValue)
  const hasSavedMinutes = Number.isFinite(parsedTimeSaved) && parsedTimeSaved > 0
  const hasSpentMinutes = Number.isFinite(parsedTimeSpent) && parsedTimeSpent > 0
  const canSubmit = isThumbsUp
    ? hasSavedMinutes
    : hasSpentMinutes

  return (
    <Modal open={open} onClose={onClose} title={title} className="sm:max-w-md">
      <div className="space-y-4">
        {isThumbsUp ? (
          <>
            <div className="space-y-2.5">
              <label className="type-size-12 font-medium text-foreground">
                How much time did this save you? <span className="text-rose-600">*</span>
              </label>
              <div className="flex gap-2">
                <Input
                  type="number"
                  value={timeSavedValue}
                  onChange={(e) => setTimeSavedValue(e.target.value)}
                  placeholder="Minutes saved (e.g., 30)"
                  min="0"
                  step="any"
                  autoFocus
                  className="flex-1"
                />
                <TimeUnitSelect value={timeSavedUnit} onChange={setTimeSavedUnit} />
              </div>
              <p className="type-size-10 text-muted-foreground">
                Estimate how long the task would have taken without assistant.
              </p>
            </div>

            <div className="space-y-2.5">
              <label className="type-size-12 font-medium text-foreground">
                What made this response helpful? <span className="text-muted-foreground">(optional)</span>
              </label>
              <Textarea
                className="min-h-24"
                placeholder="Share what worked well…"
                value={improvementNotes}
                onChange={(e) => setImprovementNotes(e.target.value)}
                maxLength={2000}
              />
              <p className="type-size-10 text-muted-foreground text-right">
                {improvementNotes.length}/2000
              </p>
            </div>
          </>
        ) : (
          <>
            <div className="space-y-2.5">
              <label className="type-size-12 font-medium text-foreground">
                What went wrong? <span className="text-muted-foreground">(optional)</span>
              </label>
              <Textarea
                className="min-h-32"
                placeholder="Please describe the issue…"
                value={issueDescription}
                onChange={(e) => setIssueDescription(e.target.value)}
                maxLength={2000}
                autoFocus
              />
              <p className="type-size-10 text-muted-foreground text-right">
                {issueDescription.length}/2000
              </p>
            </div>

            <div className="space-y-2.5">
              <label className="type-size-12 font-medium text-foreground">
                How long did you spend trying? <span className="text-rose-600">*</span>
              </label>
              <div className="flex gap-2">
                <Input
                  type="number"
                  value={timeSpentValue}
                  onChange={(e) => setTimeSpentValue(e.target.value)}
                  placeholder="Minutes spent (e.g., 15)"
                  min="0"
                  step="any"
                  className="flex-1"
                />
                <TimeUnitSelect value={timeSpentUnit} onChange={setTimeSpentUnit} />
              </div>
            </div>
          </>
        )}

        <div className="flex items-center justify-end gap-2 pt-2">
          <Button type="button" onClick={handleSubmit} disabled={submitting || !canSubmit} className="h-9">
            {submitting ? 'Submitting…' : 'Submit'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}

function TimeUnitSelect({ value, onChange }: { value: TimeUnit; onChange: (next: TimeUnit) => void }) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as TimeUnit)}>
      <SelectTrigger className="h-9 w-[120px]">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="minutes">Minutes</SelectItem>
        <SelectItem value="hours">Hours</SelectItem>
        <SelectItem value="days">Days</SelectItem>
      </SelectContent>
    </Select>
  )
}
