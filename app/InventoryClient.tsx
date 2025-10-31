'use client';

import { useState, useEffect } from 'react';
import { supabase } from './page';
import { format } from 'date-fns';

interface Item { id: number; location: string; item: string; notes: string | null; quantity: number; }
interface Tx { id: number; item: string; action: string; user: string; timestamp: string; qty: number; }

export default function InventoryClient() {
  const [items, setItems] = useState<Item[]>([]);
  const [txs, setTxs] = useState<Tx[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => { loadItems(); loadTxs(); }, []);

  async function loadItems() {
    const { data } = await supabase.from('inventory').select('*').order('location');
    setItems(data || []); setLoading(false);
  }

  async function loadTxs() {
    const { data } = await supabase.from('transactions').select('*').order('timestamp', { ascending: false }).limit(100);
    setTxs(data || []);
  }

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    const f = e.target as HTMLFormElement;
    const item = f.item.value.trim();
    const loc = f.loc.value.trim().toUpperCase().replace(/[^0-9A-Z]/g, '');
    const qty = parseInt(f.qty.value) || 0;
    const notes = f.notes.value;

    if (!item || !loc || !/^\d{1,3}[A-Z]$/.test(loc)) return alert('Invalid location');

    await supabase.from('inventory').insert({ item, location: loc, quantity: qty, notes });
    f.reset(); loadItems();
  };

  const updateNotes = async (id: number, notes: string) => {
    await supabase.from('inventory').update({ notes }).eq('id', id);
    loadItems();
  };

  const handleAction = async (row: Item, action: string, user: string, qty: number) => {
    if (!user.trim()) return alert('Enter user');
    await supabase.from('transactions').insert({ item: row.item, action, user, qty, timestamp: new Date() });
    const newQty = action === 'Check Out' ? row.quantity - qty : row.quantity + qty;
    await supabase.from('inventory').update({ quantity: Math.max(0, newQty) }).eq('id', row.id);
    loadItems(); loadTxs();
  };

  if (loading) return <div className="p-8 text-2xl text-center">Loading...</div>;

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <h1 className="text-4xl font-bold text-center text-blue-700 mb-8">CNC1 Tool Crib</h1>

      <form onSubmit={handleAdd} className="bg-white p-6 rounded-xl shadow mb-8 grid grid-cols-1 md:grid-cols-5 gap-3">
        <input name="item" placeholder="Item" required className="p-3 border rounded" />
        <input name="loc" placeholder="Loc (5A)" required className="p-3 border rounded" />
        <input name="qty" type="number" defaultValue="0" className="p-3 border rounded" />
        <textarea name="notes" placeholder="Notes" className="p-3 border rounded md:col-span-1" rows={2} />
        <button type="submit" className="bg-blue-600 text-white p-3 rounded font-bold">Add</button>
      </form>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2 space-y-4">
          {items.map(row => (
            <details key={row.id} className="border p-4 bg-white rounded shadow">
              <summary className="font-bold text-lg cursor-pointer">
                {row.item} @ {row.location} — Qty: {row.quantity}
              </summary>
              <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
                <textarea defaultValue={row.notes || ''} onBlur={e => updateNotes(row.id, e.target.value)} className="p-2 border rounded" rows={2} />
                <div className="space-y-1">
                  <select defaultValue="None" className="w-full p-2 border rounded">
                    <option>None</option>
                    <option>Check Out</option>
                    <option>Check In</option>
                  </select>
                  <input placeholder="User" className="w-full p-2 border rounded" />
                  <input type="number" defaultValue="1" min="1" className="w-full p-2 border rounded" />
                  <button
                    onClick={() => {
                      const parent = (document.activeElement as HTMLElement)?.closest('details');
                      const select = parent?.querySelector('select') as HTMLSelectElement;
                      const user = (parent?.querySelector('input[placeholder="User"]') as HTMLInputElement)?.value;
                      const qty = parseInt((parent?.querySelector('input[type="number"]') as HTMLInputElement)?.value || '1');
                      if (select?.value !== 'None' && user) handleAction(row, select.value, user, qty);
                    }}
                    className="w-full bg-green-600 text-white p-2 rounded"
                  >
                    Submit
                  </button>
                </div>
              </div>
            </details>
          ))}
        </div>

        <div>
          <h2 className="text-xl font-bold mb-3">Recent TX</h2>
          <div className="space-y-2 text-sm">
            {txs.map(tx => (
              <div key={tx.id} className="border-b pb-2">
                <div className="text-xs text-gray-500">{format(new Date(tx.timestamp), 'MM/dd HH:mm')}</div>
                <div>{tx.action} {tx.qty}× {tx.item}</div>
                <div className="text-gray-600">by {tx.user}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-8 text-center">
        <button
          onClick={() => {
            const csv = [['Location','Item','Quantity','Notes'], ...items.map(i => [i.location, i.item, i.quantity, i.notes || ''])].map(r => r.join(',')).join('\n');
            const blob = new Blob([csv], { type: 'text/csv' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'tool_crib.csv';
            a.click();
          }}
          className="bg-purple-600 text-white px-6 py-3 rounded"
        >
          Download CSV
        </button>
      </div>
    </div>
  );
}
