<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { CalendarPlus, ChevronLeft, ChevronRight, Trash2 } from 'lucide-vue-next'
import { api, type ScheduledPost } from '../api'

const items = ref<ScheduledPost[]>([])
const draftId = ref<number | null>(null)
const scheduledAt = ref('')
const weekStart = ref(startOfWeek(new Date()))

function startOfWeek(date: Date) {
  const value = new Date(date)
  const day = value.getDay() || 7
  value.setDate(value.getDate() - day + 1)
  value.setHours(0, 0, 0, 0)
  return value
}

function addDays(date: Date, days: number) {
  const value = new Date(date)
  value.setDate(value.getDate() + days)
  return value
}

const days = computed(() => Array.from({ length: 7 }, (_, index) => addDays(weekStart.value, index)))

function sameDay(left: Date, right: Date) {
  return left.getFullYear() === right.getFullYear()
    && left.getMonth() === right.getMonth()
    && left.getDate() === right.getDate()
}

function itemsForDay(day: Date) {
  return items.value.filter((item) => sameDay(new Date(item.scheduled_at), day))
}

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

function shiftWeek(days: number) {
  weekStart.value = addDays(weekStart.value, days)
}

onMounted(load)
</script>

<template>
  <section class="page-head">
    <div>
      <div class="eyebrow">calendar</div>
      <h1>Очередь публикаций</h1>
      <p class="muted">Бот проверяет очередь каждую минуту и публикует черновики в назначенное время.</p>
    </div>
    <div class="actions">
      <button class="button secondary" @click="shiftWeek(-7)"><ChevronLeft :size="18" /> Неделя</button>
      <button class="button secondary" @click="shiftWeek(7)">Неделя <ChevronRight :size="18" /></button>
    </div>
  </section>

  <form class="toolbar" @submit.prevent="create">
    <input v-model.number="draftId" class="input" style="max-width:180px" type="number" placeholder="Draft ID" />
    <input v-model="scheduledAt" class="input" style="max-width:260px" type="datetime-local" />
    <button class="button" type="submit"><CalendarPlus :size="18" /> Запланировать</button>
  </form>

  <section class="calendar-grid">
    <article v-for="day in days" :key="day.toISOString()" class="calendar-day panel">
      <header>
        <span>{{ day.toLocaleDateString('ru-RU', { weekday: 'short' }) }}</span>
        <strong>{{ day.toLocaleDateString('ru-RU', { day: '2-digit', month: 'short' }) }}</strong>
      </header>

      <div v-if="!itemsForDay(day).length" class="calendar-empty">нет публикаций</div>

      <div v-for="item in itemsForDay(day)" :key="item.id" class="schedule-card">
        <div>
          <b>Черновик #{{ item.draft_id }}</b>
          <span>{{ new Date(item.scheduled_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) }}</span>
        </div>
        <span class="pill" :class="{ green: item.status === 'published', red: item.status === 'failed', gold: item.status === 'scheduled' }">
          {{ item.status }}
        </span>
        <button class="icon-button" @click="remove(item.id)" title="Удалить"><Trash2 :size="15" /></button>
      </div>
    </article>
  </section>
</template>
