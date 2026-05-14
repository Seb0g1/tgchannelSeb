<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { CalendarPlus, Trash2 } from 'lucide-vue-next'
import { api, type ScheduledPost } from '../api'

const items = ref<ScheduledPost[]>([])
const draftId = ref<number | null>(null)
const scheduledAt = ref('')

async function load() {
  const { data } = await api.get('/schedule')
  items.value = data.items
}

async function create() {
  if (!draftId.value || !scheduledAt.value) return
  await api.post('/schedule', { draft_id: draftId.value, scheduled_at: new Date(scheduledAt.value).toISOString() })
  draftId.value = null
  scheduledAt.value = ''
  await load()
}

async function remove(id: number) {
  await api.delete(`/schedule/${id}`)
  await load()
}

onMounted(load)
</script>

<template>
  <section class="page-head">
    <div>
      <div class="eyebrow">calendar</div>
      <h1>Очередь публикаций</h1>
      <p class="muted">Календарь запланированных черновиков. Бот проверяет очередь каждую минуту.</p>
    </div>
  </section>

  <form class="toolbar" @submit.prevent="create">
    <input v-model.number="draftId" class="input" style="max-width:180px" type="number" placeholder="Draft ID" />
    <input v-model="scheduledAt" class="input" style="max-width:260px" type="datetime-local" />
    <button class="button" type="submit"><CalendarPlus :size="18" /> Запланировать</button>
  </form>

  <section class="panel">
    <div class="table-wrap">
      <table>
        <thead><tr><th>ID</th><th>Черновик</th><th>Дата</th><th>Статус</th><th></th></tr></thead>
        <tbody>
          <tr v-for="item in items" :key="item.id">
            <td>#{{ item.id }}</td>
            <td><RouterLink :to="`/drafts`">черновик #{{ item.draft_id }}</RouterLink></td>
            <td>{{ new Date(item.scheduled_at).toLocaleString('ru-RU') }}</td>
            <td><span class="pill gold">{{ item.status }}</span></td>
            <td><button class="button danger" @click="remove(item.id)"><Trash2 :size="16" /></button></td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
