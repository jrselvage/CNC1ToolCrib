'use client';

import { useState, useEffect } from 'react';
import { supabase } from './page';
import { format } from 'date-fns';

interface Item {
  id: number;
  location: string;
  item: string;
  notes: string | null;
  quantity: number;
}

interface Tx {
  id: number;
  item: string;
  action: string;
  user: string;
  timestamp: string;
  qty: number;
}

export default function InventoryClient() {
  const [items, setItems] = useState<Item[]>([]);
  const [txs, setTxs] = useState<Tx[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchItem, setSearchItem] = useState('');
  const [searchLoc, setSearchLoc] = useState('');

  useEffect(() => {
    loadItems();
    loadTxs();
  }, []);

  async function loadItems() {
    const { data } = await supabase.from('inventory').select('*').order('location');
    setItems(data || []);
    setLoading(false);
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

    if (!item || !loc || !/^\d{1,3}[A-Z]$/.test(loc)) {
      alert('Invalid location (e.g., 5A)');
      return;
    }

    await supabase.from('inventory').insert({ item, location: loc, quantity: qty, notes });
    f.reset();
    loadItems();
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
    loadItems();
    loadTxs();
  };

  const filtered = items.filter(i =>
    i.item.toLowerCase().includes(searchItem.toLowerCase()) &&
    i.location.toLowerCase().includes(searchLoc.toLowerCase())
  );

  if (loading) return <div className="p-8 text-xl">Loading...</div>;

  return (
    <div className="p-6 max-w-6xl mx-auto font-sans">
      <h1 className="text-3xl font-bold mb-6 text-blue-700">CNC1 Tool Crib</h1>

      {/* Add Form */}
      <div className="bg-gray-50 p-4 rounded-lg mb-6 shadow">
        <h2 className="font-semibold mb-3">Add New Item</h2>
        <form onSubmit={handleAdd} className="grid grid-cols-1 md:grid-cols-5 gap-3">
          <input name="item" placeholder="Item Name" required className="p-2 border rounded" />
          <input name="loc" placeholder="Location (5A)" required className="p-2 border rounded" />
          <input name="qty" type="number" defaultValue="0" min="0" className="p-2 border rounded" />
          <textarea name="notes" placeholder="Notes (optional)" className="p-2 border rounded md:col-span-1" rows={1} />
          <button type="submit" className="bg-blue-600 text-white p-2 rounded font-medium hover:bg-blue-700">Add Item</button>
        </form>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Inventory */}
        <div className="lg:col-span-2">
          <h2 className="text-xl font-semibold mb-3">Inventory</h2>
          <div className="flex gap-2 mb-3">
            <input placeholder="Search item..." value={searchItem} onChange={e => setSearchItem(e.target.value)} className="p-2 border rounded flex-1" />
            <input placeholder="Location..." value={searchLoc} onChange={e => setSearchLoc(e.target.value)} className="p-2 border rounded flex-1" />
          </div>

          <div className="space-y-3 max-h-96 overflow-y-auto">
            {filtered.map(row => (
              <details key={row.id} className="border rounded-lg p-3 bg-white shadow-sm">
                <summary className="font-medium cursor-pointer text-lg">
                  {row.item} @ {row.location} — Qty: <strong>{row.quantity}</strong>
                </summary>
                <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
                  <div>
                    <textarea
                      defaultValue={row.notes || ''}
                      onBlur={e => updateNotes(row.id, e.target.value)}
                      className="w-full p-2 border rounded text-sm"
                      rows={2}
                      placeholder="Add notes..."
                    />
                  </div>
                  <div className="space-y-2">
                    <select defaultValue="None" className="w-full p-2 border rounded text-sm">
                      <option>None</option>
                      <option>Check Out</option>
                      <option>Check In</option>
                    </select>
                    <input placeholder="Your Name" className="w-full p-2 border rounded text-sm" />
                    <input type="number" defaultValue="1" min="1" className="w-full p-2 border rounded text-sm" />
                    <button
                      onClick={() => {
                        const parent = (document.activeElement as HTMLElement)?.closest('details');
                        const select = parent?.querySelector('select') as HTMLSelectElement;
                        const userInput = parent?.querySelector('input[placeholder="Your Name"]') as HTMLInputElement;
                        const qtyInput = parent?.querySelector('input[type="number"]') as HTMLInputElement;
                        const action = select?.value;
                        const user = userInput?.value;
                        const qty = parseInt(qtyInput?.value || '1');
                        if (action && action !== 'None' && user) {
                          handleAction(row, action, user, qty);
                        }
                      }}
                      className="w-full bg-green-600 text-white p-2 rounded text-sm font-medium hover:bg-green-700"
                    >
                      Submit
                    </button>
                  </div>
                </div>
              </details>
            ))}
          </div>
        </div>

        {/* Transactions */}
        <div>
          <h2 className="text-xl font-semibold mb-3">Recent Transactions</h2>
          <div className="space-y-2 text-sm max-h-96 overflow-y-auto">
            {txs.map(tx => (
              <div key={tx.id} className="border-b pb-2">
                <div className="text-xs text-gray-500">{format(new Date(tx.timestamp), 'MM/dd HH:mm')}</div>
                <div className="font-medium">{tx.action} {tx.qty}× {tx.item}</div>
                <div className="text-gray-600">by {tx.user}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Download */}
      <div className="mt-8 text-center">
        <button
          onClick={() => {
            const csv = [
              ['Location', 'Item', 'Quantity', 'Notes'],
              ...items.map(i => [i.location, i.item, i.quantity, i.notes || ''])
            ].map(r => r.join(',')).join('\n');
            const blob = new Blob([csv], { type: 'text/csv' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `tool_crib_${new Date().toISOString().slice(0,10)}.csv`;
            a.click();
          }}
          className="bg-purple-600 text-white px-6 py-3 rounded-lg font-medium hover:bg-purple-700"
        >
          Download CSV Report
        </button>
      </div>
    </div>
  );
}
