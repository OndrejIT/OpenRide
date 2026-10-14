import { createRouter, createWebHistory } from 'vue-router'
import RouteListView from '@/views/RouteListView.vue'

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', name: 'routes', component: RouteListView },
    // lazy: MapLibre and the YouTube player stay out of the list page bundle
    { path: '/ride/:id(\\d+)', name: 'ride', component: () => import('@/views/RideView.vue') },
    { path: '/check/:id(\\d+)', name: 'check', component: () => import('@/views/CheckView.vue') },
    { path: '/manage', name: 'manage', component: () => import('@/views/ManageView.vue') },
    { path: '/trainer', name: 'trainer', component: () => import('@/views/TrainerView.vue') },
    { path: '/rides', name: 'rides', component: () => import('@/views/RidesView.vue') },
    { path: '/rides/:id(\\d+)', name: 'ride-record', component: () => import('@/views/RideRecordView.vue') },
  ],
})
