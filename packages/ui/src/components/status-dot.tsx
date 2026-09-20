import { cn } from '../cn'

export type RunStatus = 'running' | 'idle' | 'failed' | 'waiting' | 'completed'

const dotClass: Record<RunStatus, string> = {
  running: 'bg-running',
  idle: 'bg-idle',
  failed: 'bg-failed',
  waiting: 'bg-waiting',
  completed: 'bg-success',
}

export function StatusDot({ status, className }: { status: RunStatus; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        'inline-block size-2 shrink-0 rounded-full',
        dotClass[status],
        status === 'running' && 'animate-pulse',
        className,
      )}
    />
  )
}
