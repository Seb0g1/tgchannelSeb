<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Repeat2,
  Save,
  Sparkles,
  Trash2,
  WandSparkles,
} from 'lucide-vue-next'
import { api, type ScheduleRules, type ScheduledPost } from '../api'

type ScheduleApplyResult = {
  created: number
  requested: number
  existing_slots?: number
  remaining_slots?: number
  candidate_count?: number
  used_candidates?: number
  skipped_text_errors?: number
  skipped_empty_drafts?: number
  image_errors?: number
  restored_publications?: number
  active_days?: number
  sync?: {
    requested: number
    received: number
    saved: number
    skipped_variants: number
    active: number
    with_stock: number
  } | null
}

const loading = ref(false)
const saving = ref(false)
const applying = ref(false)
const statusMessage = ref('')
const lastApply = ref<ScheduleApplyResult | null>(null)
const weekStart = ref(startOfWeek(new Date()))
const items = ref<ScheduledPost[]>([])
const rules = ref<ScheduleRules>({
  active_weekdays: [0, 1, 2, 3, 4, 5, 6],
  posts_per_day: 1,
  mode: 'interval',
  exact_time: '12:00',
  start_time: '10:00',
  end_time: '22:00',
  lookahead_days: 7,
})

const weekdayButtons = [
  { key: 1, label: 'Пн' },
  { key: 2, label: 'Вт' },
  { key: 3, label: 'Ср' },
  { key: 4, label: 'Чт' },
  { key: 5, label: 'Пт' },
  { key: 6, label: 'Сб' },
  { key: 0, label: 'Вс' },
]

const days = computed(() => Array.from({ length: 7 }, (_, index) => addDays(weekStart.value, index)))
const weekItemsCount = computed(() => days.value.reduce((sum, day) => sum + itemsForDay(day).length, 0))

function startOfWeek(date: Date) {
  const value = new Date(date)
  const day = value.getDay() || 7
  value.setDate(value.getDate() - day + 1)
  value.setHours(0, 0, 0, 0)
  return value
}

function addDays(date: Date, daysCount: number) {
  const value = new Date(date)
  value.setDate(value.getDate() + daysCount)
  return value
}

function sameDay(left: Date, right: Date) {
  return (
    left.getFullYear() === right.getFullYear()
    && left.getMonth() === right.getMonth()
    && left.getDate() === right.getDate()
  )
}

function itemsForDay(day: Date) {
  return items.value.filter((item) => sameDay(new Date(item.scheduled_at), day))
}

function moveWeek(delta: number) {
  weekStart.value = addDays(weekStart.value, delta)
}

function toggleWeekday(day: number) {
  const current = new Set(rules.value.active_weekdays)
  if (current.has(day)) {
    current.delete(day)
  } else {
    current.add(day)
  }
  rules.value.active_weekdays = Array.from(current).sort((a, b) => a - b)
}

function selectAllDays() {
  rules.value.active_weekdays = [0, 1, 2, 3, 4, 5, 6]
}

function selectWorkdays() {
  rules.value.active_weekdays = [1, 2, 3, 4, 5]
}

function selectWeekends() {
  rules.value.active_weekdays = [0, 6]
}

function applyMessage(data: ScheduleApplyResult) {
  const parts = [`создано ${data.created} из ${data.requested}`]
  if (data.existing_slots) parts.push(`уже было ${data.existing_slots}`)
  if (data.remaining_slots) parts.push(`осталось ${data.remaining_slots}`)
  if (data.candidate_count !== undefined) parts.push(`кандидатов ${data.candidate_count}`)
  if (data.sync) parts.push(`Ozon: получено ${data.sync.received}, сохранено ${data.sync.saved}`)
  if (data.restored_publications) parts.push(`возвращено ${data.restored_publications}`)
  if (data.skipped_text_errors) parts.push(`ошибок текста ${data.skipped_text_errors}`)
  return `Очередь заполнена: ${parts.join(' · ')}.`
}

async function loadRules() {
  const { data } = await api.get<ScheduleRules>('/schedule/rules')
  rules.value = data
}

