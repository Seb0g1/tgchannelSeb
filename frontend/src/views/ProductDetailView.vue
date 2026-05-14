<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ImagePlus, Save, WandSparkles } from 'lucide-vue-next'
import { api, type Draft, type Product } from '../api'

const route = useRoute()
const loading = ref(true)
const saving = ref(false)
const generatingDraft = ref(false)
const generatingImage = ref(false)
const draftProgress = ref(0)
const imageProgress = ref(0)
const imageMessage = ref('')
const draftMessage = ref('')
const product = ref<Product | null>(null)
const attributes = ref<Array<{ name: string; value: string }>>([])
const drafts = ref<Draft[]>([])

let draftTimer: ReturnType<typeof setInterval> | null = null
let imageTimer: ReturnType<typeof setInterval> | null = null

const productId = computed(() => Number(route.params.id))
const form = ref({ order_url: '', is_active: true, is_excluded: false })

function startProgress(target: typeof draftProgress | typeof imageProgress, timerName: 'draft' | 'image') {
  target.value = 7
  const timer = setInterval(() => {
    if (target.value < 88) {
      target.value += Math.max(1, Math.round((92 - target.value) / 9))
    }
  }, 850)
  if (timerName === 'draft') {
    draftTimer = timer
  } else {
    imageTimer = timer
  }
}

function finishProgress(target: typeof draftProgress | typeof imageProgress, timerName: 'draft' | 'image', value = 100) {
  target.value = value
  const timer = timerName === 'draft' ? draftTimer : imageTimer
  if (timer) {
    clearInterval(timer)
  }
  if (timerName === 'draft') {
    draftTimer = null
  } else {
    imageTimer = null
  }
}

function errorText(error: unknown) {
  const candidate = error as { response?: { data?: { detail?: string; message?: string } }; message?: string }
  return candidate.response?.data?.detail || candidate.response?.data?.message || candidate.message || 'Операция завершилась ошибкой'
}

async function load() {
  loading.value = true
  const { data } = await api.get(`/products/${productId.value}`)
  product.value = data.product
  attributes.value = data.attributes
  drafts.value = data.drafts
  form.value = {
    order_url: data.product.order_url || data.product.url || '',
    is_active: data.product.is_active,
    is_excluded: data.product.is_excluded,
  }
  loading.value = false
}

async function save() {
  saving.value = true
  await api.patch(`/products/${productId.value}`, form.value)
  saving.value = false
  await load()
}

async function createDraft() {
  generatingDraft.value = true
  draftMessage.value = 'Генерирую черновик через модель...'
  startProgress(draftProgress, 'draft')
  try {
    await api.post(`/products/${productId.value}/draft`)
    finishProgress(draftProgress, 'draft')
    draftMessage.value = 'Черновик готов'
    await load()
  } catch (error) {
    finishProgress(draftProgress, 'draft', 0)
    draftMessage.value = errorText(error)
  } finally {
    generatingDraft.value = false
  }
}

async function generateImage() {
  generatingImage.value = true
  imageMessage.value = 'Обрабатываю фото товара. При лимитах FreeTheAI попробует до 5 раз...'
  startProgress(imageProgress, 'image')
  try {
    const { data } = await api.post(`/products/${productId.value}/premium-image`)
    if (data.status === 'failed') {
      finishProgress(imageProgress, 'image', 0)
    } else {
      finishProgress(imageProgress, 'image')
    }
    imageMessage.value = data.message || data.status
    if (data.product) {
      product.value = data.product
    }
  } catch (error) {
    finishProgress(imageProgress, 'image', 0)
    imageMessage.value = errorText(error)
  } finally {
    generatingImage.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-if="loading" class="panel empty">Открываю товар...</div>
  <template v-else-if="product">
    <section class="page-head">
      <div>
        <div class="eyebrow">product #{{ product.id }}</div>
        <h1>{{ product.name }}</h1>
        <p class="muted">{{ product.offer_id }} · {{ product.sku || '-' }} · {{ product.brand || 'без бренда' }}</p>
      </div>
      <button class="button" :disabled="generatingDraft || generatingImage" @click="createDraft">
        <WandSparkles :size="18" /> {{ generatingDraft ? 'Генерирую...' : 'Создать черновик' }}
      </button>
    </section>

    <div class="two">
      <section class="stack">
        <div class="panel section">
          <h2>Данные товара</h2>
          <p><b>Цена:</b> {{ product.price || '-' }}</p>
          <p><b>Остаток:</b> {{ product.stock ?? '-' }}</p>
          <p><b>Видимость:</b> {{ product.visibility || '-' }}</p>
          <p><b>Ozon:</b> <a v-if="product.url" class="muted" :href="product.url" target="_blank">{{ product.url }}</a><span v-else>-</span></p>
        </div>

        <div class="panel section">
          <h2>Характеристики</h2>
          <p v-for="attr in attributes.slice(0, 45)" :key="attr.name + attr.value">
            <span class="muted">{{ attr.name }}:</span> {{ attr.value }}
          </p>
        </div>
      </section>

      <section class="stack">
        <div class="panel section">
          <h2>Управление</h2>
          <div class="form-grid">
            <label class="label">Ссылка для заказа
              <input v-model="form.order_url" class="input" />
            </label>
            <label class="switch"><input v-model="form.is_active" type="checkbox" /> товар актуален</label>
            <label class="switch"><input v-model="form.is_excluded" type="checkbox" /> исключить из очереди</label>
            <button class="button" :disabled="saving || generatingDraft || generatingImage" @click="save">
              <Save :size="18" /> {{ saving ? 'Сохраняю...' : 'Сохранить' }}
            </button>
            <button class="button secondary" type="button" :disabled="generatingDraft || generatingImage" @click="generateImage">
              <ImagePlus :size="18" /> {{ generatingImage ? 'Делаю картинку...' : 'Premium-картинка' }}
            </button>

            <div v-if="generatingDraft || draftMessage" class="progress-card">
              <div class="progress-head">
                <span>{{ draftMessage || 'Генерация черновика' }}</span>
                <b v-if="generatingDraft">{{ draftProgress }}%</b>
              </div>
              <div class="progress-track"><span :style="{ width: `${draftProgress}%` }" /></div>
            </div>

            <div v-if="generatingImage || imageMessage" class="progress-card">
              <div class="progress-head">
                <span>{{ imageMessage || 'Генерация premium-картинки' }}</span>
                <b v-if="generatingImage">{{ imageProgress }}%</b>
              </div>
              <div class="progress-track"><span :style="{ width: `${imageProgress}%` }" /></div>
            </div>
          </div>
        </div>

        <div class="panel section">
          <h2>Черновики</h2>
          <div v-if="!drafts.length" class="muted">Черновиков пока нет.</div>
          <div v-for="draft in drafts" :key="draft.id" class="pre" style="margin-bottom: 10px">
            #{{ draft.id }} · {{ draft.status }}
            <br><br>
            {{ draft.text }}
          </div>
        </div>
      </section>
    </div>
  </template>
</template>
