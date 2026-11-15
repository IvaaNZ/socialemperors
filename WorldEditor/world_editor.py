"""World Editor: desktop window to edit mission islands, the duel arena and players' villages.

Run it with "Editor de mundo.bat" (this folder) or, from the project:  python WorldEditor/world_editor.py
Only Python's own tkinter is used. The map is drawn seen from above (the game shows it in perspective): one square
per tile, buildings as coloured blocks of their size, units as circles. The logic lives in world_editor_core.py.

Mouse and keys:
  * choose an object in the list on the right and click the map to place it (it stays chosen to place more;
    Esc or the right button stops placing);
  * click an object on the map to select it and drag it to move it;
  * R turns it, Supr deletes it, Ctrl+Z undoes, Ctrl+S saves, the wheel scrolls and Ctrl+wheel zooms.
"""

import hashlib
import tkinter as tk
from tkinter import messagebox, ttk

import world_editor_core as core

ZOOMS = (4, 6, 8, 12, 16, 24)
UNIT_COLOUR = '#d64541'
OVERLAP_COLOUR = '#ff2020'
SELECTED_COLOUR = '#ffd700'
GROUND = '#e8dcb0'
GRID = '#d3c592'
GRID_MAJOR = '#b9a96e'
KIND_NAMES = {'island': 'Isla de misión', 'arena': 'Arena de duelos', 'village': 'Aldea'}


def colour_of(entry):
    """A stable colour per building category, so walls, houses and decorations are told apart."""
    key = f"{entry.get('category_id')}-{entry.get('subcategory_id')}".encode()
    digest = hashlib.md5(key).digest()
    red, green, blue = (90 + digest[0] % 120, 90 + digest[1] % 120, 90 + digest[2] % 120)
    return f'#{red:02x}{green:02x}{blue:02x}'