async function loadSchedule() {
  const { data } = await api.get('/schedule')
  items.value = (data.items || []).slice().sort((left: ScheduledPost, right: ScheduledPost) =>
    new Date(left.scheduled_at).getTime() - new Date(right.scheduled_at).getTime(),
  )
}

async function load() {
  loading.value = true
  try {
    await Promise.all([loadRules(), loadSchedule()])
  } finally {
    loading.value = false
  }
}

async function saveRules() {
  saving.value = true
  statusMessage.value = ''
  try {
    const payload = {
      active_weekdays: rules.value.active_weekdays,
      posts_per_day: Number(rules.value.posts_per_day),
      mode: rules.value.mode,
      exact_time: rules.value.mode === 'exact' ? rules.value.exact_time : null,
      start_time: rules.value.mode === 'interval' ? rules.value.start_time : null,
      end_time: rules.value.mode === 'interval' ? rules.value.end_time : null,
      lookahead_days: Number(rules.value.lookahead_days),
    }
    const { data } = await api.put<ScheduleRules>('/schedule/rules', payload)
    rules.value = data
    statusMessage.value = 'Правила сохранены.'
    return true
  } catch (error: any) {
    statusMessage.value = error?.response?.data?.detail || error?.response?.data?.message || 'Не удалось сохранить правила.'
    return false
  } finally {
    saving.value = false
  }
}

async function applyRules() {
  applying.value = true
  statusMessage.value = ''
  try {
    const { data } = await api.post<ScheduleApplyResult>('/schedule/rules/apply')
    lastApply.value = data
    await loadSchedule()
    statusMessage.value = applyMessage(data)
  } catch (error: any) {
    statusMessage.value = error?.response?.data?.detail || error?.response?.data?.message || 'Не удалось применить правила.'
  } finally {
    applying.value = false
  }
}

async function saveAndApply() {
  const saved = await saveRules()
  if (!saved) return
  await applyRules()
}

async function removeScheduled(id: number) {
  await api.delete(`/schedule/${id}`)
  await loadSchedule()
}

onMounted(load)
</script>

