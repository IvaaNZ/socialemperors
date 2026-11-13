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
