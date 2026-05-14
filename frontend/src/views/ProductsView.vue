<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { Search } from 'lucide-vue-next'
import { api, type Product } from '../api'

const q = ref('')
const statusFilter = ref('active')
const page = ref(1)
const limit = 40
const total = ref(0)
const loading = ref(false)
const products = ref<Product[]>([])

async function load() {
  loading.value = true
  const { data } = await api.get('/products', {
    params: { q: q.value, status_filter: statusFilter.value, page: page.value, limit },
  })
  products.value = data.items
  total.value = data.total
  loading.value = false
}

watch(statusFilter, () => { page.value = 1; load() })
onMounted(load)
</script>

<template>
  <section class="page-head">
    <div>
      <div class="eyebrow">catalog</div>
      <h1>Товары Ozon</h1>
      <p class="muted">Поиск по 30k товарам, фильтр актуальности и очередь публикаций.</p>
    </div>
  </section>

  <form class="toolbar" @submit.prevent="page = 1; load()">
    <input v-model="q" class="input" style="max-width: 430px" placeholder="Название, артикул, SKU, бренд" />
    <select v-model="statusFilter" class="select" style="max-width: 230px">
      <option value="active">Актуальные</option>
      <option value="new">Новые для публикации</option>
      <option value="published">Опубликованные</option>
      <option value="excluded">Исключённые</option>
      <option value="archive">Архив</option>
      <option value="all">Все</option>
    </select>
    <button class="button" type="submit"><Search :size="17" /> Найти</button>
  </form>

  <section class="panel">
    <div v-if="loading" class="empty">Загружаю каталог...</div>
    <div v-else class="table-wrap">
      <table>
        <thead>
          <tr><th>Товар</th><th>Цена</th><th>Остаток</th><th>Статус</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="product in products" :key="product.id">
            <td>
              <RouterLink :to="`/products/${product.id}`">{{ product.name }}</RouterLink>
              <div class="muted">{{ product.offer_id }} · {{ product.sku || '-' }} · {{ product.brand || 'без бренда' }}</div>
            </td>
            <td>{{ product.price || '-' }}</td>
            <td>{{ product.stock ?? '-' }}</td>
            <td>
              <span class="pill" :class="product.is_active ? 'green' : 'red'">{{ product.is_active ? 'active' : 'archive' }}</span>
              <span v-if="product.is_published" class="pill gold">published</span>
              <span v-if="product.is_excluded" class="pill red">excluded</span>
            </td>
            <td><RouterLink class="button secondary" :to="`/products/${product.id}`">Открыть</RouterLink></td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>

  <div class="pagination">
    <button class="button secondary" :disabled="page === 1" @click="page--; load()">Назад</button>
    <span class="muted">Страница {{ page }} · всего {{ total }}</span>
    <button class="button secondary" :disabled="page * limit >= total" @click="page++; load()">Дальше</button>
  </div>
</template>
