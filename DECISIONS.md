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

## Duelo en vivo de verdad (opción A): para más adelante

Decidido el 13/11/2026: el duelo en vivo con combate calculado en el servidor (unas 4 a 6 semanas de trabajo) queda para después de las aventuras (puntos 28 a 30). Mientras tanto sigue la opción B.

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
- **Los dos ejércitos cargan solos, sin pausas largas:** al pulsar "Iniciar batalla", las tropas del jugador pasan a la condición agresiva del juego (`IA.CONDITION_AGGRESSIVE`) con un radio de búsqueda de 200 baldosas (toda la arena): buscan al enemigo más cercano y lo atacan solas (el jugador igual puede darles órdenes). La espera de la IA rival (`TournamentIA.waitingTime`) baja de 10 s a 2 s (`AI_WAITING_MS` en `swf_duel_bridge.py`), y si la atacan antes pasa a batalla al momento. Probado: los dos ejércitos avanzan y chocan en el medio unos 30 s después de empezar, sin dar órdenes. La velocidad de marcha es la de cada unidad en el juego.
- **Áreas de ataque de los dos imperios:** en la arena (modo torneo, solo se usa en duelos) se dibuja siempre el área de todas las unidades: las propias en azul y las del rival en rojo, sin seleccionar nada. Solo con `SE_DUELS=on` (`add_range_overlay(all_in_tournament=...)`); apagado, la película del juego es idéntica byte por byte a la de antes (comparado por SHA-256).
- **Sin avisos de la aldea encima de la arena:** el juego encadena ventanas de inicio (noticias, misión de mapa como "Capítulo 1: ¡Princesa secuestrada!") y la siguiente se abría al cerrarse la ventana de carga del torneo. `__startDuel` apaga las pendientes (`Base.deferredPopupQuestInfo` y `Base.showNews`); son avisos informativos y el juego los vuelve a mostrar en una próxima carga de la aldea.
- **Prueba del script de la página** (`tests/test_duels_js.py`, con Node): carga `duels.js` con un DOM simulado y le pasa cada mensaje del servidor; comprueba los avisos, que la arena se abre una sola vez, que el portal lleva al juego y que una segunda pestaña del juego se hace a un lado. Se agregó después de que un error del script (una función borrada) dejó de mostrar el aviso de reto sin que ninguna prueba lo detectara.
- **Recordatorio para probar en una sola computadora:** el navegador frena el juego de la pestaña que no está al frente; para jugar las dos batallas a la vez conviene usar dos ventanas (o dos navegadores) visibles.

Probado en el navegador (Tuki y Tuki2): reto y aceptación desde el juego y desde el portal; batalla real con victoria por 100 %; "Esperando al rival…"; huida antes de 20 s (no vale); plazo vencido (gana quien informó); los dos demasiado rápidos (anulado); resultado improbable a revisión, validado desde Administración > Duelos y avisado a los dos jugadores; ranking y aldeas sin cambios por la arena.

## Clanes, fase 1 (rama `clanes`)

Cambios de comportamiento (solo con `SE_CLANS=on`; apagado no se registra ninguna ruta, no aparece ningún enlace y las páginas quedan iguales):
- **Páginas nuevas:** `/clans` (lista, búsqueda, crear, tus solicitudes) y `/clans/<id>` (miembros, solicitudes, acciones según el rol, actividad); enlace "Clanes" en el menú del portal y del juego. **Administración > Clanes:** lista de clanes y disolver con motivo obligatorio; actividad reciente.
- **Base nueva:** `instance/clans.sqlite3` (clanes, miembros, solicitudes, salidas y registro de actividad). Las aldeas no se tocan.
- Funciona con o sin duelos (`SE_DUELS`); las guerras de clanes (fase 2) los necesitan.

Reglas (aprobadas):
- Un jugador está en un solo clan. Crear un clan exige el tutorial terminado.
- Nombre de 3 a 24 caracteres (letras, números, espacios, punto, guion, apóstrofo), único sin distinguir mayúsculas ni tildes ("Los Ñandúes" = "los nandues"); etiqueta de 2 a 5 letras sin tildes o números, única, en mayúsculas; descripción de hasta 200 caracteres.
- Hasta **70 miembros** con 1 Guild Master y hasta **3 Assist**.
- **Ingreso por solicitud**, que aprueban el Guild Master o un Assist. Hasta 3 solicitudes abiertas por jugador; vencen a los 7 días. Al aceptar a alguien se borran sus otras solicitudes; si ya entró a otro clan, la solicitud desaparece.
- **Permisos** (se controlan en la base, dentro de cada operación, no solo en la página):
  - Guild Master: todo; nombra y quita Assist, expulsa a cualquiera, edita la descripción, pasa el mando (y queda como miembro), disuelve el clan.
  - Assist: acepta o rechaza solicitudes y expulsa solo a miembros comunes.
  - Miembro: sale del clan.
- El Guild Master sale solo después de pasar el mando; si está solo, salir disuelve el clan.
- Quien sale o es expulsado espera **1 hora** para entrar a otro clan o crear uno. Disolver un clan no impone espera.
- Toda acción queda en el registro (quién, qué, a quién, cuándo); la disolución por un administrador guarda el motivo.

Configuración: los límites están al principio de `clans.py` (`MAX_MEMBERS`, `MAX_ASSISTS`, `MAX_OPEN_REQUESTS`, `REQUEST_SECONDS`, `REJOIN_SECONDS`).

Probado en el navegador con un servidor espejo (puerto 5051, copia de los datos en una carpeta temporal, para no dejar clanes de prueba en la base real): crear clan, solicitud de Tuki2, aceptación, nombrar Assist, vista del Assist y sección de administración.

## Clanes, fase 2 (retos entre clanes)

Cambios de comportamiento (solo con `SE_CLANS=on`; los retos cuentan duelos, así que para jugarlos hace falta también `SE_DUELS=on`):
- **Retos al mejor de N:** el Guild Master reta a otro clan desde la página de ese clan y elige 3, 5 o 7 duelos. El Guild Master retado tiene **10 minutos** para aceptar o rechazar; si no responde, el reto vence. Quien retó puede cancelarlo mientras está pendiente.
- **Cómo se suman las victorias:** aceptado el reto, cada duelo que termina con resultado (estado `done`, no empate) entre miembros de los dos clanes suma 1 victoria al clan del ganador. No suman los empates, los anulados ni los que están en revisión; si un administrador valida uno en revisión mientras el reto sigue abierto, suma. Cada duelo cuenta una sola vez. Solo cuentan los miembros que estaban en cada clan **al aceptarse** el reto (quien entra después no cuenta; quien sale después sigue contando para su clan en ese reto).
- **Fin del reto:** gana el clan que llega primero a la mayoría (2 de 3, 3 de 5, 4 de 7). Cualquiera de los dos Guild Master puede **rendirse** (gana el otro). Un clan disuelto durante un reto lo pierde; si estaba pendiente, se cancela. Apenas termina, los dos clanes pueden retar de nuevo, al mismo clan o a otro. Cada clan tiene un solo reto pendiente o en curso a la vez.
- **Conexión con Duelos:** el centro de duelos avisa a los "oyentes" de cada duelo terminado (`DuelHub.result_listeners`, también al validar un administrador); con los dos interruptores encendidos, `server.py` conecta Clanes como oyente. Un error de un oyente nunca afecta al duelo.
- **Avisos en vivo** (por la conexión de los duelos): al Guild Master retado le llega "¡[ETQ] Clan retó a tu clan!" con botón "Ver reto"; al que retó, la respuesta (aceptado o rechazado).
- **En Duelos:** la etiqueta del clan aparece junto a cada nombre y, durante un reto, los miembros del clan rival aparecen marcados "Clan rival" (se actualiza al recargar la página).
- **Página del clan:** el reto en curso con el marcador, los duelos que sumaron y el botón de rendirse; los retos anteriores con su resultado. **Clanes:** ranking de clanes por retos ganados, luego duelos ganados en retos.
- **Base:** tablas nuevas en `instance/clans.sqlite3` (`clan_challenges`, `clan_challenge_rosters`, `clan_challenge_duels`); los retos guardan el nombre y la etiqueta de los clanes, así el historial se ve aunque un clan se disuelva.

Configuración: `CHALLENGE_SIZES` y `CHALLENGE_ANSWER_SECONDS` al principio de `clans.py`.

Probado: reglas con reloj simulado; las páginas y los permisos (un Assist no puede retar, aceptar ni rendirse, ni armando el pedido a mano); de punta a punta con duelos reales (reto, aviso en vivo, aceptación, un duelo con alguien de fuera que no suma, dos duelos que suman y el reto termina 2–0); y en el navegador con el servidor espejo: reto, aviso "¡[NAN] Los Ñandúes retó a tu clan!", aceptación, aviso de respuesta y la marca "Clan rival" en Duelos.

## Clan dentro del juego, fase 1 (ventana del clan)

Cambios de comportamiento (solo con `SE_CLANS=on`; apagado, la página del juego queda igual):
- **Escudo "Clan" sobre el juego:** a la derecha del dibujo del juego (debajo del ícono de la mano), en la aldea y en la arena. Se ubica sobre el juego mismo, no sobre las franjas negras de los costados, con las mismas medidas que usa `game.css` para el reproductor. Es una capa HTML encima de Ruffle (`templates/_clan_overlay.html`, `js/clan_overlay.js`, `css/clan_overlay.css`); la película del juego no cambia.
- **Ventana con aspecto del juego** (pergamino, título "CLAN", pestañas): sin clan, *Buscar clan*, *Crear clan* y *Clasificación*; con clan, *Mi clan*, *Miembros*, *Retos*, *Clasificación* y *Buscar clan*. Las fichas de otros clanes se abren desde la búsqueda o el ranking. Arte propio: 12 emblemas (escudo con un símbolo), sin imágenes de otros servidores.
- **Mi clan:** estandarte con emblema, etiqueta, nombre y lema; poder (suma de la fuerza de duelo de los miembros); miembros; líder y tu rango; anuncio; resumen del reto; reclutamiento; *Editar* (Guild Master), *Disolver*, *Salir*.
- **Nuevo en el clan** (columnas nuevas en `clans`, que una base existente recibe sola al arrancar): **emblema** (1 a 12), **anuncio** (hasta 500 caracteres, con saltos de línea), **reclutamiento** abierto o con solicitud, **nivel mínimo** de la aldea principal (1 a 99) e **idioma** (todos, español, portugués, inglés). Solo el Guild Master los edita.
- **Reclutamiento abierto:** un jugador que cumple el nivel mínimo entra al momento, sin aprobación (se registra como "join" en la actividad). Con solicitud, como antes. El nivel mínimo vale para las dos formas; el idioma se muestra, no bloquea.
- **API JSON de la ventana:** `GET /clans/api/state`, `GET /clans/api/clans?q=`, `GET /clans/api/clans/<id>`, `POST /clans/api/action` (formulario con el token CSRF; cada acción pasa por las mismas reglas y permisos de `clans.py`). Un clan ajeno no muestra su reto en curso.
- Las acciones peligrosas (expulsar, pasar el mando, rendirse, salir, disolver) piden confirmación dentro de la ventana, sin diálogos del navegador.
- Todo el texto escrito por jugadores (nombres, lema, anuncio) se escapa antes de dibujarse; una prueba con Node lo verifica en cada vista.

Probado: reglas nuevas (ajustes, entrada directa, nivel mínimo, migración de una base vieja); la API (crear, sin token rechazado, ajustes, un Assist no puede editar, nivel mínimo, entrada directa, retos, búsqueda); las vistas en Node (escape, botones según el rol, sin textos faltantes, 12 emblemas, separador de miles); y en el navegador, dentro del juego, con el servidor espejo: abrir la ventana, crear un clan con emblema, editar anuncio y reclutamiento, que Tuki2 lo encuentre y entre directo, nombrarlo Assist y la confirmación de expulsar.

## Clan dentro del juego, fase 2 (chat y alianza)

Cambios de comportamiento (solo con `SE_CLANS=on`):
- **Pestaña Chat** en la ventana del clan, con el canal del clan y, si hay una alianza activa, el canal **Alianza** compartido por los dos clanes. Mensajes de hasta 300 caracteres (los espacios repetidos se juntan), como máximo uno cada 2 segundos por jugador; se guardan los últimos 200 de cada canal (`clan_messages`). La ventana pide los mensajes nuevos cada 3 segundos mientras el chat está abierto (no usa la conexión de los duelos, así funciona también con `SE_DUELS` apagado). Cada mensaje muestra la etiqueta del clan del autor.
- **Los mensajes no se borran** (decisión del dueño): nadie puede borrar mensajes, ni el autor ni los líderes; los más viejos se van solos al pasar los 200 por canal. Solo los miembros ven y escriben en su canal; el de la alianza, solo los dos clanes aliados.
- **Alianza** (`clan_alliances`): el Guild Master la propone desde la ficha de otro clan; al otro Guild Master le llega un aviso en vivo ("¡[ETQ] Clan propone una alianza a tu clan!", con los duelos encendidos) y la acepta o la rechaza desde *Mi clan*. Quien la propuso puede cancelarla mientras espera. **Una sola alianza por clan**, contando la propuesta pendiente. Los aliados **no pueden retarse** (el servidor lo rechaza y la ficha no ofrece retar). Se muestra "Aliado: [ETQ] Clan" en la ventana y en la página del clan. Cualquiera de los dos Guild Master la rompe (pide confirmación); un clan disuelto la termina. Sin vencimiento por ahora ("luego veremos qué trabajo hacemos").
- La ventana vuelve a pedir los datos al servidor en cada cambio de pestaña (una alianza o un reto pueden cambiar mientras está abierta).

