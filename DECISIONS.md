# Decisiones y cambios de comportamiento (duelos en vivo)

Registro de cada decisión tomada en la rama `duelos-en-vivo` y de todo cambio de comportamiento respecto de `mi-servidor`.

## Fase 0 (investigación)

- Sin cambios de comportamiento: solo se agregaron `DUELOS_PLAN.md` y este archivo.
- Constatado: `tournaments.py`, `gunicorn.conf.py` y `trust.py` no existen; el servidor corre con `app.run(threaded=False)` (un pedido por vez), no con gunicorn.
- Constatado: el mapa de arena de torneos (`map_id` 100000040) no está en el repositorio ni en el original.
