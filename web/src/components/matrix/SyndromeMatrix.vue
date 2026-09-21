<script setup lang="ts">
import { useMatrix } from "../../useMatrix";
const { data, error, visibleModels, cellFor } = useMatrix();

function cls(status: string) {
  if (status === "PRESENT") return "present";
  if (status === "ABSENT") return "absent";
  return "neval";
}
</script>

<template>
  <section class="block">
    <h2 id="syndrome-matrix">Syndrome matrix</h2>
    <p v-if="error" class="meta">{{ error }}</p>
    <div v-else class="panel">
      <table>
        <thead>
          <tr>
            <th class="corner">Syndrome</th>
            <th v-for="m in visibleModels" :key="m">{{ m }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in data?.syndromes || []" :key="row.id">
            <th class="row">
              <a :href="'#tree-' + row.id">{{ row.name }}</a>
            </th>
            <td
              v-for="m in visibleModels"
              :key="m"
              :class="cls(cellFor(row.cells, m)?.status || '')"
              :title="cellFor(row.cells, m)?.tip"
            >
              {{ cellFor(row.cells, m)?.text }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.block { margin: 0 0 20px; }
.panel { overflow-x: auto; border: 1px solid #ccc; }
table { border-collapse: separate; border-spacing: 0; font-size: 12px; width: max-content; min-width: 100%; }
th, td { border: 1px solid #ccc; padding: 1px 5px; text-align: center; }
th.corner, th.row { text-align: left; position: sticky; left: 0; background: #fafafa; z-index: 1; }
thead th { background: #f5f5f5; position: sticky; top: 0; }
td.present { background: #ffcdd2; }
td.absent { background: #c8e6c9; }
td.neval { background: #eee; color: #555; font-style: italic; }
</style>
