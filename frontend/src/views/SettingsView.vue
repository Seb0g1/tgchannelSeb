<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Save, Sparkles } from 'lucide-vue-next'
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
  hf_image_model: 'stabilityai/stable-diffusion-xl-refiner-1.0',
  hf_image_provider: 'auto',
  hf_image_width: 1024,
  hf_image_height: 1280,
  image_generation_mode: 'image_to_image',
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
      <p class="muted">Публикации, генерация текста, Ozon-синхронизация и premium-картинки.</p>
    </div>
  </section>

  <div v-if="loading" class="panel empty">Загружаю настройки...</div>
  <form v-else class="section form-stack" @submit.prevent="save">
    <div class="panel form-grid">
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
    </div>

    <div class="panel">
      <div class="block-head">
        <div>
          <div class="eyebrow">image generation</div>
          <h2><Sparkles :size="20" /> Premium-картинки</h2>
        </div>
      </div>
      <div class="form-grid">
        <label class="label">Генератор
          <select v-model="form.image_engine" class="select">
            <option value="none">none</option>
            <option value="huggingface">huggingface</option>
            <option value="comfyui">comfyui</option>
          </select>
        </label>
        <label class="label">Режим
          <select v-model="form.image_generation_mode" class="select">
            <option value="image_to_image">image_to_image</option>
            <option value="cover">cover</option>
          </select>
        </label>
        <label class="label">Hugging Face model
          <input v-model="form.hf_image_model" class="input" />
        </label>
        <label class="label">HF provider
          <input v-model="form.hf_image_provider" class="input" placeholder="auto" />
        </label>
        <label class="label">Ширина
          <input v-model.number="form.hf_image_width" class="input" type="number" min="256" step="64" />
        </label>
        <label class="label">Высота
          <input v-model.number="form.hf_image_height" class="input" type="number" min="256" step="64" />
        </label>
        <label class="label">ComfyUI URL
          <input v-model="form.comfyui_base_url" class="input" />
        </label>
      </div>
    </div>

    <div class="actions">
      <button class="button" type="submit" :disabled="saving">
        <Save :size="18" /> {{ saving ? 'Сохраняю...' : 'Сохранить' }}
      </button>
      <span v-if="saved" class="pill green">сохранено</span>
    </div>
  </form>
</template>
