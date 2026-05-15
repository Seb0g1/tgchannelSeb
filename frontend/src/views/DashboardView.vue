<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { AlertTriangle, ArrowRight, CalendarCheck, RefreshCw, Sparkles, Zap } from 'lucide-vue-next'
import { api, type DashboardHealth, type Draft, type Product, type RecommendationCard, type SyncReport } from '../api'

const loading = ref(true)
const counts = ref<Record<string, number>>({})
const products = ref<Product[]>([])
const drafts = ref<Draft[]>([])
const featured = ref<RecommendationCard[]>([])
const health = ref<DashboardHealth | null>(null)
const syncing = ref(false)
const syncReport = ref<SyncReport | null>(null)
const syncError = ref('')

const scheduleText = computed(() => {
  const rules = health.value?.schedule_rules
  if (!rules) return 'правила не заданы'
  const days = rules.active_weekdays.length
  const mode = rules.mode === 'exact' ? `в ${rules.exact_time}` : `${rules.start_time}-${rules.end_time}`
  return `${rules.posts_per_day} пост./день · ${days} дней · ${mode}`
})

async function load() {
  const { data } = await api.get('/dashboard')
  counts.value = data.counts
  products.value = data.products
  drafts.value = data.drafts
  featured.value = data.featured || []
  health.value = data.health || null
  loading.value = false
}

async function syncOzon() {
  syncing.value = true
  syncError.value = ''
  try {
    const { data } = await api.post<SyncReport>('/sync')
    syncReport.value = data
    await load()
  } catch (error: any) {
    syncError.value = error.response?.data?.detail || error.message || 'Синхронизация не удалась'
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
      <p class="muted">Каталог Ozon, AI-генерация, очередь публикаций и быстрый контроль здоровья системы.</p>
    </div>
    <div class="actions">
      <button class="button secondary" :disabled="syncing" @click="syncOzon">
        <RefreshCw :size="18" />
        {{ syncing ? 'Синхронизация...' : 'Синхронизировать Ozon' }}
      </button>
      <RouterLink class="button" to="/schedule">
        Автопостинг <ArrowRight :size="18" />
      </RouterLink>
    </div>
  </section>

  <div v-if="loading" class="panel empty">Загружаю данные...</div>
  <template v-else>
    <section v-if="health?.warnings?.length" class="panel sync-error">
      <strong><AlertTriangle :size="18" /> Требует внимания</strong>
      <p v-for="warning in health.warnings" :key="warning">{{ warning }}</p>
    </section>

    <section v-if="syncError" class="panel sync-error">
      <strong>Ошибка синхронизации Ozon</strong>
      <p>{{ syncError }}</p>
    </section>

    <section v-if="syncReport" class="panel sync-report">
      <div class="section">
        <h2>Отчёт синхронизации Ozon</h2>
        <p class="muted">
          Сохранено {{ syncReport.saved }} из {{ syncReport.received }} полученных товаров.
          Пропущено вариантов объёма: {{ syncReport.skipped_variants }}.
        </p>
      </div>
      <div class="report-grid">
        <div><span>Запрошено</span><strong>{{ syncReport.requested }}</strong></div>
        <div><span>Получено</span><strong>{{ syncReport.received }}</strong></div>
        <div><span>Сохранено</span><strong>{{ syncReport.saved }}</strong></div>
        <div><span>С остатком</span><strong>{{ syncReport.with_stock }}</strong></div>
      </div>
    </section>

    <section class="grid">
      <div class="panel metric"><span>Всего товаров</span><strong>{{ counts.all ?? 0 }}</strong></div>
      <div class="panel metric"><span>Готовы к постингу</span><strong>{{ counts.new ?? 0 }}</strong></div>
      <div class="panel metric"><span>В очереди</span><strong>{{ health?.scheduled ?? 0 }}</strong></div>
      <div class="panel metric"><span>Черновики</span><strong>{{ counts.drafts ?? 0 }}</strong></div>
    </section>

    <section class="health-grid">
      <div class="panel health-card">
        <div><Zap :size="18" /><span>Режим</span></div>
        <strong>{{ health?.app_mode || '-' }}</strong>
        <p class="muted">Для автопостинга должен быть режим auto.</p>
      </div>
      <div class="panel health-card">
        <div><Sparkles :size="18" /><span>AI</span></div>
        <strong>{{ health?.text_engine || '-' }} / {{ health?.image_engine || '-' }}</strong>
        <p class="muted">Текст и premium-картинки для постов.</p>
      </div>
      <div class="panel health-card">
        <div><CalendarCheck :size="18" /><span>Расписание</span></div>
        <strong>{{ scheduleText }}</strong>
        <p class="muted">Текущие правила автозаполнения очереди.</p>
      </div>
    </section>

    <section class="panel section" v-if="featured.length">
      <div class="block-head">
        <div>
          <div class="eyebrow">product of the day</div>
          <h2>Лучшие кандидаты для поста</h2>
        </div>
      </div>
      <div class="featured-grid">
        <RouterLink v-for="item in featured" :key="item.product.id" class="featured-card" :to="`/products/${item.product.id}`">
          <div class="featured-head">
            <span>#{{ item.product.id }}</span>
            <strong>{{ item.score.toFixed(0) }}</strong>
          </div>
          <h3>{{ item.product.name }}</h3>
          <p class="muted">{{ item.product.brand || 'без бренда' }} · {{ item.product.page_price || item.product.price || '-' }} · остаток {{ item.product.stock ?? '-' }}</p>
          <div class="featured-tags">
            <span v-for="reason in item.reasons.slice(0, 3)" :key="reason" class="pill gold">{{ reason }}</span>
          </div>
        </RouterLink>
      </div>
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
                <td>{{ product.page_price || product.price || '-' }}</td>
                <td><span class="pill green">new</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel">
        <div class="section">
          <h2><Sparkles :size="18" /> Черновики</h2>
          <p class="muted">Посты, ожидающие публикации или проверки.</p>
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
