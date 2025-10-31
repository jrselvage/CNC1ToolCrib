import { createClient } from '@supabase/supabase-js';
import InventoryClient from './InventoryClient';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

export const supabase = createClient(supabaseUrl, supabaseAnonKey);

export default function Home() {
  return <InventoryClient />;
}
