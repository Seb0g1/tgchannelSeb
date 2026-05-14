<script setup lang="ts">
import { Bot, Boxes, FileText, Gem, LayoutDashboard } from 'lucide-vue-next'
import { RouterLink, RouterView, useRoute } from 'vue-router'

const route = useRoute()

const items = [
  { to: '/', label: 'Дашборд', icon: LayoutDashboard },
  { to: '/products', label: 'Товары', icon: Boxes },
  { to: '/drafts', label: 'Черновики', icon: FileText },
  { to: '/emojis', label: 'Premium эмодзи', icon: Gem },
]
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark"><Bot :size="22" /></div>
        <div>
          <strong>Аромат дня</strong>
          <span>AI channel ops</span>
        </div>
      </div>

      <nav class="nav">
        <RouterLink
          v-for="item in items"
          :key="item.to"
          :to="item.to"
          :class="{ active: route.path === item.to || (item.to !== '/' && route.path.startsWith(item.to)) }"
        >
          <component :is="item.icon" :size="18" />
          {{ item.label }}
        </RouterLink>
      </nav>

      <div class="side-note">
        <span>premium mode</span>
        <b>Ollama + Ozon + Telegram</b>
      </div>
    </aside>

    <main class="content">
      <RouterView />
    </main>
  </div>
</template>
