import { createRouter, createWebHistory } from 'vue-router'
import DashboardView from './views/DashboardView.vue'
import ProductsView from './views/ProductsView.vue'
import ProductDetailView from './views/ProductDetailView.vue'
import DraftsView from './views/DraftsView.vue'
import EmojisView from './views/EmojisView.vue'
import LoginView from './views/LoginView.vue'
import SettingsView from './views/SettingsView.vue'
import ScheduleView from './views/ScheduleView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: DashboardView },
    { path: '/login', component: LoginView },
    { path: '/products', component: ProductsView },
    { path: '/products/:id', component: ProductDetailView },
    { path: '/drafts', component: DraftsView },
    { path: '/emojis', component: EmojisView },
    { path: '/schedule', component: ScheduleView },
    { path: '/settings', component: SettingsView },
  ],
})
