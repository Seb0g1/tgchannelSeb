<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ArrowRight, RefreshCw, Sparkles } from 'lucide-vue-next'
import { api, type Draft, type Product, type SyncReport } from '../api'

const loading = ref(true)
const counts = ref<Record<string, number>>({})
const products = ref<Product[]>([])
const drafts = ref<Draft[]>([])
const syncing = ref(false)
const syncReport = ref<SyncReport | null>(null)

async function load() {
  const { data } = await api.get('/dashboard')
  counts.value = data.counts
  products.value = data.products
  drafts.value = data.drafts
  loading.value = false
}

async function syncOzon() {
  syncing.value = true
  try {
    const { data } = await api.post<SyncReport>('/sync')
    syncReport.value = data
    await load()
  } finally {
    syncing.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="page-head">
    <div>
      <div class="eyebrow">operations</div>
      <h1>Панель управления каналом</h1>
      <p class="muted">Каталог Ozon, AI-черновики, premium эмодзи и публикации.</p>
    </div>
    <div class="actions">
      <button class="button secondary" :disabled="syncing" @click="syncOzon">
        <RefreshCw :size="18" /> {{ syncing ? 'Синхронизация...' : 'Синхронизировать Ozon' }}
      </button>
      <RouterLink class="button" to="/products">
        Выбрать товар <ArrowRight :size="18" />
      </RouterLink>
    </div>
  </section>

  <div v-if="loading" class="panel empty">Загружаю данные...</div>
  <template v-else>
    <section v-if="syncReport" class="panel sync-report">
      <div class="section">
        <h2>Ozon sync report</h2>
        <p class="muted">
          Saved {{ syncReport.saved }} of {{ syncReport.received }} received products.
          Skipped {{ syncReport.skipped_variants }} volume variants.
        </p>
      </div>
      <div class="report-grid">
        <div><span>Requested</span><strong>{{ syncReport.requested }}</strong></div>
        <div><span>Received</span><strong>{{ syncReport.received }}</strong></div>
        <div><span>Saved</span><strong>{{ syncReport.saved }}</strong></div>
        <div><span>With stock</span><strong>{{ syncReport.with_stock }}</strong></div>
      </div>
      <div v-if="syncReport.sample_skipped.length" class="skipped-list">
        <div class="muted">Examples of skipped variants:</div>
        <p v-for="item in syncReport.sample_skipped" :key="item.offer_id">
          {{ item.name }} <span class="muted">kept as</span> {{ item.kept_name }}
        </p>
      </div>
    </section>

    <section class="grid">
      <div class="panel metric"><span>Всего товаров</span><strong>{{ counts.all ?? 0 }}</strong></div>
      <div class="panel metric"><span>Актуальные</span><strong>{{ counts.active ?? 0 }}</strong></div>
      <div class="panel metric"><span>Архив</span><strong>{{ counts.archive ?? 0 }}</strong></div>
      <div class="panel metric"><span>Черновики</span><strong>{{ counts.drafts ?? 0 }}</strong></div>
    </section>

    <div class="two">
      <section class="panel">
        <div class="section">
          <h2>Новые товары</h2>
          <p class="muted">Первые кандидаты для premium-поста.</p>
        </div>
        <div class="table-wrap">
          <table>
            <tbody>
              <tr v-for="product in products" :key="product.id">
                <td>
                  <RouterLink :to="`/products/${product.id}`">{{ product.name }}</RouterLink>
                  <div class="muted">{{ product.offer_id }} · {{ product.brand || 'без бренда' }}</div>
                </td>
                <td>{{ product.price || '-' }}</td>
                <td><span class="pill green">new</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel">
        <div class="section">
          <h2><Sparkles :size="18" /> Черновики</h2>
          <p class="muted">Посты, ожидающие проверки.</p>
        </div>
        <div class="table-wrap">
          <table>
            <tbody>
              <tr v-for="draft in drafts" :key="draft.id">
                <td>#{{ draft.id }}</td>
                <td>товар #{{ draft.product_id }}</td>
                <td><span class="pill gold">{{ draft.status }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </template>
</template>
