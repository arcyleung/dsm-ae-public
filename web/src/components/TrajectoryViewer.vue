<script setup lang="ts">
import { onMounted, ref, watch } from "vue";

type Session = {
  short: string;
  label: string;
  file: string;
  featured?: boolean;
  n_events?: number;
};
type Event = { type: string; role?: string; tool?: string; text?: string };

const props = withDefaults(defineProps<{ featuredOnly?: boolean }>(), {
  featuredOnly: false,
});

const reportsBase = `${import.meta.env.BASE_URL}reports/`;
const indexUrl = `${reportsBase}blog/trajectories/index.json`;
const sessions = ref<Session[]>([]);
const status = ref("loading…");
const current = ref<Event[]>([]);
const active = ref("");
const q = ref("");
const typ = ref("");

const shown = () => {
  const needle = q.value.toLowerCase();
  return current.value.filter((ev) => {
    if (typ.value && ev.type !== typ.value) return false;
    if (!needle) return true;
    return `${ev.text || ""} ${ev.tool || ""}`.toLowerCase().includes(needle);
  });
};

async function pick(s: Session) {
  active.value = s.short;
  current.value = [];
  const r = await fetch(reportsBase + "blog/trajectories/" + s.file);
  if (!r.ok) {
    status.value = `failed to load ${s.file}`;
    return;
  }
  current.value = (await r.text())
    .split("\n")
    .filter(Boolean)
    .map((ln) => JSON.parse(ln));
}

onMounted(async () => {
  try {
    const r = await fetch(indexUrl);
    if (!r.ok) throw new Error(String(r.status));
    const idx = await r.json();
    const all: Session[] = idx.sessions || [];
    sessions.value = all.filter((s) => {
      if (!s.n_events) return false;
      if (props.featuredOnly) return Boolean(s.featured);
      return Boolean(s.featured);
    });
    status.value = sessions.value.length
      ? `${sessions.value.length} real sessions`
      : idx.error || "no sessions exported";
    if (sessions.value[0]) await pick(sessions.value[0]);
  } catch (e) {
    status.value = "trajectories not available (need reports/blog/trajectories/)";
  }
});

watch([q, typ], () => {});
</script>

<template>
  <div class="traj">
    <div class="bar meta">{{ status }}. Click a turn to expand.</div>
    <div class="layout">
      <aside>
        <button
          v-for="s in sessions"
          :key="s.short"
          type="button"
          :class="{ active: active === s.short }"
          @click="pick(s)"
        >
          <code>{{ s.short }}</code>
          <span v-if="s.featured"> · featured</span>
          <br />
          {{ s.label }}
          <span v-if="s.n_events"> · {{ s.n_events }}</span>
        </button>
      </aside>
      <section>
        <div class="tools">
          <input v-model="q" type="search" placeholder="filter turns…" />
          <select v-model="typ">
            <option value="">all types</option>
            <option value="message">messages</option>
            <option value="tool_call">tool calls</option>
            <option value="tool_result">tool results</option>
          </select>
        </div>
        <div class="events">
          <details v-for="(ev, i) in shown()" :key="i" class="ev" :class="[ev.type, ev.role]">
            <summary>
              <strong>{{ ev.tool ? ev.type + " · " + ev.tool : ev.role || ev.type }}</strong>
              {{ (ev.text || "").replace(/\s+/g, " ").slice(0, 140) }}
            </summary>
            <pre><code>{{ ev.text }}</code></pre>
          </details>
          <p v-if="!shown().length" class="meta">no matching turns</p>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.traj { border: 1px solid #ccc; margin: 12px 0 20px; }
.bar { padding: 6px 10px; border-bottom: 1px solid #eee; }
.layout { display: flex; min-height: 280px; max-height: 520px; }
aside {
  width: 220px; overflow: auto; border-right: 1px solid #eee; flex-shrink: 0;
}
aside button {
  display: block; width: 100%; text-align: left; border: 0; background: none;
  padding: 6px 8px; cursor: pointer; font: inherit; border-bottom: 1px solid #f2f2f2;
}
aside button.active, aside button:hover { background: #f0f4ff; }
section { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.tools { display: flex; gap: 6px; padding: 6px 8px; border-bottom: 1px solid #eee; }
.tools input { flex: 1; }
.events { overflow: auto; padding: 8px; }
.ev { border: 1px solid #e5e5e5; margin: 0 0 6px; padding: 4px 8px; background: #fafafa; }
.ev.tool_call { border-left: 3px solid #4a7; }
.ev.tool_result { border-left: 3px solid #888; }
.ev.message { border-left: 3px solid #36c; }
pre { white-space: pre-wrap; font-size: 12px; }
</style>
