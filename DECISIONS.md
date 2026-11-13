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

