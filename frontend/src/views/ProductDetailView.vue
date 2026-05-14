<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { WandSparkles } from 'lucide-vue-next'
import { api, type Draft, type Product } from '../api'

const route = useRoute()
const loading = ref(true)
const saving = ref(false)
const generating = ref(false)
const imageMessage = ref('')
const product = ref<Product | null>(null)
const attributes = ref<Array<{ name: string; value: string }>>([])
const drafts = ref<Draft[]>([])

const productId = computed(() => Number(route.params.id))
const form = ref({ order_url: '', is_active: true, is_excluded: false })

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
  generating.value = true
  await api.post(`/products/${productId.value}/draft`)
  generating.value = false
  await load()
}

async function generateImage() {
  imageMessage.value = ''
  const { data } = await api.post(`/products/${productId.value}/premium-image`)
  imageMessage.value = data.message || data.status
  if (data.product) {
    product.value = data.product
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
      <button class="button" :disabled="generating" @click="createDraft">
        <WandSparkles :size="18" /> {{ generating ? 'Генерирую...' : 'Создать черновик' }}
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
            <button class="button" :disabled="saving" @click="save">{{ saving ? 'Сохраняю...' : 'Сохранить' }}</button>
            <button class="button secondary" type="button" @click="generateImage">Premium-картинка</button>
            <span v-if="imageMessage" class="pill gold">{{ imageMessage }}</span>
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
