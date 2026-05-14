<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Plus, Trash2 } from 'lucide-vue-next'
import { api, type PremiumEmoji } from '../api'

const emojis = ref<PremiumEmoji[]>([])
const form = ref({ label: '', emoji: '', telegram_custom_emoji_id: '', description: '' })

async function load() {
  const { data } = await api.get('/emojis')
  emojis.value = data.items
}

async function createEmoji() {
  await api.post('/emojis', form.value)
  form.value = { label: '', emoji: '', telegram_custom_emoji_id: '', description: '' }
  await load()
}

async function removeEmoji(id: number) {
  await api.delete(`/emojis/${id}`)
  await load()
}

onMounted(load)
</script>

<template>
  <section class="page-head">
    <div>
      <div class="eyebrow">custom emoji</div>
      <h1>Premium эмодзи</h1>
      <p class="muted">Справочник замен: обычный эмодзи, custom emoji ID и смысл.</p>
    </div>
  </section>

  <div class="two">
    <form class="panel section form-grid" @submit.prevent="createEmoji">
      <h2>Добавить замену</h2>
      <label class="label">Название
        <input v-model="form.label" class="input" required placeholder="премиальное сияние" />
      </label>
      <label class="label">Обычный эмодзи
        <input v-model="form.emoji" class="input" required placeholder="✨" />
      </label>
      <label class="label">Telegram custom emoji ID
        <input v-model="form.telegram_custom_emoji_id" class="input" placeholder="5368324170671202286" />
      </label>
      <label class="label">Описание
        <textarea v-model="form.description" class="textarea" placeholder="Где использовать и какой обычный эмодзи заменяет" />
      </label>
      <button class="button" type="submit"><Plus :size="18" /> Сохранить</button>
    </form>

    <section class="panel">
      <div class="table-wrap">
        <table>
          <thead><tr><th>Эмодзи</th><th>Название</th><th>ID</th><th></th></tr></thead>
          <tbody>
            <tr v-for="item in emojis" :key="item.id">
              <td style="font-size: 26px">{{ item.emoji }}</td>
              <td>{{ item.label }}<div class="muted">{{ item.description || '' }}</div></td>
              <td><code>{{ item.telegram_custom_emoji_id || '-' }}</code></td>
              <td><button class="button danger" @click="removeEmoji(item.id)"><Trash2 :size="16" /></button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
