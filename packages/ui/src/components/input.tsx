import { forwardRef, type InputHTMLAttributes } from 'react'
import { cn } from '../cn'

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...props },
  ref,
) {
  return (
    <input
      ref={ref}
      className={cn(
        'h-9 w-full rounded-md border border-border bg-input px-3 text-sm text-foreground placeholder:text-faint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 focus-visible:shadow-glow disabled:opacity-50',
        className,
      )}
      {...props}
    />
  )
})
