<template>
  <span class="mark" :class="{ compact }" aria-hidden="true">
    <svg viewBox="0 0 32 32" fill="none">
      <rect width="32" height="32" rx="8" :fill="onDark ? '#2a2420' : '#161311'" />
      <path
        d="M9 11.5h8.5a5.5 5.5 0 1 1 0 11H9V11.5Z"
        :stroke="onDark ? '#E8D5C4' : '#E8D5C4'"
        stroke-width="2.2"
      />
      <circle cx="21.5" cy="17" r="2.2" fill="#C45C26" />
    </svg>
  </span>
</template>

<script setup lang="ts">
defineProps<{
  compact?: boolean
  onDark?: boolean
}>()
</script>

<style scoped>
.mark {
  display: inline-flex;
  width: 28px;
  height: 28px;
  flex-shrink: 0;
}
.mark.compact {
  width: 22px;
  height: 22px;
}
svg {
  width: 100%;
  height: 100%;
  display: block;
}
</style>