Probado: reglas con reloj simulado (canales privados, largo y ritmo, quién borra, una alianza por clan, aliados sin retos, canal compartido, disolución); la API (lectura y escritura por canal, borrar, proponer, aceptar, romper, retar después de romper); las vistas en Node; y en el navegador con el servidor espejo: alianza propuesta por Tuki, aviso en vivo a Tuki2, aceptación, y chat de la alianza en los dos sentidos.

### Arreglos pedidos después de la fase 2

- **Chat sin borrado:** se quitó por completo (reglas, API y ventana); una acción `delete_message` armada a mano responde 400.
- **Los campos de la ventana ya no se vacían:** la ventana se redibuja sola (cada 20 s y al cambiar de pestaña, cuando llegan datos nuevos) y eso borraba lo que se estaba escribiendo, por ejemplo al crear un clan. Ahora, antes de cada redibujado, guarda lo escrito en todos sus formularios (texto, selecciones, emblema elegido y la posición del cursor) y lo restaura; solo empieza vacío el formulario de una acción que salió bien. Además, la actualización periódica no corre mientras se está en *Crear clan* o editando el clan.
- **Prueba en un navegador real** (`tests/test_clan_overlay_browser.py`): abre Chrome o Edge sin ventana con `tests/clan_overlay_browser.html`, que carga la ventana real con un servidor simulado, escribe en *Crear clan*, fuerza los redibujados y comprueba que lo escrito, el emblema y el foco sigan; que crear funcione; que el borrador del chat sobreviva a sus actualizaciones; y que no haya ningún botón de borrar. Sin el arreglo, la prueba falla.

## Revisión de los puntos 19 a 22, y "Más logros"

- **"Más logros" (la mano blanca, arriba a la derecha):** era el pedido de Facebook para publicar logros en el muro (aparece desde el nivel 10 si el jugador no dio ese permiso). Al tocarla no hacía nada y volvía a aparecer en cada carga. El juego ahora arranca con ese permiso dado (`publishActions=1` en `templates/js/game.js`), así que la mano no aparece; el comando `rt_publish_achievement_unit` que el juego manda al colocar un edificio de logro se acepta y no hace nada (antes figuraba como no manejado).
- **Bono diario:** funciona (se probó en una copia: aparece "Bono diario" con su premio y se cobra). El juego cuenta los días en hora UTC, así que se renueva a las 00:00 UTC (21:00 de Argentina). No faltaba: ese día ya se había cobrado a las 21:02.
- **Alianza y retos:** dos clanes con un reto pendiente o en curso entre ellos ya no pueden aliarse (ni proponer ni aceptar la alianza), y un reto no se acepta si los clanes son aliados. Antes podían quedar aliados en medio de un reto.
- **Portal, entrar a un clan:** ahora sigue las mismas reglas que la ventana del juego: el nivel mínimo del clan se aplica también desde el portal, y un clan abierto acepta al jugador al instante (el botón dice "Entrar al clan").
- **Portal, retar:** la página de un clan aliado ya no ofrece el formulario para retarlo.
- **Texto:** el estado de un reto sin respuesta dice "Expiró sin respuesta" (antes "Venció sin respuesta", que podía leerse como que ganó).

## Botón "Clan" dentro del juego

- El botón "Clan" ahora es un ícono del propio juego, en el panel de íconos de la derecha (debajo del engranaje), donde antes estaba la mano de "Más logros". Lo agrega `swf_clan_button.py` solo con `SE_CLANS=on` (apagado, la película no cambia). El juego arma ese panel recién cuando el jugador está en el imperio, así que el botón no aparece en la pantalla de carga; el juego lo ubica junto a sus otros íconos (por ejemplo el cofre del lunes) y muestra "Clan" como ayuda al pasar el mouse.
- Al tocarlo, el juego llama a `window.seOpenClan()` (ExternalInterface) y la página abre o cierra la ventana del clan. Por eso `allowScriptAccess` se enciende también con los clanes encendidos. Las dos partes nuevas del juego están dentro de su propio try/catch: un error no puede romper la interfaz.
- La imagen (el mismo escudo verde con la palabra debajo) está en `templates/img/clan_button_<idioma>.png` ("Clan" en español e inglés, "Clã" en portugués); se dibuja de nuevo con `tools/make_clan_button.py`.
- Se quitó el escudo HTML que flotaba sobre el juego (también se veía durante la carga).

## "Retar clan", chat de la alianza y duelos entre pestañas

- **Botón "Retar clan" en el juego:** un segundo ícono (escudo rojo con espadas cruzadas) junto a "Clan", en el mismo panel del juego. El panel ubica sus íconos uno debajo del otro, a 100 px; "Retar clan" dibuja su imagen un lugar más arriba y a la izquierda, así queda al lado de "Clan" y no tapa el "+" del zoom. El panel pasa de 2 a 3 íconos visibles (la única instrucción original que cambia, del mismo tamaño), para que el cofre del lunes no oculte ninguno. Al tocarlo se abre la ventana en la pestaña nueva **Retar clan**.
- **Pestaña "Retar clan"** (para miembros de un clan): lista los otros clanes con buscador. El propio clan no aparece; el aliado se marca "Aliado" y los clanes que ya tienen un reto se marcan "En un reto". El Guild Master elige al mejor de 3, 5 o 7 y reta desde la misma fila; los demás ven "Solo el Guild Master puede retar a otro clan". Si el clan ya tiene un reto, se avisa y hay un botón para ver los retos. La pestaña "Retos" sin reto lleva a esta pestaña.
- **Chat de la alianza siempre visible:** el canal "Alianza" aparece siempre en el chat. Sin alianza explica cómo formar una (y no consulta al servidor); con una propuesta pendiente dice que el chat se abre cuando la acepten; con la alianza activa muestra "Alianza [ETQ]" y el chat compartido.
- **Al tocar un ícono del juego** se quita su cartel de ayuda (antes quedaba "Clan" en pantalla, porque la ventana se abre encima y el juego no ve salir el mouse).
- **Avisos de clan dentro del juego:** "Ver reto" y "Ver alianza" abren la ventana del clan en el juego (pestañas Retos y Mi clan) en lugar de llevar al portal y sacar al jugador del juego. En el portal siguen abriendo la página del clan.
- **Una sola copia del juego por batalla:** con dos pestañas de juego abiertas, o una de juego y la de Duelos, a veces las dos abrían la misma batalla, porque cada una decidía sola y los mensajes entre pestañas llegan tarde. Ahora cada pestaña de juego deja en `localStorage` una marca de "juego abierto" que renueva cada 2 s y borra al cerrarse. La página de Duelos no abre otro juego si esa marca está vigente (75 s, porque las pestañas en segundo plano pueden correr sus relojes una vez por minuto). Para abrir una batalla, la pestaña de juego la **reclama** y espera un instante: si otra la reclamó, se hace a un lado. Además, la pestaña que se hace a un lado **cierra su juego** y muestra "El juego se cerró en esta pestaña porque la batalla se abrió en otra", con el botón "Abrir el juego aquí". Así no quedan dos copias de la misma aldea mandando órdenes, y no se agota la memoria gráfica (con tres juegos abiertos, una pestaña perdió el WebGL). Sin `localStorage` se usa el sistema anterior.

Probado de punta a punta en el navegador, con una copia de los datos y dos jugadores en el mismo navegador (127.0.0.1 y localhost):
- se creó un clan sin que se vaciaran los campos;
- se mandó un reto con el botón del juego y se aceptó;
- se jugó un duelo real en la arena: los dos recibieron el mismo resultado, se actualizó el ranking y el reto sumó la victoria;
- se probaron la rendición, la alianza y el chat de la alianza en los dos sentidos;
- "Ver reto" se abrió dentro del juego;
- con dos pestañas de juego, solo una abrió la batalla y la otra cerró su juego.

## Segunda revisión de clanes y duelos

Fallas encontradas y corregidas:
- **Números gigantes como identificador** (en la API de la ventana, en el chat y en las direcciones del portal) daban error 500. Ahora se rechazan: la API responde que el elemento no existe, el chat los acota y una dirección con un número fuera de rango da 404. Lo encontró una revisión automática que recorre todas las páginas y acciones con valores raros.
- **Íconos del juego sin cartel de ayuda:** el panel dibujaba el cartel de "Clan" a su izquierda, justo encima de "Retar clan"; un clic ahí iba a "Clan" y cerraba la ventana. El de "Retar clan" salía un casillero más abajo, fuera de la vista. Los nombres ya están en las imágenes, así que los íconos van sin cartel.
- **Mensaje sin traducir:** al expulsar a un miembro se veía "Membro removido do clã." en portugués. Se tradujo, y una prueba nueva revisa que toda frase de clanes y duelos tenga traducción al español y al inglés.
- **Registro de actividad:** faltaban etiquetas para entrar a un clan abierto, las alianzas y, en la página de admin, los retos; se habrían visto como códigos ("join"). Ahora hay una sola lista para las dos páginas, con una prueba que exige una etiqueta por cada acción registrada. "Cambió la descripción" pasó a "editó el clan", porque la edición incluye emblema, anuncio e ingreso.
- **Página del clan en el portal:** ahora muestra el anuncio y las condiciones de ingreso (abierto o con solicitud, nivel mínimo, idioma), como la ventana del juego.
- **"Venció" ambiguo:** los vencimientos dicen "expiró" ("El reto expiró.", también en el formulario y en el saqueo vencido).
- **Ventana del clan desactualizada en otra pestaña:** al volver a la pestaña se recargan los datos (una pestaña oculta corre su actualización de 20 s muy de vez en cuando; un jugador expulsado seguía viéndose en el clan).
- **Confirmaciones:** al pedir una confirmación se borra el mensaje de la acción anterior.
- **Duelo con la ventana del clan abierta:** la ventana se cierra al entrar a la arena, para que no tape la batalla.

Probado en el navegador con una copia de los datos y los dos roles: nombrar y quitar Assist, pasar el mando, editar el clan (anuncio con HTML, que se muestra como texto, en varias líneas), expulsar, la espera para volver a entrar, "Retar clan" sin clan, y duelos cancelados, rechazados y vencidos.

## Sin el botón "Retar clan" en el juego

Decisión del dueño: en la pantalla del juego queda solo el botón **Clan**; para retar se usa la pestaña **Retar clan** de su ventana. Se quitaron el segundo ícono y sus imágenes, y el panel del juego vuelve a su capacidad original (2 íconos, alcanza para el cofre del lunes y "Clan"), así que el parche ya no cambia ninguna instrucción original del juego: solo agrega el ícono y su clic.

## Habilidades automáticas de las unidades (`SE_ABILITIES=on`)

Pedido del dueño: que las habilidades de las unidades se lancen solas, que las unidades que invocan tengan un límite de 1 invocación, una descripción al pasar el mouse por cada habilidad, y que el botón de invocar quede en rojo con "Límite 1/1" cuando terminó su recarga pero ya hay una invocación viva (la descripción cuenta "Límite 0/1", "Límite 1/1"). Decisiones del dueño: automáticas para **todas** las unidades (las del jugador y las enemigas, solo en combate), el límite cuenta las invocaciones **vivas** y las descripciones van **por tipo** de habilidad.

- Lo agrega `swf_unit_abilities.py` a la película del juego solo con `SE_ABILITIES=on`. Apagado, el juego es el original. `SE_ABILITIES_DEBUG=on` escribe en la consola del navegador cada lanzamiento automático y los errores que atrapan las protecciones (solo para probar).
- **Lanzamiento automático:** en cada paso del reloj de la unidad, si está viva, quieta (sin lanzar ni recargar) y peleando, lanza su próxima habilidad lista, por turnos, con la misma función que usa el clic. Solo las habilidades de usos ilimitados: las de usos limitados siguen siendo a mano, para no gastarlas sin querer. Si la unidad está seleccionada, su recuadro muestra la recarga como si se hubiera tocado el botón.
- **Límite de 1 invocación:** el juego rechaza una invocación mientras la unidad tiene una viva, y las rutinas comunes de invocar crean como máximo una unidad. Las invocaciones se reconocen por su código (revisan la cantidad de esbirros o crean esbirros, dragoncitos, huevos, diablillos o arañas); los torbellinos no cuentan.
- **Descripción:** al pasar el mouse por un botón de habilidad aparece un cartel a la izquierda de los botones (sin taparlos) con el tipo (invocación, curación, protección, ataque definitivo, torbellino, ataque en área, a distancia, golpe fuerte u otra), una frase, "Límite X/1" en las invocaciones y si se lanza sola o es de usos limitados. Está en español, inglés y portugués.
- **Botón en rojo:** cuando el botón de invocar terminó su recarga y la unidad ya tiene su invocación viva, se tiñe de rojo con el cartelito "Límite 1/1"; un clic no invoca otra. Al morir la invocación, vuelve a la normalidad.
- Todo el código nuevo corre dentro de su propio try/catch: si algo falla, el juego sigue con su código original.
- Limitaciones: algunas unidades tienen su propia forma de invocar (unas 20); si no pasan por las rutinas comunes, una sola invocación podría crear más de una unidad, aunque igual no se puede volver a invocar mientras quede una viva. El efecto `p.miniFireball2.swf` no está entre los archivos del juego (404); ya faltaba antes, pero ahora se nota más porque la bola de fuego se lanza sola.

Probado en el navegador con una copia de los datos: en un duelo real las habilidades se lanzaron solas (bolas de fuego, lluvia de fuego, torbellino, lluvia mortal); en la aldea, el Dragón Vulcano mostró las descripciones de sus 4 habilidades, el huevo invocó una unidad (población 27 → 28), la descripción pasó a "Límite 1/1", al terminar la recarga el huevo quedó rojo con "Límite 1/1" y otro clic no invocó nada.

### Habilidades en la fuerza del duelo, y Ruffle sin caídas

Medición previa con la copia de los datos (Tuki 19.395 de fuerza contra Tuki2 27.900): el más fuerte ganó los 16 duelos. Sin habilidades, Tuki destruyó en promedio el 46 % del ejército rival; con habilidades, entre el 19 y el 33 %. La fórmula de fuerza no les daba ningún valor.

