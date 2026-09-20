import { forwardRef, type TextareaHTMLAttributes } from 'react'
import { cn } from '../cn'

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className, ...props }, ref) {
    return (
      <textarea
        ref={ref}
        className={cn(
          'w-full rounded-md border border-border bg-input px-3 py-2 text-sm text-foreground placeholder:text-faint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 focus-visible:shadow-glow disabled:opacity-50',
          className,
        )}
        {...props}
      />
    )
  },
)
