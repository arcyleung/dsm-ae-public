<script setup lang="ts">
import { ref } from "vue";
import BlogPost from "./components/BlogPost.vue";
import DsmMatrix from "./components/DsmMatrix.vue";
import TrajectoryViewer from "./components/TrajectoryViewer.vue";

const initial = (new URLSearchParams(location.search).get("tab") || "blog") as
  | "blog"
  | "matrix"
  | "traj";
const tab = ref<"blog" | "matrix" | "traj">(
  ["blog", "matrix", "traj"].includes(initial) ? initial : "blog",
);
</script>

<template>
  <div class="wrap" :class="{ wide: tab === 'matrix' || tab === 'blog' }">
    <nav class="top">
      <strong>DSM-AE</strong>
      <button :class="{ active: tab === 'blog' }" @click="tab = 'blog'">Blog</button>
      <button :class="{ active: tab === 'matrix' }" @click="tab = 'matrix'">Matrix</button>
      <button :class="{ active: tab === 'traj' }" @click="tab = 'traj'">Trajectories</button>
    </nav>
    <BlogPost v-if="tab === 'blog'" />
    <DsmMatrix v-else-if="tab === 'matrix'" />
    <TrajectoryViewer v-else />
  </div>
</template>