- **Fuerza** (decisión del dueño: +25 %): con `SE_ABILITIES=on`, cada unidad cuyas habilidades se lanzan solas cuenta un 25 % más en la fuerza del duelo (`duels.duel_unit_power`; se cambia con `SE_DUEL_ABILITY_BONUS`). Vale para elegir las 20 tropas del duelo, para el control de duelo improbable y para la fuerza de los miembros de un clan. Apagado, la fuerza es la de siempre.
- **Qué unidades:** solo la película del juego lo dice (la clase de cada unidad en `IsoEngine.CreateIsoElement` y sus habilidades con usos ilimitados). `tools/make_ability_units.py` lo lee con `swf_unit_abilities.automatic_ability_units` y lo guarda en `config/duels/ability_units.json` (162 unidades), así el servidor no lee la película para armar un ejército. Una prueba verifica que el archivo coincide con la película.
- **Ruffle se caía** ("Algo salió mal") al dibujar el filtro de color de los efectos de las habilidades (congelar, envenenar, piedra, rayos) con su forma de dibujo "wgpu-webgl", que es la que elige incluso con WebGPU disponible. Con las habilidades automáticas esos efectos aparecen mucho más, y en las pruebas se cayó uno de los dos juegos en cada tanda. Con `SE_ABILITIES=on` la página le pide a Ruffle su forma de dibujo WebGL propia (`preferredRenderer: "webgl"`). Probado: 4 duelos con habilidades sin caídas en el mismo navegador. Apagado, la página no cambia.

## Panel de administración: dar y quitar unidades, completar y reiniciar misiones

Decisión del dueño (revisión del punto 19): el panel de cada aldea, además de mostrar el ejército y las misiones, puede cambiarlos.

- **Dar unidades:** cualquier unidad que el juego vende (con precio en oro o en dinero; 750 de 771), de 1 a 100 por cambio. Van al almacén del jugador ("Regalos"), igual que los regalos del juego, y el jugador las coloca con "Usar".
- **Quitar unidades:** de las que tiene la aldea, de 1 a 100 por cambio. Salen primero del almacén, después del mapa y por último de dentro de los edificios.
- **Misiones:** "Completar" marca la misión como hecha y deja la recompensa para que el jugador la cobre en el juego; "Reiniciar" borra la misión y su recompensa cobrada, para que se pueda volver a hacer.
- Cada cambio pide motivo, queda en el historial con el antes y el después (cantidad total de esa unidad, o el estado de la misión) y usa el mismo diario que la edición de recursos: se guarda la partida completa antes de escribirla, y si algo falla a mitad, se recupera. El jugador con el juego abierto ve el aviso para recargar.

Probado en el navegador con una copia de los datos: se dieron 2 Dragón Vulcano (2 → 4), se quitó 1 (4 → 3), se completó "Entrena un aldeano", y en el juego de Tuki2 el almacén mostró los 3 dragones y uno se colocó en la aldea.

## Cuentas activas al crearse, y bloqueo con motivo

Decisiones del dueño (revisión del punto 19):
- **Las cuentas nuevas quedan activas al registrarse:** el jugador entra enseguida y su aldea se crea al primer ingreso. Ya no hace falta aprobarlas una por una. Con `SE_AUTO_APPROVE=off` vuelve la aprobación manual (las pendientes se aprueban o se rechazan como antes).
- **Bloquear con motivo:** en Administración > Cuentas, cada cuenta activa tiene "Bloquear", que pide un motivo (3 a 200 caracteres). El jugador queda afuera al instante, aunque tenga el juego abierto, y al intentar entrar lee "Tu cuenta está bloqueada… Motivo: …". "Desbloquear" le devuelve el acceso y borra el motivo. Antes, "Suspender" devolvía la cuenta a "pendiente", sin motivo, y se mezclaba con los registros nuevos.
- Por dentro, una cuenta bloqueada usa el estado "rechazada" que ya existía (un registro rechazado también queda bloqueado, sin motivo) y una columna nueva, `block_reason`, que se agrega sola a la base de cuentas existente sin tocar las cuentas. Así no hace falta reconstruir la tabla.
- La página de Cuentas abre en "Todas" y muestra los filtros Activas y Bloqueadas; "Pendientes" aparece solo si hay alguna.

Probado en el navegador con una copia de los datos: una cuenta nueva entró al juego sin aprobación, se la bloqueó con motivo (se cerró su sesión abierta y al entrar vio el motivo) y se la desbloqueó.

## Música y sonido del juego: la elección se mantiene (`SE_SOUND_FIX`, encendido por defecto)

Pedido del dueño: "lo desactivé pero sigue activándose solo el sonido".

- **Causa:** el juego guarda música y efectos en su almacenamiento local (`settings.data.music`, `settings.data.sfx`) pero nunca llama a `flush()`. Flash lo escribía al cerrar la página; Ruffle no. Después de recargar (o en la próxima visita) el juego volvía a sonar.
- **Segundo error:** al volver a prender la música, el botón arranca la música antes de marcarla como encendida, y el juego no la reproduce mientras figure apagada: quedaba en silencio hasta cambiar de mapa.
- **Arreglo** (`swf_sound_settings.py`): los botones de música y de sonido guardan la elección en el momento (`flush()` dentro de su propio try/catch), y el de música la marca encendida antes de arrancarla. No cambia ninguna instrucción original. Es un arreglo pedido, por eso está encendido por defecto; `SE_SOUND_FIX=off` sirve el juego como antes.
- Probado en el navegador con la copia de los datos: apagar la música, recargar y sigue apagada; apagar y prender los efectos; volver a prender la música. Cada cambio queda guardado al instante.

## Botón PvP y elección de tropas en saqueos y duelos (`SE_PVP=on`)

Pedido del dueño: que en Rivales, Saqueos y Duelos cada jugador elija sus unidades, como en la ventana de equipo del juego, y un botón "PvP" debajo de "Clan". Decisiones del dueño: la elección en la **ventana del propio juego**; en los saqueos **solo cuentan las tropas elegidas** (hasta 20; siguen sin batalla); el botón abre una **ventana dentro del juego**.

- **Botón PvP** (`swf_pvp.py`): un ícono del juego en el panel de la derecha, debajo de "Clan" (escudo rojo con dos espadas, `tools/make_pvp_button.py`). Al tocarlo, la página abre la ventana PvP (`templates/js/pvp_overlay.js`), con el mismo aspecto que la del clan y tres pestañas: **Rivales** (las aldeas que se pueden atacar, su defensa y el saqueo posible), **Saqueos** (el historial) y **Duelos** (jugadores conectados para retar, la puntuación y los últimos duelos). Abajo, un enlace a la página completa.
- **Elegir tropas:** al tocar "Atacar" o "Retar", la ventana PvP se aparta y se abre la ventana "Elige tu equipo" del juego (la que usan las aventuras antes de zarpar), con 20 casillas. El juego la llena solo en sus propios modos; se usa el de torneo, que además deja afuera las unidades que la arena no admite, y se vuelve a mostrar su botón de cerrar (ese modo lo oculta). Cerrarla sin elegir cancela. La ventana recuerda el último equipo: el juego lo manda con su comando `set_attack_team`, que ahora el servidor guarda (`privateState.teams.tournament`).
- **Saqueos:** la fuerza de ataque es la de las tropas elegidas, si la aldea las tiene (cada una tantas veces como la tenga), hasta 20. Sin elección (por ejemplo desde la página del portal) atacan las 20 más fuertes, para que elegir no sea peor que no elegir. La defensa no cambia.
- **Duelos:** quien reta elige antes de enviar el reto, y quien lo acepta dentro del juego elige al aceptar. Esas tropas son las que van a la arena y las que cuentan para la fuerza. Como elegir lleva tiempo, el reto dura **90 s** en vez de 30. Quien acepta desde la página del portal, o fuera de su aldea, va con las 20 más fuertes. Un equipo vacío o mal formado se rechaza y el reto sigue abierto.
- Apagado (`SE_PVP` sin poner), nada cambia: ni la película, ni las rutas, ni la fuerza de los saqueos, ni el tiempo de los retos.
- Se arregló de paso `tools/make_clan_button.py`, que usaba `WIDTH` y `HEIGHT` sin definirlos.

Probado en el navegador con la copia de los datos: el ícono aparece debajo de "Clan"; la ventana muestra los rivales; un saqueo con 3 tropas elegidas atacó con la fuerza de esas 3 (8.875) y la ventana volvió en Saqueos con el resultado; la ventana de equipo recordó esas 3 tropas al retar; Tuki retó a Tuki2, que al aceptar eligió 2 tropas, y el duelo arrancó con 3 contra 2.

Limitación conocida: el botón "+" del zoom del juego tapa parte de la palabra "PvP" debajo del ícono.

## Letras blancas con borde negro y unidades agotadas fuera de la ventana de equipo (`SE_READABLE_UI`, encendido por defecto)

Pedido del dueño: que la ventana PvP se lea mejor, un borde negro en las letras blancas de todo el juego, y que en "Elige tu equipo" una unidad que llegó a x0 deje de verse.

- **Ventanas HTML** (clan, PvP, avisos de duelo): los textos claros (título, pestañas, encabezados, botones verdes y marrones) pasan a blanco con borde negro; la ventana PvP tiene letra un poco más grande y los textos grises, más oscuros.
- **Juego** (`swf_readable_text.py`): cada texto blanco que aparece en pantalla (un `TextField` con color 0xFFFFFF y sin filtros) recibe un borde negro (`GlowFilter`), como los rótulos propios del juego. Lo hace un único escucha en la fase de captura de `ADDED_TO_STAGE` del escenario, dentro de su propio try/catch.
- **Ventana de equipo:** el juego solo agrisaba una miniatura agotada con un filtro de color; ahora se oculta (`ThumbUnit.deactivate`) y vuelve a verse cuando se quita esa unidad del equipo (`activate`). Queda el hueco: el juego no reacomoda la lista.
- Es un pedido del dueño, por eso está encendido por defecto; `SE_READABLE_UI=off` sirve el juego como antes.
- Los bordes del juego son filtros: se ven con la forma de dibujo normal de Ruffle (ver la sección siguiente). Ocultar las unidades agotadas funciona con cualquier forma de dibujo.

Probado en el navegador con la copia de los datos (forma de dibujo habitual de Ruffle): borde en "Elige tu equipo", "Unidades seleccionadas" y las cantidades x1/x2; un caballero x1 desapareció al elegirlo y el dragón azul volvió con x1 al quitarlo del equipo.

## Forma de dibujo de Ruffle: la normal, con calidad "alta" si hay habilidades

Pedido del dueño: algunas palabras no se distinguían y aparecían puntos verdes al pasar el puntero sobre edificios y unidades (y puntos oscuros en el pasto).

- **Causa:** con `SE_ABILITIES=on` la página pedía a Ruffle su forma de dibujo WebGL propia, para evitar que el juego se cerrara con los efectos de las habilidades. Esa forma de dibujo no dibuja los filtros del juego: ni el borde de las letras blancas, ni el gris de lo deshabilitado, y el resaltado verde (un brillo) salía como puntos sueltos.
- **Lo que se encontró:** el cierre no era de la forma de dibujo normal en sí, sino de la calidad máxima que pedía la página (`16x16`): con esa calidad, Ruffle fallaba al preparar el filtro de color. Con calidad `high`, 4 duelos con habilidades (con los dos juegos completos) terminaron sin ninguna caída; con `16x16` se caía un juego en cada tanda.
- **Ahora:** la página usa la forma de dibujo que elige Ruffle y, con las habilidades encendidas, calidad `high`. Sin habilidades, todo igual que antes (`16x16`). Se cambia con `SE_RUFFLE_RENDERER` (`webgpu`, `wgpu-webgl`, `webgl`, `canvas`; sin poner, la elige Ruffle) y `SE_RUFFLE_QUALITY` (`low`, `medium`, `high`, `best`, `8x8`, `16x16`...). Si el juego volviera a cerrarse en alguna computadora, `SE_RUFFLE_RENDERER=webgl` vuelve a la forma anterior.
- Probado en el navegador con la copia de los datos: 4 duelos con habilidades sin caídas; el resaltado del molino se ve parejo, sin puntos; "CONSTRUIR", "Campamento enemigo", "Elegir área" y los carteles de las unidades con borde negro.

## Nombre al pasar el puntero también en castillos, murallas y torres (`SE_READABLE_UI`)

Pedido del dueño: algunas estructuras no mostraban su nombre al pasar el puntero, en su imperio, en los de otros y en las misiones.

- **Causa:** el juego original arma la tarjeta con el nombre (`InfoPopup`, en `IsoInteractiveElement.highlight`) para todo, **salvo** las estructuras de defensa (categoría 2: castillos, murallas, torres), que solo mostraban la barra de vida.
- **Arreglo** (`swf_readable_text.py`): esa comparación usa ahora una categoría que ningún ítem tiene (-1), así que todas las estructuras muestran su nombre. Es un solo byte (el operando de la comparación), dentro del try/catch propio del juego; es el único cambio a una instrucción original de este parche.
- Probado en el navegador: "Torre V" y "Castillo III" muestran su nombre. Con la cámara muy cerca, la tarjeta de una estructura grande cerca del borde inferior puede quedar debajo de la barra de abajo del juego (el juego la ubica al pie de la estructura).

## Dardos diarios (`SE_DAILY_DARTS`, encendido)

Pedido del dueño: los Dardos eran semanales y los quería diarios.

