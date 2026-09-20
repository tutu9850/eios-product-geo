import { Select as BaseSelect } from '@base-ui/react/select'
import { cn } from '../cn'

export type SelectOption = { value: string; label: string }

export function Select({
  value,
  onValueChange,
  options,
  placeholder = '请选择',
  ariaLabel,
  className,
}: {
  value?: string | null
  onValueChange?: (value: string | null) => void
  options: SelectOption[]
  placeholder?: string
  ariaLabel?: string
  className?: string
}) {
  return (
    <BaseSelect.Root value={value} onValueChange={onValueChange} items={options}>
      <BaseSelect.Trigger
        aria-label={ariaLabel}
        className={cn(
          'flex h-9 w-full items-center justify-between gap-2 rounded-md border border-border bg-input px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 focus-visible:shadow-glow',
          className,
        )}
      >
        <BaseSelect.Value placeholder={placeholder} />
        <BaseSelect.Icon>
          <svg
            className="size-4 text-muted"
            aria-hidden="true"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="m6 9 6 6 6-6" />
          </svg>
        </BaseSelect.Icon>
      </BaseSelect.Trigger>
      <BaseSelect.Portal>
        <BaseSelect.Positioner className="z-50">
          <BaseSelect.Popup className="min-w-[var(--anchor-width)] rounded-lg border border-border bg-surface p-1 shadow-popover">
            <BaseSelect.List className="max-h-64 overflow-y-auto outline-none">
              {options.map((option) => (
                <BaseSelect.Item
                  key={option.value}
                  value={option.value}
                  className="flex cursor-pointer items-center justify-between rounded-md px-3 py-2 text-sm text-foreground data-[highlighted]:bg-surface-raised"
                >
                  <BaseSelect.ItemText>{option.label}</BaseSelect.ItemText>
                  <BaseSelect.ItemIndicator>
                    <svg
                      className="size-4 text-accent"
                      aria-hidden="true"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M20 6 9 17l-5-5" />
                    </svg>
                  </BaseSelect.ItemIndicator>
                </BaseSelect.Item>
              ))}
            </BaseSelect.List>
          </BaseSelect.Popup>
        </BaseSelect.Positioner>
      </BaseSelect.Portal>
    </BaseSelect.Root>
  )
}
