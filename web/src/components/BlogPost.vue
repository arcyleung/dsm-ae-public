<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from "vue";
import mermaid from "mermaid";
import source from "virtual:blog.md";
import { renderMarkdown } from "../md";
import { setupMermaid } from "../mermaid";
import MetricResults from "./matrix/MetricResults.vue";
import SyndromeMatrix from "./matrix/SyndromeMatrix.vue";
import TrajectoryViewer from "./TrajectoryViewer.vue";

setupMermaid();

const root = ref<HTMLElement | null>(null);

function splitForEmbeds(md: string) {
  const parts: { html: string; embed?: "metrics" | "syndromes" | "traj" }[] = [];
  const chunks = md.split(/<!-- embed:(metrics|syndromes|traj) -->/);
  for (let i = 0; i < chunks.length; i++) {
    const piece = chunks[i];
    if (piece === "metrics" || piece === "syndromes" || piece === "traj") {
      parts.push({ html: "", embed: piece });
    } else if (piece.trim()) {
      parts.push({ html: renderMarkdown(piece) });
    }
  }
  return parts;
}

const sections = ref(splitForEmbeds(source));

async function draw() {
  await nextTick();
  if (!root.value) return;
  const nodes = root.value.querySelectorAll<HTMLElement>(".mermaid");
  if (!nodes.length) return;
  await mermaid.run({ nodes });
}

onMounted(draw);
watch(sections, draw, { flush: "post" });
</script>

<template>
  <article ref="root" class="blog">
    <template v-for="(sec, i) in sections" :key="i">
      <div v-if="sec.html" class="md" v-html="sec.html" />
      <div v-else-if="sec.embed === 'metrics'" class="embed-block">
        <MetricResults />
      </div>
      <div v-else-if="sec.embed === 'syndromes'" class="embed-block">
        <SyndromeMatrix />
      </div>
      <TrajectoryViewer v-else-if="sec.embed === 'traj'" featured-only />
    </template>
  </article>
</template>

<style scoped>
.blog :deep(h1) { font-size: 1.6rem; margin: 0 0 8px; }
.blog :deep(h2) { font-size: 1.2rem; margin: 28px 0 8px; }
.blog :deep(h3) { font-size: 1.05rem; margin: 20px 0 8px; }
.blog :deep(h4) { font-size: 0.97rem; margin: 18px 0 6px; color: #3d4450; }
.blog :deep(img) {
  display: block; max-width: 100%; height: auto;
  margin: 14px 0; border: 1px solid #d0d7de; border-radius: 4px;
}
.blog :deep(pre) {
  background: #f6f8fa; border: 1px solid #d0d7de; padding: 10px 12px;
  overflow-x: auto; border-radius: 4px;
}
.blog :deep(.table-wrap) { overflow-x: auto; margin: 14px 0 18px; }
.blog :deep(.table-wrap table) {
  border-collapse: collapse;
  font-size: 13px;
  width: max-content;
  margin: 0 auto;
}
.blog :deep(.table-wrap th), .blog :deep(.table-wrap td) { border: 1px solid #ccc; padding: 5px 10px; }
.blog :deep(.mermaid-wrap) {
  overflow-x: auto;
  margin: 12px 0 16px;
  padding-bottom: 6px;
}
.blog :deep(.mermaid) { display: inline-block; min-width: max-content; }
.blog :deep(.mermaid svg) { max-width: none !important; height: auto; }
.blog {
  --prose: min(100%, max(50vw, 920px));
  --wide: min(100%, max(80vw, var(--prose)));
}
.blog > .meta,
.blog > .md,
.blog > :deep(.traj) {
  width: var(--prose);
  max-width: var(--prose);
  margin-left: auto;
  margin-right: auto;
}
.embed-block { margin: 16px 0 24px; overflow-x: auto; }
.embed-block :deep(h2),
.embed-block :deep(h3),
.embed-block :deep(.legend),
.embed-block :deep(.refs),
.embed-block :deep(p.meta) {
  width: var(--prose);
  max-width: var(--prose);
  margin-left: auto;
  margin-right: auto;
}
.embed-block :deep(.panel) {
  width: var(--wide);
  max-width: 100%;
  margin-left: auto;
  margin-right: auto;
}
</style>
