<script setup lang="ts">
import { nextTick, watch } from "vue";
import mermaid from "mermaid";
import { horizontalMermaid } from "../../md";
import { setupMermaid } from "../../mermaid";
import { useMatrix } from "../../useMatrix";

setupMermaid();
const { data, error, hidden } = useMatrix();

async function draw(id: string) {
  await nextTick();
  const el = document.getElementById("mm-" + id);
  if (!el || el.querySelector("svg")) return;
  try {
    await mermaid.run({ nodes: [el] });
  } catch {
    /* leave source visible */
  }
}
watch(
  () => data.value?.trees.length,
  async () => {
    await nextTick();
  },
);
</script>

<template>
  <section class="block">
    <h2 id="decision-trees">Decision trees</h2>
    <p v-if="error" class="meta">{{ error }}</p>
    <details
      v-for="t in data?.trees || []"
      :key="t.id"
      :id="'tree-' + t.id"
      class="syndrome"
      @toggle="(e) => (e.target as HTMLDetailsElement).open && draw(t.id)"
    >
      <summary>
        <strong>{{ t.code }}</strong>: {{ t.name }}
        <span class="chips">
          <span
            v-for="c in t.chips.filter((x) => !hidden.has(x.model))"
            :key="c.model"
            class="chip"
            :class="c.cls.split(/\s+/)"
          >{{ c.text }}</span>
        </span>
      </summary>
      <div class="body">
        <p v-if="t.desc" class="meta">{{ t.desc }}</p>
        <div class="mermaid-wrap">
          <div :id="'mm-' + t.id" class="mermaid">{{ horizontalMermaid(t.mermaid) }}</div>
        </div>
      </div>
    </details>
  </section>
</template>

<style scoped>
.block { margin: 0 0 20px; }
.syndrome { border: 1px solid #ccc; margin: 0 0 8px; background: #fff; }
summary { cursor: pointer; padding: 6px 8px; background: #f7f7f7; font-size: 13px; }
.body { padding: 8px 10px 10px; }
.chips { display: inline-flex; flex-wrap: wrap; gap: 4px; margin-left: 8px; }
.chip { font-size: 11px; padding: 1px 6px; border: 1px solid #bbb; border-radius: 3px; }
.chip.present { background: #ffcdd2; }
.chip.absent { background: #c8e6c9; }
.chip.neval { background: #eee; color: #555; }
.mermaid-wrap { overflow-x: auto; padding-bottom: 6px; }
.mermaid { display: inline-block; min-width: max-content; }
.mermaid :deep(svg) { max-width: none !important; }
</style>
