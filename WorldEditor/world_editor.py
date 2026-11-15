"""World Editor: desktop window to edit mission islands, the duel arena and players' villages.

Run it with "World Editor.exe" or "Editor de mundo.bat" (this folder) or, from the project:
python WorldEditor/world_editor.py. The logic lives in world_editor_core.py and the game's pictures in sprites.py.

Two views of the map:
  * the game view (default): the game's perspective (tiles in a diamond, 108 x 54 pixels), with the real pictures
    of buildings and units taken from the game's sprites, farther objects drawn first;
  * the plan view: seen from above, one square per tile, coloured blocks of each object's size.
The list of objects shows a preview of the chosen one.

Mouse and keys:
  * choose an object in the list on the right and click the map to place it (a see-through copy follows the
    mouse; it stays chosen to place more; Esc or the right button stops placing);
  * click an object on the map to select it and drag it to move it;
  * R turns it, Supr deletes it, Ctrl+Z undoes, Ctrl+S saves, the wheel scrolls and Ctrl+wheel zooms;
  * V switches between the game view and the plan view.
"""

import hashlib
import tkinter as tk
from tkinter import messagebox, ttk

import world_editor_core as core

try:
    from PIL import Image, ImageTk

    import sprites
except ImportError:  # without Pillow the editor still works, with the plan view only
    sprites = None

