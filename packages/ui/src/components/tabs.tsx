import { Tabs as BaseTabs } from '@base-ui/react/tabs'
import type { ReactNode } from 'react'
import { cn } from '../cn'

export type TabItem = { value: string; label: ReactNode; content: ReactNode }

export function Tabs({
  defaultValue,
  items,
  className,
}: {
  defaultValue: string
  items: TabItem[]
  className?: string
}) {
  return (
    <BaseTabs.Root defaultValue={defaultValue} className={className}>
      <BaseTabs.List className="flex gap-1 border-b border-border">
        {items.map((item) => (
          <BaseTabs.Tab
            key={item.value}
            value={item.value}
            className={cn(
              '-mb-px border-b-2 border-transparent px-3 py-2 text-sm text-muted transition-colors hover:text-foreground data-[active]:border-accent data-[active]:text-foreground',
            )}
          >
            {item.label}
          </BaseTabs.Tab>
        ))}
      </BaseTabs.List>
      {items.map((item) => (
        <BaseTabs.Panel key={item.value} value={item.value} className="pt-4">
          {item.content}
        </BaseTabs.Panel>
      ))}
    </BaseTabs.Root>
  )
}
