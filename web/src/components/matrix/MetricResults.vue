<script setup lang="ts">
import { computed, ref } from "vue";
import { useMatrix } from "../../useMatrix";
const { data, error, visibleModels, cellFor } = useMatrix();

// A row measured on a handful of models cannot be compared across the
// matrix, and reading one is more misleading than reading none. Hide those
// by default; the toggle restores them.
const MIN_MODELS = 10;

const showIncomplete = ref(false);

function modelsRun(row: { cells: { status?: string }[] }) {
  return row.cells.filter((c) => c && c.status && c.status !== "NOT_RUN").length;
}

const allRows = computed(() => data.value?.metrics ?? []);
const completeRows = computed(() =>
  allRows.value.filter((r) => modelsRun(r) >= MIN_MODELS),
);
const rows = computed(() =>
  showIncomplete.value ? allRows.value : completeRows.value,
);
const hiddenCount = computed(() => allRows.value.length - completeRows.value.length);
</script>

<template>
  <section class="block">
    <h2 id="metric-results">Metric results</h2>
    <div class="legend">
      <span>Pass rate</span>
      <span>0%</span>
      <i class="bar" />
      <span>100%</span>
      <span v-if="hiddenCount" class="filter">
        <a href="#" @click.prevent="showIncomplete = !showIncomplete">{{
          showIncomplete ? "Hide incomplete" : "Show all"
        }}</a>
        <span class="note">
          {{ showIncomplete
            ? `showing ${hiddenCount} row(s) run on fewer than ${MIN_MODELS} models`
            : `${hiddenCount} row(s) hidden: run on fewer than ${MIN_MODELS} models` }}
        </span>
      </span>
    </div>
    <p v-if="error" class="meta">{{ error }}</p>
    <div v-else class="panel">
      <table>
        <thead>
          <tr>
            <th class="corner">Metric</th>
            <th v-for="m in visibleModels" :key="m">{{ m }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id">
            <th class="row">
              <code>{{ row.id }}</code>
              <sup v-if="row.cites?.length" class="cites">
                [
                <template v-for="(n, i) in row.cites" :key="n">
                  <a class="cite" :href="'#ref-' + n">{{ n }}</a><template v-if="i < row.cites.length - 1">,</template>
                </template>
                ]
              </sup>
            </th>
            <td
              v-for="m in visibleModels"
              :key="m"
              :style="cellFor(row.cells, m)?.color
                ? { background: cellFor(row.cells, m)!.color!, color: cellFor(row.cells, m)!.fg }
                : undefined"
              :class="{ 'not-run': cellFor(row.cells, m)?.status === 'NOT_RUN' }"
              :title="cellFor(row.cells, m)?.tip"
            >
              {{ cellFor(row.cells, m)?.label }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <h3 v-if="data?.references?.length" id="references">References</h3>
    <ul v-if="data?.references?.length" class="refs">
      <li v-for="r in data.references" :id="'ref-' + r.id" :key="r.id">
        <template v-if="r.url">
          [{{ r.id }}] <a :href="r.url" target="_blank" rel="noopener">{{ r.text }}</a>
        </template>
        <template v-else>[{{ r.id }}] {{ r.text }}</template>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.block { margin: 0 0 10px; }
.legend { display: flex; align-items: center; gap: 8px; font-size: 12px; color: #444; margin: 0 0 4px; flex-wrap: wrap; }
.filter { display: inline-flex; align-items: baseline; gap: 6px; margin-left: 6px; }
.filter a { color: #0b5cad; }
.filter .note { color: #777; }
.bar {
  width: 160px; height: 10px; border: 1px solid #999;
  background: linear-gradient(90deg, rgb(165,0,38), rgb(255,255,191), rgb(0,104,55));
}
.panel { overflow-x: auto; border: 1px solid #ccc; }
table { border-collapse: separate; border-spacing: 0; font-size: 12px; width: max-content; min-width: 100%; }
th, td { border: 1px solid #ccc; padding: 1px 5px; text-align: center; }
th.corner, th.row { text-align: left; position: sticky; left: 0; background: #fafafa; z-index: 1; }
thead th { background: #f5f5f5; position: sticky; top: 0; }
td.not-run { background: #eee; color: #555; font-style: italic; }
.cites { margin-left: 3px; font-size: 0.85em; white-space: nowrap; font-weight: 400; }
.cite { color: #0645ad; text-decoration: none; }
.refs { margin: 12px 0 0; padding-left: 0; list-style: none; font-size: 12px; color: #333; }
.refs li { margin: 0 0 4px; }
.refs li:target { background: #fff3cd; }
</style>
