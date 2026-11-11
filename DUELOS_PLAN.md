# Duelos PvP en vivo: plan (fase 0)

Rama: `duelos-en-vivo` (sale de `mi-servidor`, commit `c4bcd28`). En esta fase no se cambió código.

## 1. Qué hay hoy en el repositorio

Algunos archivos del pedido no existen en este repositorio:

| Pedido | Qué hay |
| --- | --- |
| `pvp.py` | Existe. Saqueos de Rivales resueltos en el servidor por fuerza; guarda en `instance/raids.sqlite3`. |
| `tournaments.py` | **No existe.** El servidor no implementa ningún servicio de torneos (`tournaments/*.php` responde 404). |
| `sessions.py` | Existe. Aldeas en memoria (`__villages`), guardadas en `saves/*.save.json`. |
| `gunicorn.conf.py` | **No existe y gunicorn no está instalado** (`requirements.txt`: Flask, jsonpatch, Werkzeug). El servidor arranca con `app.run(..., threaded=False)`: **atiende un pedido por vez**. |
| `trust.py` | **No existe.** La seguridad está en `auth.py` (sesión, CSRF, clave por aldea) y en `server.py` (`protect_access`). |

Avisos hoy: la página pregunta cada 15 s a `/village/events` (consulta periódica). Todas las mutaciones toman `village_lock` (un `RLock`).

## 2. Respuestas

### (a) ¿La batalla del cliente es determinista?

**No.** Y hacerla determinista no es viable con un esfuerzo razonable:

- **Azar sin semilla:** el código del juego llama a `Math.random()` unas **400 veces**. En combate: `IsoUnit`, `IsoFightingElement`, `IA`, las clases de dragones y decenas de "delegates" de unidades especiales. El `Math.random()` de AS3 no admite semilla.
- **Reloj real:**
  - El bucle es `Event.ENTER_FRAME → Base.UpdateGame`, o sea, un paso por cuadro dibujado. Los cuadros por segundo varían entre navegadores y bajan si la pestaña no está al frente.
  - El buscador de caminos `AStar.findPath` **corta la búsqueda por tiempo real** (`getTimer()` contra `CANCEL_TIME`): en una PC más lenta, el mismo pedido da otro camino.
  - En las clases de combate hay **114 `Timer`** (disparos demorados, reposicionamientos) y **135 animaciones `TweenLite`** basadas en tiempo.
- **Para hacerla determinista habría que:**
  - cambiar los 400 `Math.random()` por un generador con semilla;
  - pasar los 114 timers y 135 tweens a un reloj de cuadros fijo;
  - quitar el corte por tiempo del A*;
  - fijar el paso de la simulación.

  Basta un solo punto olvidado para que los dos clientes se separen y la diferencia crezca. Es la opción de mayor riesgo.

### (b) ¿Qué mapa usa la arena de torneos y cómo se elige?

- **De dónde sale:** cada tipo de torneo del config (`tournament_type`, 8 tipos) tiene `map_id`. El cliente lo lee en `TournamentManager.currentMap = currentTournamentDefinition.map_id`.
- **Qué mapa es:** los 8 tipos usan el **`100000040`**.
- **Ese mapa no existe:** no está en `villages/quests/` ni en el repositorio original de AcidCaos. El juego lo pediría como pide los mapas de aventura (`get_player_info.php` con `user=1000000xx`), pero sus datos nunca se publicaron.
- **Propuesta:**
  - crear un archivo de datos de arena vacía (`config/duels/arena.json`), con el mismo formato que los mapas de aventura;
  - el id y el archivo del mapa se leen de configuración (variable de entorno o ajuste del admin), con esa arena por defecto;
  - más adelante se reemplaza por el mapa del editor de mundo sin tocar código.
- **Cómo funcionaban los torneos originales:** de forma asíncrona. Tu ejército peleaba contra el del rival manejado por la IA del cliente (`TournamentIA`: formaciones y avance). Al final, el cliente informaba `attacker_won`, `attacker_points` y `victim_points` a `finish_tournament_match.php`. El resultado lo decidía el cliente, así que se podía falsear.

### (c) ¿Cómo se calcula hoy el ranked y dónde se guardaría un duelo?

- **No hay ranked.** Lo más parecido es la "Clasificación" de Rivales (`pvp.py`): ordena por victorias y recursos saqueados en los saqueos, guardados en `instance/raids.sqlite3`.
- **Para los duelos propongo una base nueva, `instance/duels.sqlite3`**, con el mismo patrón que `raids.sqlite3` y `treasury.sqlite3` (SQLite, transacciones cortas). Tendría:
  - tabla de retos;
  - tabla de duelos con los resultados que informa cada cliente y el resultado aceptado;
  - tabla de puntuación del ranked;
  - tabla de revisiones para los resultados que no coinciden.
- **Los ejércitos no se tocan:** ningún duelo cambia las partidas guardadas.

## 3. Formas de sincronizar la batalla

