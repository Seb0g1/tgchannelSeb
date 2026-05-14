import axios from 'axios'

export const api = axios.create({
  baseURL: '/api',
  timeout: 180000,
})

export type Product = {
  id: number
  offer_id: string
  product_id: string | null
  sku: string | null
  name: string
  brand: string | null
  category: string | null
  description: string | null
  price: string | null
  stock: number | null
  url: string | null
  order_url: string | null
  visibility: string | null
  is_active: boolean
  is_excluded: boolean
  is_published: boolean
  styled_image_path: string | null
  created_at: string | null
  updated_at: string | null
}

export type Draft = {
  id: number
  product_id: number
  text: string
  status: string
  style: string
  telegram_message_id: number | null
  created_at: string | null
  updated_at: string | null
}

export type PremiumEmoji = {
  id: number
  label: string
  emoji: string
  telegram_custom_emoji_id: string | null
  description: string | null
  is_active: boolean
}
