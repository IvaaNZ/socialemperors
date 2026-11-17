# Aventuras en Solitario o con el Clan (puntos 28, 29 y 30): plan

Decisiones del dueño (2026-11-17):

- Antes de zarpar a una isla de aventura se elige **Solitario** o **Clan**.
- **Solitario:** como hoy, con la ventana "Elige tu equipo" de 20 casillas.
- **Clan:** hasta **3 miembros del mismo clan** juegan **en vivo** la misma isla; cada uno lleva **hasta 10 unidades** de su aldea, elegidas con la misma ventana del juego.
- Forma de sincronizar: **el anfitrión simula todo**. El juego del que arma la incursión corre la batalla completa con las unidades de los tres; los otros dos ven lo mismo y mandan órdenes a sus propias unidades.
- Recompensas (punto 30): se reparten por igual; en Clan, 30% menos; en Solitario, 20% más. Dificultad igual o mayor.
- Prestigio del clan (punto 29): 5 por misión en Solitario, 15 por misión en grupo.

## Por qué "anfitrión simula"

El juego no es determinista (azar sin semilla, relojes reales, el buscador de caminos corta por tiempo: ver DUELOS_PLAN.md), así que dos navegadores no pueden simular la misma batalla por separado. Uno solo la simula y los demás la dibujan. Costos conocidos: los invitados ven con algo de retraso (~100-300 ms), el anfitrión podría hacer trampa (se mitiga con controles de verosimilitud en el servidor) y Ruffle va más lento con el triple de unidades (el modo rendimiento y la imagen fluida ayudan).

## Fases

1. **Elección y sala (punto 28).** Al tocar una isla, la página pregunta Solitario o Clan. Solitario sigue el camino del juego. Clan abre una sala: el anfitrión invita a miembros de su clan conectados, cada uno acepta y elige hasta 10 unidades con "Elige tu equipo" (límite 10), y todos ven quién está listo. El servidor guarda la sala (`instance/coop.sqlite3`) y avisa en vivo por el WebSocket que ya usan los duelos.
2. **El anfitrión pelea con las tres tropas.** Al zarpar, el juego del anfitrión carga la isla y suma las unidades de los invitados (con el dueño marcado). Los invitados ven una pantalla de espera con el estado.
3. **Los invitados ven la batalla.** El anfitrión manda el estado (posición, vida, animación, muertes) varias veces por segundo; el juego de cada invitado carga la misma isla en modo "marioneta": no simula, dibuja lo que recibe, interpolando.
4. **Los invitados mandan órdenes.** Cada invitado selecciona solo sus unidades y les da órdenes de mover y atacar; viajan al anfitrión, que las aplica.
5. **Fin, recompensas y prestigio (puntos 29 y 30).** El servidor reparte recursos y XP (−30% en Clan, +20% en Solitario), descuenta las unidades perdidas de la aldea de cada dueño, suma prestigio al clan y revisa que el resultado sea verosímil.

Cada fase queda detrás de `SE_COOP` (apagado por defecto hasta que la fase 3 funcione) y se prueba en la copia antes de seguir.