- **Causa:** el tablero (25 globos y 6 premios) solo se reinicia cuando empieza una nueva entrada de `darts_items` en la configuración, y esas entradas van de semana en semana y terminan en septiembre de 2012 (la última no tiene premios: con la fecha de hoy el juego no encontraba ningún tablero). El dardo gratis ya era diario, pero solo hasta reventar todos los globos. Además, el servidor no atendía las órdenes de los dardos: los globos reventados, el dardo gratis y los **premios se perdían** al recargar.
- **Ahora** (`darts.py`): el servidor arma `darts_items` con una entrada por día (desde 3 días atrás hasta 60 adelante) y va rotando los 32 juegos de premios originales del juego. El juego solo lee la fecha, como medianoche local del jugador, así que el tablero se renueva a la medianoche de cada jugador y la cuenta regresiva muestra lo que falta para el día siguiente. Los textos dicen "mañana" y "cada día" en vez de "la próxima semana" y "cada semana".
- **Órdenes atendidas:** `darts_reset` (tablero nuevo con dardo gratis), `darts_new_free`, `darts_shoot_balloon` (un dardo pagado descuenta `DART_COST_CASH`, 20 de dinero) y `store_add_items` (el premio va al almacén, como `store_item`). El premio lo elige el juego, igual que el resto de las órdenes.
- Con `SE_DAILY_DARTS=off` todo queda como antes.
- Probado en el navegador con la copia de los datos: aparece "¡Ganaste un dardo GRATIS!"; la cuenta regresiva llega hasta la medianoche; el dardo gratis dio un Paladín alado, que quedó en el almacén; un dardo pagado descontó 20 de dinero; los globos reventados quedan guardados.

## Registro: el nombre del jugador nombra el imperio; registrarse cierra la sesión anterior (`SE_EMPIRE_NAME`, encendido)

Pedido del dueño: que el "Nombre del jugador" del registro sea el nombre del imperio, sin espacios ni símbolos, y que una cuenta nueva no entre como administradora.

- **Nombre:** al registrarse, el nombre del jugador solo puede tener letras (también acentuadas y ñ) y números, de 2 a 32 caracteres (el largo máximo de un nombre de aldea). El formulario lo avisa y el servidor lo valida (`validate_player_name` en `village_names.py`).
- **Imperio:** cuando la cuenta entra por primera vez y se le crea la aldea, la aldea toma ese nombre (`map_names`), en vez de "Mi Imperio". Se puede cambiar después como siempre. Las aldeas que ya existen conservan su nombre.
- **Administrador:** las cuentas nuevas nunca se crean administradoras (en la base, `is_admin` es 0). Lo que pasaba: el registro no cerraba la sesión que ya estaba abierta en ese navegador. Si alguien se registraba estando conectado como administrador, después de "¡Cuenta creada!" el login lo devolvía al juego con la cuenta del administrador. Ahora registrarse cierra esa sesión (se conserva el idioma elegido) y muestra el formulario para entrar con la cuenta nueva.
- **Barra de amigos** (pedido después): los demás ven a cada jugador por `playerInfo.name`, que en toda aldea nueva era "Emperador". Al entrar, un jugador que todavía tiene ese nombre por defecto (Imperador, Emperador, Emperor) recibe el nombre de su cuenta (`name_default_player`); también las cuentas que ya existían, porque nunca lo eligieron. Un nombre distinto guardado en la partida se respeta, y un nombre de cuenta que no sirve como etiqueta (más de 32 caracteres, < o >) deja el de siempre. Cambiar el nombre de la aldea sigue sin tocar este nombre.
- Con `SE_EMPIRE_NAME=off` el registro queda como antes.
- Probado en el navegador con la copia de los datos: "Mi Reino" da error; "MiReino" crea la cuenta y muestra el login aunque había otra sesión abierta; la cuenta nueva no es administradora y su aldea se llama "MiReino".

## Ajustes en `server.env`: alcanza con `python server.py`

Pedido del dueño: no tener que escribir `SE_DUELS=on SE_CLANS=on SE_ABILITIES=on SE_PVP=on python server.py` para prender las funciones.

- **`server.env`** (junto a `server.py`, como la carpeta `mods`): una línea `CLAVE=valor` por ajuste, con comentarios en español. Trae prendidas las cuatro funciones (duelos, clanes, habilidades, PvP) y los arreglos; los ajustes avanzados (forma de dibujo de Ruffle, calidad, puerto) están comentados y usan el valor de fábrica.
- **`server_settings.py`:** `server.py` lee el archivo apenas arranca, antes de que cualquier módulo mire los interruptores, y muestra en la consola cuáles quedaron prendidos. Una variable puesta en la consola gana sobre el archivo (`SE_PVP=off python server.py` sigue funcionando). Sin el archivo, todo usa los valores de fábrica de siempre.
- Solo se lee cuando `server.py` es el programa que se ejecuta: las pruebas y los comandos `flask --app server ...` siguen con los valores de fábrica, así las pruebas no dependen de lo que tenga el archivo.

## Órdenes de la aldea que el servidor ignoraba (`SE_VILLAGE_COMMANDS`, encendido)

Pedido del dueño: "que todo funcione correctamente". Se revisaron todas las órdenes que la película del juego puede enviar: unas 80 no tenían manejo en `command.py` ("Unhandled command") y lo que hacían se perdía al recargar. Algunas son código muerto del juego (por ejemplo `upgrade`: `doUpgrade` no tiene quién lo llame) o del panel de administración de Social Point. El dueño eligió empezar por la aldea básica (`village_commands.py`). Las reglas y los números salen del propio código del juego:

- **Hechizos y maná:** `use_magic` descuenta el maná del hechizo y cuenta un uso (`privateState.magics`); `buy_magic` cobra el precio (dinero u oro), aprende el hechizo y trae su primera carga de maná; `buy_mana_new` da `MANA_PER_PURCHASE` por `COST_MANA_CASH` dinero o `COST_MANA_GOLD` oro.
- **Maná por nivel:** desde el nivel `START_LEVEL_MANA_REWARD` (36), cada nivel da `MANA_REWARD_PER_LEVEL` (2), como el juego. Como el servidor nunca lo contaba, todos tenían 0 de maná: al entrar, cada jugador recibe una sola vez el maná de los niveles que ya pasó (`privateState.manaRewardLevel` marca hasta dónde se contó). Tuki2 (nivel 99) recibió 128.
- **Mercado** (`trade_resource`): precio = `MARKET_BASE_COSTS[recurso] × cantidad / 100`, más `MARKET_INCREMENT` (2 %) por cada paso de `map.resourcesTraded`; vender paga el 75 %. Comprar sube el paso y vender lo baja, entre -25 y 200. El servidor calcula el precio con la misma fórmula (no confía en un precio del juego). No se implementó que el precio vuelva a bajar con el tiempo (`MARKET_PERIOD_HOURS`): el juego tampoco lo hace por su cuenta.
- **Desbloquear un edificio antes de tiempo** (`unlock_building`): cuesta `ceil(nivel mínimo / 3)` de dinero y queda en `privateState.unlockedEarlyBuildings`.
- **Población** (`increase_population`): suma un aumento en `map.increasedPopulation`.
- **Almacén:** un ítem guardado en la misma sesión se coloca (`place_stored_item`) o se vende (`sell_stored_item`) igual que un regalo, porque el servidor guarda todo lo almacenado en `privateState.gifts`. Además: `place_gift` usaba el cuadro (`frame`) como número de isla (ahora usa el quinto dato, la isla), y vender un regalo que ya no está no da error.
- Una orden imposible (hechizo o recurso desconocido) se registra como rechazada y no cambia la partida. Con `SE_VILLAGE_COMMANDS=off` todo queda como antes.
- Probado en el navegador con la copia de los datos: Tuki2 entró con 128 de maná; aprender Estragos de Fuego con oro descontó 1000 de oro y dio 5 de maná; lanzarlo gastó 5; comprar maná con dinero descontó 1 y dio 5. Mercado, desbloqueo, población y almacén se probaron con pruebas automáticas (sus datos se leyeron del código del juego).
- **Tropas pagadas con dinero** (`buy_unit_with_cash` [tropa, x, y, cuadro, isla]): el entrenamiento normal envía `buy` al terminar y ya se guardaba; solo se perdían las tropas entrenadas pagando con dinero y los héroes comprados en su tienda. Ahora cuestan el `cost_unit_cash` de la tropa, suman su experiencia y quedan en la aldea. Si la tienda de héroes no tiene altar, el juego primero guarda el héroe en el almacén (`store_add_items`, en el mismo envío) y después manda esta orden con una posición sin sentido: ahí solo se cobra, porque el héroe ya está en el almacén. `store_add_items` se atiende también con los dardos apagados. Probado con pruebas automáticas, no jugando.
- **Pendiente, por grupos:** almacén de unidades, edificios sociales (muelle, zepelín), clima, colecciones, misiones del mapa, exploración y ataques, supervivencia, máquina del tiempo y torneos.

## Pruebas dentro del juego y edificios sociales (`SE_VILLAGE_COMMANDS`)

Pedido del dueño: probar siempre dentro del juego, arreglar lo que aparezca y llevar un bloc de notas corto (`Correcciones-Fixeos.txt`) con lo que falta.

- **Probado jugando** (copia de los datos, Tuki2): entrenar pagando con dinero (la orden real es `buy_cash`) deja la tropa en la aldea y la cobra; guardar una casa y venderla (`sell_stored_item`) o volver a colocarla (`place_stored_item`) en la misma sesión; `place_gift` manda la isla como quinto dato (`[194, 55, 42, 0, 0]`); mejorar un cuartel (el juego manda `buy` del nivel siguiente, ya funcionaba); mercado: compra (`trade_resource_b`) y venta con el precio del juego.
- **Edificios sociales** (mercado, muelle, zepelín, molino II...): el juego los deja "en construcción" mientras sus atributos (octavo dato del ítem) tengan `si`, la lista de ayudantes contratados (`Base.IsBeingBuilt`). El servidor nunca la guardaba: al recargar se abrían gratis y el dinero pagado por los ayudantes no se descontaba. Ahora, al comprarlos, quedan con `{"si": []}`; `buy_si_help` [x, y, isla, edificio] cobra `worker_cost` de `social_items` y suma un ayudante (gratis si el juego lo regala, quinto dato 1); `finish_si` los abre. Los que el juego coloca solo (muelle y zepelín iniciales, `buy` sin cobrar) y los que no cobran ayudantes (solo amigos) quedan como antes. Probado: comprar un mercado, contratar uno, recargar (recuerda el ayudante), contratar dos más, abrir y recargar: abierto, 6 de dinero descontados.
- **Mercado:** "Intercambios restantes hoy" mostraba NaN: el juego lee `numTradesDone` y `timestampLastTrade` de la isla y el servidor no los tenía. Ahora se agregan al entrar (0) y cada intercambio cuenta; a las `MARKET_PERIOD_HOURS` (20) del primero vuelve a 0, y se aceptan hasta 20 por período, como el juego.
- **Resucitar héroes:** el código usaba `map` e `id` sin definir (las funciones de Python): daba error y el héroe se perdía. Ahora se coloca en la isla.
- **Efecto faltante:** el proyectil `P_MINI_FIREBALL` pedía `fx/p.miniFireball2.swf`, que no está entre los recursos (error 404 en cada combate); se sirve `p.fireBall_02.swf` en su lugar.
- Para las pruebas: un clic necesita apretar y soltar con una pausa breve, y colocar desde el almacén necesita dos clics (el primero solo marca el lugar).


## Almacén de unidades (`SE_VILLAGE_COMMANDS`)

Grupo 1 de `Correcciones-Fixeos.txt`. El almacén de unidades (edificio 1284) guarda tropas por isla en `map.warehousedUnits` (`{id de tropa: cantidad}`) hasta `map.warehouseAditionalCapacitySingle` lugares (`Base.loadPlayerInfoSuccess`).

- Las partidas no tenían esos dos campos: el juego leía la capacidad como NaN y ninguna tropa podía entrar. Ahora se agregan al entrar: capacidad 20 (el valor de las aldeas originales en `villages/quests`) y almacén vacío.
- `add_unit_warehouse` [x, y, isla, tropa]: la tropa sale del mapa y entra, si hay lugar (`IsoBuilding.pushUnitToWarehause`). `place_warehoused_item` [tropa, x, y, 0, isla]: vuelve al mapa (`PopupUnitWarehouse.onUseClick`). `buy_warehouse_capacity_single` [isla]: un lugar más por `WAREHOUSE_CAPACITY_INCREASE_PRICE_SINGLE` (2) de dinero, hasta `WAREHOUSE_MAX_CAPACITY` (1000). `reset_warehouse` [isla]: al guardar el edificio, sus tropas pasan al almacén general (`Base.storeItem`). Si la tropa no está en el mapa o el almacén no la tiene, la orden se rechaza y no se duplica ni se pierde nada.
- Textos del almacén escritos en inglés dentro del código del juego ("Buy now", "Buy 1 more slot for … cash", "USE UNIT") se traducen con la lista de `swf_abc_strings.py`; solo se usan en esa ventana. El botón "OPEN" es un dibujo de otro archivo y sigue en inglés.
- Probado jugando (Tuki2, copia de los datos): el mapa de Tuki2 no tiene lugar libre para un edificio de 6×6, así que el almacén se agregó a la partida de la copia; meter una vaca, comprar un lugar (21, 2 de dinero), sacarla, volver a meterla, recargar (sigue adentro, capacidad 21) y guardar el almacén (la vaca y el edificio quedan en el almacén general).

## Lo colocado justo antes de recargar se perdía (`SE_QUICK_SAVE`, encendido)

Pedido del dueño: una tropa de "Regalos" puesta en el imperio volvía a "Regalos" al recargar.

