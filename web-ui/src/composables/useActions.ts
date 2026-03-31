import { ref } from 'vue'
import { getActions } from '@/api/actions'
import type { ActionRecord } from '@/types/action.d.ts'

export function useActions() {
  const actions = ref<ActionRecord[]>([])
  const isLoading = ref(false)
  const error = ref<Error | null>(null)

  async function fetchActions(params?: {
    limit?: number
    task_id?: number
    status?: string
  }) {
    isLoading.value = true
    error.value = null
    try {
      actions.value = await getActions(params)
    } catch (e) {
      if (e instanceof Error) {
        error.value = e
      }
      throw e
    } finally {
      isLoading.value = false
    }
  }

  return {
    actions,
    isLoading,
    error,
    fetchActions,
  }
}
