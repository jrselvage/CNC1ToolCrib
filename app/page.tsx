import { createClient } from '@supabase/supabase-js';
import InventoryClient from './InventoryClient';

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
);

export { supabase };

export default function Home() {
  return <InventoryClient />;
}