<template>
  <section class="page-head">
    <div>
      <div class="eyebrow">calendar</div>
      <h1>Очередь публикаций</h1>
      <p class="muted">
        Настрой правила один раз: дни недели, количество постов и время. Сервис сам подтянет Ozon,
        выберет товары, создаст текст с картинкой и поставит публикации в очередь.
      </p>
    </div>
    <div class="actions">
      <button class="button secondary" type="button" @click="moveWeek(-7)">
        <ChevronLeft :size="18" />
        Неделя
      </button>
      <button class="button secondary" type="button" @click="moveWeek(7)">
        Неделя
        <ChevronRight :size="18" />
      </button>
    </div>
  </section>

  <section class="panel section rules-panel">
    <div class="section-title">
      <div>
        <h2><Sparkles :size="18" /> Правила автопостинга</h2>
        <p class="muted">
          Ручной выбор товаров не нужен. Если каталога мало, автоплан сам запустит синхронизацию Ozon
          и покажет, сколько кандидатов нашёл.
        </p>
      </div>
      <div class="rules-hint">
        <CalendarDays :size="16" />
        <span>{{ weekItemsCount }} постов на видимой неделе</span>
      </div>
    </div>

    <div class="weekday-actions">
      <button class="button secondary" type="button" @click="selectAllDays">Все дни</button>
      <button class="button secondary" type="button" @click="selectWorkdays">Пн-Пт</button>
      <button class="button secondary" type="button" @click="selectWeekends">Сб-Вс</button>
    </div>

    <div class="weekday-grid">
      <button
        v-for="day in weekdayButtons"
        :key="day.key"
        class="weekday-pill"
        :class="{ active: rules.active_weekdays.includes(day.key) }"
        type="button"
        @click="toggleWeekday(day.key)"
      >
        {{ day.label }}
      </button>
    </div>

    <div class="rules-grid">
      <label class="label">
        <span>Сколько постов в день</span>
        <input v-model.number="rules.posts_per_day" class="input" type="number" min="1" max="20" />
      </label>

      <label class="label">
        <span>Режим расписания</span>
        <select v-model="rules.mode" class="select">
          <option value="interval">Интервал</option>
          <option value="exact">Точное время</option>
        </select>
      </label>

      <label v-if="rules.mode === 'exact'" class="label">
        <span>Точное время публикации</span>
        <input v-model="rules.exact_time" class="input" type="time" />
      </label>

      <template v-else>
        <label class="label">
          <span>Начало интервала</span>
          <input v-model="rules.start_time" class="input" type="time" />
        </label>
        <label class="label">
          <span>Конец интервала</span>
          <input v-model="rules.end_time" class="input" type="time" />
        </label>
      </template>

      <label class="label">
        <span>Горизонт планирования, дней</span>
        <input v-model.number="rules.lookahead_days" class="input" type="number" min="1" max="60" />
      </label>
    </div>

    <div class="rules-actions">
      <button class="button" type="button" :disabled="saving" @click="saveRules">
        <Save :size="18" />
        {{ saving ? 'Сохраняю...' : 'Сохранить правила' }}
      </button>
      <button class="button secondary" type="button" :disabled="applying" @click="applyRules">
        <WandSparkles :size="18" />
        {{ applying ? 'Заполняю очередь...' : 'Заполнить сейчас' }}
      </button>
      <button class="button secondary" type="button" :disabled="saving || applying" @click="saveAndApply">
        <Repeat2 :size="18" />
        Сохранить и запустить
      </button>
    </div>

    <div class="schedule-summary">
      <div>
        <span>Дней активно</span>
        <strong>{{ rules.active_weekdays.length }}</strong>
      </div>
      <div>
        <span>Постов в день</span>
        <strong>{{ rules.posts_per_day }}</strong>
      </div>
      <div>
        <span>Режим</span>
        <strong>{{ rules.mode === 'exact' ? 'точное время' : 'интервал' }}</strong>
      </div>
      <div>
        <span>Горизонт</span>
        <strong>{{ rules.lookahead_days }} дней</strong>
      </div>
    </div>

    <div v-if="lastApply" class="schedule-diagnostics">
      <div><span>Нужно слотов</span><b>{{ lastApply.requested }}</b></div>
      <div><span>Уже было</span><b>{{ lastApply.existing_slots || 0 }}</b></div>
      <div><span>Создано</span><b>{{ lastApply.created }}</b></div>
      <div><span>Кандидатов</span><b>{{ lastApply.candidate_count || 0 }}</b></div>
      <div><span>Ozon получено</span><b>{{ lastApply.sync?.received || 0 }}</b></div>
      <div><span>Ошибок текста</span><b>{{ lastApply.skipped_text_errors || 0 }}</b></div>
    </div>
  </section>

  <div v-if="statusMessage" class="status-line">{{ statusMessage }}</div>
  <p v-if="loading" class="muted">Загружаю правила и расписание...</p>

  <section class="calendar-grid">
    <article v-for="day in days" :key="day.toISOString()" class="calendar-day panel">
      <header>
        <div class="calendar-meta">
          <span>{{ day.toLocaleDateString('ru-RU', { weekday: 'short' }) }}</span>
          <strong>{{ day.toLocaleDateString('ru-RU', { day: '2-digit', month: 'short' }) }}</strong>
        </div>
        <div class="calendar-count">
          <Clock3 :size="14" />
          <span>{{ itemsForDay(day).length }}</span>
        </div>
      </header>

      <div v-if="!itemsForDay(day).length" class="calendar-empty">
        Нет публикаций на этот день
      </div>

      <div v-for="item in itemsForDay(day)" :key="item.id" class="schedule-card">
        <div class="schedule-card-head">
          <b>Черновик #{{ item.draft_id }}</b>
          <span>{{ new Date(item.scheduled_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) }}</span>
        </div>
        <span class="pill" :class="{ green: item.status === 'published', red: item.status === 'failed', gold: item.status === 'scheduled' }">
          {{ item.status }}
        </span>
        <button class="icon-button" type="button" title="Удалить из очереди" @click="removeScheduled(item.id)">
          <Trash2 :size="15" />
        </button>
      </div>
    </article>
  </section>
</template>
