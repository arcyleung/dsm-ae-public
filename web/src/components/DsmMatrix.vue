<script setup lang="ts">
import ModelFilter from "./matrix/ModelFilter.vue";
import SyndromeMatrix from "./matrix/SyndromeMatrix.vue";
import DecisionTrees from "./matrix/DecisionTrees.vue";
import MetricResults from "./matrix/MetricResults.vue";

defineProps<{ compact?: boolean }>();
</script>

<template>
  <div class="matrix" :class="{ compact }">
    <p class="meta">
      Data extracted from <code>reports/dsm-ae-matrix.html</code>
      via <code>web/scripts/extract_matrix_data.py</code>.
    </p>
    <ModelFilter />
    <SyndromeMatrix />
    <DecisionTrees v-if="!compact" />
    <MetricResults />
  </div>
</template>

<style scoped>
.matrix { width: 100%; }
.compact :deep(.panel) { max-height: 360px; overflow: auto; }
</style>
