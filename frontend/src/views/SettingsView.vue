<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Save } from 'lucide-vue-next'
import { api } from '../api'

const loading = ref(true)
const saving = ref(false)
const saved = ref(false)
const form = ref({
  app_mode: 'manual',
  post_style: 'premium',
  max_products_per_sync: 100,
  post_interval_minutes: 360,
  ollama_model: 'qwen2.5:7b',
  ollama_timeout_seconds: 300,
  ollama_num_predict: 650,
  image_engine: 'none',
  comfyui_base_url: 'http://127.0.0.1:8188',
})

async function load() {
  const { data } = await api.get('/settings')
  form.value = data
  loading.value = false
}

async function save() {
  saving.value = true
  saved.value = false
  await api.patch('/settings', form.value)
  saving.value = false
  saved.value = true
}

onMounted(load)
</script>

<template>
  <section class="page-head">
    <div>
      <div class="eyebrow">configuration</div>
      <h1>Настройки</h1>
      <p class="muted">Стиль генерации, Ollama, синхронизация и режим публикации.</p>
    </div>
  </section>

  <div v-if="loading" class="panel empty">Загружаю настройки...</div>
  <form v-else class="panel section form-grid" style="max-width: 760px" @submit.prevent="save">
    <label class="label">Режим публикации
      <select v-model="form.app_mode" class="select">
        <option value="manual">manual</option>
        <option value="auto">auto</option>
      </select>
    </label>
    <label class="label">Стиль текста
      <select v-model="form.post_style" class="select">
        <option value="premium">premium</option>
        <option value="selling">selling</option>
        <option value="info">info</option>
        <option value="short">short</option>
        <option value="long">long</option>
      </select>
    </label>
    <label class="label">Лимит синхронизации Ozon
      <input v-model.number="form.max_products_per_sync" class="input" type="number" min="1" />
    </label>
    <label class="label">Интервал автопостинга, минут
      <input v-model.number="form.post_interval_minutes" class="input" type="number" min="1" />
    </label>
    <label class="label">Модель Ollama
      <input v-model="form.ollama_model" class="input" />
    </label>
    <label class="label">Таймаут Ollama, секунд
      <input v-model.number="form.ollama_timeout_seconds" class="input" type="number" min="30" />
    </label>
    <label class="label">Длина ответа модели
      <input v-model.number="form.ollama_num_predict" class="input" type="number" min="100" />
    </label>
    <label class="label">Генератор premium-картинок
      <select v-model="form.image_engine" class="select">
        <option value="none">none</option>
        <option value="comfyui">comfyui</option>
      </select>
    </label>
    <label class="label">ComfyUI URL
      <input v-model="form.comfyui_base_url" class="input" />
    </label>
    <div class="actions">
      <button class="button" type="submit" :disabled="saving"><Save :size="18" /> {{ saving ? 'Сохраняю...' : 'Сохранить' }}</button>
      <span v-if="saved" class="pill green">сохранено</span>
    </div>
  </form>
</template>
