<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { api, type Draft } from '../api'

const statusFilter = ref('pending')
const page = ref(1)
const limit = 30
const total = ref(0)
const drafts = ref<Draft[]>([])
const loading = ref(false)
const selected = ref<Draft | null>(null)
const editText = ref('')
const saving = ref(false)

async function load() {
  loading.value = true
  const { data } = await api.get('/drafts', { params: { status_filter: statusFilter.value, page: page.value, limit } })
  drafts.value = data.items
  total.value = data.total
  loading.value = false
}

async function openDraft(draft: Draft) {
  const { data } = await api.get(`/drafts/${draft.id}`)
  selected.value = data.draft
  editText.value = data.draft.text
}

async function saveDraft() {
  if (!selected.value) return
  saving.value = true
  const { data } = await api.patch(`/drafts/${selected.value.id}`, { text: editText.value })
  selected.value = data
  saving.value = false
  await load()
}

async function rejectDraft() {
  if (!selected.value) return
  await api.post(`/drafts/${selected.value.id}/reject`)
  selected.value = null
  await load()
}

watch(statusFilter, () => { page.value = 1; load() })
onMounted(load)
</script>

<template>
  <section class="page-head">
    <div>
      <div class="eyebrow">ai drafts</div>
      <h1>Черновики</h1>
      <p class="muted">Тексты, которые уже создала нейросеть.</p>
    </div>
  </section>

  <div class="toolbar">
    <select v-model="statusFilter" class="select" style="max-width: 240px">
      <option value="pending">На проверке</option>
      <option value="published">Опубликованные</option>
      <option value="rejected">Отклонённые</option>
      <option value="all">Все</option>
    </select>
  </div>

  <div class="two">
    <section class="panel">
      <div v-if="loading" class="empty">Загружаю черновики...</div>
      <div v-else class="table-wrap">
        <table>
          <thead><tr><th>ID</th><th>Товар</th><th>Статус</th><th>Стиль</th><th>Дата</th></tr></thead>
          <tbody>
            <tr v-for="draft in drafts" :key="draft.id" @click="openDraft(draft)" style="cursor:pointer">
              <td>#{{ draft.id }}</td>
              <td><RouterLink :to="`/products/${draft.product_id}`">товар #{{ draft.product_id }}</RouterLink></td>
              <td><span class="pill gold">{{ draft.status }}</span></td>
              <td>{{ draft.style }}</td>
              <td>{{ draft.created_at ? new Date(draft.created_at).toLocaleString('ru-RU') : '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="panel section">
      <h2>Редактор</h2>
      <div v-if="!selected" class="muted">Выберите черновик в таблице.</div>
      <div v-else class="form-grid">
        <div class="muted">Черновик #{{ selected.id }} · товар #{{ selected.product_id }}</div>
        <textarea v-model="editText" class="textarea" />
        <div class="actions">
          <button class="button" :disabled="saving" @click="saveDraft">{{ saving ? 'Сохраняю...' : 'Сохранить текст' }}</button>
          <button class="button danger" @click="rejectDraft">Отклонить</button>
        </div>
      </div>
    </section>
  </div>
</template>
