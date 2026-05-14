<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { LockKeyhole } from 'lucide-vue-next'
import { api } from '../api'

const router = useRouter()
const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

async function login() {
  error.value = ''
  loading.value = true
  try {
    await api.post('/auth/login', { username: username.value, password: password.value })
    await router.push('/')
  } catch {
    error.value = 'Неверный логин или пароль'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <form class="login-card" @submit.prevent="login">
      <div class="brand-mark" style="margin-bottom: 16px"><LockKeyhole :size="22" /></div>
      <div class="eyebrow">secure admin</div>
      <h1>Аромат дня</h1>
      <p class="muted">Войдите в панель управления Telegram-каналом.</p>
      <label class="label">Логин
        <input v-model="username" class="input" autocomplete="username" required />
      </label>
      <label class="label">Пароль
        <input v-model="password" class="input" type="password" autocomplete="current-password" required />
      </label>
      <div v-if="error" class="pill red">{{ error }}</div>
      <button class="button" type="submit" :disabled="loading">{{ loading ? 'Вхожу...' : 'Войти' }}</button>
    </form>
  </main>
</template>
