<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { BarChart3, CheckCircle2, CopyPlus, ImagePlus, RefreshCw, RotateCcw, Save, Send, Sparkles, WandSparkles } from 'lucide-vue-next'
import { api, type Draft, type Product, type ProductInsights } from '../api'

const route = useRoute()
const loading = ref(true)
const saving = ref(false)
const assembling = ref(false)
const generatingDraft = ref(false)
const generatingImage = ref(false)
const checkingPublication = ref(false)
const draftProgress = ref(0)
const imageProgress = ref(0)
const assembleProgress = ref(0)
const statusMessage = ref('')
const product = ref<Product | null>(null)
const attributes = ref<Array<{ name: string; value: string }>>([])
const drafts = ref<Draft[]>([])
const insights = ref<ProductInsights | null>(null)
const seriesGenerating = ref(false)

let draftTimer: ReturnType<typeof setInterval> | null = null
let imageTimer: ReturnType<typeof setInterval> | null = null
let assembleTimer: ReturnType<typeof setInterval> | null = null

const productId = computed(() => Number(route.params.id))
const form = ref({ order_url: '', is_active: true, is_excluded: false })
const latestDraft = computed(() => drafts.value.find((item) => item.status === 'pending') || drafts.value[0])
const sourceImage = computed(() => product.value?.images?.[0] || '')
const premiumImage = computed(() => product.value?.styled_image_url || product.value?.styled_image_path || '')
const heroImage = computed(() => premiumImage.value || sourceImage.value)
const busy = computed(() => saving.value || assembling.value || generatingDraft.value || generatingImage.value || checkingPublication.value)

function startProgress(target: typeof draftProgress | typeof imageProgress | typeof assembleProgress, timerName: 'draft' | 'image' | 'assemble') {
  target.value = 8
  const timer = setInterval(() => {
    if (target.value < 92) {
      target.value += Math.max(1, Math.round((95 - target.value) / 10))
    }
  }, 900)
  if (timerName === 'draft') draftTimer = timer
  if (timerName === 'image') imageTimer = timer
  if (timerName === 'assemble') assembleTimer = timer
}

function finishProgress(target: typeof draftProgress | typeof imageProgress | typeof assembleProgress, timerName: 'draft' | 'image' | 'assemble', value = 100) {
  target.value = value
  const timer = timerName === 'draft' ? draftTimer : timerName === 'image' ? imageTimer : assembleTimer
  if (timer) clearInterval(timer)
  if (timerName === 'draft') draftTimer = null
  if (timerName === 'image') imageTimer = null
  if (timerName === 'assemble') assembleTimer = null
}

function errorText(error: unknown) {
  const candidate = error as { response?: { data?: { detail?: string; message?: string } }; message?: string }
  return candidate.response?.data?.detail || candidate.response?.data?.message || candidate.message || 'Операция завершилась ошибкой'
}

async function load() {
  loading.value = true
  const [{ data: productData }, { data: insightsData }] = await Promise.all([
    api.get(`/products/${productId.value}`),
    api.get(`/products/${productId.value}/insights`),
  ])
  product.value = productData.product
  attributes.value = productData.attributes
  drafts.value = productData.drafts
  insights.value = insightsData
  form.value = {
    order_url: productData.product.order_url || productData.product.url || '',
    is_active: productData.product.is_active,
    is_excluded: productData.product.is_excluded,
  }
  loading.value = false
}

async function save() {
  saving.value = true
  try {
    await api.patch(`/products/${productId.value}`, form.value)
    statusMessage.value = 'Настройки товара сохранены'
    await load()
  } finally {
    saving.value = false
  }
}

async function createDraft() {
  generatingDraft.value = true
  statusMessage.value = 'Пишу текст поста...'
  startProgress(draftProgress, 'draft')
  try {
    await api.post(`/products/${productId.value}/draft`)
    finishProgress(draftProgress, 'draft')
    statusMessage.value = 'Черновик готов'
    await load()
  } catch (error) {
    finishProgress(draftProgress, 'draft', 0)
    statusMessage.value = errorText(error)
  } finally {
    generatingDraft.value = false
  }
}

async function createSeries() {
  seriesGenerating.value = true
  statusMessage.value = 'Генерирую серию вариантов...'
  try {
    await api.post(`/products/${productId.value}/draft-series`)
    statusMessage.value = 'Серия черновиков готова'
    await load()
  } catch (error) {
    statusMessage.value = errorText(error)
  } finally {
    seriesGenerating.value = false
  }
}

