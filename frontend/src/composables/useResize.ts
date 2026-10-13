import { onBeforeUnmount, onMounted, type Ref } from 'vue'

/** Calls fn after mount and whenever the element changes size. */
export function useResize(el: Readonly<Ref<Element | undefined>>, fn: () => void) {
  let ro: ResizeObserver | null = null
  onMounted(() => {
    if (!el.value) return
    ro = new ResizeObserver(() => fn())
    ro.observe(el.value)
    fn()
  })
  onBeforeUnmount(() => ro?.disconnect())
}