| | A. Lockstep (los dos simulan) | B. Anfitrión simula y reparte | C. El servidor simula |
| --- | --- | --- | --- |
| Cómo funciona | Los dos clientes corren la misma simulación con semilla y paso fijos; solo se intercambian las órdenes. | El cliente de un jugador corre el motor real y manda el estado (posición, vida, animación) por el servidor; el otro cliente solo dibuja y envía sus órdenes. | El servidor corre la batalla a paso fijo (por ejemplo 10 por segundo) con las estadísticas del config (ataque, defensa, vida, alcance, intervalo, velocidad); los dos clientes dibujan el mismo estado y envían órdenes. |
| Desfase visible | Ninguno si es determinista; **total** si se separan, y aquí se separarían (ver 2a). | El invitado ve con ~100-200 ms de retraso y sus órdenes tardan un viaje de ida y vuelta. | Los dos ven el mismo estado con el mismo retraso (~100 ms de búfer); no hay versiones distintas. |
| Trampas | Difíciles si es determinista (solo viajan órdenes). | **Fáciles para el anfitrión**: un cliente modificado decide la batalla. Solo se mitiga con controles de verosimilitud. | **No se puede falsear**: el resultado lo calcula el servidor. |
| Fidelidad al juego | Total. | Total. | Parcial: las habilidades especiales (cientos de "delegates") no se replican. Las unidades especiales se excluirían de los duelos, como el juego ya hace en torneos (`TOURNAMENT_UNITS_NOT_ALLOWED`), o pelearían como unidades básicas. |
| Trabajo en el cliente | Muy alto: cambiar cientos de puntos del motor. | Alto: modo "marioneta" (el invitado no simula y aplica el estado recibido) y captura de órdenes. | Alto: el mismo modo marioneta, para los dos clientes. |
| Trabajo en el servidor | Bajo (reenviar órdenes). | Medio (reenviar estado, controles). | Alto (motor de combate en Python, bucle de simulación). |
| Riesgo | **Muy alto**. | Alto (trampas del anfitrión). | Medio. |
| Estimación | 6-10 semanas, sin garantía. | 3-5 semanas. | 4-6 semanas. |

**Recomendación: C (el servidor simula).** Es la única que cumple las dos prioridades a la vez: los dos jugadores ven el mismo estado y nadie puede falsear el resultado, porque lo calcula el servidor. El costo es la fidelidad, porque las unidades con habilidades especiales no pelean igual que en una batalla normal. Propongo empezar con unidades sin habilidad especial y una regla de duelo explícita (qué unidades entran y cuántas, como el límite de 10 "complejas" de los torneos). Con C, la regla de la fase 3 ("los dos clientes informan y deben coincidir") queda como control adicional: el resultado oficial lo da el servidor, y si los clientes informan otra cosa se registra para revisión.

**Cómo dibuja el cliente (C y B):**
- Se reutilizan la arena y las unidades del propio juego.
- Las unidades del duelo no corren su IA: cada cuadro toman posición, dirección, vida y animación del último estado recibido, interpolando entre dos estados para que el movimiento sea suave.
- Las órdenes de selección y movimiento del jugador se capturan y se envían al servidor en vez de ejecutarse.
- Esto se agrega al código del juego con la misma técnica que el área de ataque (`swf_abc.py`). Solo se activa en modo duelo.

## 4. Canal de comunicación

| | Consulta periódica | Eventos del servidor (SSE) | WebSockets |
| --- | --- | --- | --- |
| Latencia | La del intervalo (con 15 s es inservible; con 100 ms, mucha carga). | Baja hacia el cliente; las órdenes van por POST. | La más baja, en los dos sentidos. |
| Con el servidor actual (`threaded=False`) | Funciona. | **Bloquea todo el servidor**: una conexión abierta ocupa el único hilo. | Igual que SSE: necesita hilos. |
| Requisitos | Ninguno. | Servidor con hilos (Flask `threaded=True` o gunicorn `--threads`). | Servidor con hilos más un paquete: `flask-sock` (que trae `simple-websocket`). |
| Railway | Sí. | Sí (cuidar el corte de conexiones inactivas con un latido). | Sí, soporta WebSockets. |

**Recomendación: WebSockets**, con un solo proceso y varios hilos. Las aldeas siguen en memoria y protegidas por `village_lock`, igual que hoy.

- **Cómo llega al juego:** el SWF no habla WebSocket. La conexión la abre el JavaScript de la página (`game.js`) y se pasa al juego con `ExternalInterface`, que Ruffle soporta.
- **Plan B sin paquete nuevo:** SSE para recibir el estado y POST para mandar órdenes, también con hilos.
- Las dos opciones necesitan que me apruebes cosas que menciono en la sección 5.

## 5. Decisiones que necesito antes de la fase 1

1. **Paquete nuevo:** `flask-sock` (y su dependencia `simple-websocket`), para WebSockets (sección 4). ¿Lo instalo o voy con SSE sin paquetes?
2. **Hilos en el servidor:** hoy `app.run(threaded=False)` atiende un pedido por vez, y gunicorn no está. Los avisos en vivo necesitan hilos. Propongo `threaded=True` solo con `SE_DUELS` encendido, y con `SE_DUELS=off` el servidor queda exactamente como hoy. ¿Lo apruebas? ¿O preparo también un `gunicorn.conf.py` con `workers=1` e hilos para Railway, que agregaría gunicorn como paquete?
3. **Forma de sincronizar:** C, recomendada (servidor simula, sin trampas, fidelidad parcial), o B (motor real del juego, pero el anfitrión podría hacer trampa).
4. **Qué unidades entran en un duelo** (si es C): solo las que no tienen habilidad especial, o todas peleando como básicas. ¿Y un límite de unidades por ejército?
5. **El ranked desde nivel 25:** ¿cuenta el nivel de la aldea principal o de cualquier isla? ¿Y se puntúa con Elo o por victorias? (Está en tus "Decisiones abiertas".)
6. **El mapa:** la arena `100000040` no existe. ¿La creo como un mapa vacío del mismo tamaño que las aventuras, con dos zonas de inicio enfrentadas?

## 6. Encendido y apagado

Todo lo nuevo quedaría detrás de `SE_DUELS`, que viene apagado por defecto. Con `SE_DUELS=off` el servidor:
- no registra las rutas de duelos;
- no agrega nada al juego;
- no abre hilos ni conexiones nuevas.

Un test comparará el juego servido y las rutas con y sin la variable.
