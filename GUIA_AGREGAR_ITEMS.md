# Guía: agregar edificios y unidades nuevas

Edificios y unidades son entradas de la lista `items` del config del juego. El servidor carga `config/game_config_20120826.json` y, al arrancar, le aplica parches con [JSON Patch](https://datatracker.ietf.org/doc/html/rfc6902) (`get_game_config.py`). **No edites el JSON base**: agregá un parche.

## 1. Dónde poner el parche

Hay dos lugares posibles; los dos usan el mismo formato:

| Lugar | Cuándo se aplica | Uso recomendado |
| --- | --- | --- |
| `config/patch/*.json` | Siempre, todos los `.json` de la carpeta (el orden depende del sistema de archivos). | Correcciones permanentes del proyecto. |
| `mods/<nombre>.json` | Solo si `<nombre>` figura en `mods/mods.txt`, sin `.json`; se aplica en el orden de esa lista y después de los parches. | Contenido nuevo y opcional. **Recomendado.** |

Las líneas de `mods/mods.txt` que empiezan con `#` se ignoran. Por ejemplo, `mod_venzkaizer` está desactivado.

Si dos entradas tienen el mismo `id`, `remove_duplicate_items()` elimina la anterior y **conserva la que se aplicó última**. Así, un mod puede reemplazar un ítem existente volviendo a agregarlo con su mismo `id`.

## 2. Estructura mínima del parche

```json
[
  {
    "op": "add",
    "path": "/items/-",
    "value": { "id": "60001", "name": "Iron Tower", "type": "b", "...": "..." }
  }
]
```

La forma más segura es **copiar un ítem existente parecido** y cambiar solo lo necesario. Por ejemplo:

```sh
python -c "import json;c=json.load(open('config/game_config_20120826.json',encoding='utf-8'));print(json.dumps(next(i for i in c['items'] if i['name']=='Castle I'),indent=2))"
```

**Todos los valores son strings**, incluidos los números (`"cost": "1000"`). Mantené todas las claves del ítem copiado: el cliente SWF espera el set completo.

## 3. Campos principales

| Campo | Significado / valores observados |
| --- | --- |
| `id` | Único. El mayor existente es `50031`; usá un rango propio, por ejemplo `60000+`. |
| `name` | Nombre **en inglés**. Funciona como clave de traducción (paso 5). |
| `type` | `b` = edificio, `u` = unidad. |
| `race` | `h`, `e`, `a`, `t` (razas jugables) o `n` (neutral/animales). |
| `category_id` / `subcategory_id` | Pestaña de la tienda. `1` Aldea (11–14), `2` Defensa (21 torres, 22 muros, 23 castillos, 24 refugios), `3` Ejército (31 infantería, 32 arqueros…). Revisá `categories` en el config. |
| `subcat_functional` | Usalo **único**: el servidor arma un índice por este campo y un valor repetido pisa al otro. |
| `in_store`, `store_level`, `min_level`, `display_order` | Visibilidad en la tienda, nivel requerido y orden. |
| `cost`, `cost_type` | Precio y moneda: `g` oro, `w` madera, `f` comida, `s` piedra, `c` dinero. |
| `xp`, `collect`, `collect_type`, `collect_xp`, `activation` | XP de compra y producción; `activation` = segundos de construcción o producción. |
| `width`, `height`, `elevation` | Tamaño en celdas del mapa. |
| `attack`, `defense`, `life`, `velocity`, `attack_range`, `attack_interval`, `flying` | Estadísticas que usan las batallas del SWF. |
| `trains` | En edificios, el `id` de la unidad que entrena (Town Hall → `500`, Church → `502`). |
| `unit_capacity`, `units_limit`, `population` | Capacidad de refugio y límites. |
| `groups` | Etiquetas como `worker`, `healer`, `dragon`. |
| `img_name` | Nombre base de los gráficos (paso 4). |

## 4. Gráficos

`img_name: "X"` hace que el cliente busque estos archivos:

- `assets/buildingsprites/X.swf`: sprite animado del mapa (`max_frame` = cantidad de frames).
- `assets/buildingthumbs/X.jpg`: miniatura de la tienda (90 × 90).

**Reutilizar un `img_name` existente** es lo más simple: el ítem funciona sin crear arte. Un sprite nuevo exige un SWF con la misma estructura de símbolos y frames que los originales. No hay pipeline para generarlos en el repo, así que conviene partir de uno existente con una herramienta de edición de SWF y probarlo en Ruffle.

## 5. Traducción (obligatoria para que pasen los tests)

Agregá el nombre original y su traducción en `config/locales/pt-BR-items.json`:

```json
"Iron Tower": "Torre de Ferro"
```

Sin esa entrada, el juego muestra el texto en inglés, pero `tests/test_localization.py` falla: el test exige que todo `name`, `achievement_desc` y demás campos visibles estén en el catálogo. El idioma es global (pt-BR para todos).

## 6. Cómo cuenta en Rivais (PvP del servidor)

`pvp.py` solo usa los stats del config:

- Una **unidad** suma `10 × attack + 5 × defense + life` al ataque y a la defensa de la vila si es `type: u`, tiene la `race` de la vila y `attack > 0` y `life > 0`, y no tiene `worker` ni `healer` en `groups`. También cuenta cuando está refugiada en un edificio propio.
- Un **edificio** suma la misma fórmula a la defensa si es `type: b`, tiene la `race` de la vila y `category_id: "2"`.

Valores altos de stats en un ítem nuevo cambian directamente el equilibrio de los saqueos.

## 7. Unidades en lote (dragones, etc.)

`tools/make_se_unit_patch.py` genera `config/patch/unit_patch.json` a partir de `tools/se_unit_patch.csv` y las plantillas de `tools/unit_templates.json`. Para muchas unidades similares, agregá filas al CSV y regenerá el parche desde `tools/`:

```sh
cd tools && ../.venv/Scripts/python make_se_unit_patch.py
```

Revisá el diff resultante antes de commitear.

## 8. Probar

1. Reiniciá el servidor: el config se carga y se cachea al iniciar.
2. Recargá la pestaña con **Ctrl+F5**.
3. Corré los tests:
   ```sh
   .venv\Scripts\python -m unittest discover -s tests -v
   ```
4. En la consola del servidor debería aparecer `* Mod applied: <nombre>` o `* Patch applied: <nombre>`.

## Errores comunes

- Un `id` o un `subcat_functional` repetido pisa ítems existentes sin aviso.
- Números como enteros JSON en vez de strings.
- Un `img_name` sin `.swf`/`.jpg` en `assets/`: el ítem aparece sin gráfico y en la consola del navegador hay un 404.
- No reiniciar el servidor después de editar el parche.
- Olvidar la traducción, lo que rompe `test_localization`.
