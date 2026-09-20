import type { ReactNode } from 'react'

export function EmptyState({ icon, title, description, actions }: { icon?: ReactNode; title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border-strong bg-surface/60 px-8 py-16 text-center">
      {icon ? <div className="mb-4 text-muted">{icon}</div> : null}
      <h2 className="text-lg font-semibold">{title}</h2>
      {description ? <p className="mt-1 max-w-md text-sm text-muted">{description}</p> : null}
      {actions ? <div className="mt-6 flex flex-wrap items-center justify-center gap-3">{actions}</div> : null}
    </div>
  )
}
