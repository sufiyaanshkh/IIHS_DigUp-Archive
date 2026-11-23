import test from "node:test";
import assert from "node:assert/strict";
import { loadSource } from "./source-loader.mjs";

const types = loadSource("src/lib/archive-types.ts");

test("the existing file-kind controls map to DigUp search kinds", () => {
  const { ResultFilters } = loadSource("src/components/archive/result-filters.tsx", {
    "@/lib/archive-types": types,
    "@/components/ui/button": { Button: () => null },
  });
  let selected = null;
  const nav = ResultFilters({
    active: "all", limit: 50, counts: { all: 0, screenshot: 0, image: 0, document: 0, video: 0, audio: 0 },
    onChange: (value) => { selected = value; },
  });
  nav.props.children[3].props.onClick();
  assert.equal(selected, "document");
  assert.deepEqual(types.kindsForFilter(selected), ["pdf", "doc"]);
  assert.deepEqual(types.kindsForFilter("video"), ["video"]);
  assert.equal(types.kindsForFilter("all"), null);
});

test("search sends the selected kinds, mode, scope and result limit", async () => {
  const { archiveApi } = loadSource("src/lib/archive-api.ts", { "@/lib/auth-api": { authApi: {} } });
  const originalFetch = global.fetch;
  let payload;
  global.fetch = async (url, init) => {
    assert.equal(url, "/api/search");
    payload = JSON.parse(init.body);
    return { ok: true, status: 200, json: async () => ({ hits: [] }) };
  };
  try {
    await archiveApi.search("sample", "keyword", "archive", types.kindsForFilter("document"), 25);
    assert.deepEqual(payload, { query: "sample", mode: "keyword", scope: "archive", kinds: ["pdf", "doc"], limit: 25 });
    await archiveApi.search("sample", "hybrid", "code");
    assert.deepEqual(payload, { query: "sample", mode: "hybrid", scope: "code", kinds: null, limit: 100 });
  } finally {
    global.fetch = originalFetch;
  }
});

test("result cards expose the engine score without changing the displayed content", () => {
  const { ResultsGrid } = loadSource("src/components/archive/results-grid.tsx");
  const result = { id: "one", name: "sample.pdf", folder: "Archive", kind: "document", score: 2.75 };
  const grid = ResultsGrid({
    results: [result], selectedId: "one", onSelect: () => {}, onNavigate: () => {},
    query: "sample", loading: false, error: null,
  });
  const button = grid.props.children[0];
  assert.equal(button.props.title, "DigUp ranking score: 2.75");
  assert.match(button.props["aria-label"], /DigUp ranking score 2\.75/);
});

test("the result-limit control reports the selected limit", () => {
  const { ArchiveToolbar } = loadSource("src/components/archive/archive-toolbar.tsx", {
    react: { useEffect: () => {} },
    "@hookform/resolvers/zod": { zodResolver: () => () => {} },
    "react-hook-form": {
      useForm: () => ({ register: () => ({ ref: () => {} }), control: {}, setValue: () => {}, formState: { errors: {} } }),
      useWatch: () => "",
    },
    "@/components/ui/button": { Button: () => null },
    "@/lib/search-schema": { searchSchema: {} },
    "@/store/search-store": {
      useSearchStore: (selector) => selector({ query: "", mode: "keyword", setQuery: () => {}, setMode: () => {} }),
    },
    "@/components/auth/session-actions": { SessionActions: () => null },
  });
  let selected;
  const tree = ArchiveToolbar({ resultLimit: 100, onResultLimitChange: (value) => { selected = value; } });
  function find(element) {
    if (!element || typeof element !== "object") return null;
    if (element.props?.["aria-label"] === "Maximum search results") return element;
    for (const child of [element.props?.children].flat(Infinity)) {
      const found = find(child);
      if (found) return found;
    }
    return null;
  }
  const control = find(tree);
  assert.equal(control.props.value, 100);
  control.props.onChange({ target: { value: "50" } });
  assert.equal(selected, 50);
});

test("selecting a file-kind filter runs a filtered engine query", async () => {
  const states = ["document", "archive", null, true, false, "saffron", 50];
  const queries = [];
  let searchArgs;
  const shell = loadSource("src/components/archive/archive-shell.tsx", {
    react: {
      useState: () => [states.shift(), () => {}],
      useEffect: () => {},
      useMemo: (fn) => fn(),
      useRef: () => ({ current: null }),
    },
    "@tanstack/react-query": {
      useQueryClient: () => ({}),
      useMutation: () => ({ mutate: () => {}, isPending: false }),
      useQuery: (options) => {
        queries.push(options);
        return options.queryKey[0] === "archive-health"
          ? { data: { digup_cli_available: true, status: "ok" }, isSuccess: true }
          : {};
      },
    },
    "@/components/archive/archive-toolbar": {},
    "@/components/archive/preview-pane": {},
    "@/components/archive/results-grid": {},
    "@/components/archive/result-filters": {},
    "@/components/archive/status-bar": {},
    "@/lib/archive-api": {
      archiveApi: { search: (...args) => { searchArgs = args; } },
      ArchiveApiError: class ArchiveApiError extends Error {},
    },
    "@/lib/archive-types": types,
    "@/store/search-store": {
      useSearchStore: (selector) => selector({ query: "saffron", mode: "keyword", setQuery: () => {} }),
    },
  });
  shell.ArchiveShell({ user: { role: "ARCHIVE_OPERATOR" } });
  const filtered = queries.find((entry) => entry.queryKey.at(-1) === "document");
  assert.equal(filtered.enabled, true);
  filtered.queryFn();
  assert.deepEqual(searchArgs, ["saffron", "keyword", "archive", ["pdf", "doc"], 50]);
});
