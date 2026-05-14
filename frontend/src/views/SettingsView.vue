<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Save, Sparkles } from 'lucide-vue-next'
import { api } from '../api'

const loading = ref(true)
const saving = ref(false)
const saved = ref(false)
const modelOptions = ref({
  pollinations_text: [] as string[],
  pollinations_image: [] as string[],
})

const form = ref({
  app_mode: 'manual',
  post_style: 'premium',
  max_products_per_sync: 100,
  post_interval_minutes: 360,
  text_engine: 'pollinations',
  ollama_model: 'qwen2.5:7b',
  ollama_timeout_seconds: 300,
  ollama_num_predict: 650,
  freetheai_api_key: '',
  freetheai_base_url: 'https://api.freetheai.xyz/v1',
  freetheai_text_model: 'bbl/gpt-4.1',
  freetheai_text_timeout_seconds: 180,
  freetheai_text_max_tokens: 900,
  image_engine: 'pollinations',
  comfyui_base_url: 'http://127.0.0.1:8188',
  hf_image_model: 'stabilityai/stable-diffusion-xl-refiner-1.0',
  hf_image_provider: 'auto',
  hf_image_width: 1024,
  hf_image_height: 1280,
  image_generation_mode: 'image_to_image',
  local_sdcpp_bin: '/opt/stable-diffusion.cpp/build/bin/sd-cli',
  local_image_model: '/opt/tgchannelSeb/models/sd15-gguf/stable-diffusion-v1-5-Q4_0.gguf',
  local_image_width: 512,
  local_image_height: 640,
  local_image_steps: 20,
  local_image_strength: 0.30,
  local_image_cfg_scale: 6.5,
  local_image_seed: -1,
  local_image_threads: 4,
  local_image_timeout_seconds: 1800,
  freetheai_image_model: 'img/gpt-image-2',
  freetheai_timeout_seconds: 180,
  pollinations_api_key: '',
  pollinations_base_url: 'https://gen.pollinations.ai',
  pollinations_text_model: 'openai',
  pollinations_text_timeout_seconds: 180,
  pollinations_text_max_tokens: 900,
  pollinations_image_model: 'zimage',
  pollinations_image_width: 1024,
  pollinations_image_height: 1280,
  pollinations_image_quality: 'medium',
  pollinations_image_timeout_seconds: 240,
})

async function load() {
  const { data } = await api.get('/settings')
  form.value = {
    ...form.value,
    ...data,
    text_engine: 'pollinations',
    image_engine: 'pollinations',
    pollinations_image_model: data.pollinations_image_model === 'kontext' ? 'zimage' : (data.pollinations_image_model || 'zimage'),
  }

  try {
    const models = await api.get('/model-options')
    modelOptions.value = models.data
  } catch {
    modelOptions.value = {
      pollinations_text: ['openai', 'openai-fast', 'gpt-5.5', 'gemini', 'claude', 'qwen-large', 'mistral'],
      pollinations_image: ['zimage', 'flux', 'gptimage', 'gptimage-large'],
    }
  }

  loading.value = false
}

async function save() {
  saving.value = true
  saved.value = false
  form.value.text_engine = 'pollinations'
  form.value.image_engine = 'pollinations'
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
      <p class="muted">Публикации, Ozon-синхронизация и генерация через Pollinations.</p>
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
    </div>

    <div class="panel">
      <div class="block-head">
        <div>
          <div class="eyebrow">pollinations</div>
          <h2><Sparkles :size="20" /> Тексты постов</h2>
        </div>
      </div>
      <div class="form-grid">
        <label class="label">API key
          <input v-model="form.pollinations_api_key" class="input" type="password" autocomplete="off" />
        </label>
        <label class="label">Base URL
          <input v-model="form.pollinations_base_url" class="input" />
        </label>
        <label class="label">Модель текста
          <input v-model="form.pollinations_text_model" class="input" list="pollinations-text-models" />
          <datalist id="pollinations-text-models">
            <option v-for="model in modelOptions.pollinations_text" :key="model" :value="model" />
          </datalist>
        </label>
        <label class="label">Timeout текста, секунд
          <input v-model.number="form.pollinations_text_timeout_seconds" class="input" type="number" min="30" />
        </label>
        <label class="label">Максимум токенов
          <input v-model.number="form.pollinations_text_max_tokens" class="input" type="number" min="200" />
        </label>
      </div>
    </div>

    <div class="panel">
      <div class="block-head">
        <div>
          <div class="eyebrow">pollinations image</div>
          <h2><Sparkles :size="20" /> Premium-картинки</h2>
        </div>
      </div>
      <div class="form-grid">
        <label class="label">Режим
          <select v-model="form.image_generation_mode" class="select">
            <option value="image_to_image">image_to_image</option>
            <option value="cover">cover</option>
          </select>
        </label>
        <label class="label">Модель картинки
          <input v-model="form.pollinations_image_model" class="input" list="pollinations-image-models" />
          <datalist id="pollinations-image-models">
            <option v-for="model in modelOptions.pollinations_image" :key="model" :value="model" />
          </datalist>
        </label>
        <label class="label">Качество
          <select v-model="form.pollinations_image_quality" class="select">
            <option value="low">low</option>
            <option value="medium">medium</option>
            <option value="high">high</option>
            <option value="hd">hd</option>
          </select>
        </label>
        <label class="label">Ширина
          <input v-model.number="form.pollinations_image_width" class="input" type="number" min="256" step="64" />
        </label>
        <label class="label">Высота
          <input v-model.number="form.pollinations_image_height" class="input" type="number" min="256" step="64" />
        </label>
        <label class="label">Timeout картинки, секунд
          <input v-model.number="form.pollinations_image_timeout_seconds" class="input" type="number" min="30" />
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
