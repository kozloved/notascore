import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";

// Placeholder values keep `next build` working when Auth is not configured yet.
export const supabase: SupabaseClient = createClient(
  url || "https://placeholder.supabase.co",
  anonKey || "public-anon-key"
);

export const isSupabaseConfigured = Boolean(url && anonKey);
