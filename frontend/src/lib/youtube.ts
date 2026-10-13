let api: Promise<void> | null = null

/** Loads the YouTube IFrame API once per page. */
export function loadYouTubeApi(): Promise<void> {
  if (window.YT?.Player) return Promise.resolve()
  api ??= new Promise((resolve, reject) => {
    const prev = window.onYouTubeIframeAPIReady
    window.onYouTubeIframeAPIReady = () => {
      prev?.()
      resolve()
    }
    const s = document.createElement('script')
    s.src = 'https://www.youtube.com/iframe_api'
    s.onerror = () => {
      api = null
      reject(new Error('YouTube IFrame API se nenačetlo'))
    }
    document.head.append(s)
  })
  return api
}
