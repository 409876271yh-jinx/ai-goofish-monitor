<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useActions } from '@/composables/useActions'
import { useTasks } from '@/composables/useTasks'

const { t } = useI18n()
const { actions, isLoading, error, fetchActions } = useActions()
const { tasks, fetchTasks } = useTasks()
const selectedTaskId = ref<string>('all')
const selectedStatus = ref<string>('all')

const statusOptions = computed(() => [
  { value: 'all', label: t('actions.filters.allStatus') },
  { value: 'pending', label: 'pending' },
  { value: 'running', label: 'running' },
  { value: 'success', label: 'success' },
  { value: 'failed', label: 'failed' },
  { value: 'cancelled', label: 'cancelled' },
])

function formatTimestamp(value?: string | null) {
  if (!value) return t('common.empty')
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function statusTone(status: string) {
  if (status === 'success') return 'bg-emerald-50 text-emerald-700'
  if (status === 'failed') return 'bg-rose-50 text-rose-700'
  if (status === 'running') return 'bg-amber-50 text-amber-700'
  if (status === 'cancelled') return 'bg-slate-100 text-slate-600'
  return 'bg-blue-50 text-blue-700'
}

async function refresh() {
  await fetchActions({
    limit: 200,
    task_id: selectedTaskId.value === 'all' ? undefined : Number(selectedTaskId.value),
    status: selectedStatus.value === 'all' ? undefined : selectedStatus.value,
  })
}

watch([selectedTaskId, selectedStatus], refresh)

onMounted(async () => {
  await fetchTasks()
  await refresh()
})
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-bold text-gray-800">{{ t('actions.title') }}</h1>
        <p class="mt-1 text-sm text-slate-500">{{ t('actions.description') }}</p>
      </div>
      <Button @click="refresh">{{ t('common.refresh') }}</Button>
    </div>

    <div class="rounded-2xl border border-slate-200 bg-white/70 p-4 backdrop-blur">
      <div class="grid gap-4 md:grid-cols-2">
        <div class="space-y-2">
          <label class="text-xs font-black uppercase tracking-widest text-slate-500">{{ t('actions.filters.task') }}</label>
          <select
            v-model="selectedTaskId"
            class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          >
            <option value="all">{{ t('actions.filters.allTasks') }}</option>
            <option v-for="task in tasks" :key="task.id" :value="String(task.id)">{{ task.task_name }}</option>
          </select>
        </div>
        <div class="space-y-2">
          <label class="text-xs font-black uppercase tracking-widest text-slate-500">{{ t('actions.filters.status') }}</label>
          <select
            v-model="selectedStatus"
            class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          >
            <option v-for="option in statusOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </div>
      </div>
    </div>

    <div v-if="error" class="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      {{ error.message }}
    </div>

    <div class="rounded-2xl border border-slate-200 bg-white/70 backdrop-blur">
      <div v-if="isLoading" class="px-6 py-12 text-center text-slate-500">
        {{ t('common.loading') }}
      </div>
      <div v-else-if="actions.length === 0" class="px-6 py-12 text-center text-slate-400">
        {{ t('actions.empty') }}
      </div>
      <div v-else class="divide-y divide-slate-100">
        <div
          v-for="action in actions"
          :key="action.id"
          class="grid gap-4 px-6 py-5 lg:grid-cols-[160px_1fr_240px]"
        >
          <div class="space-y-2">
            <Badge :class="statusTone(action.status)" variant="outline">{{ action.status }}</Badge>
            <div class="text-xs font-bold uppercase tracking-wider text-slate-500">{{ action.action_type }}</div>
            <div class="text-xs text-slate-400">{{ formatTimestamp(action.created_at) }}</div>
          </div>

          <div class="space-y-2">
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-sm font-black text-slate-900">{{ action.summary.title || action.item_id }}</span>
              <Badge v-if="action.summary.template_id" variant="outline">{{ action.summary.template_id }}</Badge>
            </div>
            <div class="text-sm text-slate-600">{{ action.summary.task_name || t('common.unnamed') }}</div>
            <div class="text-sm text-slate-600">
              {{ t('actions.fields.price') }}: {{ action.summary.price || t('common.empty') }}
            </div>
            <div class="text-sm text-slate-600">
              {{ t('actions.fields.reason') }}: {{ action.summary.reason || t('common.empty') }}
            </div>
            <div v-if="action.summary.risk_tags?.length" class="flex flex-wrap gap-2">
              <Badge v-for="risk in action.summary.risk_tags" :key="risk" variant="outline">{{ risk }}</Badge>
            </div>
            <a
              v-if="action.summary.link"
              :href="action.summary.link"
              target="_blank"
              rel="noreferrer"
              class="text-sm font-medium text-primary underline-offset-2 hover:underline"
            >
              {{ t('actions.fields.openItem') }}
            </a>
          </div>

          <div class="space-y-2 text-sm text-slate-600">
            <div>{{ t('actions.fields.itemId') }}: {{ action.item_id }}</div>
            <div>{{ t('actions.fields.sellerId') }}: {{ action.seller_id || t('common.empty') }}</div>
            <div>{{ t('actions.fields.retryCount') }}: {{ action.retry_count }}</div>
            <div>{{ t('actions.fields.executorStatus') }}: {{ action.summary.executor_status || t('common.empty') }}</div>
            <div v-if="action.last_error" class="rounded-lg bg-rose-50 px-3 py-2 text-rose-700">
              {{ action.last_error }}
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