PLAN_ZOOMS = (4, 6, 8, 12, 16, 24)  # pixels per tile
GAME_ZOOMS = (0.15, 0.22, 0.3, 0.4, 0.55, 0.75, 1.0)  # scale of the game's pictures
UNIT_COLOUR = '#d64541'
OVERLAP_COLOUR = '#ff2020'
SELECTED_COLOUR = '#ffd700'
GHOST_OK = '#5cff5c'
WATER = '#3a6ea5'
GROUND = '#e8dcb0'
SAND = '#dcc58c'
SAND_LINE = '#cdb579'
GRID = '#d3c592'
GRID_MAJOR = '#b9a96e'
PREVIEW_SIZE = 150
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
        self.minsize(1000, 600)
        self.geometry(f'{min(1360, self.winfo_screenwidth() - 40)}x{min(860, self.winfo_screenheight() - 100)}+10+10')
        try:
            self.state('zoomed')  # Windows: the whole screen, so the panels and the status bar fit
        except tk.TclError:
            pass
        self.doc = None
        self.selected = None
        self.placing = None
        self.dragging = None
        self.view = 'game' if sprites else 'plan'
        self.zooms = {'plan': 2, 'game': 2}
        self.catalog = core.load_catalog()
        self.catalog_rows = []
        self.library = sprites.Library(core.ROOT, core.ROOT / 'WorldEditor' / 'imagenes') if sprites else None
        self.pictures = {}  # (img_name, unit, flipped, scale, ghost) -> (PhotoImage, PIL picture, dx, dy)
        self.hits = {}  # canvas id -> (item index, PIL picture, left, top) for picking by the picture's pixels
        self.preview_photo = None
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
        self.name_entry = ttk.Entry(top, width=22)
        self.name_entry.pack(side='right', padx=2)
        ttk.Label(top, text='Nombre:').pack(side='right')
        ttk.Separator(top, orient='vertical').pack(side='right', fill='y', padx=8)
        self.view_var = tk.StringVar(value=self.view)
        ttk.Radiobutton(top, text='Vista de plano', value='plan', variable=self.view_var,
                        command=self._view_changed).pack(side='right')
        game = ttk.Radiobutton(top, text='Vista del juego', value='game', variable=self.view_var,
                               command=self._view_changed)
        game.pack(side='right')
        if not sprites:
            game.state(['disabled'])

        body = ttk.Panedwindow(self, orient='horizontal')
        body.pack(fill='both', expand=True)

        # left: what to open
        left = ttk.Notebook(body, width=240)
        body.add(left, weight=0)
        islands = ttk.Frame(left, padding=4)
        left.add(islands, text='Islas')
        self.island_list = tk.Listbox(islands, activestyle='none', exportselection=False)
        self.island_list.pack(fill='both', expand=True)
        self.island_list.bind('<Double-Button-1>', lambda e: self.open_island())
        ttk.Button(islands, text='Abrir isla', command=self.open_island).pack(fill='x', pady=(4, 0))
        ttk.Label(islands, text='(nueva) = el juego la conoce pero no tiene mapa',
                  wraplength=220, foreground='#666').pack(fill='x')

        arena = ttk.Frame(left, padding=8)
        left.add(arena, text='Arena')
        ttk.Label(arena, text='El mapa donde se pelean los duelos.\nEl servidor lo lee al prenderse: '
                              'después de guardar, reinicialo.', wraplength=220).pack(fill='x')
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
                                 '(guarda las aldeas en memoria).', wraplength=220, foreground='#a33').pack(fill='x')

        # centre: the map
        centre = ttk.Frame(body)
        body.add(centre, weight=1)
        self.canvas = tk.Canvas(centre, background=WATER, highlightthickness=0)
        xbar = ttk.Scrollbar(centre, orient='horizontal', command=self.canvas.xview)
        ybar = ttk.Scrollbar(centre, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
        ybar.pack(side='right', fill='y')
        xbar.pack(side='bottom', fill='x')
        self.canvas.pack(fill='both', expand=True)

        # right: objects, the preview and the selection
        right = ttk.Frame(body, padding=4, width=290)
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
        self.catalog_list = tk.Listbox(right, activestyle='none', exportselection=False, height=12)
        self.catalog_list.pack(fill='both', expand=True, pady=2)
        self.catalog_list.bind('<<ListboxSelect>>', lambda e: self.choose_object())
        self.catalog_list.bind('<Up>', lambda e: self.after_idle(self.choose_object))
        self.catalog_list.bind('<Down>', lambda e: self.after_idle(self.choose_object))

        frame = tk.Frame(right, height=PREVIEW_SIZE, width=270, background='#f4ecd2', relief='groove', borderwidth=2)
        frame.pack(fill='x', pady=(4, 0))
        frame.pack_propagate(False)  # a fixed box: a picture never pushes the rest of the panel away
        self.preview = tk.Label(frame, background='#f4ecd2', text='Vista previa', foreground='#998')
        self.preview.pack(fill='both', expand=True)
        self.preview_text = ttk.Label(right, text='', wraplength=270, justify='left')
        self.preview_text.pack(fill='x')

        ttk.Separator(right).pack(fill='x', pady=6)
        ttk.Label(right, text='Seleccionado en el mapa', font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        self.info = ttk.Label(right, text='Nada', wraplength=270, justify='left')
        self.info.pack(fill='x')
        buttons = ttk.Frame(right)
        buttons.pack(fill='x', pady=4)
        ttk.Button(buttons, text='Girar (R)', command=self.rotate).pack(side='left', expand=True, fill='x')
        ttk.Button(buttons, text='Borrar (Supr)', command=self.delete).pack(side='left', expand=True, fill='x')
        zoom = ttk.Frame(right)
        zoom.pack(fill='x')
        ttk.Button(zoom, text='Acercar +', command=lambda: self.change_zoom(1)).pack(side='left', expand=True, fill='x')
        ttk.Button(zoom, text='Alejar -', command=lambda: self.change_zoom(-1)).pack(side='left', expand=True, fill='x')
        self.counts = ttk.Label(right, text='', wraplength=270, justify='left')
        self.counts.pack(fill='x', pady=(6, 0))

        self.status = ttk.Label(self, text='', relief='sunken', padding=(6, 2))
        self.status.pack(side='bottom', fill='x')

        c = self.canvas
        c.bind('<Button-1>', self.on_press)
        c.bind('<B1-Motion>', self.on_drag)
        c.bind('<ButtonRelease-1>', self.on_release)
        c.bind('<Button-3>', lambda e: self.stop_placing())
        c.bind('<Motion>', self.on_motion)
        c.bind('<Leave>', lambda e: c.delete('ghost'))
        c.bind('<MouseWheel>', self.on_wheel)
        c.bind('<Shift-MouseWheel>', lambda e: c.xview_scroll(-1 if e.delta > 0 else 1, 'units'))
        c.bind('<Control-MouseWheel>', lambda e: self.change_zoom(1 if e.delta > 0 else -1))
        self.bind('<Control-z>', lambda e: self.undo())
        self.bind('<Control-s>', lambda e: self.save())
        self.bind('<Escape>', lambda e: self.stop_placing())
        self.bind('<Delete>', lambda e: self._map_key(self.delete))
        self.bind('<KeyPress-r>', lambda e: self._map_key(self.rotate))
        self.bind('<KeyPress-v>', lambda e: self._map_key(self.toggle_view))

    def _map_key(self, action):
        if isinstance(self.focus_get(), (ttk.Entry, tk.Entry)):
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

    # ------------------------------------------------------------------ pictures
    def _is_unit(self, item_id):
        return (self.catalog.get(int(item_id)) or {}).get('type') == 'u'

    def _picture(self, item_id, scale, flipped=False, ghost=False):
        """(PhotoImage, PIL picture, dx, dy) of an item in the game view: draw it at anchor + (dx, dy)."""
        entry = self.catalog.get(int(item_id)) or {}
        unit = entry.get('type') == 'u'
        key = (entry.get('img_name'), unit, flipped, scale, ghost)
        if key in self.pictures:
            return self.pictures[key]
        found = self.library.picture(entry.get('img_name'), unit) if self.library else None
        if not found:
            self.pictures[key] = None
            return None
        picture, (origin_x, origin_y) = found
        if flipped:
            picture = picture.transpose(Image.FLIP_LEFT_RIGHT)
            origin_x = picture.width - origin_x
        width, height = max(1, round(picture.width * scale)), max(1, round(picture.height * scale))
        picture = picture.resize((width, height), Image.LANCZOS)
        if ghost:
            alpha = picture.getchannel('A').point(lambda value: value * 6 // 10)
            picture.putalpha(alpha)
        if unit:  # the sprite's own origin is at the unit's feet
            dx, dy = -origin_x * scale, -origin_y * scale
        else:  # Base buildings: the picture stands on the bottom corner of its base, centred
            dx, dy = -width / 2, -height
        result = (ImageTk.PhotoImage(picture), picture, dx, dy)
        self.pictures[key] = result
        return result

    def _anchor(self, item_id, x, y, orientation=0):
        """Screen point (scale 1) the item's picture stands on."""
        if self._is_unit(item_id):
            return core.iso_point(x + 0.5, y + 0.5)
        width, height = core.footprint([item_id, x, y, orientation], self.catalog)
        return core.iso_point(x + width, y + height)

    def _show_preview(self, item_id):
        entry = self.catalog.get(int(item_id)) or {}
        image = None
        if self.library:
            found = self.library.picture(entry.get('img_name'), entry.get('type') == 'u')
            image = found[0] if found else self.library.thumbnail(item_id, entry.get('img_name'))
            self.library.save_index()
        if image is not None:
            image = image.copy()
            image.thumbnail((260, PREVIEW_SIZE - 10), Image.LANCZOS)
            self.preview_photo = ImageTk.PhotoImage(image)
            self.preview.configure(image=self.preview_photo, text='')
        else:
            self.preview_photo = None
            self.preview.configure(image='', text='Sin imagen')
        kind = 'Unidad' if entry.get('type') == 'u' else 'Edificio o decoración'
        self.preview_text['text'] = (f"{entry.get('label', item_id)}  (#{item_id})\n{kind}, "
                                     f"{entry.get('width')}x{entry.get('height')} casillas")

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
        self._show_preview(self.placing)
        entry = self.catalog[self.placing]
        self.status['text'] = f"Colocando {entry['label']}: hacé clic en el mapa. Esc o botón derecho para dejar de colocar."
        self._draw()

    def stop_placing(self):
        self.placing = None
        self.catalog_list.selection_clear(0, 'end')
        self.canvas.delete('ghost')
        self.status['text'] = ''

    def toggle_view(self):
        if sprites:
            self.view_var.set('plan' if self.view == 'game' else 'game')
            self._view_changed()

    def _view_changed(self):
        centre = self._centre_tile()
        self.view = self.view_var.get()
        self._draw()
        self._show_tile(*centre)

    def change_zoom(self, step):
        zooms = GAME_ZOOMS if self.view == 'game' else PLAN_ZOOMS
        index = max(0, min(len(zooms) - 1, self.zooms[self.view] + step))
        if index != self.zooms[self.view]:
            centre = self._centre_tile()
            self.zooms[self.view] = index
            self._draw()
            self._show_tile(*centre)

    # ------------------------------------------------------------------ coordinates
    @property
    def scale(self):
        return GAME_ZOOMS[self.zooms['game']] if self.view == 'game' else PLAN_ZOOMS[self.zooms['plan']]

    def _to_canvas(self, tile_x, tile_y):
        """Canvas point of a (fractional) tile position."""
        if self.view == 'game':
            px, py = core.iso_point(tile_x, tile_y)
            return px * self.scale, py * self.scale
        return tile_x * self.scale, tile_y * self.scale

    def _tile_at(self, canvas_x, canvas_y):
        if self.view == 'game':
            return core.iso_tile(canvas_x / self.scale, canvas_y / self.scale)
        return int(canvas_x // self.scale), int(canvas_y // self.scale)

    def _tile(self, event):
        return self._tile_at(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))

    def _size(self):
        if self.view == 'game':
            return 2 * core.HALF_WIDTH * core.MAP_SIZE * self.scale, 2 * core.HALF_HEIGHT * core.MAP_SIZE * self.scale
        return core.MAP_SIZE * self.scale, core.MAP_SIZE * self.scale

    def _centre_tile(self):
        c = self.canvas
        return self._tile_at(c.canvasx(c.winfo_width() / 2), c.canvasy(c.winfo_height() / 2))

    def _show_tile(self, x, y):
        c = self.canvas
        c.update_idletasks()
        width, height = self._size()
        px, py = self._to_canvas(x + 0.5, y + 0.5)
        c.xview_moveto(max(0.0, (px - c.winfo_width() / 2) / width))
        c.yview_moveto(max(0.0, (py - c.winfo_height() / 2) / height))

    def center_on_items(self):
        if not self.doc or not self.doc.items:
            self._show_tile(50, 50)
            return
        xs = [int(item[1]) for item in self.doc.items]
        ys = [int(item[2]) for item in self.doc.items]
        self._show_tile((min(xs) + max(xs)) // 2, (min(ys) + max(ys)) // 2)

    def _inside(self, x, y):
        return 0 <= x < core.MAP_SIZE and 0 <= y < core.MAP_SIZE

    # ------------------------------------------------------------------ mouse
    def _pick(self, event):
        """Index of the item under the mouse: the topmost picture with a visible pixel there, else the base."""
        c = self.canvas
        cx, cy = c.canvasx(event.x), c.canvasy(event.y)
        if self.view == 'game':
            for canvas_id in reversed(c.find_overlapping(cx, cy, cx, cy)):
                hit = self.hits.get(canvas_id)
                if not hit:
                    continue
                index, picture, left, top = hit
                u, v = int(cx - left), int(cy - top)
                if 0 <= u < picture.width and 0 <= v < picture.height and picture.getpixel((u, v))[3] > 60:
                    return index
        x, y = self._tile_at(cx, cy)
        return core.item_at(self.doc.items, self.catalog, x, y)

    def on_press(self, event):
        if not self.doc:
            return
        self.canvas.focus_set()
        x, y = self._tile(event)
        if self.placing is not None:
            if self._inside(x, y):
                self.selected = self.doc.add(self.placing, x, y)
                self._draw()
            return
        self.selected = self._pick(event)
        if self.selected is not None:
            item = self.doc.items[self.selected]
            self.dragging = (x - int(item[1]), y - int(item[2]), int(item[1]), int(item[2]))
            self._show_preview(item[0])
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
        if not self._inside(x, y):
            self.canvas.delete('ghost')
            return
        if self.placing is not None:
            self._draw_ghost(x, y)
            return
        text = f'Casilla {x}, {y}'
        index = self._pick(event)
        if index is not None:
            item = self.doc.items[index]
            text += f" - {self.catalog.get(int(item[0]), {}).get('label', item[0])} en {item[1]}, {item[2]}"
        self.status['text'] = text

    def on_wheel(self, event):
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')

    # ------------------------------------------------------------------ drawing
    def _base_polygon(self, item):
        if self.view == 'game':
            return [value * self.scale for point in core.iso_footprint(item, self.catalog) for value in point]
        width, height = core.footprint(item, self.catalog)
        x0, y0 = int(item[1]) * self.scale, int(item[2]) * self.scale
        x1, y1 = x0 + width * self.scale, y0 + height * self.scale
        return [x0, y0, x1, y0, x1, y1, x0, y1]

    def _draw_ghost(self, x, y):
        c = self.canvas
        c.delete('ghost')
        probe = [self.placing, x, y, 0, 0]
        others = self.doc.items + [probe]
        clash = (not self._is_unit(self.placing)) and len(others) - 1 in core.overlapping(others, self.catalog)
        c.create_polygon(self._base_polygon(probe), fill='', outline=OVERLAP_COLOUR if clash else GHOST_OK,
                         width=2, tags='ghost')
        if self.view == 'game':
            found = self._picture(self.placing, self.scale, ghost=True)
            if found:
                photo, _, dx, dy = found
                ax, ay = self._anchor(self.placing, x, y)
                c.create_image(ax * self.scale + dx, ay * self.scale + dy, image=photo, anchor='nw', tags='ghost')
        self.status['text'] = f'Casilla {x}, {y}' + ('  -  pisa otro objeto' if clash else '')

    def _draw(self):
        c = self.canvas
        c.delete('all')
        self.hits = {}
        width, height = self._size()
        c.configure(scrollregion=(0, 0, width, height))
        if self.view == 'game':
            self._draw_game_ground()
        else:
            self._draw_plan_ground()
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
        if self.view == 'game':
            self._draw_game_items(items)
        else:
            self._draw_plan_items(items)
        if self.selected is not None and self.selected < len(items):
            colour = OVERLAP_COLOUR if clash else SELECTED_COLOUR
            c.create_polygon(self._base_polygon(items[self.selected]), fill='', outline=colour, width=3)
        if self.library:
            self.library.save_index()
        self.title_label['text'] = f"{KIND_NAMES[self.doc.kind]}: {self.doc.title}{'  *' if self.doc.dirty else ''}"
        units = sum(1 for item in items if self._is_unit(item[0]))
        self.counts['text'] = (f'{len(items) - units} edificios y decoración, {units} unidades.'
                               + ('\nEl seleccionado pisa otro objeto (borde rojo).' if clash else ''))
        if self.selected is not None and self.selected < len(items):
            item = items[self.selected]
            entry = self.catalog.get(int(item[0])) or {}
            w, h = core.footprint(item, self.catalog)
            self.info['text'] = (f"{entry.get('label', item[0])} (#{item[0]})\n"
                                 f"Casilla {item[1]}, {item[2]}  -  tamaño {w}x{h}"
                                 f"{'  -  girado' if int(item[3]) % 2 else ''}")
        else:
            self.info['text'] = 'Nada (hacé clic en un objeto del mapa)'

    def _draw_plan_ground(self):
        c, z = self.canvas, self.scale
        size = core.MAP_SIZE * z
        c.create_rectangle(0, 0, size, size, fill=GROUND, outline='')
        if z >= 8:
            for i in range(core.MAP_SIZE + 1):
                c.create_line(i * z, 0, i * z, size, fill=GRID)
                c.create_line(0, i * z, size, i * z, fill=GRID)
        for i in range(0, core.MAP_SIZE + 1, 10):
            c.create_line(i * z, 0, i * z, size, fill=GRID_MAJOR)
            c.create_line(0, i * z, size, i * z, fill=GRID_MAJOR)

    def _draw_game_ground(self):
        c = self.canvas
        x0, y0, x1, y1 = core.island_area(self.doc.items if self.doc else [], self.catalog)
        corners = [self._to_canvas(*point) for point in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        c.create_polygon([value for point in corners for value in point], fill=SAND, outline='#c9b06f', width=2)
        if self.scale >= 0.3:  # the tiles, so it is clear where an object will land
            for x in range(x0, x1 + 1):
                c.create_line(*self._to_canvas(x, y0), *self._to_canvas(x, y1), fill=SAND_LINE)
            for y in range(y0, y1 + 1):
                c.create_line(*self._to_canvas(x0, y), *self._to_canvas(x1, y), fill=SAND_LINE)

    def _draw_game_items(self, items):
        c, scale = self.canvas, self.scale
        for index in core.depth_order(items, self.catalog):
            item = items[index]
            flipped = int(item[3]) % 2 == 1
            found = self._picture(item[0], scale, flipped)
            if found is None:  # no picture: its base in colour
                entry = self.catalog.get(int(item[0])) or {}
                c.create_polygon(self._base_polygon(item), fill=UNIT_COLOUR if self._is_unit(item[0])
                                 else colour_of(entry), outline='#333')
                continue
            photo, picture, dx, dy = found
            ax, ay = self._anchor(item[0], int(item[1]), int(item[2]), int(item[3]))
            left, top = ax * scale + dx, ay * scale + dy
            canvas_id = c.create_image(left, top, image=photo, anchor='nw')
            self.hits[canvas_id] = (index, picture, left, top)

    def _draw_plan_items(self, items):
        c, z = self.canvas, self.scale

        def layer(i):  # units on top; big blocks (forests) under the small ones
            w, h = core.footprint(items[i], self.catalog)
            return self._is_unit(items[i][0]), -w * h, i

        for index in sorted(range(len(items)), key=layer):
            item = items[index]
            entry = self.catalog.get(int(item[0])) or {'label': f'#{item[0]}'}
            w, h = core.footprint(item, self.catalog)
            x0, y0 = int(item[1]) * z, int(item[2]) * z
            x1, y1 = x0 + w * z, y0 + h * z
            if entry.get('type') == 'u':
                pad = max(1, z // 6)
                c.create_oval(x0 + pad, y0 + pad, x1 - pad, y1 - pad, fill=UNIT_COLOUR, outline='#333')
            else:
                c.create_rectangle(x0, y0, x1, y1, fill=colour_of(entry), outline='#333')
            if z >= 12 and w * z >= 40:
                c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=entry['label'], width=w * z - 4,
                              font=('Segoe UI', 7))

    def close(self):
        if self.confirm_discard():
            self.destroy()


def main():
    try:
        app = Editor()
    except Exception as error:  # the .exe has no console: say what went wrong in a window
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror('World Editor', f'No se pudo abrir el editor:\n\n{error}')
        root.destroy()
        return
    app.mainloop()


if __name__ == '__main__':
    main()