- El servidor sí guarda `place_gift`; el problema era el tiempo. El juego junta lo que hace el jugador y lo envía cada `push_time` segundos, un parámetro de la página (entre 3 y 60, `Base`); la página no lo pasaba y el juego usaba su valor propio, unos 30 segundos. Recargar antes de ese envío perdía lo último: la tropa seguía en los regalos.
- Ahora la página pide 3 segundos, el mínimo que acepta el juego. Con la cola vacía el juego no envía nada (`CommandManager.sendCommands`), así que solo hay más pedidos cuando el jugador hace algo. `SE_QUICK_SAVE=off` deja el intervalo del juego.
- Además, colocar un regalo suma la experiencia del ítem, como muestra el juego (antes se veía y al recargar se perdía); solo si el regalo estaba en el almacén. La estatua de nivel, que completa el nivel, queda como antes.
- Probado jugando: colocar el Paladín alado desde el almacén llegó al servidor un segundo después y, saliendo de la página a los 4 segundos, al recargar sigue en la aldea y no en el almacén; colocar el Sacerdote celestial sumó 200 de experiencia y se mantuvo al recargar.

## Clima (`SE_VILLAGE_COMMANDS`)

Grupo 3 de `Correcciones-Fixeos.txt`. La Máquina del clima (edificio 373) abre el "Selector de temas" (`PopupWeather`): seis climas (0, 1, 2, 4, 5 y 6); el 0, Praderas Verdes, siempre está.

- `unlock_skin` [clima] cobra `COST_UNLOCK_SKIN` (20) de dinero y lo guarda en `privateState.unlockedSkins`; `set_skin` [isla, clima] guarda `map.skin`. El juego vuelve a cargar la isla del servidor justo después, así que antes el clima nuevo no se veía nunca y el dinero cobrado volvía al recargar.
- La ventana muestra un clima como desbloqueado cuando `unlockedSkins[id] == "true"`, una comparación con el texto: un `true` de JSON lo mostraría bloqueado otra vez. Se guarda `"true"`. Las aldeas originales usaban una lista (`[true]`); se convierte al leerla. Un clima que no existe, o aplicar uno bloqueado, se rechaza; desbloquear uno ya desbloqueado no cobra de nuevo.
- "Unlock for" se traducía "Desbloquear por" y el precio lo tapaba ("Desbloquear po20"); ahora dice "Desbloquear" (español y portugués), con el precio y el billete al lado.
- Probado jugando (Tuki2, copia de los datos; la Máquina del clima se agregó a la partida de la copia): desbloquear Llanuras Nevadas descontó 20 y la aldea se volvió nevada; volver a Praderas Verdes no cobró; al recargar la página la aldea sigue verde, el dinero sigue descontado y Nevadas aparece con "Aplicar tema".

## Colecciones (`SE_VILLAGE_COMMANDS`)

Grupo 4 de `Correcciones-Fixeos.txt`.

- **Piezas:** el servidor recibía `add_collectable` [colección, pieza] (al juntar una pieza de un enemigo, un jefe o una cosecha) y no hacía nada (`# TODO`): las piezas se perdían al recargar y ninguna colección se podía completar. Ahora se guardan en `privateState.collections[colección]` = [canjeada (1), cantidad de la pieza 1 a 5], el formato que lee el juego (`Base.processAttacks`).
- **Canjear** (`finish_collection` [colección]): pide las cinco piezas, gasta una de cada una, marca la colección y deja el premio (`COLLECTION_REWARDS`) en el almacén; se suma a `collectionsCompleted`. **Comprar con dinero** (`finish_collection` [colección, 1, precio]): una sola vez por colección; el servidor calcula el precio como el juego (`CollectableManager.getRealPrice`): `PRIZE_COLLECTIONS_CASH` (5 casi todas, 15 la 10, 20 la 20, 400, 400 y 999 las últimas) menos 1 por cada pieza que ya se tiene, mínimo 1; la 10 y la 20 tienen precio fijo.
- **Colecciones de tropas** (`unit_collections_completed` [categoría]): el premio es 1 de dinero (lo único que muestra el juego), una sola vez por categoría, guardado en `unitCollectionsCompleted`. El juego cuenta las tropas "obtenidas" de `privateState.boughtUnits`, que el servidor nunca llenaba: solo contaban las tropas en el mapa al cargar. Ahora se anotan las tropas que el jugador consigue (compra o entrenamiento pagado, con dinero, o colocadas desde regalos/almacén); las del campamento enemigo (compras gratis) no. Es una lista de ids: con un diccionario el juego se quedaba en "Loading".
- **`activate`** [x, y, isla, edificio, cp]: guarda en los atributos del edificio la producción elegida (`attrs.cp`, `PopupCollect`); vuelve a 0 al recolectar.
- Probado jugando (Tuki2, copia de los datos, con piezas y tropas puestas en la partida de la copia): canjear "Misterios de la Arena" dio la Pirámide; comprar "El Viejo Cofre" con dos piezas costó 3; "Espadas" 5/5 dio 1 de dinero; al recargar todo sigue completado y sin volver a ofrecerse. Juntar una pieza de verdad y `activate` se probaron solo con pruebas automáticas.
- "COMPLETED!" en la ventana de colecciones es un dibujo y sigue en inglés.

## Estaciones de Argentina (`SE_SEASONS`, encendido)

Pedido del dueño: que el clima cambie solo, con las cuatro estaciones de Argentina. El dueño eligió los climas, qué pasa con la elección del jugador y el costo (`seasons.py`).

- **Fechas y climas:** verano (21 dic – 20 mar) Desierto Soleado; otoño (21 mar – 20 jun) Montañas Rocosas; invierno (21 jun – 22 sep) Llanuras Nevadas; primavera (23 sep – 20 dic) Praderas Verdes. Se usa la fecha del servidor.
- **Cuándo cambia:** la primera vez que el jugador entra en una estación nueva, todas sus islas toman el clima de la estación (`privateState.seasonKey` recuerda la última, por ejemplo "2026-spring"). Si el jugador elige otro clima en la Máquina del clima, se queda hasta la estación siguiente.
- **Costo:** el clima de la estación es gratis mientras dura: se marca desbloqueado y al terminar la estación se vuelve a bloquear (`seasonSkinGranted`), salvo que el jugador lo hubiera comprado antes.
- `SE_SEASONS=off` deja el clima solo en manos del jugador. Al encenderlo, cada jugador recibe el clima de la estación actual la próxima vez que entra.
- Probado jugando (Tuki2, copia de los datos, preparada como si hubiera entrado por última vez en invierno con la nieve regalada): al entrar en primavera la aldea pasó a Praderas Verdes y la nieve volvió a pedir desbloqueo; desbloquear y aplicar Desierto Soleado (20 de dinero) se mantuvo al recargar. Las demás estaciones y sus bordes se probaron con pruebas automáticas.

## Misiones del mapa y tesoros (`SE_VILLAGE_COMMANDS`)

Grupo 5 de `Correcciones-Fixeos.txt`. Las misiones del mapa son el "Campamento enemigo" y las misiones con jefes que aparecen en la aldea (`QuestsInMap`, `CustomQuest`/`CustomQuestNew`).

- **Tesoro** (`collect_treasure` [oro, xp, misión siguiente, comida, piedra, isla]): al terminar una misión el juego da oro y experiencia según el nivel (250 a 750 de oro y 50 a 100 de experiencia, por `REWARD_QUESTS_CHAPTERS_MULTIPLIER`, que el juego deja entre 0 y 2) y pasa a la misión siguiente. El servidor no lo guardaba: el premio se perdía, `map.idCurrentTreasure` volvía siempre a la misión 0 y `map.timestampLastTreasure` (la cuenta regresiva hasta el próximo campamento) no se guardaba, así que el campamento volvía lleno en cada carga. Ahora se guarda todo; un premio mayor de lo que da el juego (1500 de oro, 200 de experiencia) se rechaza. `[0, 0, misión, 0, 0, isla]` solo corrige la misión (`MapInitializer.setCorrectQuest`).
- **Estado de la misión** (`set_quest_var` [isla, nombre, valor JSON]): `spawned`, `activators`, `boss` y `treasure` de las misiones nuevas se guardan en `map.currentQuestVars`, que el juego lee al cargar: una misión ya empezada no vuelve a aparecer. Las primeras misiones (0 a 6, los campamentos trolls, `CustomQuest`) no guardan su estado en el juego mismo: se recrean en cada carga (`CLEAN_0` y compras gratis) y se terminan en una sesión; lo que ahora sí queda es el avance a la misión siguiente.
- **Ayuda de amigos en una recolección** (`accept_collect_help` [x, y, isla, edificio, amigo]): adelanta la recolección `COLLECT_HELP_SECONDS` (una hora) y quita la ayuda de `attrs.hc`. **Misión de ciudad** (`perform_city_quest` [x, y, isla, misión]): el edificio vuelve a empezar su tiempo (la ventana `cityQuest` está vacía en esta versión del juego). **Mercado de aliados** (`set_resource_allies` [recurso, x, y, isla, edificio]): el recurso elegido queda en `map.resourceAlliesMarket` (`n` = ninguno).
- Probado jugando (Tuki2, copia de los datos, puesta en la misión 7): el juego cerró la misión y dio su tesoro (750 de oro, 100 de experiencia, misión 8); al recargar el oro y la experiencia siguen, la misión sigue en 8, el tesoro no se repite y el campamento muestra la cuenta regresiva. Las ayudas, la misión de ciudad y el mercado de aliados se probaron solo con pruebas automáticas (las ayudas llegan de otros jugadores, grupo 10).

## Pruebas jugando de lo que faltaba (grupos 4 y 5) y lo que apareció

Pedido del dueño: "Prueba jugando para que todo funcione correctamente al 100%". Se probó en la copia (Tuki2) lo que antes solo tenía pruebas automáticas, y se arregló lo que apareció:

- **Piezas de colección de verdad:** las defensas mataron enemigos del campamento y cayó una pieza (`add_collectable [6, 2]`); quedó guardada al recargar.
- **Producción de molinos y minas** (`activate`, ventana "Elegir tiempo"): la elección se guarda. Apareció que el servidor (1) no reiniciaba el tiempo al elegir, así que al recargar el molino ya estaba listo (elegir 8 h y cobrar al instante), y (2) daba siempre la producción base: el juego multiplica por `COLLECT_MULTIPLIER` (0,5 / 1 / 2 / 3 para 5 min / 1 h / 4 h / 8 h) pero manda 1 al servidor. Ahora elegir reinicia el tiempo y cobrar usa el multiplicador de lo elegido. Probado: "Poca comida", recargar (sigue produciendo), esperar 5 minutos, cobrar: +125 de comida en la partida.
- **Recolectar no reiniciaba el tiempo de ningún edificio** (`collect_new`): la partida guardaba el momento en que se construyó, así que tras recargar todo estaba listo otra vez (recursos sin fin). Ahora cada cobro guarda la hora.
- **Nombres de las opciones** de esa ventana estaban en inglés ("Some Food", "Lots of Gold"...): se traducen (español y portugués) con la lista de `swf_abc_strings.py`; esas 16 palabras solo se usan ahí.
- **Ayuda de un amigo** (`accept_collect_help`): probada con una ayuda puesta en el Coliseo de la copia; se acepta, adelanta una hora y no vuelve al recargar. Se corrigió la marca de usada: el juego guarda las ayudas como `u<amigo>` y marca `<amigo>`; el servidor ahora marca las dos.
- **Mercado de aliados:** sin `map.resourceAlliesMarket` el juego mostraba que producía dinero en vez de preguntar el recurso; ahora vale `n` (ninguno) por defecto y el juego pregunta. Elegir un recurso reinicia sus 24 horas (`PopupSelectResource.onSelect`); antes, al recargar, el juego lo daba por terminado y volvía a `n`. Probado: elegir piedra y oro, recargar, el recurso y el tiempo siguen.
- **Estado de misiones nuevas** (`set_quest_var`): probado con la misión 14 (fuegos artificiales): el juego guarda `spawned`, el servidor lo devuelve y al recargar el juego reconstruye la misión según su estado en vez de empezarla de cero. Completar una parte (activadores, jefe) no se pudo hacer desde las pruebas; queda cubierto por pruebas automáticas.
- **Misión de ciudad** (`perform_city_quest`): ningún objeto del juego tiene `quest_id` en las aldeas y su ventana está vacía en esta versión; no se puede alcanzar jugando.

## Aviso "Toca el juego para activar el sonido" (`SE_SOUND_FIX`)

Propuesta del dueño: un mensaje en la carga del juego. Los navegadores no dejan sonar una página hasta que la persona la toca; Ruffle arranca el juego mudo y solo muestra un parlante chico (y oscurece el juego). Ahora, si el navegador todavía no tuvo ningún toque en la página (`navigator.userActivation`) y el jugador no silenció el sonido, aparece "Toca el juego para activar el sonido" (español, inglés y portugués) sobre el juego. El mensaje deja pasar el toque al juego, donde Ruffle activa el sonido, y desaparece con ese primer toque o una tecla. Con `SE_SOUND_FIX=off` no aparece. Probado en el navegador de pruebas: el mensaje aparece en la carga y se va al tocar, junto con la capa oscura de Ruffle (el sonido en sí no se puede escuchar en ese navegador).

## Explorador del mundo contra jugadores reales (`SE_WORLD_EXPLORER`, encendido)

Grupo 6 de `Correcciones-Fixeos.txt`. El Explorador del mundo (botón "mundo") era un esqueleto: el servidor respondía siempre el mismo continente fijo y no guardaba nada. El dueño eligió que funcione **contra jugadores reales** y que los territorios sin jugador **queden vacíos** (`world.py`). Las reglas y números son los del juego:

