/** 桌面端走系统保存框（默认桌面）；浏览器仍用 a[download]。 */

type TauriIpc = {
  invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown>
}

function tauriIpc(): TauriIpc | null {
  if (typeof window === 'undefined') return null
  const internals = (window as unknown as { __TAURI_INTERNALS__?: TauriIpc }).__TAURI_INTERNALS__
  if (!internals || typeof internals.invoke !== 'function') return null
  return internals
}

function browserDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

export async function saveBlobToDisk(blob: Blob, filename: string): Promise<'saved' | 'cancelled' | 'browser'> {
  const ipc = tauriIpc()
  if (!ipc) {
    browserDownload(blob, filename)
    return 'browser'
  }
  try {
    const bytes = Array.from(new Uint8Array(await blob.arrayBuffer()))
    await ipc.invoke('save_file_to_disk', { defaultName: filename, bytes })
    return 'saved'
  } catch (error) {
    const message = typeof error === 'string' ? error : error instanceof Error ? error.message : String(error)
    if (message === 'cancelled' || /cancel/i.test(message)) return 'cancelled'
    throw new Error(message)
  }
}
