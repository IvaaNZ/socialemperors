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

## Fase 2 (batalla en la arena, opción B)

Cambios de comportamiento (solo con `SE_DUELS=on`; apagado, nada cambia: ni la película del juego, ni las rutas, ni los comandos):
- **Aceptar un reto ya no resuelve por fuerza:** los dos jugadores entran a la arena de torneo del juego. Cada uno comanda su ejército contra el ejército del otro, manejado por la IA del juego (`TournamentIA`). Desde el portal, la página lleva sola al juego.
- **Película del juego:** `swf_duel_bridge.py` agrega `Base.__startDuel` (abre la arena con los datos del duelo), `Base.__registerDuel` (registra la orden `startDuel` para la página, con su propio try/catch) y hace que el puntaje del torneo sea el **porcentaje del ejército rival destruido**. No cambia ninguna instrucción original; solo agrega código al principio de `Base.init`, `TournamentIA.end` y `TournamentManager.end`. Un try/catch puesto directamente en `Base.init` fallaba en el verificador de Ruffle (VerifyError #1026), por eso va en un método aparte.
- **`allowScriptAccess`:** la página del juego habilita la comunicación página↔juego (ExternalInterface) solo cuando existe la configuración de duelos (`SE_DUELS=on` y jugador conectado). Apagado sigue en `false`.
- **Servicios nuevos:** `tournaments/start_tournament_match.php` y `tournaments/finish_tournament_match.php`, con la respuesta firmada `HMAC-SHA256(SERVER_KEY, payload);payload` que espera el `ServiceManager` del juego. `finish` responde siempre OK para que el juego vuelva a la aldea; el resultado real lo dice el aviso de la página.
- **Arena:** el mapa `100000040` (el que la config del juego asigna a los torneos y que nunca se publicó) se sirve desde `config/duels/arena.json` (o `SE_DUEL_ARENA_FILE`), generado por `tools/make_arena.py`: una isla de aventura vacía. El juego ubica los ejércitos solo, en las baldosas (10, 59) y (90, 59), enfrentados.
- **Las muertes en la arena no llegan a la aldea:** cuando muere una unidad, el juego llama a los comandos `kill`/`sell` (motivo `KILL`) con la posición y el mapa del jugador (`IsoFightingElement.kill`). Pero `CommandManager.addCommand` solo encola comandos en el modo NORMAL (o ayudas en modo vecino), así que **el juego nunca los manda desde la arena**: comprobado en el código y en el navegador (durante la batalla no llegó ningún `command.php`). Como segunda protección, mientras un jugador está en la batalla (desde "Iniciar batalla" hasta su informe o el plazo) el servidor descarta solo los comandos de muerte de unidades de esa aldea y los anota en la consola (`[duel] arena command dropped`). Los demás comandos pasan, y al volver a la aldea todo cuenta normalmente. Una primera versión descartaba todos los comandos hasta 20 s después del informe; en la prueba con dos navegadores eso descartó comandos legítimos de la aldea al volver, por eso se acotó.
- **Ejército de duelo:** las **20** tropas de combate más fuertes (antes 30): el modo torneo del juego ubica como máximo 20 por lado. Se excluyen las unidades de `TOURNAMENT_UNITS_NOT_ALLOWED` de la config del juego. La fuerza (para el control de improbabilidad) es la de esas mismas 20.
- **Base:** la tabla `duels` gana columnas (estado, informes, porcentajes, tiempos, revisión). Los duelos de la fase 1 se migran solos como duelos terminados (`status = 'done'`). Las batallas que un reinicio del servidor deja a medias quedan anuladas (`review_reason = 'restart'`).

Reglas (aprobadas):
- Gana el **mayor porcentaje** de ejército rival destruido; si empatan (a dos decimales), el **más rápido** (a la décima de segundo, medido con el reloj del servidor desde "Iniciar batalla"); si también empatan, empate.
- Un informe **no vale** si: la batalla duró menos que el mínimo, el porcentaje no es un número de 0 a 100, el jugador nunca pulsó "Iniciar batalla", o ya había informado. Un informe que no vale cuenta como no informado.
- **Plazo:** cuenta desde que se acepta el reto. Si uno solo informa a tiempo, gana; si ninguno, el duelo se **anula**.
- **Improbable:** si el ganador tenía menos de un tercio de la fuerza del perdedor, el duelo no cuenta para el ranking y queda **en revisión**. En **Administración > Duelos** un administrador lo **valida** (aplica el Elo) o lo **anula**; queda guardado quién y cuándo, y los dos jugadores reciben la decisión al momento.
- **"Esperando al rival…":** quien termina primero ve el aviso con el tiempo que le queda al rival (cuenta regresiva). Si recarga la página, el aviso vuelve; si recarga durante la batalla, vuelve a entrar a la arena.

### Configuración (un solo lugar: el principio de `duels.py`)

| Variable de entorno | Por defecto | Qué hace |
| --- | --- | --- |
| `SE_DUEL_MIN_SECONDS` | `20` | Duración mínima de una batalla para que el informe valga |
| `SE_DUEL_DEADLINE_SECONDS` | `600` (10 min) | Plazo para informar, desde que se acepta el reto |
| `SE_DUEL_POWER_RATIO` | `0.3333` (un tercio) | Si la fuerza del ganador es menor que esta fracción de la del perdedor, el duelo va a revisión |
| `SE_DUEL_ARENA_FILE` | `config/duels/arena.json` | Mapa de la arena |

Valores vacíos, no numéricos, cero, negativos o infinitos se ignoran y se usa el valor por defecto.

### Ajustes después de la prueba con dos navegadores

- **Resultados que no se perdieron:** una pestaña en segundo plano puede quedar congelada y perder la conexión justo cuando llega el resultado. El servidor guarda el último resultado de cada jugador (hasta 1 hora) y lo vuelve a mandar cuando una página se reconecta, hasta que una página confirma que lo mostró (mensaje `seen`). La decisión de un administrador llega por el mismo camino. Un reinicio del servidor borra esos pendientes; el resultado igual queda en el historial.
- **Cuentas regresivas exactas:** se calculan contra la hora de fin, no contando "tics" (Chrome da muy pocos tics a las pestañas en segundo plano y la cuenta se atrasaba minutos).
- **Al aceptar, los dos van a la arena:** la página que el jugador está mirando lo lleva: un portal visible va al juego; un juego visible abre la arena; si ninguna página está a la vista, la pestaña del juego abre la arena sola después de un momento (y queda lista al volver). Las páginas de un mismo navegador se coordinan por `BroadcastChannel`: el portal que se va al juego avisa a las pestañas del juego ocultas para que no abran otra arena, y la pestaña que abre la arena avisa a las demás. (Una primera versión usaba bloqueos `navigator.locks`; en la prueba, una página vieja que el navegador guardaba en caché retenía el bloqueo e impedía abrir la arena, por eso se quitaron.)
- **La IA del rival ataca:** `TournamentIA` solo sale de su espera (avanza y ataca) en los torneos **semanales**; el tipo de torneo 1 tiene `weekly_tournaments: 0`, por eso el ejército rival avanzaba un poco y se quedaba quieto. Con duelos encendidos, la configuración que recibe el juego trae ese tipo en modo semanal (`weekly_tournaments: 1`; la configuración real no se toca): el rival forma, espera 10 s, avanza, espera 10 s y ataca; las tropas del jugador se defienden solas. Probado: dos batallas completas sin dar ninguna orden.
- **Sin avisos de la aldea encima de la arena:** el juego encadena ventanas de inicio (noticias, misión de mapa como "Capítulo 1: ¡Princesa secuestrada!") y la siguiente se abría al cerrarse la ventana de carga del torneo. `__startDuel` apaga las pendientes (`Base.deferredPopupQuestInfo` y `Base.showNews`); son avisos informativos y el juego los vuelve a mostrar en una próxima carga de la aldea.
- **Prueba del script de la página** (`tests/test_duels_js.py`, con Node): carga `duels.js` con un DOM simulado y le pasa cada mensaje del servidor; comprueba los avisos, que la arena se abre una sola vez, que el portal lleva al juego y que una segunda pestaña del juego se hace a un lado. Se agregó después de que un error del script (una función borrada) dejó de mostrar el aviso de reto sin que ninguna prueba lo detectara.
- **Recordatorio para probar en una sola computadora:** el navegador frena el juego de la pestaña que no está al frente; para jugar las dos batallas a la vez conviene usar dos ventanas (o dos navegadores) visibles.

Probado en el navegador (Tuki y Tuki2): reto y aceptación desde el juego y desde el portal; batalla real con victoria por 100 %; "Esperando al rival…"; huida antes de 20 s (no vale); plazo vencido (gana quien informó); los dos demasiado rápidos (anulado); resultado improbable a revisión, validado desde Administración > Duelos y avisado a los dos jugadores; ranking y aldeas sin cambios por la arena.
