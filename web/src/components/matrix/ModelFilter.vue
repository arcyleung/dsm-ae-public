<script setup lang="ts">
import { useMatrix } from "../../useMatrix";
const { data, hidden, toggle, showAll } = useMatrix();
</script>

<template>
  <div v-if="data" class="filter">
    <button type="button" @click="showAll">Show all</button>
    <label v-for="m in data.models" :key="m">
      <input type="checkbox" :checked="!hidden.has(m)" @change="toggle(m)" />
      <code>{{ m }}</code>
    </label>
  </div>
</template>

<style scoped>
.filter {
  display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: center;
  font-size: 12px; margin: 0 0 10px;
}
.filter label { display: inline-flex; gap: 4px; align-items: center; }
button { font: inherit; }
</style>