- **Islas:** de la 50 (donde empiezan todos) a la 1; cada isla en continentes de 8 territorios, uno por jugador. Aparecen los jugadores aprobados que terminaron el tutorial y llegaron al nivel 6 (el juego no abre el explorador antes). Cada uno recibe un territorio la primera vez que alguien mira su isla. Conquistar los otros 7 (`map.universAttackWin`) pasa a la isla siguiente (`worldChange`), y el juego pide su premio (`apply_rewards_ranking`, de `level_ranking_reward`, una vez por isla). "Mudarse" (`reset_position_univers`) pierde el progreso y busca otro lugar.
- **Ataques:** 3 cada 6 horas y al mismo jugador una vez cada 4 (el juego los cuenta desde `privateState.attacksSent`); espionajes 3 por día. La batalla la corre el navegador del atacante (como siempre en este juego), así que el servidor solo acepta el resultado (`end_attack`) después de su propio `attack_player`, y lo acota: el atacante gana el oro de lo que destruyó (el juego lo paga aunque se retire) hasta `MAX_GOLD_ASSAULT` (20.000) y hasta 2.000 de experiencia; la víctima pierde oro solo si el atacante gana, como máximo el 20 % de su oro (igual que los saqueos) y no otra vez durante una hora. Ganar contra un jugador de la misma isla conquista su territorio.
- **Historial:** los dos jugadores ven la batalla en "Resultados de batalla" (`attacksSent` / `attacksReceived`, con el combate en `description` y el otro jugador en `oponent`); la víctima ve "¡Te atacaron!" al entrar y "GANASTE/PERDISTE" desde su lado; "NEW" desaparece al verlo (`clean_attacks` borra `viewPending`, porque el juego marca "NEW" mientras el campo exista).
- También se guardan: comprar un territorio de jugador por 5 de dinero (`buy_pvp_territory`, sin batalla ni botín), paquetes de 50 ataques (30) o espionajes (15), el cambio de posición (`modify_position_univers`).
- Probado jugando (copia de los datos, cuentas de prueba): la isla 50 muestra a los jugadores; Tuki2 atacó y venció a MiReino (territorio conquistado, 1/7, se mantiene al recargar); el juego no deja atacar dos veces al mismo jugador en 4 horas; el contador de ataques y la espera de 6 horas coinciden; Tuki atacó a Tuki2 y se retiró: Tuki2 vio "¡Te atacaron!" y "GANASTE"; "Mudarse" volvió el progreso a 0/7. Se arreglaron en el camino: el juego pedía la isla del rival (`map=null`, error 500), el historial necesitaba `description`/`oponent`, el lado de la víctima y "NEW". No se pudo probar jugando: comprar territorios (el juego solo ofrece "Conquistar" sin ejército), los paquetes (ninguna parte de esta versión del juego abre esa ventana), espiar (pide un Centro de espionaje) y pasar de isla con su premio; quedan cubiertos por pruebas automáticas.

## Punto 23: clima y ciclo día/noche (`SE_DAY_NIGHT`, encendido)

El dueño eligió un ciclo visual que sigue la hora real de Argentina, con lluvia o nieve según la estación. El clima de cada estación ya lo da `SE_SEASONS` (desierto, montañas, nieve, praderas).

- **Día y noche:** la página calcula la hora de Argentina (`America/Argentina/Buenos_Aires`) y cada 10 segundos le pide al juego el color de la aldea con `seSetDayLight` (`swf_daylight.py`, agregado a `Base`, registrado con `ExternalInterface` en `Base.init`). El juego aplica ese color solo a su capa del mundo (`Base.buildingLayer`: el suelo, los edificios y las tropas); el HUD y las ventanas no cambian. `Base.Iso` no sirve: es el motor, no algo que se dibuja. Noche de 20:30 a 5:30 (azul oscuro), amanecer de 5:30 a 7:30 y atardecer de 18:30 a 20:30 (pasando por un tono anaranjado), día de 7:30 a 18:30.
- **Lluvia y nieve:** una capa de dibujo de la página sobre el juego, del tamaño exacto de la película, que deja pasar los clics. Nieve en invierno, lluvia en el resto, por rachas: la probabilidad por hora es 35 % en invierno, 30 % en otoño, 15 % en primavera y 6 % en verano, calculada con la fecha y la hora (todos los jugadores ven el mismo clima a la misma hora). Si el navegador pide reducir el movimiento, no se dibuja.
- Para probar: `?hora=22.5` y `?clima=lluvia|nieve|despejado` en la dirección de la página fuerzan una hora o un clima (solo cambian lo que se ve).
- Probado en el navegador (copia de los datos): de noche (21:38) la aldea se oscurece y el HUD queda igual; a las 19:00 tono de atardecer con nieve; al mediodía colores normales con lluvia; la lluvia y la nieve quedan dentro del juego y los botones siguen respondiendo.

## Estrellas de dificultad de las misiones y desbloqueo de islas (`SE_VILLAGE_COMMANDS`)

Pedido del dueño: aumentar las estrellas de dificultad de las misiones. Las estrellas son la dificultad que se elige antes de cada isla (1 a 3, `PopupLoadingQuest.setDifficulty`): la 2 se ofrece después de ganar la isla con 1, y la 3 después de ganarla con 2, según `privateState.questsRank[id de la isla]`. El servidor nunca lo guardaba (`# TODO`), así que todas las islas quedaban en 1 estrella.

- Ahora, al ganar una isla (`end_quest` con `win`), se guarda la mayor dificultad ganada en `questsRank` (las aldeas nuevas lo tienen como el texto `'{}'`; se convierte). Más de 3 estrellas no: la ventana del juego tiene dibujadas solo 3.
- **Desbloqueo de islas:** el código original guardaba en `unlockedQuestIndex` el id de la isla + 1 (por ejemplo 100000007) después de cualquier `end_quest`, aun perdido, y eso abría todas las islas de golpe. El juego espera la posición de la isla en la ruta de aventuras (28 islas, de `PopupQuestsManager.goToIsland`). Ahora solo una victoria abre la isla siguiente de la ruta. Las partidas que ya tienen todo abierto por ese error quedan así (no se les quita nada).
- Probado jugando (Tuki2, copia de los datos): la isla de los trolls muestra la dificultad con la 2 y la 3 bloqueadas; el juego manda `quest_id` "100000006" y `difficulty` 1; una derrota no guarda nada; con la isla marcada como ganada con 1 estrella, el mapa del barco la muestra con 1 estrella dorada y la ventana deja elegir 2 estrellas. Ganar la isla en sí no se pudo completar desde las pruebas (el cofre quedó tapado por los dragones); está cubierto por pruebas automáticas.

## Editor de mundo de escritorio (punto 24 del bloque E)

Pedido del dueño: una aplicación de escritorio para editar las islas de misión, la arena de duelos y las aldeas de los jugadores.

- **Tecnología:** tkinter, que viene con Python: no hay que instalar nada. Todo está en la carpeta `WorldEditor/`, con su guía de uso (`LEEME - Uso del World Editor.txt`). Se abre con `WorldEditor/Editor de mundo.bat` (sin consola) o con `python WorldEditor/world_editor.py`, usando el Python del proyecto. La lógica está en `world_editor_core.py`, probada sin ventana (`tests/test_world_editor.py`); `world_editor.py` es solo la ventana. Con la aprobación del dueño se instaló PyInstaller en el `.venv`: `WorldEditor/Crear exe.bat` crea `WorldEditor/WorldEditor.exe` (un solo archivo, sin consola, unos 12 MB; ignorado por git, como el `.exe` del servidor). El `.exe` no trae datos: toma como proyecto la carpeta de arriba de donde está, y como dentro del `.exe` `bundle.py` apuntaría a su carpeta temporal, el editor le cambia `CONFIG_DIR`, `CONFIG_PATCH_DIR` y `MODS_DIR` a los del proyecto antes de leer la configuración. Si no encuentra el proyecto, o falla al abrir, lo dice en una ventana.
- **Vista:** el mapa de 100 x 100 casillas (`Config.EI_MAP_WIDTH/HEIGHT`) se ve desde arriba, no en perspectiva como en el juego. Cada objeto es un bloque de su tamaño (ancho y alto de la configuración, intercambiados si está girado) y las unidades son círculos rojos. Las miniaturas del juego son `.jpg`, y tkinter no las lee sin Pillow, así que los bloques llevan color por categoría y su nombre al acercar. Los objetos grandes (palmerales de 8 x 8) se dibujan debajo de los chicos.
- **Edición:** elegir un objeto de la lista (nombres en español, buscador, filtro de edificios o unidades) y hacer clic en el mapa para colocarlo; arrastrar para mover, R para girar, Supr para borrar, Ctrl+Z para deshacer (hasta 100 pasos); cambiar el nombre de la isla o del imperio. Solo se marca en rojo el objeto seleccionado cuando pisa a otro: las islas originales ponen palmeras, calaveras y muros encimados a propósito, y marcarlos todos era ruido.
- **Guardado:** antes del primer guardado de cada archivo se deja una copia `archivo.bak-AAAAMMDD-HHMMSS` (ignorada por git). Se escribe a un archivo temporal y después se reemplaza, y se respeta el formato de cada archivo (islas en una línea con `\/` como las escribía PHP, arena con sangría 1, partidas con sangría 4, finales de línea de Windows donde los había): 28 islas, la arena y las partidas quedan iguales byte a byte si no se cambia nada. Nueve islas escritas a mano (35, 51 a 55, 90 a 92) se reformatean la primera vez que se guardan, con el mismo contenido.
- **Cuándo se ve el cambio:** el servidor lee las islas del disco en cada batalla (cambio inmediato) y la arena al prenderse (hay que reiniciarlo). Las aldeas viven en la memoria del servidor mientras está prendido y las vuelve a escribir, así que el editor no deja guardar una aldea si el servidor responde en su puerto (`PORT`, 5050 de fábrica). Las partidas se buscan en la misma carpeta que usa el servidor (`SOCIAL_EMPIRES_SAVES_DIR` o `SOCIAL_EMPIRES_DATA_DIR/saves`).
- **Islas nuevas:** la lista muestra las 42 islas que el juego nombra en `Constants.QUEST_*` y las 5 islas extra de la carpeta (51 a 55). Las 12 que no tienen mapa aparecen como "(nueva)" y empiezan vacías, con la configuración de la isla de trolls 1. Ojo: ninguna de esas 12 está en la ruta del barco (`PopupQuestsManager.goToIsland`), así que el juego no tiene un botón para navegar a ellas; para jugarlas habría que cambiar la ruta del barco o reemplazar una isla existente.
- Probado: la ventana abre las islas, la arena y las aldeas (capturas sobre copias). En el juego, en la copia de los datos, la isla de trolls 1 guardada por el editor con otro nombre y 3 trolls más mostró "Prueba del Editor" y 8 trolls con vida en lugar de 5. Después se restauró la isla original.

### World Editor: vista del juego con los dibujos reales

Pedido del dueño: ver las imágenes de unidades, edificios y objetos al elegirlos, y ver el mundo como en el juego, al estilo del editor de Warcraft III. Con su aprobación se instaló Pillow en el `.venv` (también va dentro del `.exe`, que pasó a pesar unos 19 MB).

- **Dibujos:** los del mundo están en `assets/buildingsprites/<img_name>.swf`, como fotos JPEG con transparencia (DefineBitsJPEG3) puestas en formas, a veces dentro de animaciones. `WorldEditor/sprites.py` lee el `.swf` sin Flash: sigue el primer cuadro del símbolo exportado con el `img_name` del objeto, multiplica las matrices de ubicación y relleno, y compone un PNG con el punto de origen del símbolo. Las unidades usan el cuadro 4 de su animación QUIETO (los cuadros 1 a 5 giran de espaldas a de frente), la vista de 3/4 de frente. Los PNG quedan en `WorldEditor/imagenes` (ignorada por git), hechos la primera vez que aparece cada objeto.
- **Perspectiva:** la del juego (`Base.addElement`): casillas de 108 x 54 píxeles (`Config.EI_TILE_WIDTH/HEIGHT_PIXELS`), con la casilla (x, y) en (54·(x − y), 27·(x + y)). Un edificio se dibuja con el centro de abajo de su imagen en la esquina de abajo de su base, como el fantasma de construcción del juego (`IsoElement.setGraphic`: x = −ancho/2, y = −alto); una unidad, con su origen (los pies) en el centro de su casilla. Se dibuja de lo más lejano a lo más cercano. Un objeto girado se muestra espejado. La arena cubre lo que usan los objetos (como mínimo el centro del mapa); `expansions` no coincide con donde están los objetos de las islas, así que no se usa.
- **Uso:** "Vista del juego" (de fábrica) y "Vista de plano" (la de antes; tecla V). Al elegir un objeto se ve su dibujo en la vista previa (o la miniatura de la tienda si no tiene dibujo), y una copia transparente sigue al ratón con su base en verde, o en rojo si pisa otro objeto. Un objeto se elige tocando un píxel visible de su dibujo (el de más adelante); si no hay, por la casilla de su base. Sin Pillow, el editor sigue andando solo con la vista de plano.
- **Probado:** la isla de trolls 1 se ve como en el juego (el bosque en U, el claro y el campamento); la aldea MiReino de la copia, con su castillo, casas, árboles, vacas y aldeanos. Colocar, elegir por el dibujo, acercar y cambiar de vista, con el `.exe` y clics reales. 1642 objetos tienen miniatura y 1685 tienen dibujo.

### World Editor: ícono del castillo, zoom con la rueda y arrastre del mapa

Pedido del dueño. El `.exe` se llama `WorldEditor.exe` (antes "World Editor.exe": Windows oculta la extensión y no lo encontraba) y lleva como ícono el castillo del juego (`WorldEditor/castillo.ico`, armado con el dibujo de `castillo1.swf`), que también usa la ventana. La rueda del ratón acerca o aleja manteniendo bajo el cursor el mismo punto del mapa (Mayús + rueda lo mueve a los lados). Mantener el clic izquierdo sobre una zona vacía y arrastrar mueve el mapa; sobre un objeto, lo sigue moviendo a él. Con el botón derecho o la rueda presionados se mueve el mapa en cualquier lugar, también mientras se colocan objetos; un clic derecho sin arrastrar deja de colocar.

### World Editor: terrenos, zoom suave y sin barras de desplazamiento

