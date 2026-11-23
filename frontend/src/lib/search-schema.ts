import { z } from "zod";

export const searchSchema = z.object({
  query: z.string().trim().max(500, "Search is limited to 500 characters."),
});

export type SearchValues = z.infer<typeof searchSchema>;
