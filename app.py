"""Network Explorer: a local, observational Mac device inventory window."""
import argparse
import json
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from inventory import collect

BASE = Path(__file__).resolve().parent
STATE = BASE / '.state'

class Explorer:
    def __init__(self, root):
        self.root, self.snapshot, self.rows = root, None, {}
        self.results, self.busy, self.closed = queue.Queue(), False, False
        self.first_result = True
        self.labels, self.label_error = {}, ''
        try:
            if (STATE / 'labels.json').exists():
                raw = json.loads((STATE / 'labels.json').read_text())
                if not isinstance(raw, dict): raise ValueError('Expected an object')
                self.labels = {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}
        except (OSError, ValueError) as exc:
            self.label_error = f'Saved labels could not be read: {exc}'
        root.title('Network Explorer — Devices')
        root.geometry('1160x780')
        root.minsize(920, 650)
        root.configure(bg='#f2f5f9')
        root.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('.', font=('Helvetica', 12), background='#f2f5f9', foreground='#15283e')
        style.configure('TButton', padding=(12, 8), background='#e5edf5')
        style.map('TButton', background=[('active', '#d2e2f1')])
        style.configure('Treeview', background='white', fieldbackground='white', rowheight=34, borderwidth=0)
        style.configure('Treeview.Heading', font=('Helvetica', 11, 'bold'), padding=10, background='#e5edf5')
        style.map('Treeview', background=[('selected', '#d5e8f6')], foreground=[('selected', '#12263c')])
        frame = ttk.Frame(root, padding=24)
        frame.pack(fill='both', expand=True)
        head = ttk.Frame(frame)
        head.pack(fill='x')
        ttk.Label(head, text='Network Explorer', font=('Helvetica', 26, 'bold')).pack(side='left')
        self.refresh_button = ttk.Button(head, text='Refresh devices', command=self.refresh)
        self.refresh_button.pack(side='right')
        ttk.Label(frame, text='DEVICES  /  Observed from this Mac', foreground='#487797', padding=(0, 9)).pack(anchor='w')
        self.summary = tk.StringVar(value='Reading the Mac’s local neighbor tables…')
        ttk.Label(frame, textvariable=self.summary, font=('Helvetica', 15, 'bold')).pack(anchor='w', pady=(8, 5))
        self.context = tk.StringVar()
        ttk.Label(frame, textvariable=self.context, foreground='#52677e').pack(anchor='w')
        ttk.Label(frame, text='Read-only inventory • No device connections, login attempts, scans, or router changes.', foreground='#226b60').pack(anchor='w', pady=8)
        filters = ttk.Frame(frame)
        filters.pack(fill='x', pady=8)
        ttk.Label(filters, text='Find device').pack(side='left')
        self.search = tk.StringVar()
        self.search.trace_add('write', lambda *_: self.render())
        ttk.Entry(filters, textvariable=self.search, width=26).pack(side='left', padx=8)
        self.interface = tk.StringVar(value='All interfaces')
        self.interface_box = ttk.Combobox(filters, textvariable=self.interface, state='readonly', width=18, values=['All interfaces'])
        self.interface_box.pack(side='left', padx=8)
        self.interface_box.bind('<<ComboboxSelected>>', lambda _: self.render())
        self.auto = tk.BooleanVar(value=False)
        ttk.Checkbutton(filters, text='Refresh every 15 seconds', variable=self.auto).pack(side='right')
        table = ttk.Frame(frame)
        table.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(table, columns=('name', 'address', 'role', 'interface', 'evidence'), show='headings', selectmode='browse', height=6)
        cols = [('name', 'Device / your label', 200), ('address', 'Address', 230), ('role', 'Identity evidence', 180), ('interface', 'Interface', 90), ('evidence', 'Observation', 180)]
        for col, title, width in cols:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, minwidth=70)
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.tree.bind('<<TreeviewSelect>>', self.select)
        self.details = tk.Text(frame, height=4, wrap='word', bg='#ffffff', fg='#263f57', font=('Helvetica', 12), relief='flat', padx=14, pady=12, state='disabled')
        self.details.pack(fill='x', pady=(14, 8))
        edit = ttk.Frame(frame)
        edit.pack(fill='x')
        ttk.Label(edit, text='Your label').pack(side='left')
        self.label = tk.StringVar()
        self.label_entry = ttk.Entry(edit, textvariable=self.label, width=28)
        self.label_entry.pack(side='left', padx=8)
        self.save_button = ttk.Button(edit, text='Save label', command=self.save_label)
        self.save_button.pack(side='left')
        ttk.Button(edit, text='Export snapshot…', command=self.export).pack(side='right')
        self.status = tk.StringVar(value=self.label_error or 'Labels identify your devices; IP address ranges do not identify device types.')
        ttk.Label(frame, textvariable=self.status, wraplength=1080, foreground='#52677e').pack(anchor='w', pady=(12, 0))
        self.set_details('Select a device to see its addresses and evidence. Unknown devices stay unknown until you label them. Cached records may describe devices that have disconnected.')
        root.bind('<Command-r>', lambda _: self.refresh())
        root.bind('<Command-q>', lambda _: self.close())
        root.after(80, self.poll)
        root.after(15000, self.tick)
        self.refresh()

    def close(self):
        self.closed = True
        self.root.destroy()

    def tick(self):
        if self.closed: return
        if self.auto.get() and self.root.focus_get() != self.label_entry: self.refresh()
        self.root.after(15000, self.tick)

    def refresh(self):
        if self.busy or self.closed: return
        self.busy = True
        self.refresh_button.configure(state='disabled')
        self.status.set('Reading existing local records; no packets are being sent to devices.')
        def work():
            try: self.results.put(('ok', collect()))
            except Exception as exc: self.results.put(('error', str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        if self.closed: return
        try:
            kind, value = self.results.get_nowait()
        except queue.Empty: pass
        else:
            self.busy = False
            self.refresh_button.configure(state='normal')
            if kind == 'error' or value.get('errors', {}).get('interfaces'):
                error = value if kind == 'error' else value['errors']['interfaces']
                self.status.set('Refresh failed; previous data is stale. ' + error)
            else:
                self.snapshot = value
                choices = ['All interfaces'] + list(value['interfaces'])
                self.interface_box.configure(values=choices)
                if self.first_result and value['route'].get('interface') in choices:
                    self.interface.set(value['route']['interface'])
                self.first_result = False
                if self.interface.get() not in choices: self.interface.set('All interfaces')
                errors = value['errors']
                self.status.set('Some sources unavailable: ' + '; '.join(f'{k}: {v}' for k, v in errors.items()) if errors else 'Local cache read complete. Cached does not mean online; this may not include every device.')
                self.render()
        self.root.after(80, self.poll)

    def render(self):
        if not self.snapshot: return
        previous = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        term = self.search.get().casefold()
        for item in self.snapshot['devices']:
            name = self.labels.get(item['label_key'], item['role'])
            if self.interface.get() != 'All interfaces' and item['interface'] != self.interface.get(): continue
            if term not in ' '.join([name, item['role'], item['mac']] + item['addresses']).casefold(): continue
            self.rows[item['id']] = item
            address = item['addresses'][0] + (f' (+{len(item["addresses"])-1})' if len(item['addresses']) > 1 else '')
            self.tree.insert('', 'end', iid=item['id'], values=(name, address, item['role'], item['interface'], 'Local interface' if item['role']=='This Mac' else 'Cached; not verified online'))
        local = sum(d['role'] == 'This Mac' for d in self.rows.values())
        self.summary.set(f'{len(self.rows) - local} observed neighbors · {local} local Mac interface' + ('s' if local != 1 else ''))
        network = ', '.join(f'{i}: {", ".join(v["networks"]) or "IPv6"}' for i, v in self.snapshot['interfaces'].items()) or 'No active hardware interface found'
        self.context.set(f'{network}   •   Read at {self.snapshot["observed_at"]}')
        if previous and previous[0] in self.rows:
            self.tree.selection_set(previous[0]); self.select()
        else:
            self.label.set('')
            self.set_details('Select a row for evidence. A cache entry is an observation, not proof that a device is online. The same neighbor can have multiple IPv4/IPv6 addresses.')

    def selected(self):
        selection = self.tree.selection()
        return self.rows.get(selection[0]) if selection else None

    def select(self, _=None):
        item = self.selected()
        if not item: return
        self.label.set(self.labels.get(item['label_key'], ''))
        text = f'{item["role"]}  •  Hardware address: {item["mac"]}\nAddresses: {", ".join(item["addresses"])}\nEvidence: {"; ".join(item["sources"])}\n'
        text += ('This hardware address is locally administered; it may be private/randomized. ' if item['private_mac'] else '')
        text += 'An IP or MAC address alone does not establish a phone/computer identity. Labels are yours and may need updating if the device changes its address.'
        self.set_details(text)

    def set_details(self, text):
        self.details.configure(state='normal')
        self.details.delete('1.0', 'end')
        self.details.insert('1.0', text)
        self.details.configure(state='disabled')

    def save_label(self):
        item = self.selected()
        if not item:
            self.status.set('Select a device before saving a label.'); return
        label = self.label.get().strip()
        if len(label) > 80 or any(ord(c) < 32 for c in label):
            self.status.set('Use a label of up to 80 characters without control characters.'); return
        changed = dict(self.labels)
        if label: changed[item['label_key']] = label
        else: changed.pop(item['label_key'], None)
        try:
            STATE.mkdir(mode=0o700, exist_ok=True)
            temp = STATE / 'labels.tmp'
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w') as f: json.dump(changed, f, indent=2)
            temp.replace(STATE / 'labels.json')
        except OSError as exc:
            messagebox.showerror('Label not saved', str(exc)); return
        self.labels = changed
        self.render()
        self.status.set('Label saved locally. Clear the label and save to restore the evidence-based name.')

    def export(self):
        if not self.snapshot: return
        path = filedialog.asksaveasfilename(title='Export private network inventory', defaultextension='.json', initialfile='network-inventory.json', filetypes=[('JSON snapshot', '*.json')])
        if not path: return
        data = dict(self.snapshot)
        data['devices'] = [dict(d, user_label=self.labels.get(d['label_key'], '')) for d in data['devices']]
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w') as f: json.dump(data, f, indent=2)
            self.status.set('Exported locally. The file includes private network addresses and labels.')
        except OSError as exc: messagebox.showerror('Export failed', str(exc))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', action='store_true', help='Print observed inventory as JSON without opening a window')
    args = parser.parse_args()
    if args.snapshot: print(json.dumps(collect(), indent=2))
    else:
        window = tk.Tk()
        Explorer(window)
        window.mainloop()
