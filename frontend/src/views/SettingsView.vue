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
  openrouter_text: [] as string[],
})

const form = ref({
  app_mode: 'manual',
  post_style: 'premium',
  max_products_per_sync: 30000,
  post_interval_minutes: 360,
  text_engine: 'openrouter',
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
  openrouter_api_key: '',
  openrouter_base_url: 'https://openrouter.ai/api/v1',
  openrouter_text_model: 'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free',
  openrouter_text_timeout_seconds: 180,
  openrouter_text_max_tokens: 900,
  openrouter_site_url: 'https://parfum.sebog1.ru',
  openrouter_site_name: 'Aromat Day',
  pollinations_image_model: 'zimage',
  pollinations_image_width: 1024,
  pollinations_image_height: 1280,
  pollinations_image_quality: 'medium',
  pollinations_image_timeout_seconds: 240,
  cloudflare_worker_url: '',
  cloudflare_worker_api_key: '',
  cloudflare_worker_timeout_seconds: 180,
  codex_sale_api_key: '',
  codex_sale_base_url: 'https://codex.sale/v1',
  codex_sale_image_model: 'gpt-image-2',
  codex_sale_image_size: '1024x1024',
  codex_sale_timeout_seconds: 300,
})

async function load() {
  const { data } = await api.get('/settings')
  form.value = {
    ...form.value,
    ...data,
    pollinations_image_model: data.pollinations_image_model === 'kontext' ? 'zimage' : (data.pollinations_image_model || 'zimage'),
  }

  try {
    const models = await api.get('/model-options')
    modelOptions.value = models.data
  } catch {
    modelOptions.value = {
      pollinations_text: ['openai', 'openai-fast', 'gpt-5.5', 'gemini', 'claude', 'qwen-large', 'mistral'],
      pollinations_image: ['zimage', 'flux', 'gptimage', 'gptimage-large'],
      openrouter_text: [
        'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free',
        'openrouter/free',
        'meta-llama/llama-3.1-8b-instruct:free',
        'qwen/qwen-2.5-7b-instruct:free',
        'google/gemini-2.0-flash-exp:free',
      ],
    }
  }

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
      <p class="muted">Публикации, Ozon-синхронизация, генерация текста и premium-картинки.</p>
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
        <input v-model.number="form.max_products_per_sync" class="input" type="number" min="1" max="30000" />
      </label>
      <label class="label">Интервал автопостинга, минут
        <input v-model.number="form.post_interval_minutes" class="input" type="number" min="1" />
      </label>
    </div>

    <div class="panel">
      <div class="block-head">
        <div>
          <div class="eyebrow">text generation</div>
          <h2><Sparkles :size="20" /> Тексты постов</h2>
        </div>
      </div>
      <div class="form-grid">
        <label class="label">Генератор текста
          <select v-model="form.text_engine" class="select">
            <option value="openrouter">openrouter</option>
            <option value="pollinations">pollinations</option>
            <option value="ollama">ollama</option>
          </select>
        </label>
        <template v-if="form.text_engine === 'openrouter'">
          <label class="label">OpenRouter API key
            <input v-model="form.openrouter_api_key" class="input" type="password" autocomplete="off" />
          </label>
          <label class="label">OpenRouter base URL
            <input v-model="form.openrouter_base_url" class="input" />
          </label>
          <label class="label">OpenRouter text model
            <input v-model="form.openrouter_text_model" class="input" list="openrouter-text-models" />
            <datalist id="openrouter-text-models">
              <option v-for="model in modelOptions.openrouter_text" :key="model" :value="model" />
            </datalist>
          </label>
          <label class="label">OpenRouter timeout, seconds
            <input v-model.number="form.openrouter_text_timeout_seconds" class="input" type="number" min="30" />
          </label>
          <label class="label">OpenRouter max tokens
            <input v-model.number="form.openrouter_text_max_tokens" class="input" type="number" min="200" />
          </label>
          <label class="label">OpenRouter site URL
            <input v-model="form.openrouter_site_url" class="input" />
          </label>
          <label class="label">OpenRouter site name
            <input v-model="form.openrouter_site_name" class="input" />
          </label>
        </template>
        <template v-if="form.text_engine === 'pollinations'">
          <label class="label">Pollinations API key
            <input v-model="form.pollinations_api_key" class="input" type="password" autocomplete="off" />
          </label>
          <label class="label">Pollinations base URL
            <input v-model="form.pollinations_base_url" class="input" />
          </label>
          <label class="label">Pollinations text model
            <input v-model="form.pollinations_text_model" class="input" list="pollinations-text-models" />
            <datalist id="pollinations-text-models">
              <option v-for="model in modelOptions.pollinations_text" :key="model" :value="model" />
            </datalist>
          </label>
          <label class="label">Pollinations timeout, seconds
            <input v-model.number="form.pollinations_text_timeout_seconds" class="input" type="number" min="30" />
          </label>
          <label class="label">Pollinations max tokens
            <input v-model.number="form.pollinations_text_max_tokens" class="input" type="number" min="200" />
          </label>
        </template>
      </div>
    </div>

    <div class="panel">
      <div class="block-head">
        <div>
          <div class="eyebrow">image generation</div>
          <h2><Sparkles :size="20" /> Premium-картинки</h2>
        </div>
      </div>
      <div class="form-grid">
        <label class="label">Генератор картинок
          <select v-model="form.image_engine" class="select">
            <option value="codex_sale">codex_sale</option>
            <option value="cloudflare_worker">cloudflare_worker</option>
            <option value="pollinations">pollinations</option>
          </select>
        </label>
        <template v-if="form.image_engine === 'codex_sale'">
          <label class="label">Codex Sale API key
            <input v-model="form.codex_sale_api_key" class="input" type="password" autocomplete="off" />
          </label>
          <label class="label">Codex Sale base URL
            <input v-model="form.codex_sale_base_url" class="input" />
          </label>
          <label class="label">Codex Sale image model
            <input v-model="form.codex_sale_image_model" class="input" />
          </label>
          <label class="label">Codex Sale image size
            <select v-model="form.codex_sale_image_size" class="select">
              <option value="1024x1024">1024x1024</option>
              <option value="1024x1536">1024x1536</option>
              <option value="1536x1024">1536x1024</option>
            </select>
          </label>
          <label class="label">Codex Sale timeout, seconds
            <input v-model.number="form.codex_sale_timeout_seconds" class="input" type="number" min="30" />
          </label>
        </template>
        <template v-if="form.image_engine === 'cloudflare_worker'">
          <label class="label">Cloudflare Worker URL
            <input v-model="form.cloudflare_worker_url" class="input" placeholder="https://your-worker.your-subdomain.workers.dev" />
          </label>
          <label class="label">Cloudflare Worker API key
            <input v-model="form.cloudflare_worker_api_key" class="input" type="password" autocomplete="off" />
          </label>
          <label class="label">Cloudflare timeout, seconds
            <input v-model.number="form.cloudflare_worker_timeout_seconds" class="input" type="number" min="30" />
          </label>
        </template>
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