class Editor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Editor de mundo - Social Empires')
        self.geometry('1280x820')
        self.minsize(960, 600)
        self.doc = None
        self.selected = None
        self.placing = None
        self.dragging = None
        self.zoom = ZOOMS[2]
        self.catalog = core.load_catalog()
        self.catalog_rows = []
        self._build()
        self._fill_islands()
        self._fill_villages()
        self._fill_catalog()
        self.protocol('WM_DELETE_WINDOW', self.close)
        self._draw()

    # ------------------------------------------------------------------ layout
    def _build(self):
        top = ttk.Frame(self, padding=(8, 6))
        top.pack(side='top', fill='x')
        self.title_label = ttk.Label(top, text='Elegí qué editar a la izquierda', font=('Segoe UI', 12, 'bold'))
        self.title_label.pack(side='left')
        ttk.Button(top, text='Guardar (Ctrl+S)', command=self.save).pack(side='right', padx=2)
        ttk.Button(top, text='Deshacer (Ctrl+Z)', command=self.undo).pack(side='right', padx=2)
        ttk.Button(top, text='Cambiar nombre', command=self.rename).pack(side='right', padx=2)
        self.name_entry = ttk.Entry(top, width=24)
        self.name_entry.pack(side='right', padx=2)
        ttk.Label(top, text='Nombre:').pack(side='right')

        body = ttk.Panedwindow(self, orient='horizontal')
        body.pack(fill='both', expand=True)

        # left: what to open
        left = ttk.Notebook(body, width=250)
        body.add(left, weight=0)
        islands = ttk.Frame(left, padding=4)
        left.add(islands, text='Islas')
        self.island_list = tk.Listbox(islands, activestyle='none', exportselection=False)
        self.island_list.pack(fill='both', expand=True)
        self.island_list.bind('<Double-Button-1>', lambda e: self.open_island())
        ttk.Button(islands, text='Abrir isla', command=self.open_island).pack(fill='x', pady=(4, 0))
        ttk.Label(islands, text='(nueva) = el juego la conoce pero no tiene mapa',
                  wraplength=230, foreground='#666').pack(fill='x')

        arena = ttk.Frame(left, padding=8)
        left.add(arena, text='Arena')
        ttk.Label(arena, text='El mapa donde se pelean los duelos.\nEl servidor lo lee al prenderse: '
                              'después de guardar, reinicialo.', wraplength=230).pack(fill='x')
        ttk.Button(arena, text='Abrir arena de duelos', command=self.open_arena).pack(fill='x', pady=8)

        villages = ttk.Frame(left, padding=4)
        left.add(villages, text='Aldeas')
        self.village_list = tk.Listbox(villages, activestyle='none', exportselection=False)
        self.village_list.pack(fill='both', expand=True)
        self.village_list.bind('<Double-Button-1>', lambda e: self.open_village())
        ttk.Button(villages, text='Abrir aldea', command=self.open_village).pack(fill='x', pady=(4, 0))
        ttk.Label(villages, text='Isla de la aldea:').pack(anchor='w', pady=(6, 0))
        self.map_choice = ttk.Combobox(villages, state='readonly')
        self.map_choice.pack(fill='x')
        self.map_choice.bind('<<ComboboxSelected>>', lambda e: self.choose_map())
        ttk.Label(villages, text='Para guardar una aldea, el servidor tiene que estar apagado '
                                 '(guarda las aldeas en memoria).', wraplength=230, foreground='#a33').pack(fill='x')

        # centre: the map
        centre = ttk.Frame(body)
        body.add(centre, weight=1)
        self.canvas = tk.Canvas(centre, background='#3a6ea5', highlightthickness=0)
        xbar = ttk.Scrollbar(centre, orient='horizontal', command=self.canvas.xview)
        ybar = ttk.Scrollbar(centre, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
        ybar.pack(side='right', fill='y')
        xbar.pack(side='bottom', fill='x')
        self.canvas.pack(fill='both', expand=True)

        # right: objects and the selection
        right = ttk.Frame(body, padding=4, width=280)
        body.add(right, weight=0)
        ttk.Label(right, text='Objetos para colocar', font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        self.search = tk.StringVar()
        self.search.trace_add('write', lambda *a: self._fill_catalog())
        ttk.Entry(right, textvariable=self.search).pack(fill='x', pady=2)
        kinds = ttk.Frame(right)
        kinds.pack(fill='x')
        self.kind = tk.StringVar(value='')
        for text, value in (('Todos', ''), ('Edificios', 'b'), ('Unidades', 'u')):
            ttk.Radiobutton(kinds, text=text, value=value, variable=self.kind,
                            command=self._fill_catalog).pack(side='left')
        self.catalog_list = tk.Listbox(right, activestyle='none', exportselection=False, height=18)
        self.catalog_list.pack(fill='both', expand=True, pady=2)
        self.catalog_list.bind('<<ListboxSelect>>', lambda e: self.choose_object())

        ttk.Separator(right).pack(fill='x', pady=6)
        ttk.Label(right, text='Seleccionado', font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        self.info = ttk.Label(right, text='Nada', wraplength=260, justify='left')
        self.info.pack(fill='x')
        buttons = ttk.Frame(right)
        buttons.pack(fill='x', pady=4)
        ttk.Button(buttons, text='Girar (R)', command=self.rotate).pack(side='left', expand=True, fill='x')
        ttk.Button(buttons, text='Borrar (Supr)', command=self.delete).pack(side='left', expand=True, fill='x')
        zoom = ttk.Frame(right)
        zoom.pack(fill='x')
        ttk.Button(zoom, text='Acercar +', command=lambda: self.change_zoom(1)).pack(side='left', expand=True, fill='x')
        ttk.Button(zoom, text='Alejar -', command=lambda: self.change_zoom(-1)).pack(side='left', expand=True, fill='x')
        self.counts = ttk.Label(right, text='', wraplength=260, justify='left')
        self.counts.pack(fill='x', pady=(6, 0))

        self.status = ttk.Label(self, text='', relief='sunken', padding=(6, 2))
        self.status.pack(side='bottom', fill='x')

        c = self.canvas
        c.bind('<Button-1>', self.on_press)
        c.bind('<B1-Motion>', self.on_drag)
        c.bind('<ButtonRelease-1>', self.on_release)
        c.bind('<Button-3>', lambda e: self.stop_placing())
        c.bind('<Motion>', self.on_motion)
        c.bind('<MouseWheel>', self.on_wheel)
        c.bind('<Shift-MouseWheel>', lambda e: c.xview_scroll(-1 if e.delta > 0 else 1, 'units'))
        c.bind('<Control-MouseWheel>', lambda e: self.change_zoom(1 if e.delta > 0 else -1))
        self.bind('<Control-z>', lambda e: self.undo())
        self.bind('<Control-s>', lambda e: self.save())
        self.bind('<Escape>', lambda e: self.stop_placing())
        self.bind('<Delete>', lambda e: self._map_key(self.delete))
        self.bind('<KeyPress-r>', lambda e: self._map_key(self.rotate))

    def _map_key(self, action):
        if self.focus_get() in (self.name_entry,) or isinstance(self.focus_get(), (ttk.Entry, tk.Entry)):
            return  # typing a name or a search
        action()

    # ------------------------------------------------------------------ lists
    def _fill_islands(self):
        self.island_ids = []
        self.island_list.delete(0, 'end')
        for quest_id, name, has_map in core.quest_islands():
            self.island_ids.append(quest_id)
            self.island_list.insert('end', f"{name}{'' if has_map else '  (nueva)'}")
            if not has_map:
                self.island_list.itemconfigure('end', foreground='#888')

    def _fill_villages(self):
        self.village_paths = []
        self.village_list.delete(0, 'end')
        for path, name, level in core.player_villages():
            self.village_paths.append(path)
            self.village_list.insert('end', f'{name or path.stem}  (nivel {level})')

    def _fill_catalog(self):
        text = self.search.get().strip().lower()
        kind = self.kind.get()
        self.catalog_rows = []
        self.catalog_list.delete(0, 'end')
        for item_id, entry in sorted(self.catalog.items(), key=lambda pair: str(pair[1]['label']).lower()):
            if kind and entry.get('type') != kind:
                continue
            label = str(entry['label'])
            if text and text not in label.lower() and text not in str(entry.get('name', '')).lower() \
                    and text != str(item_id):
                continue
            self.catalog_rows.append(item_id)
            self.catalog_list.insert('end', f"{label}  [{entry.get('width')}x{entry.get('height')}]  #{item_id}")

    # ------------------------------------------------------------------ opening
    def _replace_document(self, opener):
        if not self.confirm_discard():
            return
        try:
            doc = opener()
        except (core.EditorError, OSError, ValueError, KeyError) as error:
            messagebox.showerror('No se pudo abrir', str(error))
            return
        self.doc, self.selected, self.placing = doc, None, None
        self.name_entry.delete(0, 'end')
        self.name_entry.insert(0, doc.title)
        if doc.kind == 'village':
            names = doc.data['playerInfo'].get('map_names') or []
            self.map_choice['values'] = [f"{i}: {names[i] if i < len(names) else 'Isla'}" for i in range(len(doc.maps))]
            self.map_choice.current(doc.map_index)
        else:
            self.map_choice['values'] = []
            self.map_choice.set('')
        self._draw()
        self.center_on_items()

    def open_island(self):
        selection = self.island_list.curselection()
        if selection:
            self._replace_document(lambda: core.Document.open_island(self.island_ids[selection[0]]))

    def open_arena(self):
        self._replace_document(core.Document.open_arena)

    def open_village(self):
        selection = self.village_list.curselection()
        if selection:
            self._replace_document(lambda: core.Document.open_village(self.village_paths[selection[0]]))

    def choose_map(self):
        if self.doc and self.doc.kind == 'village':
            self.doc.select_map(self.map_choice.current())
            self.selected = None
            self._draw()
            self.center_on_items()

    def confirm_discard(self):
        if not self.doc or not self.doc.dirty:
            return True
        answer = messagebox.askyesnocancel('Cambios sin guardar',
                                           f'"{self.doc.title}" tiene cambios sin guardar. ¿Guardarlos?')
        if answer is None:
            return False
        return self.save() if answer else True

    # ------------------------------------------------------------------ actions
    def save(self):
        if not self.doc:
            return False
        try:
            path = self.doc.save()
        except (core.EditorError, OSError) as error:
            messagebox.showerror('No se guardó', str(error))
            return False
        note = {'island': 'El juego la usa en la próxima batalla de esa isla.',
                'arena': 'Reiniciá el servidor para que los duelos usen la arena nueva.',
                'village': 'El jugador la ve la próxima vez que prenda el servidor.'}[self.doc.kind]
        self._fill_islands()
        self._draw()
        self.status['text'] = f'Guardado en {path}. {note}'
        return True

    def undo(self):
        if self.doc and self.doc.undo():
            self.selected = None
            self._draw()

    def rename(self):
        if not self.doc:
            return
        try:
            self.doc.set_name(self.name_entry.get())
        except core.EditorError as error:
            messagebox.showerror('Nombre', str(error))
        self._draw()

    def rotate(self):
        if self.doc and self.selected is not None:
            self.doc.rotate(self.selected)
            self._draw()

    def delete(self):
        if self.doc and self.selected is not None:
            self.doc.delete(self.selected)
            self.selected = None
            self._draw()

    def choose_object(self):
        selection = self.catalog_list.curselection()
        if not selection:
            return
        self.placing = self.catalog_rows[selection[0]]
        self.selected = None
        entry = self.catalog[self.placing]
        self.status['text'] = f"Colocando {entry['label']}: hacé clic en el mapa. Esc o botón derecho para dejar de colocar."
        self._draw()

    def stop_placing(self):
        self.placing = None
        self.catalog_list.selection_clear(0, 'end')
        self.canvas.delete('ghost')
        self.status['text'] = ''

    def change_zoom(self, step):
        index = max(0, min(len(ZOOMS) - 1, ZOOMS.index(self.zoom) + step))
        if ZOOMS[index] != self.zoom:
            centre = self._view_centre()
            self.zoom = ZOOMS[index]
            self._draw()
            self._scroll_to(*centre)

    # ------------------------------------------------------------------ mouse
    def _tile(self, event):
        z = self.zoom
        return int(self.canvas.canvasx(event.x) // z), int(self.canvas.canvasy(event.y) // z)

    def on_press(self, event):
        if not self.doc:
            return
        self.canvas.focus_set()
        x, y = self._tile(event)
        if not (0 <= x < core.MAP_SIZE and 0 <= y < core.MAP_SIZE):
            return
        if self.placing is not None:
            self.selected = self.doc.add(self.placing, x, y)
            self._draw()
            return
        self.selected = core.item_at(self.doc.items, self.catalog, x, y)
        if self.selected is not None:
            item = self.doc.items[self.selected]
            self.dragging = (x - int(item[1]), y - int(item[2]), int(item[1]), int(item[2]))
        self._draw()

    def on_drag(self, event):
        if self.dragging is None or self.selected is None:
            return
        x, y = self._tile(event)
        dx, dy, _, _ = self.dragging
        item = self.doc.items[self.selected]
        nx, ny = core.clamp_tile(x - dx), core.clamp_tile(y - dy)
        if (nx, ny) != (int(item[1]), int(item[2])):
            item[1], item[2] = nx, ny  # shown while dragging; recorded for undo when released
            self._draw()

    def on_release(self, event):
        if self.dragging is None or self.selected is None:
            self.dragging = None
            return
        _, _, start_x, start_y = self.dragging
        self.dragging = None
        item = self.doc.items[self.selected]
        end = int(item[1]), int(item[2])
        if end != (start_x, start_y):
            item[1], item[2] = start_x, start_y
            self.doc.move(self.selected, *end)
            self._draw()

    def on_motion(self, event):
        if not self.doc:
            return
        x, y = self._tile(event)
        if not (0 <= x < core.MAP_SIZE and 0 <= y < core.MAP_SIZE):
            return
        text = f'Casilla {x}, {y}'
        index = core.item_at(self.doc.items, self.catalog, x, y)
        if index is not None:
            item = self.doc.items[index]
            text += f" - {self.catalog.get(int(item[0]), {}).get('label', item[0])} en {item[1]}, {item[2]}"
        if self.placing is None:
            self.status['text'] = text
        else:
            self._draw_ghost(x, y)

    def on_wheel(self, event):
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')

    # ------------------------------------------------------------------ drawing
    def _view_centre(self):
        c = self.canvas
        size = core.MAP_SIZE * self.zoom
        return ((c.canvasx(c.winfo_width() / 2)) / size, (c.canvasy(c.winfo_height() / 2)) / size)

    def _scroll_to(self, fx, fy):
        c = self.canvas
        size = core.MAP_SIZE * self.zoom
        c.update_idletasks()
        c.xview_moveto(max(0.0, fx - c.winfo_width() / 2 / size))
        c.yview_moveto(max(0.0, fy - c.winfo_height() / 2 / size))

    def center_on_items(self):
        if not self.doc or not self.doc.items:
            self._scroll_to(0.5, 0.5)
            return
        xs = [int(item[1]) for item in self.doc.items]
        ys = [int(item[2]) for item in self.doc.items]
        self._scroll_to((min(xs) + max(xs)) / 2 / core.MAP_SIZE, (min(ys) + max(ys)) / 2 / core.MAP_SIZE)

    def _draw_ghost(self, x, y):
        self.canvas.delete('ghost')
        entry = self.catalog[self.placing]
        z = self.zoom
        width, height = int(entry.get('width') or 1), int(entry.get('height') or 1)
        self.canvas.create_rectangle(x * z, y * z, (x + width) * z, (y + height) * z, outline='white',
                                     dash=(3, 2), width=2, tags='ghost')

    def _draw(self):
        c, z = self.canvas, self.zoom
        size = core.MAP_SIZE * z
        c.delete('all')
        c.configure(scrollregion=(0, 0, size, size))
        c.create_rectangle(0, 0, size, size, fill=GROUND, outline='')
        if z >= 8:
            for i in range(core.MAP_SIZE + 1):
                c.create_line(i * z, 0, i * z, size, fill=GRID)
                c.create_line(0, i * z, size, i * z, fill=GRID)
        for i in range(0, core.MAP_SIZE + 1, 10):
            c.create_line(i * z, 0, i * z, size, fill=GRID_MAJOR)
            c.create_line(0, i * z, size, i * z, fill=GRID_MAJOR)
        if not self.doc:
            self.title_label['text'] = 'Elegí qué editar a la izquierda'
            self.info['text'] = 'Nada'
            self.counts['text'] = ''
            return
        items = self.doc.items
        # The original islands put palms, skulls and walls on top of each other on purpose: only the selected
        # object is checked, so placing something shows when it lands on another.
        clash = set()
        if self.selected is not None and self.selected < len(items):
            clash = {i for i in core.overlapping(items, self.catalog) if i == self.selected}

        def layer(i):  # units on top; big blocks (forests) under the small ones
            width, height = core.footprint(items[i], self.catalog)
            return self.catalog.get(int(items[i][0]), {}).get('type') == 'u', -width * height, i

        order = sorted(range(len(items)), key=layer)
        for index in order:
            item = items[index]
            entry = self.catalog.get(int(item[0])) or {'label': f'#{item[0]}'}
            width, height = core.footprint(item, self.catalog)
            x0, y0 = int(item[1]) * z, int(item[2]) * z
            x1, y1 = x0 + width * z, y0 + height * z
            outline = SELECTED_COLOUR if index == self.selected else (OVERLAP_COLOUR if index in clash else '#333')
            line = 3 if index == self.selected or index in clash else 1
            if entry.get('type') == 'u':
                pad = max(1, z // 6)
                c.create_oval(x0 + pad, y0 + pad, x1 - pad, y1 - pad, fill=UNIT_COLOUR, outline=outline, width=line)
            else:
                c.create_rectangle(x0, y0, x1, y1, fill=colour_of(entry), outline=outline, width=line)
            if z >= 12 and width * z >= 40:
                c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=entry['label'], width=width * z - 4,
                              font=('Segoe UI', 7))
        self.title_label['text'] = f"{KIND_NAMES[self.doc.kind]}: {self.doc.title}{'  *' if self.doc.dirty else ''}"
        units = sum(1 for item in items if self.catalog.get(int(item[0]), {}).get('type') == 'u')
        self.counts['text'] = (f'{len(items) - units} edificios y decoración, {units} unidades.'
                               + ('\nEl seleccionado pisa otro objeto (borde rojo).' if clash else ''))
        if self.selected is not None and self.selected < len(items):
            item = items[self.selected]
            entry = self.catalog.get(int(item[0])) or {}
            width, height = core.footprint(item, self.catalog)
            self.info['text'] = (f"{entry.get('label', item[0])} (#{item[0]})\n"
                                 f"Casilla {item[1]}, {item[2]}  -  tamaño {width}x{height}"
                                 f"{'  -  girado' if int(item[3]) % 2 else ''}")
        else:
            self.info['text'] = 'Nada (hacé clic en un objeto del mapa)'

    def close(self):
        if self.confirm_discard():
            self.destroy()


if __name__ == '__main__':
    Editor().mainloop()