Pedido del dueño: ver los terrenos para distinguir mejor los mapas, un zoom más suave y quitar las barras de desplazamiento.

- **Terreno, como lo arma el juego:** el mapa son 5 x 5 zonas de 20 x 20 casillas (`Config.EI_TILES_IN_BIGTILE`). `expansions` son las zonas compradas, numeradas de 1 a 25 por filas (`Base.purchaseLand`: columna (n − 1) % 5, fila (n − 1) / 5; la 13 es la del centro). El juego dibuja cada zona comprada con el objeto de terreno 1000 + `skin` (`Base.addExpandedTileBuilding`: 1000 pradera, 1001 desierto, 1002 hielo, 1003 mar, 1004 mineral, 1005 selva, 1006 nubes, de `assets/buildingsprites/terreno*.swf`, una imagen de 2160 x 1080 por zona) y el resto con el color de fondo de ese `skin` (`Config.BG_SKIN_COLORS`: #669c2c, #eabc4c, #dfecf2, #2e94e6, #863814, #398a00, #ffffff). El editor hace lo mismo en aldeas y arena, y marca con líneas punteadas los bordes de las 25 zonas; en la vista de plano, las zonas compradas van con el color promedio de su terreno. Las islas de misión se ven en la batalla como arena en el mar (no usan el terreno del `skin`), así que se dibujan así, con la costa marcada. El panel dice el terreno y cuántas zonas tiene compradas el mapa.
- **Corrección de posiciones:** leyendo `Base.setOccupiedGrid` se vio que la posición guardada de un objeto es su **última** casilla: ocupa de x − ancho + 1 a x (cuenta `tx` hacia atrás), igual que el terreno de una zona se pone en su casilla +19. El editor suponía la primera casilla; ahora las bases, el elegir por casilla, los choques y el anclaje de los dibujos (el centro de abajo de la imagen en la esquina de abajo de la última casilla) siguen la regla del juego. Colocar un objeto deja su última casilla donde se hace clic.
- **Zoom suave:** en vez de 7 niveles fijos, cada muesca de la rueda acerca o aleja un 12 % (vista del juego de 0,12 a 1,2; plano de 3 a 32 píxeles por casilla), manteniendo bajo el cursor el mismo punto; las muescas que llegan juntas se dibujan una sola vez (en una aldea de 378 objetos, 6 muescas en 0,4 s). Al cambiar el zoom se descartan las imágenes de los otros tamaños.
- **Sin barras de desplazamiento:** el mapa se mueve arrastrando (clic en zona vacía, o rueda o botón derecho presionados).

### Varias arenas PvP (World Editor y duelos)

Pedido del dueño: crear arenas para PvP y editarlas. Había una sola arena (`config/duels/arena.json`, el mapa 100000040), vacía, compartida por los duelos en vivo y los 4 torneos del juego. El dueño eligió **varias arenas PvP**, con la de torneos aparte.

- **Arenas PvP:** cada una es un archivo en `config/duels/arenas/<nombre>.json` (letras minúsculas, números, `-` y `_`; `SE_DUEL_ARENAS_DIR` cambia la carpeta). Cuando arranca un duelo, `DuelHub` elige una al azar y la guarda en la batalla; los dos jugadores reciben la misma. Si no hay ninguna, los duelos usan la arena de torneos, como antes.
- **Servida del disco:** el juego pide la arena como un mapa de aventura (`get_player_info` con `user=100000040`). `duels_web` busca el duelo de quien la pide y lee su arena del disco en ese momento, así que un cambio del editor vale para el próximo duelo sin reiniciar. Sin duelo, sirve la arena de torneos (también leída del disco). Si un archivo no se puede leer, se usa la arena cargada al prender el servidor y queda una línea en la consola.
- **Editor:** la pestaña "Arenas" lista las arenas PvP, con Nueva (pide el nombre; empieza con el terreno de la de torneos y sin objetos; se escribe al guardar), Abrir y Borrar (pide confirmación; el archivo queda como `.bak-AAAAMMDD-HHMMSS`, que el servidor no lee), y aparte "Abrir arena de torneos". El nombre de la arena es `playerInfo.name`.
- **Objetos sin dibujo:** 96 de los 1781 objetos no tienen su `.swf` en `assets/buildingsprites` (39 son de la versión de celular, como la Muralla reforzada, y el resto son archivos que faltan). En el mapa se muestran con su miniatura de la tienda; en la lista salen en gris con "· sin dibujo" y la vista previa avisa que en el juego no se verán bien.
- **Probado:** pruebas del hub (la misma arena para los dos, ninguna sin arenas PvP) y una prueba con un servidor real y WebSockets (un duelo entre dos jugadores recibe la arena PvP; sin duelo, la de torneos). En la copia de los datos, una arena hecha con el editor y un duelo entre Tuki2 y Tuki jugado en el juego.

## Actualizador automático y aviso de actualización (`SE_AUTO_UPDATE`, `SE_UPDATE_NOTICE`)

Pedido del dueño: no tener que reiniciar el servidor a mano, y que a los jugadores les salga un cartel "Hay una actualización disponible" con un botón "Reiniciar"; si no lo tocan, la página se reinicia sola a los 10 segundos. Sin posibilidad de postergarlo.

- **Qué se puede sin reiniciar y qué no:** los datos (islas, arenas) ya se leen del disco en cada uso. El código del servidor y el juego parcheado no se pueden cambiar dentro de un proceso que ya corre: hace falta uno nuevo. El actualizador hace ese cambio solo.
- **El mismo comando:** `python server.py` con `SE_AUTO_UPDATE=on` (de fábrica) no sirve el juego: arranca `updater.py`, que corre el servidor de verdad como proceso hijo (`SE_SERVER_CHILD=1`) y cada 10 s mira el commit actual (`git rev-parse HEAD`) y `server.env`. Al hijo le pasa el entorno de la consola de antes de leer `server.env`, para que cada servidor nuevo lea el `server.env` del momento.
- **Antes de reemplazar el servidor:** con un commit nuevo, corren todas las pruebas; después (también para un cambio de `server.env`), el servidor nuevo tiene que arrancar en un puerto libre con una carpeta de datos vacía y temporal (nunca toca aldeas ni cuentas) y responder `/login`. Si algo falla, sigue el servidor anterior, queda escrito en `instance/actualizaciones.log` (con las pruebas que fallaron o las últimas líneas de error) y ese commit no se vuelve a intentar. Si el servidor se cae solo, se vuelve a arrancar.
- **Solo commits:** un archivo a medio editar nunca llega a los jugadores; el servidor nuevo lee los archivos de la carpeta tal como están en ese commit.
- **Sin pérdida de datos:** cada aldea se escribe al disco después de cada tanda de órdenes del juego (cada 3 s con `SE_QUICK_SAVE`), con reemplazo atómico, así que detener el servidor no pierde lo guardado. Lo que el juego intente mandar en los segundos en que el servidor nuevo arranca puede no llegar; por eso el cambio es lo más corto posible (el arranque ya se probó antes de detener el viejo).
- **Aviso a los jugadores:** cada arranque del servidor tiene su propia versión (`SE_BUILD`; un servidor arrancado a mano también genera una), pública en `/version`. La página del juego la pregunta cada 5 s; si cambió, muestra encima de todo "Hay una actualización disponible", "Reinicia para cargar los cambios. Tu progreso está guardado.", el botón "Reiniciar" y la cuenta "Se reinicia en 10 s". A los 10 s recarga sola; el botón espera el envío de órdenes del juego (unos 3,5 s, "Guardando tu progreso…") antes de recargar, para no perder lo último que hizo el jugador. No se puede postergar. `SE_UPDATE_NOTICE=off` lo apaga.
- **Probado en la copia (5051) con el juego abierto:** un cambio en `server.env` pasó la prueba de arranque, reinició el servidor y en unos segundos apareció el cartel; sin tocar nada la página se recargó sola con la versión nueva; con otro cambio, el botón mostró "Guardando tu progreso…" y recargó. El paso de las pruebas, corrido de verdad, rechazó una versión con una prueba fallando (un cambio de `server.py` que rompía una prueba de `server.env`, ya corregido). Pruebas en `tests/test_updater.py`.

## Pase de temporada gratuito (punto 25 del bloque E, `SE_SEASON_PASS`)

El punto decía solo "Pase de temporada gratuito". El dueño eligió: temporadas por estación de Argentina, desafíos más puntos por jugar, recursos más unidades, y un botón dentro del juego.

- **Temporada:** la estación de Argentina (`seasons.season_of`, la misma del clima de la aldea): Pase de Verano (21/12), Otoño (21/3), Invierno (21/6) y Primavera (23/9). Días y semanas con la hora de Argentina (UTC−3). Una temporada nueva empieza de cero; lo no cobrado se pierde (la ventana dice cuánto falta para que termine).
- **Niveles:** 40, de 600 puntos cada uno. **Puntos por jugar** (`season_pass.EVENT_POINTS`): recolectar 2, isla de aventura ganada 25 (+10 por cada estrella de dificultad arriba de 1), saqueo ganado 20, ataque del Explorador ganado 25, duelo jugado 10 y ganado 30 más; hasta 300 por día. **Desafíos:** 3 diarios (150 a 200 puntos) y 3 semanales (500 a 600), sorteados con la fecha como semilla: los mismos para todos. Un saqueo o duelo informado dos veces cuenta una vez.
- **Premios** (`season_pass.reward_of`): oro, madera, comida o piedra en los niveles comunes (creciendo con el nivel); dinero cada 5 niveles (5, y 10 desde el 25); una unidad de la estación cada 10 niveles, a Regalos (`privateState.gifts`), de menor a mayor, la del 40 propia de la temporada. Todas tienen dibujo en el juego de PC y no son de celular. Verano: Guerrero egipcio, Momia, T-Rex de fuego, Dragoncito extremo de fuego. Otoño: Jinete de jabalí, Minotauro, Jinete de jabalí con hacha, Dragoncito extremo de roca. Invierno: Yeti, Yeti negro, Kong nevado, Dragoncito extremo de escarcha. Primavera: Arquero elfo, Tigre elfo, Ent, Caballero elfo imperial.
- **Dónde se guarda:** en la aldea (`privateState.seasonPass`), así se guarda y respalda con ella.
- **Cobrar con el juego abierto:** el juego tiene su propia copia del oro y los regalos. Como el Tesoro y los saqueos, cobrar cambia la versión de la aldea (`season_pass.revision`, parte de `village_revision`): la página pausa el juego y pide recargar; la ventana también muestra "Recargar la aldea".
- **Puntos desde el juego:** `command.py` (recolectar y ganar islas), `world.py` (ataques ganados del Explorador), las dos rutas de saqueo (página de rivales y ventana PvP) y los duelos (la misma escucha de resultados que los clanes, para los dos jugadores).
- **Ventana y botón:** botón "Pase" (escudo azul con estrella, `tools/make_season_pass_button.py`) que abre una ventana con el aspecto de la del clan: nivel, barra de progreso, días que faltan, pestaña Recompensas (cobrar uno o todos) y pestaña Desafíos (progreso, puntos y cuándo cambian).
- **Botones del juego en su propia columna:** el panel de íconos del juego (`GuiManager.createViralButtons`: `new IconPanel(100, SIDE_RIGHT, 200)`) muestra solo 2 íconos y no dibuja los demás: los lunes su cofre ocupaba un lugar y PvP no aparecía, y un tercer botón nunca se habría visto. Clan, PvP y Pase van ahora a un panel propio igual (`GuiManager.__seButtonPanel`, a la izquierda del del juego, para 3 íconos); la barra de zoom del juego queda libre.
- **Probado en la copia (5051):** los tres botones se ven; el Pase abre "Pase de Primavera 2026" con los 40 niveles y los desafíos; con 10 niveles cobrados de una vez, el juego avisó que la aldea cambió y, al recargar, tenía 4.500 de oro y 5 de dinero más, y el Arquero elfo en Regalos (6 regalos en lugar de 5). Pruebas en `tests/test_season_pass.py` y `tests/test_season_pass_web.py`.

### Pase de temporada: íconos de las recompensas

Pedido del dueño. Cada nivel de la ventana muestra la imagen de su premio (`templates/img/season_pass/*.png`, 64 × 64 transparentes, hechas por `tools/make_season_pass_icons.py`):

- **Oro, madera, comida y piedra:** las imágenes del propio juego en el SWF del cliente (bitmaps 156, 329, 782 y 783). Los símbolos `icoGoldMC`, `icoWoodMC`… de la barra de recursos son solo rectángulos grises de reemplazo que el juego llena al jugar, por eso se usan los bitmaps.
- **Dinero:** los billetes del juego (`CashMC`, formas vectoriales dibujadas con `tools/swf_raster.py`).
- **Unidades:** su dibujo en el mapa, de frente (lector del World Editor, `WorldEditor/sprites.py`); el Yeti negro, hecho solo de formas vectoriales, se dibuja con `swf_raster.py`.

El servidor agrega la dirección de la imagen a cada premio; una prueba revisa que existan las imágenes de los premios de las cuatro temporadas.

## Íconos del juego en HD (`SE_HD_ICONS`)

Pedido del dueño: "Aplica todos los iconos en HD dentro de todo el juego", después de ver una comparación de filtros contra IA (eligió la IA). Con su permiso se usó Real-ESRGAN portable (`realesrgan-ncnn-vulkan`, usa la placa de video; en `tools/realesrgan`, fuera de git).

- **Qué se agranda:** de las 365 imágenes del juego, las que se pueden cambiar sin riesgo (`swf_hd_icons.eligible_bitmaps`): no exportadas al código (ActionScript podría leer su tamaño), usadas por alguna forma y por ninguna forma animada (morph), y sin HD propio (Construir y la otra de `swf_hd_art`). De esas, los **íconos**: hasta 256 píxeles por lado (259); los fondos y ventanas grandes quedan como están.
- **Cómo:** `tools/make_hd_icons.py` agranda cada una 4× con el modelo anime de Real-ESRGAN y la reduce a exactamente **2×** (más nítido que agrandar 2× directo). 4× habría costado unos 116 MB de memoria en el juego; 2× unos 29 MB. Las imágenes traducidas (español y portugués) se agrandan desde su traducción (`config/hd_icons/<idioma>/`). Al armar el juego, `swf_hd_icons.apply_hd_icons` pone cada imagen HD con el mismo número y divide por 2 la escala de cada relleno que la usa: el dibujo ocupa lo mismo en pantalla. No toca el código del juego.
- **Transparencia:** se midió que Flash guarda tanto las imágenes sin pérdida como las JPEG3 con el color ya multiplicado por la transparencia; se deshace al leerlas (`WorldEditor/sprites.py`, también mejora los bordes en el World Editor y en los íconos del pase) y se rehace al guardarlas.
- **Peso:** guardadas sin pérdida, el juego pasaba de 4,1 a 14 MB; como JPEG3 (calidad 92, como la mayoría de las imágenes del juego) queda en 6,8 MB.
- **Error encontrado y corregido:** las formas de Flash pueden declarar rellenos nuevos en medio de su dibujo (StyleChangeRecord con NewStyles), no solo al principio. Al principio solo se ajustaban los del principio y el ícono del oro de la barra de recursos salía encimado con las piedras. Ahora se recorre el dibujo completo de las 1.347 formas (1.073 rellenos con imagen). `SE_HD_ICONS_SKIP` deja sin HD las imágenes que se le indiquen, para buscar una que falle.
- **Probado en la copia:** la barra de recursos (oro, madera, comida, piedra, dinero), los íconos del costado y el menú Construir se ven bien y más nítidos; el juego arma su película con HD en unos 5 s.

### Edificios, decoraciones y recursos del mapa en HD (`SE_HD_SPRITES`)

Pedido del dueño ("faltarían los recursos y demás cosas dentro del juego"). Los dibujos del mundo son 1.587 archivos aparte (`assets/buildingsprites`, 914 MB, 61.431 imágenes): 900 de edificios, decoraciones y recursos (5.529 imágenes, unas 5 horas de IA) y 669 de unidades (55.558 imágenes de animación, unas 35 horas). El dueño eligió **edificios y recursos primero**; las unidades quedan para después.

- `tools/make_hd_sprites.py` agranda las imágenes de cada objeto de tipo edificio igual que los íconos (Real-ESRGAN 4× y reducción exacta a 2×) y escribe el archivo de nuevo con `swf_hd_icons.replace_pictures` (mismos números, rellenos reescalados: nada se mueve). Las texturas de más de 1.024 píxeles por lado (los terrenos) quedan como están. Trabaja por tandas, saltea lo ya hecho (se puede cortar y volver a correr) y anota el avance en `assets_hd/progreso.txt`.
- Los archivos HD van a `assets_hd/buildingsprites`, **fuera de git** (son cientos de MB y se pueden regenerar). Con `SE_HD_SPRITES=on` el servidor entrega la versión HD de un dibujo cuando existe; si no, el original.

### HD apagado (resultado medido)

Probado en la copia con una pantalla de alta resolución simulada: el juego HD y los edificios HD se entregan y Ruffle dibuja a resolución completa, pero la diferencia a tamaño normal es mínima (unos 2 tonos sobre 255 en promedio) y Ruffle achica las imágenes grandes sin suavizarlas bien, lo que deja bordes inclinados algo serruchados. El dueño no vio cambios y eligió apagarlo: `SE_HD_ICONS=off` y `SE_HD_SPRITES=off` (el juego vuelve a 4,1 MB). La generación de edificios se detuvo (quedaron unos 75 en `assets_hd`, fuera de git); el código y las herramientas quedan por si se usan con pantallas grandes.

### HD prendido de nuevo

El dueño pidió dejarlos prendidos: `SE_HD_ICONS=on` y `SE_HD_SPRITES=on` en `server.env`, y se retomó la generación de los edificios (`tools/make_hd_sprites.py` sigue donde quedó; el servidor usa los que ya están hechos).

### Solo los recursos del mapa en HD (`SE_HD_SPRITES=recursos`)

El dueño vio HD en partes del HUD y pidió los **recursos** en HD, no los edificios por ahora. Eligió las tres clases de recursos: los del mapa, lo que salta al recolectar y los de las ventanas. Los dos últimos ya están en el juego principal y los cubren los íconos HD (`SE_HD_ICONS`). Para el mapa, `swf_hd_icons.resource_sprite_names`: la categoría "Recursos" del propio juego (subcategoría 12: molinos, cultivos, ranchos, minas de oro y piedra, árboles) más lo que da madera o piedra al recolectarlo (árboles y rocas del mapa), sin las Maravillas (también producen, pero son edificios): 66 dibujos. `tools/make_hd_sprites.py --recursos` los generó en unos 3 minutos. `SE_HD_SPRITES` acepta `off`, `recursos` (solo esos, aunque haya edificios HD ya hechos en `assets_hd`) y `on`/`todo` (todo lo hecho). La generación de los demás edificios quedó parada (unos 130 de 896 hechos).

## Punto 26 (HUD), etapas 1 y 2: burbujas de recolección y reloj con clima (`SE_HUD`)

El dueño mostró una captura de Empires Reborn (otra versión del juego) y eligió sus cuatro partes: burbujas de recolección, barra de recursos y perfil, reloj y clima, y botones y barra inferior. Se hacen con implementación propia y el arte del juego, sin copiar nada de ese sitio.

- **Burbujas de recolección:** ya son del juego original (`IsoElement.addIconoCollect`: la burbuja `IconCollect` con el ícono del recurso según `collect_type` y sin la mano). Aparecen sobre los edificios que terminaron de producir, y esos edificios necesitan unidades adentro (aldeanos en molinos, minas y aserraderos; animales en los ranchos): vacíos no producen. Los árboles, el oro y la piedra sueltos se recolectan solos (`Config.AUTO_COLLECT`) y no las muestran. Probado en la copia: con un rancho, minas y un aserradero con trabajadores, aparecieron las burbujas con bife y se recolectaron. No hizo falta cambiar nada.
- **Reloj y clima:** un recuadro sobre el juego, a la izquierda debajo de la barra de recursos, con un ícono propio (sol, luna, amanecer/atardecer, lluvia o nieve), la hora de Argentina y el clima en palabras (Soleado, Despejado, Amanecer, Atardecer, Lluvia, Nieve); la estación en el texto al pasar el mouse. Usa las mismas funciones que el día/noche y la lluvia/nieve (`game.js`), así que siempre coincide con lo que se ve; se actualiza cada 10 s y se ajusta al tamaño del juego. `SE_HUD=on` (de fábrica) lo muestra; necesita `SE_DAY_NIGHT=on`. Probado en la copia con la hora real (05:00 Lluvia, y llovía) y con `?hora=` y `?clima=`: 14:00 Soleado, 23:00 Nieve, 19:12 Atardecer.

## Punto 26 (HUD), etapa 3: barra de recursos y perfil (`SE_HUD`)

- **La página dibuja la barra y el juego le pasa los números.** Un parche del juego (`swf_hud.py`) agrega `seHudState()`, que devuelve el oro, la madera, la comida, la piedra, el dinero, el nivel, la experiencia y el nombre y la población que muestra el juego. La página (`game.js`) lo lee cada medio segundo. Así la barra cambia en vivo al recolectar, comprar o atacar: en la prueba, la comida pasó de 200.203.125 a 200.203.395 al tocar una burbuja y la barra se actualizó sola.
- **Se oculta la cinta original de arriba** (`seHudHide()`), con sus textos, su fondo, la estrella del nivel y la barra de experiencia. **El globo "mundo" queda del juego.** El nombre y la población estaban sobre la cinta, así que ahora los dibuja la página, a la derecha del globo, con el texto que el juego pone ahí (también el del vecino o el enemigo). El ocultado se repite cada 3 s por si un cambio de mapa vuelve a mostrar la cinta.
- **Diseño:** una fila arriba a la izquierda con el nivel en una moneda dorada y la barra de experiencia en porcentaje (los números exactos al pasar el mouse). Después van oro, madera, comida, piedra y dinero en píldoras azules con borde dorado, con los íconos originales del juego. Desde 100.000 se usa la forma corta ("200,1 M"); el número completo aparece al pasar el mouse. El número se pone verde si subió y naranja si bajó. El reloj y clima pasa a la segunda fila.
- **El "+" del dinero** hace lo mismo que el botón original (`seHudCash()` le manda la pulsación que espera, `MOUSE_DOWN`): abre el Tesoro.
- Todo va con `SE_HUD=on`. Si el parche falla, el juego conserva su cinta original.

## Pantalla completa en el navegador y zoom fluido (`SE_VIEW`)

Pedido del dueño: que el juego se vea en pantalla completa en el navegador, sin el zoom de la derecha, y con un zoom muy fluido tanto en la PC como en el celular.

- **El juego ocupa toda la ventana.** Antes era una imagen fija de 760×600 con franjas verdes a los costados. Ahora el escenario del juego mide lo mismo que su lugar en la página (Ruffle con `noScale`). Para que la interfaz no quede diminuta en pantallas grandes, la página hace el reproductor k veces más chico y lo agranda k veces con CSS; k es el factor que hace entrar 760×600. Así los botones tienen el mismo tamaño que antes y el lugar que sobra muestra más mapa. A Ruffle se le informa una pantalla k veces más densa (`devicePixelRatio`), así dibuja tantos píxeles como tiene la pantalla y la imagen se ve nítida, no estirada.
- **La interfaz se acomoda con el diseño de pantalla completa del propio juego** (`GuiManager.fullscreen`, el que usaba en Facebook): centra la barra de abajo y pega los botones a los bordes. La página lo pide cada vez que cambia el tamaño (`Base.__seFit`, `swf_view.py`), deshaciendo antes el anterior (`normalscreen`). El botón ☰ flota arriba a la izquierda y la barra de recursos arranca a su derecha. El nombre y la población siguen al globo, que el juego centra.
- **Sin el zoom de la derecha:** `__seFit` oculta `GuiManager.zoomSlider`.
- **Zoom fluido:** la página atrapa la rueda antes que Ruffle, así no corre el zoom a saltos del juego (`Base.zoomMap`, ×1,1 por paso). Después lleva el nivel hacia el pedido cuadro a cuadro con `Base.__seZoom`, que usa el modo rápido de `Base.setZoom` y deja quieto el punto del mapa bajo el puntero. Al terminar se vuelven a suavizar los edificios una sola vez y el nivel queda guardado (`GuiManager.setZoom`). Cada cuadro tarda unos 1,6 ms. En el celular, dos dedos acercan o alejan y arrastran el mapa en vivo (`__seMove` → `Base.moveMap`); un dedo sigue siendo el arrastre del juego. Se respetan los mismos bloqueos que el zoom del juego: tutorial, mapa bloqueado y colocando un edificio. Límites del juego: 0,15 a 1,4.
- **Las ventanas del juego quedan visibles:** con una ventana abierta (`PopupManager.popupLayer`), la barra, el reloj y el nombre se atenúan y dejan pasar los clics.
- Probado en la copia: PC 1280×860 (escenario 991×600), celular horizontal 844×390 (1298×600 a escala 0,65, nítido) y vertical 390×844 (760×1645), y el modo "Restaurar ventana" (760×600 dentro de la página). Si se cambia el tamaño con una ventana del juego abierta, esa ventana queda donde estaba hasta reabrirla, porque el juego centra cada ventana al abrirla.

## Punto 26 (HUD), etapa 4: nombres en la barra, Menú, Bono diario y "Más" (`SE_HUD`)

El dueño eligió tres partes de los botones al estilo Empires Reborn: nombres en la barra de abajo, "Menú" y "Bono diario", y un botón "Más". Descartó mover Clan, PvP y Pase a la barra.

- **Nombres en la barra de abajo**: Herramientas (cursor: Recolección rápida, Quitar, Multiherramienta), Juegos (la bola verde: Aldea, Dardos), Área (Elegir área), Mundo y Regalos. "Construir" ya trae el suyo. Salieron de los cartelitos y menús del propio juego. El juego le dice a la página dónde está cada botón (`Base.__hudButtons`, sus límites en el escenario con `getBounds`) cada medio segundo. La página escribe el nombre sobre el borde de abajo de cada botón, con contorno oscuro, así no hace falta agrandar la barra. Un nombre se oculta si su botón o la barra no se ven (por ejemplo, en un ataque).
- **Menú**: sobre el juego, el ☰ pasa a ser un botón redondo dorado "Menú" arriba a la derecha (abre el mismo panel de sonido, pantalla completa, etc.). Mientras el panel está abierto, la columna de la derecha se oculta para no taparlo.
- **Bono diario**: un cofre (dibujo propio) con la cuenta regresiva a la próxima recompensa diaria del Tesoro (`next_claim_at`, que el servidor le pasa a la página al abrir el juego). Cuando ya se puede cobrar, brilla y dice "¡Cobrar!". Lleva al Tesoro, igual que el "+" del dinero.
- **Más (+2)**: agrupa lo que se usa poco arriba a la derecha: el cofre "Premio" del juego (`_viralButtonPanel`) y su panel de opciones (`options_panel`: engranaje, música, sonido, pantalla completa, pausa). Cerrado, están ocultos. Abierto, el juego los muestra apilados debajo del botón, contra el borde derecho (`Base.__hudShow(nombre, visible, x, y)`, que solo acepta esas dos piezas). El estado se vuelve a aplicar cada 3 s por si un cambio de mapa las muestra de nuevo.
- La columna de la derecha baja sola si el nombre del imperio llega hasta ella (escenario angosto, modo "Restaurar ventana"). Con una ventana del juego abierta, los nombres y la columna se atenúan como la barra.
