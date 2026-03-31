import type { ActionRecord } from '@/types/action.d.ts'
import { http } from '@/lib/http'

export async function getActions(params?: {
  limit?: number
  task_id?: number
  status?: string
}): Promise<ActionRecord[]> {
  return await http('/api/actions', { params })
}
