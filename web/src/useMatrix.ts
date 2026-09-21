import { computed, ref } from "vue";

export type Cell = {
  model: string;
  status: string;
  severity?: string | null;
  text?: string;
  tip?: string;
  pass?: number | null;
  n?: number | null;
  std?: string | null;
  label?: string;
  color?: string;
  fg?: string;
};

export type MatrixData = {
  models: string[];
  syndromes: { id: string; name: string; cells: Cell[] }[];
  metrics: { id: string; cites?: number[]; cells: Cell[] }[];
  references?: { id: number; text: string; url: string }[];
  trees: {
    id: string;
    code: string;
    name: string;
    desc: string;
    chips: { model: string; cls: string; text: string }[];
    mermaid: string;
  }[];
};

const data = ref<MatrixData | null>(null);
const error = ref("");
const hidden = ref<Set<string>>(new Set());
let loading: Promise<void> | null = null;

export function useMatrix() {
  if (!loading) {
    loading = fetch(`${import.meta.env.BASE_URL}reports/matrix/vue-data.json`)
      .then((r) => {
        if (!r.ok) throw new Error(String(r.status));
        return r.json();
      })
      .then((j) => {
        data.value = j;
      })
      .catch((e) => {
        error.value = String(e);
      });
  }
  const visibleModels = computed(() =>
    (data.value?.models || []).filter((m) => !hidden.value.has(m)),
  );
  function toggle(model: string) {
    const next = new Set(hidden.value);
    if (next.has(model)) next.delete(model);
    else next.add(model);
    hidden.value = next;
  }
  function showAll() {
    hidden.value = new Set();
  }
  function cellFor(cells: Cell[], model: string) {
    return cells.find((c) => c.model === model);
  }
  return { data, error, hidden, visibleModels, toggle, showAll, cellFor };
}
