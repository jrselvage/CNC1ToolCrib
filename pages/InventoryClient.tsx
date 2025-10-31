'use client';

import { useState, useEffect } from 'react';
import { supabase } from './index';
import { format } from 'date-fns';

interface Item { id: number; location: string; item: string; notes: string | null; quantity: number; }
interface Tx { id: number; item: string; action: string; user: string; timestamp: string; qty: number; }

export default function InventoryClient() {
  const [items, setItems] = useState<Item[]>([]);
  const [txs, setTxs] = useState<Tx[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchItem, setSearchItem] = useState('');
  const [searchLoc, setSearchLoc] = useState('');

  useEffect(() => { loadItems(); loadTxs(); }, []);

  async function loadItems() {
    const { data } = await supabase.from('inventory').select('*').order('location');
    setItems(data || []); setLoading(false);
  }

  async function loadTxs() {
    const { data } = await supabase.from('transactions').select('*').order('timestamp', { ascending: false }).limit(100);
    setTxs(data || []);
  }

  const handleAdd = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = e.currentTarget;
    const item = f.item.value.trim();
    const loc = f.loc.value.trim().toUpperCase().replace(/[^0-9A-Z]/g, '');
    const qty = parseInt(f.qty.value) || 0;
    const notes = f.notes.value;

    if (!item || !loc || !/^\d{1,3}[A-Z]$/.test(loc)) return alert('Invalid location (e.g., 5A)');

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

  const filtered = items.filter(i =>
    i.item.toLowerCase().includes(searchItem.toLowerCase()) &&
    i.location.toLowerCase().includes(searchLoc.toLowerCase())
  );

  if (loading) return <div className="p-8 text-2xl font-bold text-center">Loading Tool Crib...</div>;

  return (
    <div className="p-6 max-w-6xl mx-auto font-sans bg-gray-50 min-h-screen">
      <h1 className="text-4xl font-bold mb-8 text-center text-blue-700">CNC1 Tool Crib</h1>

      <div className="bg-white p-6 rounded-xl shadow-lg mb-8">
        <h2 className="text-xl font-semibold mb-4">Add New Item</h2>
        <form onSubmit={handleAdd} className="grid grid-cols-1 md:grid-cols-5 gap-3">
          <input name="item" placeholder="Item Name" required className="p-3 border rounded-lg" />
          <input name="loc" placeholder="Location (5A)" required className="p-3 border rounded-lg" />
          <input name="qty" type="number" defaultValue="0" min="0" className="p-3 border rounded-lg" />
          <textarea name="notes" placeholder="Notes" className="p-3 border rounded-lg md:col-span-1" rows={2} />
          <button type="submit" className="bg-blue-600 text-white p-3 rounded-lg font-bold hover:bg-blue-700">Add Item</button>
        </form>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2">
          <h2 className="text-2xl font-semibold mb-4">Inventory</h2>
          <div className="flex gap-3 mb-4">
            <input placeholder="Search item..." value={searchItem} onChange={e => setSearchItem(e.target.value)} className="p-3 border rounded-lg flex-1" />
            <input placeholder="Location..." value={searchLoc} onChange={e => setSearchLoc(e.target.value)} className="p-3 border rounded-lg flex-1" />
          </div>

          <div className="space-y-4 max-h-96 overflow-y-auto">
            {filtered.length === 0 ? (
              <p className="text-center text-gray-500 py-8">No items found. Add one above!</p>
            ) : (
              filtered.map(row => (
                <details key={row.id} className="border rounded-xl p-4 bg-white shadow">
                  <summary className="font-bold text-lg cursor-pointer">
                    {row.item} @ {row.location} — Qty: <strong className="text-green-600">{row.quantity}</strong>
                  </summary>
                  <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                    <div>
                      <textarea
                        defaultValue={row.notes || ''}
                        onBlur={e => updateNotes(row.id, e.target.value)}
                        className="w-full p-3 border rounded-lg"
                        rows={3}
                        placeholder="Add notes..."
                      />
                    </div>
                    <div className="space-y-2">
                      <select defaultValue="None" className="w-full p-3 border rounded-lg">
                        <option>None</option>
                        <option>Check Out</option>
                        <option>Check In</option>
                      </select>
                      <input placeholder="Your Name" className="w-full p-3 border rounded-lg" />
                      <input type="number" defaultValue="1" min="1" className="w-full p-3 border rounded-lg" />
                      <button
                        onClick={() => {
                          const parent = (document.activeElement as HTMLElement)?.closest('details');
                          const select = parent?.querySelector('select') as HTMLSelectElement;
                          const userInput = parent?.querySelector('input[placeholder="Your Name"]') as HTMLInputElement;
                          const qtyInput = parent?.querySelector('input[type="number"]') as HTMLInputElement;
                          const action = select?.value;
                          const user = userInput?.value;
                          const qty = parseInt(qtyInput?.value || '1');
                          if (action && action !== 'None' && user) handleAction(row, action, user, qty);
                        }}
                        className="w-full bg-green-600 text-white p-3 rounded-lg font-bold hover:bg-green-700"
                      >
                        Submit
                      </button>
                    </div>
                  </div>
                </details>
              ))
            )}
          </div>
        </div>

        <div>
          <h2 className="text-2xl font-semibold mb-4">Recent Transactions</h2>
          <div className="space-y-3 text-sm max-h-96 overflow-y-auto">
            {txs.length === 0 ? (
              <p className="text-center text-gray-500">No transactions yet.</p>
            ) : (
              txs.map(tx => (
                <div key={tx.id} className="border-b pb-3">
                  <div className="text-xs text-gray-500">{format(new Date(tx.timestamp), 'MM/dd HH:mm')}</div>
                  <div className="font-medium">{tx.action} {tx.qty}× {tx.item}</div>
                  <div className="text-gray-600">by {tx.user}</div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      <div className="mt-10 text-center">
        <button
          onClick={() => {
            const csv = [['Location','Item','Quantity','Notes'], ...items.map(i => [i.location, i.item, i.quantity, i.notes || ''])].map(r => r.join(',')).join('\n');
            const blob = new Blob([csv], { type: 'text/csv' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `tool_crib_${new Date().toISOString().slice(0,10)}.csv`;
            a.click();
          }}
          className="bg-purple-600 text-white px-8 py-4 rounded-xl text-lg font-bold hover:bg-purple-700"
        >
          Download CSV Report
        </button>
      </div>
    </div>
  );
}
