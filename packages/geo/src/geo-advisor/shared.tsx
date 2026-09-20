import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Loader2 } from 'lucide-react'
import { Button, cn } from '@yayu/ui'

/** GEO 卡片外壳（自适应聊天界面宽度，内容舒适排版） */
export function GeoCardShell({ title, children, className }: { title?: string; children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        'w-full space-y-2 rounded-xl border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-3 py-2.5 text-[12.5px]',
        className,
      )}
    >
      {title ? <div className="text-[12px] font-semibold leading-tight text-[var(--yayu-foreground)]">{title}</div> : null}
      {children}
    </div>
  )
}

export function GeoRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="shrink-0 text-[11px] text-[var(--yayu-muted)]">{label}</span>
      <span className="truncate text-right text-[12px] font-medium text-[var(--yayu-foreground)]">{value}</span>
    </div>
  )
}

export function GeoList({ items }: { items: Array<{ title: string; desc?: string; meta?: string }> }) {
  return (
    <div className="space-y-1">
      {items.map((item, index) => (
        <div key={index} className="flex items-start justify-between gap-2.5 rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1">
          <div className="min-w-0">
            <div className="text-[12px] leading-snug text-[var(--yayu-foreground)]">{item.title}</div>
            {item.desc ? <div className="mt-px text-[10px] leading-snug text-[var(--yayu-muted)]">{item.desc}</div> : null}
          </div>
          {item.meta ? (
            <span className="shrink-0 rounded bg-[var(--yayu-surface-raised)] px-1 py-px text-[9.5px] text-[var(--yayu-muted)]">{item.meta}</span>
          ) : null}
        </div>
      ))}
    </div>
  )
}

export function GeoLoading({ text = '加载中…' }: { text?: string }) {
  return (
    <div className="flex items-center gap-2 py-3 text-[12px] text-[var(--yayu-muted)]">
      <Loader2 className="size-3.5 animate-spin" /> {text}
    </div>
  )
}

export function GeoError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-3 py-2 text-[12px] text-[var(--yayu-muted)]">
      <span className="min-w-0 truncate">⚠️ {message}</span>
      {onRetry ? (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          重试
        </Button>
      ) : null}
    </div>
  )
}

export function GeoButtonRow({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-center gap-2 pt-1">{children}</div>
}

/** 单卡崩溃不拖垮整页（监测两卡并排时尤其需要） */
export class GeoCardErrorBoundary extends Component<{ children: ReactNode; label: string }, { message: string | null }> {
  state = { message: null as string | null }

  static getDerivedStateFromError(error: Error) {
    return { message: error.message || '卡片渲染失败' }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[geo-advisor] ${this.props.label} crashed`, error, info.componentStack)
  }

  render() {
    if (this.state.message) {
      return <GeoError message={`${this.props.label}打不开：${this.state.message}`} />
    }
    return this.props.children
  }
}