async function generateImage() {
  generatingImage.value = true
  statusMessage.value = 'Переделываю premium-картинку с логотипом Аромат дня...'
  startProgress(imageProgress, 'image')
  try {
    const { data } = await api.post(`/products/${productId.value}/premium-image`)
    finishProgress(imageProgress, 'image', data.status === 'failed' ? 0 : 100)
    statusMessage.value = data.message || data.status
    if (data.product) product.value = data.product
    await load()
  } catch (error) {
    finishProgress(imageProgress, 'image', 0)
    statusMessage.value = errorText(error)
  } finally {
    generatingImage.value = false
  }
}

async function assemblePost() {
  assembling.value = true
  statusMessage.value = 'Собираю пост: картинка + текст...'
  startProgress(assembleProgress, 'assemble')
  try {
    const { data } = await api.post(`/products/${productId.value}/assemble`)
    finishProgress(assembleProgress, 'assemble', data.image?.status === 'failed' ? 65 : 100)
    statusMessage.value = data.image?.status === 'failed'
      ? `Текст готов, картинка не создалась: ${data.image.message}`
      : 'Пост собран: текст и картинка готовы'
    await load()
  } catch (error) {
    finishProgress(assembleProgress, 'assemble', 0)
    statusMessage.value = errorText(error)
  } finally {
    assembling.value = false
  }
}

async function checkPublication() {
  checkingPublication.value = true
  statusMessage.value = 'Проверяю, есть ли пост в Telegram...'
  try {
    const { data } = await api.post(`/products/${productId.value}/publication-check`)
    statusMessage.value = data.message || data.status
    if (data.product) product.value = data.product
    await load()
  } catch (error) {
    statusMessage.value = errorText(error)
  } finally {
    checkingPublication.value = false
  }
}

