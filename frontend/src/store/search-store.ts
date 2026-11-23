import { create } from "zustand";
import type { SearchMode } from "@/lib/archive-types";

type SearchStore = {
  query: string;
  mode: SearchMode;
  setQuery: (query: string) => void;
  setMode: (mode: SearchMode) => void;
};

export const useSearchStore = create<SearchStore>((set) => ({
  query: "",
  mode: "hybrid",
  setQuery: (query) => set({ query }),
  setMode: (mode) => set({ mode }),
}));
