# Decisiones y cambios de comportamiento (duelos en vivo)

Registro de cada decisión tomada en la rama `duelos-en-vivo` y de todo cambio de comportamiento respecto de `mi-servidor`.

## Fase 0 (investigación)

- Sin cambios de comportamiento: solo se agregaron `DUELOS_PLAN.md` y este archivo.
- Constatado: `tournaments.py`, `gunicorn.conf.py` y `trust.py` no existen; el servidor corre con `app.run(threaded=False)` (un pedido por vez), no con gunicorn.
- Constatado: el mapa de arena de torneos (`map_id` 100000040) no está en el repositorio ni en el original.

## Fase 1 (retos en vivo, resueltos por fuerza)

Cambios de comportamiento (solo con `SE_DUELS=on`; apagado, nada cambia):
- **Hilos:** `app.run(threaded=True)`, necesario para mantener WebSockets abiertos. Las aldeas siguen en memoria y toda mutación toma `village_lock` (RLock), como antes. Apagado sigue `threaded=False`. Probado con 10 duelos simultáneos más navegación concurrente (`tests/duels_live_checks.py`).
- **Rutas nuevas:** `/duels` (página) y `/duels/ws` (WebSocket); enlace "Duelos" en el menú del portal y del juego; aviso de reto en todas las páginas.
- **Base nueva:** `instance/duels.sqlite3` (duelos y puntos). Las partidas no se modifican.
- **Paquetes nuevos** (aprobados): `flask-sock==0.7.0`, `simple-websocket==1.1.0`, `wsproto==1.3.2`, `h11==0.16.0`.

Decisiones:
- **Conectado** = tener una página del portal o del juego abierta (un WebSocket por página).
- **Seguridad del WebSocket:** antes del handshake se exige sesión de una cuenta aprobada cuya aldea coincide con la sesión, y que `Origin` sea este mismo sitio; si no, 403 sin abrir el socket. Mensajes de 4 KB como máximo; latido cada 25 s.
- **Reglas:** nadie se reta a sí mismo; un jugador envía o recibe un solo reto a la vez; el reto vence a los 30 s; máximo 5 retos enviados por minuto por jugador; hace falta tutorial terminado y al menos una tropa de combate (como en Rivales).
- **Recarga de pestaña:** si un participante se queda sin páginas abiertas, el reto espera 5 s antes de cancelarse; al volver, la página recibe el reto pendiente con el tiempo que le queda.
- **Resultado por fuerza:** suma de `balance.pvp_unit_power` de las **30 tropas de combate más fuertes** de la aldea principal (sueltas o refugiadas). El 30 viene del modo supervivencia del juego ("tus 30 unidades más poderosas"). Gana la mayor; igual fuerza = **empate**.
- **Ranked:** Elo, inicio 1000, K = 32 (ganar contra alguien con más puntos da más). Solo si **las dos** aldeas principales tienen nivel 25 o más; si no, el duelo queda guardado como **amistoso** sin cambiar puntos.
- Los dos jugadores reciben **el mismo mensaje de resultado** en el mismo momento; los mensajes llevan códigos y números, y cada página los muestra en su idioma.
- Duelo aceptado de alguien que se quedó sin tropas en el medio: se cancela.