async function resetPublication() {
  checkingPublication.value = true
  statusMessage.value = 'Возвращаю товар в очередь публикаций...'
  try {
    const { data } = await api.post(`/products/${productId.value}/publication-reset`)
    statusMessage.value = 'Статус публикации сброшен'
    if (data.product) product.value = data.product
    await load()
  } catch (error) {
    statusMessage.value = errorText(error)
  } finally {
    checkingPublication.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-if="loading" class="panel empty">Открываю товар...</div>
  <template v-else-if="product">
    <section class="product-hero panel">
      <div class="product-media">
        <img v-if="heroImage" :src="heroImage" :alt="product.name">
        <div v-else class="product-media-empty">Фото нет</div>
        <div class="media-badges">
          <span>{{ premiumImage ? 'premium image' : 'ozon photo' }}</span>
          <span v-if="product.is_published" class="ok">published</span>
          <span v-else>in queue</span>
        </div>
      </div>

      <div class="product-summary">
        <div class="eyebrow">product #{{ product.id }}</div>
        <h1>{{ product.name }}</h1>
        <p class="muted">{{ product.offer_id }} · {{ product.sku || '-' }} · {{ product.brand || 'без бренда' }}</p>

        <div class="product-stats">
          <div><span>Цена для поста</span><b>{{ product.price || '-' }}</b></div>
          <div><span>Остаток</span><b>{{ product.stock ?? '-' }}</b></div>
          <div><span>Видимость</span><b>{{ product.visibility || '-' }}</b></div>
        </div>

        <div class="actions product-actions">
          <button class="button" :disabled="busy" @click="assemblePost">
            <Sparkles :size="18" /> {{ assembling ? 'Собираю...' : 'Собрать пост' }}
          </button>
          <button class="button secondary" :disabled="busy" @click="createDraft">
            <WandSparkles :size="18" /> Текст
          </button>
          <button class="button secondary" :disabled="busy || seriesGenerating" @click="createSeries">
            <CopyPlus :size="18" /> {{ seriesGenerating ? 'Серии...' : 'A/B варианты' }}
          </button>
          <button class="button secondary" :disabled="busy" @click="generateImage">
            <ImagePlus :size="18" /> {{ premiumImage ? 'Переделать картинку' : 'Сделать картинку' }}
          </button>
          <button class="button secondary" :disabled="busy" @click="checkPublication">
            <CheckCircle2 :size="18" /> Проверить Telegram
          </button>
          <button class="button danger" :disabled="busy" @click="resetPublication">
            <RotateCcw :size="18" /> Сбросить публикацию
          </button>
        </div>

        <div v-if="statusMessage" class="status-line">{{ statusMessage }}</div>
        <div v-if="assembling" class="progress-card">
          <div class="progress-head"><span>Генерация текста и картинки</span><b>{{ assembleProgress }}%</b></div>
          <div class="progress-track"><span :style="{ width: `${assembleProgress}%` }" /></div>
        </div>
        <div v-if="generatingDraft" class="progress-card">
          <div class="progress-head"><span>Генерация текста</span><b>{{ draftProgress }}%</b></div>
          <div class="progress-track"><span :style="{ width: `${draftProgress}%` }" /></div>
        </div>
        <div v-if="generatingImage" class="progress-card">
          <div class="progress-head"><span>Генерация картинки</span><b>{{ imageProgress }}%</b></div>
          <div class="progress-track"><span :style="{ width: `${imageProgress}%` }" /></div>
        </div>
      </div>
    </section>

    <div class="product-layout">
      <section class="stack">
        <div class="panel section">
          <div class="block-head">
            <div>
              <div class="eyebrow">telegram preview</div>
              <h2>Черновик поста</h2>
            </div>
            <span v-if="latestDraft" class="pill gold">#{{ latestDraft.id }} · {{ latestDraft.status }}</span>
          </div>
          <div v-if="latestDraft" class="telegram-preview">
            <img v-if="heroImage" :src="heroImage" :alt="product.name">
            <div class="telegram-text">{{ latestDraft.text }}</div>
            <button class="telegram-order">
              <Send :size="15" /> Заказать{{ product.price ? ` · ${product.price}` : '' }}
            </button>
          </div>
          <div v-else class="empty compact">Черновика пока нет. Нажмите “Собрать пост”.</div>
        </div>

        <div class="panel section">
          <h2>Фото товара</h2>
          <div class="thumb-grid">
            <img v-if="premiumImage" :src="premiumImage" alt="Premium image">
            <img v-for="image in product.images?.slice(0, 5)" :key="image" :src="image" :alt="product.name">
          </div>
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
            <button class="button" :disabled="busy" @click="save">
              <Save :size="18" /> {{ saving ? 'Сохраняю...' : 'Сохранить' }}
            </button>
          </div>
        </div>

        <div class="panel section">
          <div class="block-head">
            <div>
              <div class="eyebrow">history</div>
              <h2>Черновики</h2>
            </div>
            <button class="button secondary" :disabled="busy" @click="load"><RefreshCw :size="16" /> Обновить</button>
          </div>
          <div v-if="!drafts.length" class="muted">Черновиков пока нет.</div>
          <div v-for="draft in drafts" :key="draft.id" class="draft-mini">
            <div><b>#{{ draft.id }}</b><span>{{ draft.status }}</span></div>
            <p>{{ draft.text.slice(0, 220) }}{{ draft.text.length > 220 ? '...' : '' }}</p>
          </div>
        </div>

        <div class="panel section" v-if="insights">
          <div class="block-head">
            <div>
              <div class="eyebrow">analytics</div>
              <h2><BarChart3 :size="18" /> Товарная аналитика</h2>
            </div>
          </div>
          <div class="analytics-grid">
            <div><span>Черновики</span><strong>{{ insights.drafts_count }}</strong></div>
            <div><span>Генерации текста</span><strong>{{ insights.events.draft_generated || 0 }}</strong></div>
            <div><span>Генерации картинок</span><strong>{{ insights.events.image_generated || 0 }}</strong></div>
            <div><span>Проверки Telegram</span><strong>{{ insights.events.publication_checked || 0 }}</strong></div>
            <div><span>Серии</span><strong>{{ insights.events.series_generated || 0 }}</strong></div>
            <div><span>Публикации</span><strong>{{ insights.events.published || 0 }}</strong></div>
            <div><span>Score</span><strong>{{ insights.recommended.score.toFixed(0) }}</strong></div>
          </div>
          <div class="recommendation-box">
            <div class="muted">Почему товар хорош для поста дня</div>
            <p>{{ insights.recommended.reasons.join(' · ') || 'Нет данных' }}</p>
          </div>
          <div v-if="insights.timeline.length" class="timeline">
            <div v-for="event in insights.timeline" :key="event.created_at + event.event_type">
              <b>{{ event.event_type }}</b>
              <span>{{ event.value || '-' }}</span>
              <p>{{ event.note || '' }}</p>
            </div>
          </div>
        </div>
      </section>
    </div>
  </template>
</template>
