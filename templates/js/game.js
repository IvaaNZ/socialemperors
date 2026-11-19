/* Local browser player. Runtime binaries and game requests stay on this origin. */
(() => {
    "use strict";

    const config = JSON.parse(document.getElementById("game-config").textContent);
    // Portal wording comes from the server in the active language; Portuguese is the source text.
    const texts = config.texts && typeof config.texts === "object" ? config.texts : {};
    const t = (text, values = {}) => Object.entries(values).reduce(
        (result, [name, value]) => result.split(`{${name}}`).join(String(value)),
        typeof texts[text] === "string" ? texts[text] : text,
    );
    // The public scheme, host and port belong to the browser. A TLS proxy may
    // forward HTTP to Flask, so its absolute URL can otherwise cause mixed content.
    const base = new URL(config.baseUrl, window.location.href);
    const runtimePath = new URL("vendor/ruffle/", base).href;
    const staticPath = new URL("default01.static.socialpointgames.com/static/socialempires/", base).href;
    const dynamicPath = new URL("dynamic.flash1.dev.socialpoint.es/appsfb/socialempiresdev/srvempires/", base).href;
    const container = document.getElementById("game-player");
    const overlay = document.getElementById("game-loading");
    const title = document.getElementById("loading-title");
    const message = document.getElementById("loading-message");
    const status = document.getElementById("game-status");
    const retry = document.getElementById("retry-button");
    const fullscreen = document.getElementById("fullscreen-button");
    const expand = document.getElementById("expand-button");
    const shell = document.getElementById("vila");
    const volume = document.getElementById("game-volume");
    const volumeValue = document.getElementById("volume-value");
    const mute = document.getElementById("mute-button");
    const audioStatus = document.getElementById("audio-status");
    const controlsDock = document.getElementById("controls-dock");
    const controlsToggle = document.getElementById("controls-toggle");
    const controlsPanel = document.getElementById("controls-panel");
    const villageUpdate = document.getElementById("village-update");
    const soundHint = document.getElementById("sound-hint");
    const weatherLayer = document.getElementById("weather-layer");
    const preferenceKey = "socialempires.player";
    let player;
    let loadingTimer;
    let expanded = true;
    let controlsActivated = false;
    let revealOnFocus = true;
    let pointerInDock = false;
    let hideControlsTimer;
    let hoverControlsTimer;
    let villageEventsTimer;
    let villageEventsPending = false;
    let villageChanged = false;
    const preferences = { volume: 100, muted: false, sharp: false, perf: true };

    try {
        const saved = JSON.parse(localStorage.getItem(preferenceKey));
        if (saved && typeof saved === "object") {
            if (Number.isFinite(saved.volume) && saved.volume >= 0 && saved.volume <= 100) {
                preferences.volume = Math.round(saved.volume);
            }
            preferences.muted = saved.muted === true;
            preferences.sharp = saved.sharp === true;
            preferences.perf = saved.perf !== false;
        }
    } catch {
        // Playing and changing controls still work when browser storage is blocked.
    }

    function savePreferences() {
        try {
            localStorage.setItem(preferenceKey, JSON.stringify(preferences));
        } catch {
            // Preferences apply for this visit even without persistent storage.
        }
    }

    function pauseUpdatedVillage() {
        if (!player) return;
        try {
            const api = player.ruffle();
            if (typeof api.pause === "function") api.pause();
        } catch {
            // The reload notice remains available if a runtime cannot pause yet.
        }
    }

    async function checkVillageEvents() {
        if (document.visibilityState !== "visible" || villageEventsPending || villageChanged) return;
        villageEventsPending = true;
        try {
            const response = await fetch(config.eventsUrl, {
                credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" },
            });
            if (!response.ok) return;
            const events = await response.json();
            if (!events || typeof events.revision !== "string" || events.revision === config.raidRevision) return;
            villageChanged = true;
            clearInterval(villageEventsTimer);
            pauseUpdatedVillage();
            villageUpdate.hidden = false;
            controlsToggle.classList.add("has-update");
            controlsToggle.title = t("Sua vila foi atualizada. Abra os controles para carregar as alterações.");
            controlsToggle.setAttribute("aria-label", t("Controles: há uma atualização da vila"));
        } catch {
            // An unavailable update check must not interrupt the running game.
        } finally {
            villageEventsPending = false;
        }
    }

    function scheduleVillageEvents(checkNow = false) {
        clearInterval(villageEventsTimer);
        if (document.visibilityState !== "visible" || villageChanged) return;
        if (checkNow) checkVillageEvents();
        villageEventsTimer = setInterval(checkVillageEvents, 15000);
    }

    if (typeof config.eventsUrl === "string" && typeof config.raidRevision === "string") {
        scheduleVillageEvents();
        document.addEventListener("visibilitychange", () => scheduleVillageEvents(true));
    }

    function applyAudio() {
        const silent = preferences.muted || preferences.volume === 0;
        volume.value = String(preferences.volume);
        volume.setAttribute("aria-valuetext", `${preferences.volume}%${silent ? ", sem som" : ""}`);
        volumeValue.value = `${preferences.volume}%`;
        mute.textContent = silent ? t("Ativar som") : t("Silenciar");
        mute.setAttribute("aria-pressed", String(silent));
        if (player) player.ruffle().volume = silent ? 0 : preferences.volume / 100;
    }

    // Browsers keep a page silent until the player touches it: until then Ruffle starts the game muted and
    // only shows a small speaker. The hint asks for that first touch on the game, where Ruffle turns the sound on;
    // it lets the touch through and goes away with it (SE_SOUND_FIX).
    function showSoundHint() {
        const activation = navigator.userActivation;
        if (!config.soundHint || !soundHint || !activation || activation.hasBeenActive) return;
        if (preferences.muted || preferences.volume === 0) return;
        soundHint.textContent = t("Toque no jogo para ativar o som");
        soundHint.hidden = false;
        const hide = () => {
            soundHint.hidden = true;
            container.removeEventListener("pointerdown", hide, true);
            document.removeEventListener("keydown", hide, true);
        };
        container.addEventListener("pointerdown", hide, true);
        document.addEventListener("keydown", hide, true);
    }

    // Updates (SE_UPDATE_NOTICE): every start of the server has its own build. When /version answers another one,
    // the server was updated: a notice asks to restart and the page reloads by itself after 10 seconds, so nobody
    // keeps playing against an old server. The game sends what the player did every few seconds (SE_QUICK_SAVE);
    // the Restart button waits that long before reloading, so the last actions are saved too.
    const UPDATE_SECONDS = 10;
    const UPDATE_CHECK_MS = 5000;
    let updateShown = false;

    function watchServerVersion() {
        if (!config.updateNotice || !config.build || !config.versionUrl) return;
        const check = async () => {
            if (updateShown) return;
            try {
                const response = await fetch(config.versionUrl, { credentials: "same-origin", cache: "no-store" });
                if (!response.ok) return;
                const answer = await response.json();
                if (answer && typeof answer.build === "string" && answer.build && answer.build !== config.build) {
                    showUpdateNotice();
                }
            } catch {
                // While the server restarts nothing answers: try again on the next check.
            }
        };
        setInterval(check, UPDATE_CHECK_MS);
        document.addEventListener("visibilitychange", check);
    }

    function showUpdateNotice() {
        const notice = document.getElementById("update-notice");
        const restart = document.getElementById("update-restart");
        const countdown = document.getElementById("update-countdown");
        if (!notice || updateShown) return;
        updateShown = true;
        notice.hidden = false;
        restart.focus();
        const savingMs = (Number(config.pushTime) || 3) * 1000 + 500;
        let left = UPDATE_SECONDS;
        let reloading = false;
        const reload = (delay) => {
            if (reloading) return;
            reloading = true;
            clearInterval(timer);
            restart.disabled = true;
            countdown.textContent = t("Salvando seu progresso…");
            setTimeout(() => window.location.reload(), delay);
        };
        const tick = () => {
            countdown.textContent = t("Reiniciando em {seconds} s", { seconds: left });
            if (left <= 0) reload(0);
            left -= 1;
        };
        const timer = setInterval(tick, 1000);
        tick();
        restart.addEventListener("click", () => reload(Math.min(savingMs, left * 1000)));
    }

    // Point 23 (SE_DAY_NIGHT): the village follows Argentina's hour. The game tints only its map layer
    // (Base.__setDayLight, swf_daylight.py); rain or snow falls now and then by season, drawn over the game.
    // ?hora=22.5 and ?clima=lluvia|nieve|despejado on the page's address show a given hour or weather.
    const ARGENTINA = "America/Argentina/Buenos_Aires";
    const NIGHT = [0.5, 0.55, 0.78];
    const DUSK = [0.95, 0.72, 0.62];
    const pageParams = new URLSearchParams(location.search);

    function argentinaNow() {
        const parts = Object.fromEntries(new Intl.DateTimeFormat("en-GB", {
            timeZone: ARGENTINA, year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric",
            hourCycle: "h23",
        }).formatToParts(new Date()).map(part => [part.type, Number(part.value)]));
        const forced = Number.parseFloat(pageParams.get("hora"));
        const hour = Number.isFinite(forced) ? forced : parts.hour + parts.minute / 60;
        return { hour: ((hour % 24) + 24) % 24, month: parts.month, day: parts.day, year: parts.year };
    }

    const mix = (from, to, amount) => from.map((value, index) => value + (to[index] - value) * amount);

    function lightAt(hour) {
        const day = [1, 1, 1];
        if (hour < 5.5 || hour >= 20.5) return NIGHT;
        if (hour < 6.5) return mix(NIGHT, DUSK, hour - 5.5);          // dawn
        if (hour < 7.5) return mix(DUSK, day, hour - 6.5);
        if (hour < 18.5) return day;
        if (hour < 19.5) return mix(day, DUSK, hour - 18.5);          // dusk
        return mix(DUSK, NIGHT, hour - 19.5);
    }

    // Argentina's seasons (seasons.py): summer from 21 Dec, autumn 21 Mar, winter 21 Jun, spring 23 Sep.
    function seasonOf(month, day) {
        const date = month * 100 + day;
        if (date >= 1221 || date < 321) return "summer";
        if (date < 621) return "autumn";
        if (date < 923) return "winter";
        return "spring";
    }

    const WEATHER_CHANCE = { summer: ["rain", 0.06], autumn: ["rain", 0.3], winter: ["snow", 0.35], spring: ["rain", 0.15] };

    function weatherNow(clock) {
        const forced = pageParams.get("clima");
        if (forced === "lluvia") return "rain";
        if (forced === "nieve") return "snow";
        if (forced === "despejado") return "";
        const [kind, chance] = WEATHER_CHANCE[seasonOf(clock.month, clock.day)];
        // The same for every player in the same hour: a small hash of the date and the hour.
        let hash = clock.year * 1000003 + clock.month * 10007 + clock.day * 101 + Math.floor(clock.hour);
        hash = Math.imul(hash ^ (hash >>> 15), 2246822507) >>> 0;
        hash = Math.imul(hash ^ (hash >>> 13), 3266489909) >>> 0;
        return (hash % 1000) / 1000 < chance ? kind : "";
    }

    let weatherKind = "";
    let particles = [];
    let weatherFrame = 0;

    function drawWeather() {
        weatherFrame = 0;
        if (!weatherKind || !weatherLayer) return;
        // Only over the game itself: the stage is wider than the movie in the expanded and fullscreen views.
        const stage = weatherLayer.parentElement.getBoundingClientRect();
        const box = container.getBoundingClientRect();
        weatherLayer.style.left = `${box.left - stage.left}px`;
        weatherLayer.style.top = `${box.top - stage.top}px`;
        weatherLayer.style.width = `${box.width}px`;
        weatherLayer.style.height = `${box.height}px`;
        const width = Math.max(1, Math.round(box.width));
        const height = Math.max(1, Math.round(box.height));
        if (weatherLayer.width !== width || weatherLayer.height !== height) {
            weatherLayer.width = width;
            weatherLayer.height = height;
        }
        const context = weatherLayer.getContext("2d");
        context.clearRect(0, 0, width, height);
        const snow = weatherKind === "snow";
        const count = snow ? 110 : 160;
        while (particles.length < count) {
            particles.push({ x: Math.random(), y: Math.random(), speed: 0.5 + Math.random(), size: 0.5 + Math.random() });
        }
        context.strokeStyle = "rgba(200, 220, 255, 0.6)";
        context.fillStyle = "rgba(255, 255, 255, 0.85)";
        context.lineWidth = 1.5;
        for (const drop of particles) {
            if (snow) {
                drop.y += 0.0012 * drop.speed;
                drop.x += 0.0004 * Math.sin(drop.y * 20 + drop.size * 6);
                context.beginPath();
                context.arc(drop.x * width, drop.y * height, 1.2 + drop.size * 1.6, 0, Math.PI * 2);
                context.fill();
            } else {
                drop.y += 0.018 * drop.speed;
                drop.x += 0.003 * drop.speed;
                context.beginPath();
                context.moveTo(drop.x * width, drop.y * height);
                context.lineTo((drop.x - 0.004) * width, drop.y * height - 10 - drop.size * 8);
                context.stroke();
            }
            if (drop.y > 1.05 || drop.x > 1.05 || drop.x < -0.05) {
                drop.y = -0.05;
                drop.x = Math.random();
            }
        }
        weatherFrame = requestAnimationFrame(drawWeather);
    }

    function setWeather(kind) {
        if (!weatherLayer || kind === weatherKind) return;
        weatherKind = kind;
        particles = [];
        weatherLayer.hidden = !kind;
        if (weatherFrame) cancelAnimationFrame(weatherFrame);
        weatherFrame = 0;
        if (kind) weatherFrame = requestAnimationFrame(drawWeather);
    }

    // SE_VIEW: the game's stage fills its place on the page (the whole tab when expanded) instead of a 760 x 600
    // picture with bands at its sides. Ruffle draws the stage without scaling it ("noScale"); the page makes the
    // player 1/k of its place and scales it by k with CSS, k fitting 760 x 600 in it, so the interface keeps its
    // size and the rest of the room shows more map. The game lays its interface out for that size with its own
    // full-screen layout (Base.__seFit, swf_view.py). Ruffle is told the screen is k times denser
    // (devicePixelRatio), so it draws as many pixels as the screen has and the picture stays sharp.
    const fullView = Boolean(config.fullView);
    let viewScale = 1;
    let fittedSize = "";
    let stageWidth = 760;  // the game's stage, in its own pixels
    let stageHeight = 600;
    const realPixelRatio = (() => {
        const own = Object.getOwnPropertyDescriptor(window, "devicePixelRatio");
        const inherited = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(window), "devicePixelRatio")
            || Object.getOwnPropertyDescriptor(Window.prototype, "devicePixelRatio");
        const descriptor = own && own.get ? own : inherited;
        if (descriptor && descriptor.get) return () => descriptor.get.call(window) || 1;
        const fixed = window.devicePixelRatio || 1;
        return () => fixed;
    })();

    // How many pixels Ruffle draws. Sharp: as many as the screen has. Fluid (the default): at most a 1366 x 768
    // screen's, and never fewer than the stage's own; the browser enlarges the picture. Drawing is shared with the
    // game's own work on one core and, with an integrated graphics card, measured on a 1920 x 1080 screen: 12
    // frames a second sharp, 19 fluid. A phone drew up to 3 million pixels.
    const FLUID_PIXELS = 1366 * 768;

    function drawRatio() {
        const sharp = realPixelRatio() * viewScale;
        if (preferences.sharp || !player) return sharp;
        const stagePixels = Math.max(1, player.clientWidth * player.clientHeight);
        return Math.min(sharp, Math.max(1, Math.sqrt(FLUID_PIXELS / stagePixels)));
    }

    function overlayScale(box) {
        return fullView ? viewScale : Math.max(0.6, box.width / 760);
    }

    // A phone held upright: the game's 760 pixels fill the width, so everything is drawn at half size or less. The
    // page's bar, clock, empire's name and right column are drawn bigger (the bar in two rows), and so are the
    // game's globe, Clan column and spell book (layoutPieces); the bottom bar already fills the width.
    const TALL_HUD = 1.45;

    function isTall() {
        return fullView && viewReady && container.clientHeight > container.clientWidth * 1.15;
    }

    function hudScale(box) {
        const scale = overlayScale(box);
        return isTall() ? Math.min(1, scale * TALL_HUD) : scale;
    }

    // The page's overlays start right of the menu button when the game reaches the tab's left edge.
    function overlayLeft(box, stage, scale) {
        return box.left - stage.left + 6 * scale;
    }

    // While the game loads, its loading screen is a 760 x 600 picture drawn at the stage's top left corner: the
    // stage stays 760 x 600, centred, until the village is ready (viewReady), and then fills the place.
    let viewReady = false;

    function sizeView() {
        if (!fullView || !player) return;
        const width = Math.max(1, container.clientWidth);
        const height = Math.max(1, container.clientHeight);
        viewScale = Math.min(width / 760, height / 600);
        const stageWidthPx = viewReady ? width / viewScale : 760;
        const stageHeightPx = viewReady ? height / viewScale : 600;
        player.style.width = `${stageWidthPx}px`;
        player.style.height = `${stageHeightPx}px`;
        player.style.left = `${(width - stageWidthPx * viewScale) / 2}px`;
        player.style.top = `${(height - stageHeightPx * viewScale) / 2}px`;
        player.style.transform = `scale(${viewScale})`;
        container.classList.toggle("is-loading", !viewReady);
        placeHud();
        placeClock();
    }

    function viewState() {
        try {
            return player && typeof player.seView === "function" ? player.seView() : null;
        } catch (error) {
            return null;
        }
    }

    function fitView() {
        const state = viewState();
        if (!state || !state.sw) return;
        if (!viewReady) {
            // Ready: the village is up (the player's numbers arrive, or with SE_HUD off, the view's bridge answers).
            if (config.hudBar && !hudShown) return;
            viewReady = true;
            sizeView();
            return;  // the next round lays the interface out for the new size
        }
        const size = `${state.sw}x${state.sh}`;
        if (size === fittedSize) return;
        try {
            player.seFit(!fittedSize);  // the first time, the map also centres on the buildings
            if (fittedSize) {
                // The game's open windows were centred on the old size: they move by half the change.
                try {
                    player.seShift((state.sw - stageWidth) / 2, (state.sh - stageHeight) / 2);
                } catch (error) {
                    // a game without the bridge: its windows stay
                }
            }
            fittedSize = size;
            stageWidth = state.sw;
            stageHeight = state.sh;
            placeHud();
        } catch (error) {
            // the game is loading or changing maps: the next round lays it out
        }
    }

    // The map zooms smoothly: the page eases the zoom toward where the wheel or the fingers ask, frame by frame
    // (Base.__seZoom, fast), keeping the map point under the pointer in place, and lets the game re-smooth the
    // buildings once at the end.
    const zoomMotion = { current: 0, target: 0, x: 0, y: 0, frame: 0, min: 0.15, max: 1.4 };

    function stagePoint(clientX, clientY) {
        const box = player.getBoundingClientRect();
        return { x: (clientX - box.left) / viewScale, y: (clientY - box.top) / viewScale };
    }

    function zoomStart() {
        if (zoomMotion.frame) return true;
        const state = viewState();
        if (!state || !state.zoom) return false;
        zoomMotion.current = zoomMotion.target = state.zoom;
        zoomMotion.min = state.zMin || 0.15;
        zoomMotion.max = state.zMax || 1.4;
        return true;
    }

    function zoomCall(fast) {
        try {
            player.seZoom(zoomMotion.current, zoomMotion.x, zoomMotion.y, fast);
        } catch (error) {
            // the game is busy: the next frame tries again
        }
    }

    function zoomStep() {
        const gap = zoomMotion.target - zoomMotion.current;
        if (Math.abs(gap) < 0.002) {
            zoomMotion.current = zoomMotion.target;
            zoomMotion.frame = 0;
            zoomCall(false);
            return;
        }
        zoomMotion.current += gap * 0.22;
        zoomCall(true);
        zoomMotion.frame = requestAnimationFrame(zoomStep);
    }

    function zoomTo(target, x, y) {
        zoomMotion.target = Math.min(zoomMotion.max, Math.max(zoomMotion.min, target));
        zoomMotion.x = x;
        zoomMotion.y = y;
        if (!zoomMotion.frame) zoomMotion.frame = requestAnimationFrame(zoomStep);
    }

    function startZoom() {
        // The wheel: caught before Ruffle, so the game's own step zoom (Base.zoomMap) does not run as well.
        container.addEventListener("wheel", (event) => {
            if (!player || !zoomStart()) return;
            event.preventDefault();
            event.stopPropagation();
            const lines = event.deltaMode === 1 ? 33 : event.deltaMode === 2 ? 400 : 1;
            const delta = Math.max(-300, Math.min(300, event.deltaY * lines));
            const point = stagePoint(event.clientX, event.clientY);
            zoomTo(zoomMotion.target * Math.exp(-delta * 0.0016), point.x, point.y);
        }, { capture: true, passive: false });

        // Two fingers: pinch to zoom and drag to move, live (no easing). One finger stays the game's own drag.
        const touches = new Map();
        let pinch = null;
        const centre = () => {
            const [a, b] = [...touches.values()];
            return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, distance: Math.hypot(a.x - b.x, a.y - b.y) };
        };
        const swallow = (event) => {
            event.preventDefault();
            event.stopPropagation();
        };
        container.addEventListener("pointerdown", (event) => {
            if (event.pointerType !== "touch") return;
            touches.set(event.pointerId, { x: event.clientX, y: event.clientY });
            if (touches.size === 2 && zoomStart()) {
                if (zoomMotion.frame) cancelAnimationFrame(zoomMotion.frame);
                zoomMotion.frame = 0;
                const c = centre();
                pinch = { distance: Math.max(1, c.distance), zoom: zoomMotion.current, last: stagePoint(c.x, c.y) };
                swallow(event);
            } else if (touches.size > 2) {
                swallow(event);
            }
        }, { capture: true, passive: false });
        container.addEventListener("pointermove", (event) => {
            if (!touches.has(event.pointerId)) return;
            touches.set(event.pointerId, { x: event.clientX, y: event.clientY });
            if (!pinch || touches.size < 2) return;
            swallow(event);
            const c = centre();
            const point = stagePoint(c.x, c.y);
            try {
                player.seMove(point.x - pinch.last.x, point.y - pinch.last.y);
            } catch (error) {
                // the game is busy
            }
            pinch.last = point;
            zoomMotion.current = Math.min(zoomMotion.max, Math.max(zoomMotion.min, pinch.zoom * c.distance / pinch.distance));
            zoomMotion.target = zoomMotion.current;
            zoomMotion.x = point.x;
            zoomMotion.y = point.y;
            zoomCall(true);
        }, { capture: true, passive: false });
        const lift = (event) => {
            if (!touches.has(event.pointerId)) return;
            touches.delete(event.pointerId);
            if (pinch && touches.size < 2) {
                pinch = null;
                zoomCall(false);  // the end of the pinch: the buildings are re-smoothed once
            }
        };
        container.addEventListener("pointerup", lift, true);
        container.addEventListener("pointercancel", lift, true);
        // Safari's own page zoom on a pinch.
        for (const name of ["gesturestart", "gesturechange"]) container.addEventListener(name, swallow, { passive: false });
    }

    function startView() {
        if (!fullView) return;
        container.classList.add("is-view");
        shell.classList.add("view-full");
        Object.defineProperty(window, "devicePixelRatio", { configurable: true, get: drawRatio });
        sizeView();
        new ResizeObserver(() => sizeView()).observe(container);
        setInterval(fitView, 300);
        startZoom();
    }

    // Point 26 (SE_HUD): a small clock with the village's hour and weather, the same ones the game shows (the
    // day and night tint and the rain or snow above), with the season in its tooltip. Own drawings for its icon.
    const hudClock = document.getElementById("hud-clock");
    const CLOCK_ICONS = {
        sun: '<svg viewBox="0 0 26 26"><rect width="26" height="26" fill="#6fb3ff"/><circle cx="13" cy="12" r="5.5" fill="#ffd84a" stroke="#f0a020" stroke-width="1.2"/><g stroke="#ffd84a" stroke-width="1.6" stroke-linecap="round"><path d="M13 2.5v2.5M13 19v2.5M3.5 12H6M20 12h2.5M6.3 5.3l1.8 1.8M17.9 16.9l1.8 1.8M6.3 18.7l1.8-1.8M17.9 7.1l1.8-1.8"/></g><path d="M0 22q7-4 13 0t13 0v4H0z" fill="#5aa83c"/></svg>',
        moon: '<svg viewBox="0 0 26 26"><rect width="26" height="26" fill="#1d2f66"/><circle cx="6" cy="6" r=".8" fill="#fff"/><circle cx="20" cy="5" r=".7" fill="#fff"/><circle cx="17" cy="15" r=".6" fill="#fff"/><path d="M15 4.5a7.5 7.5 0 1 0 5 12.6 6.2 6.2 0 1 1-5-12.6z" fill="#ffe9a8"/><path d="M0 22q7-4 13 0t13 0v4H0z" fill="#2c5a2a"/></svg>',
        dusk: '<svg viewBox="0 0 26 26"><rect width="26" height="26" fill="#f2a35c"/><rect width="26" height="13" fill="#7a5fb8"/><circle cx="13" cy="17" r="5" fill="#ffd25a"/><path d="M0 20q7-3 13 0t13 0v6H0z" fill="#4c7f34"/></svg>',
        rain: '<svg viewBox="0 0 26 26"><rect width="26" height="26" fill="#6d7f99"/><path d="M6 13a4 4 0 0 1 1-7.8A5.5 5.5 0 0 1 17.6 6 3.6 3.6 0 0 1 20 13z" fill="#e8eef7"/><g stroke="#a8d0ff" stroke-width="1.6" stroke-linecap="round"><path d="M8 16l-1 3M13 16l-1 3M18 16l-1 3M10.5 20l-1 3M15.5 20l-1 3"/></g></svg>',
        snow: '<svg viewBox="0 0 26 26"><rect width="26" height="26" fill="#8fa6c4"/><path d="M6 13a4 4 0 0 1 1-7.8A5.5 5.5 0 0 1 17.6 6 3.6 3.6 0 0 1 20 13z" fill="#fff"/><g fill="#fff"><circle cx="8" cy="17" r="1.3"/><circle cx="13" cy="19" r="1.3"/><circle cx="18" cy="17" r="1.3"/><circle cx="10.5" cy="22" r="1.3"/><circle cx="15.5" cy="22.5" r="1.3"/></g></svg>',
    };
    const SEASON_TEXT = { summer: t("Verão"), autumn: t("Outono"), winter: t("Inverno"), spring: t("Primavera") };

    function placeClock() {
        if (!hudClock || hudClock.hidden) return;
        const stage = hudClock.parentElement.getBoundingClientRect();
        const box = container.getBoundingClientRect();
        const scale = hudScale(box);
        hudClock.style.setProperty("--hud-scale", scale.toFixed(3));
        hudClock.style.left = `${overlayLeft(box, stage, scale) + 2 * scale}px`;
        // below the resource bar: the page's own one (SE_HUD, in two rows on an upright phone) or the game's
        let top = box.top - stage.top + (hudShown ? 52 : 96) * scale;
        if (hudShown && hudBar && !hudBar.hidden && isTall()) top = hudBar.getBoundingClientRect().bottom - stage.top + 6 * scale;
        hudClock.style.top = `${top}px`;
    }

    function updateClock(clock, weather) {
        if (!config.hudClock || !hudClock) return;
        const hour = Math.floor(clock.hour);
        const minute = Math.floor((clock.hour - hour) * 60);
        const night = clock.hour < 5.5 || clock.hour >= 20.5;
        const twilight = (clock.hour >= 5.5 && clock.hour < 7.5) || (clock.hour >= 18.5 && clock.hour < 20.5);
        let icon = night ? "moon" : twilight ? "dusk" : "sun";
        let text = night ? t("Noite clara") : twilight ? (clock.hour < 12 ? t("Amanhecer") : t("Entardecer")) : t("Ensolarado");
        if (weather === "rain") { icon = "rain"; text = t("Chuva"); }
        if (weather === "snow") { icon = "snow"; text = t("Neve"); }
        hudClock.querySelector(".hud-clock-icon").innerHTML = CLOCK_ICONS[icon];
        hudClock.querySelector(".hud-clock-time").textContent = `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
        hudClock.querySelector(".hud-clock-weather").textContent = text;
        hudClock.title = `${text} · ${SEASON_TEXT[seasonOf(clock.month, clock.day)]}`;
        hudClock.hidden = false;
        placeClock();
    }

    // Point 26 (SE_HUD): the page's resource bar. The game (swf_hud.py) answers seHudState() with the player's
    // numbers and hides its own top ribbon on seHudHide(); seHudCash() opens the game's own "+ cash" window.
    const hudBar = document.getElementById("hud-bar");
    const hudEmpire = document.getElementById("hud-empire");
    let hudShown = false;
    let hudLast = {};
    let hudHiddenAt = 0;
    const numberFormat = new Intl.NumberFormat(document.documentElement.lang || "es");
    const compactFormat = new Intl.NumberFormat(document.documentElement.lang || "es", { notation: "compact", maximumFractionDigits: 1 });
    const shortNumber = value => (Math.abs(value) < 100000 ? numberFormat.format(value) : compactFormat.format(value));

    function placeHud() {
        if (!hudBar || hudBar.hidden) return;
        const stage = hudBar.parentElement.getBoundingClientRect();
        const box = container.getBoundingClientRect();
        const scale = hudScale(box);
        const tall = isTall();
        hudBar.style.setProperty("--hud-scale", scale.toFixed(3));
        hudBar.style.left = `${overlayLeft(box, stage, scale)}px`;
        hudBar.style.top = `${box.top - stage.top + 6 * scale}px`;
        // Upright, the bar wraps into rows that keep clear of the menu button on the right.
        hudBar.classList.toggle("is-tall", tall);
        hudBar.style.maxWidth = tall ? `${Math.max(160, box.width - 6 * scale - 84)}px` : "";
        if (hudEmpire) {
            // Right of the World globe: 645 of the game's pixels into its top interface, which the game's
            // full-window layout centres on the stage (GuiManager.fullscreen: x = stage width / 2 - 380).
            hudEmpire.style.setProperty("--hud-scale", scale.toFixed(3));
            const globe = hudButtons && hudButtons.globe;
            const position = positionScale(box);
            const after = globe && globe.w > 0 ? globe.x + globe.w + 2 : stageWidth / 2 - 380 + 645;
            hudEmpire.style.left = `${box.left - stage.left + after * position}px`;
            // Upright, the globe is under the clock: the name and population beside it, centred on it.
            const top = tall && globe && globe.w > 0
                ? box.top - stage.top + (globe.y + globe.h / 2) * position - hudEmpire.offsetHeight / 2
                : box.top - stage.top + 22 * scale;
            hudEmpire.style.top = `${top}px`;
        }
    }

    function readHud() {
        let state = null;
        try {
            if (player && typeof player.seHudState === "function") state = player.seHudState();
        } catch (error) {
            state = null;  // the game is loading or changing maps
        }
        if (!state || typeof state.g !== "number") return;
        const now = Date.now();
        if (!hudShown || now - hudHiddenAt > 3000) {  // again now and then: a map change may show the ribbon again
            try {
                player.seHudHide();
                if (hudSide) showSidePieces();
                hudHiddenAt = now;
            } catch (error) {
                return;  // keep the game's own ribbon
            }
        }
        for (const key of ["g", "w", "f", "s", "c"]) {
            const pill = hudBar.querySelector(`[data-hud="${key}"]`);
            const value = state[key];
            if (hudLast[key] === value) continue;
            pill.querySelector("b").textContent = shortNumber(value);
            pill.title = numberFormat.format(value);
            if (typeof hudLast[key] === "number") {
                pill.classList.remove("is-up", "is-down");
                void pill.offsetWidth;
                pill.classList.add(value > hudLast[key] ? "is-up" : "is-down");
                clearTimeout(pill.hudTimer);
                pill.hudTimer = setTimeout(() => pill.classList.remove("is-up", "is-down"), 1200);
            }
        }
        const span = Math.max(1, state.xpMax - state.xpMin);
        const progress = Math.min(1, Math.max(0, (state.xp - state.xpMin) / span));
        hudBar.querySelector(".hud-level-number").textContent = state.lvl;
        hudBar.querySelector(".hud-xp-fill").style.width = `${(progress * 100).toFixed(1)}%`;
        hudBar.querySelector(".hud-xp-text").textContent = `${Math.floor(progress * 100)}%`;
        hudBar.querySelector('[data-hud="profile"]').title =
            `${t("Nível")} ${state.lvl} · ${numberFormat.format(state.xp)} / ${numberFormat.format(state.xpMax)} XP`;
        // A window of the game is open (the news, a shop, ...): the page's overlays step back so it shows whole.
        document.body.classList.toggle("hud-dimmed", state.windows > 0);
        if (hudEmpire) {
            hudEmpire.querySelector(".hud-name").textContent = state.name || "";
            hudEmpire.querySelector(".hud-pop b").textContent = state.popText || "";
        }
        hudLast = state;
        if (!hudShown) {
            hudShown = true;
            hudBar.hidden = false;
            if (hudEmpire) hudEmpire.hidden = false;
            placeHud();
            placeClock();
        }
    }

    // Point 26: the bottom bar's names, the right column (daily bonus chest, "More") and the menu button above it.
    const hudLabels = document.getElementById("hud-labels");
    const hudSide = document.getElementById("hud-side");
    const hudDaily = document.getElementById("hud-daily");
    const hudMore = document.getElementById("hud-more");
    const SIDE_PIECES = ["options_panel", "_viralButtonPanel"];  // swf_hud.SIDE_BUTTONS
    let moreOpen = false;
    // SE_HUD_GROUP: one "Modos" button stands where the Clan, PvP and Pase column was; open, the column shows below
    // it (above it upright, where the column sits on the bottom). GROUP_W x GROUP_H: the button, in game pixels,
    // the size of one of the column's badges.
    const hudGroup = config.hudGroup ? document.getElementById("hud-group") : null;
    const GROUP_W = 60;
    const GROUP_H = 72;
    let groupOpen = false;
    let groupHome = null;  // the column's place in a fixed 760 x 600 game (no SE_VIEW layout)
    let morePieces = 0;
    let hudButtons = null;
    const clockOffset = (Number(config.serverTime) || Date.now() / 1000) * 1000 - Date.now();

    // The game's pixels to the page's, for positions (not floored like the overlays' size).
    function positionScale(box) {
        return fullView ? viewScale : box.width / 760;
    }

    function menuOverGame() {
        return fullView && (shell.classList.contains("is-expanded") || document.fullscreenElement === shell);
    }

    function placeButtons() {
        if (!hudButtons) return;
        const stage = hudBar.parentElement.getBoundingClientRect();
        const box = container.getBoundingClientRect();
        const scale = positionScale(box);
        const left = box.left - stage.left;
        const top = box.top - stage.top;
        const bar = hudButtons.bgBar;
        const barShown = Boolean(bar && bar.v && bar.on);
        hudLabels.style.setProperty("--hud-scale", overlayScale(box).toFixed(3));
        for (const label of hudLabels.querySelectorAll("[data-button]")) {
            const button = hudButtons[label.dataset.button];
            const shown = barShown && button && button.v && button.on && button.w > 0;
            label.hidden = !shown;
            if (!shown) continue;
            label.style.left = `${left + (button.x + button.w / 2) * scale}px`;
            label.style.top = `${top + (button.y + button.h - 1) * scale}px`;
        }
        hudLabels.hidden = false;

        // The right column: below the menu button when it is over the game, else on the stage's top right; lower
        // when the empire's name reaches it (a narrow stage).
        hudSide.style.setProperty("--hud-scale", hudScale(box).toFixed(3));
        const right = stage.right - box.right + 8;
        let columnTop = top + 8;
        if (menuOverGame()) {
            const empire = hudEmpire && !hudEmpire.hidden ? hudEmpire.getBoundingClientRect() : null;
            let dockTop = 8;
            if (empire && empire.right > stage.right - right - 64) dockTop = empire.bottom - stage.top + 6;
            controlsDock.style.top = `${dockTop}px`;
            columnTop = dockTop + 52 + 22;
        } else {
            controlsDock.style.top = "";
            const empire = hudEmpire && !hudEmpire.hidden ? hudEmpire.getBoundingClientRect() : null;
            if (empire && empire.right > stage.right - right - 64) columnTop = empire.bottom - stage.top + 6;
        }
        hudSide.style.right = `${right}px`;
        hudSide.style.top = `${columnTop}px`;
        const moved = hudSide.dataset.place !== `${right},${columnTop}`;
        hudSide.dataset.place = `${right},${columnTop}`;
        hudSide.hidden = false;
        if (moved && moreOpen) showSidePieces();  // the open pieces follow the column
    }

    // What shows of a side piece, from its origin (stage pixels): its bounds change with what the game shows in it
    // (the "Prize" box grows with offers such as "Get your Monday Bonus!"), its origin does not. The box's picture
    // is 62 x 88 at (-66, -16) from it, the options panel 90 x 59 at its origin. Measured in the game.
    const SIDE_ART = { _viralButtonPanel: [-66, -16, 62, 88], options_panel: [-1, 0, 90, 59] };

    function sidePieceArt(name, piece) {
        const art = SIDE_ART[name];
        if (!art || !Number.isFinite(piece.ox)) return piece;
        return { x: piece.ox + art[0], y: piece.oy + art[1], w: art[2], h: art[3] };
    }

    // Open, "More" shows the pieces stacked below it, centred on the right column (the "Prize" box first).
    function showSidePieces() {
        const box = container.getBoundingClientRect();
        const scale = positionScale(box);
        const more = hudMore.getBoundingClientRect();
        const centre = (more.left + more.width / 2 - box.left) / scale;
        let top = (more.bottom + 6 - box.top) / scale;
        for (const name of ["_viralButtonPanel", "options_panel"]) {
            const piece = hudButtons && hudButtons[name];
            let x = NaN;
            let y = NaN;
            if (moreOpen && piece && piece.w > 0) {
                const art = sidePieceArt(name, piece);
                const artLeft = Math.min(centre - art.w / 2, stageWidth - art.w - 3);  // whole on the stage
                x = artLeft - (art.x - piece.x);
                y = top - (art.y - piece.y);
                top += art.h + 6 / scale;
            }
            try {
                player.seHudShow(name, moreOpen, x, y);
            } catch (error) {
                // the game is busy: the next round
            }
        }
    }

    // On a stage wider than the game's 760 pixels, the World globe with the empire's name and the Clan, PvP and
    // Pass column go against the right edge, beside the page's column (the game's layout centres them), and the
    // spell book to the bottom left corner when it fits beside the bottom bar. Elsewhere they go back where the
    // game puts them: their places relative to the centred interface are read once, before moving anything.
    const pieceHome = {};

    function placePiece(name, x, y) {
        const piece = hudButtons[name];
        const moveX = Number.isFinite(x) && Math.abs(x - piece.x) > 0.5;
        const moveY = Number.isFinite(y) && Math.abs(y - piece.y) > 0.5;
        if (!moveX && !moveY) return;
        try {
            player.seHudPlace(name, moveX ? x : NaN, moveY ? y : NaN);
        } catch (error) {
            // the game is busy: the next round
        }
    }

    // Upright, how much bigger the game draws them (seHudScale); elsewhere 1.
    const TALL_PIECES = { globe: 1.4, clanPanel: 1.5, magicBox: 1.4 };

    function scalePiece(name, scale) {
        const piece = hudButtons[name];
        const home = pieceHome[name];
        if (!piece || !home || !(piece.w > 0) || Math.abs(piece.w - home.w * scale) <= 1) return;
        try {
            player.seHudScale(name, scale);
        } catch (error) {
            // the game is busy, or a game without it: the next round
        }
    }

    // The "Modos" button at (x, y) of the game's stage with the column's width `columnW` (game pixels); `up`: the
    // column opens above it. Returns where the column goes when open.
    function placeGroup(x, y, columnW, columnH, size, up) {
        const box = container.getBoundingClientRect();
        const stage = hudGroup.parentElement.getBoundingClientRect();
        const scale = positionScale(box);
        const w = GROUP_W * size;
        const h = GROUP_H * size;
        const left = x + (columnW - w) / 2;
        hudGroup.style.setProperty("--hud-group", (scale * size).toFixed(3));
        hudGroup.style.left = `${box.left - stage.left + left * scale}px`;
        hudGroup.style.top = `${box.top - stage.top + y * scale}px`;
        hudGroup.classList.toggle("opens-up", up);
        hudGroup.hidden = false;
        return up ? { x, y: y - 4 - columnH } : { x, y: y + h + 4 };
    }

    // Shown or hidden as the button says (asked again after the game builds its interface anew).
    function showGroupColumn(clan) {
        if (Boolean(clan.v) === groupOpen) return;
        try {
            player.seHudShow("clanPanel", groupOpen, NaN, NaN);
        } catch (error) {
            // the game is busy: the next round
        }
    }

    // Without SE_VIEW's layout the column stays where the game put it: the button takes its place.
    function layoutGroupFixed() {
        const clan = hudButtons.clanPanel;
        if (!clan || !(clan.w > 0) || !clan.on) {
            hudGroup.hidden = true;
            return;
        }
        if (!groupHome) groupHome = { x: clan.x, y: clan.y };
        const spot = placeGroup(groupHome.x, groupHome.y, clan.w, clan.h, 1, false);
        placePiece("clanPanel", spot.x, spot.y);
        showGroupColumn(clan);
    }

    function layoutPieces() {
        if (!fullView || !fittedSize) return;
        const centred = stageWidth / 2 - 380;  // where the game's full-window layout puts its interface
        for (const name of ["globe", "clanPanel", "magicBox"]) {
            const piece = hudButtons[name];
            if (piece && piece.w > 0 && !pieceHome[name]) {
                // y: the globe hangs from the top, the others sit on the bottom bar
                pieceHome[name] = { x: piece.x - centred, y: name === "globe" ? piece.y : piece.y - stageHeight, w: piece.w, h: piece.h };
            }
        }
        const tall = isTall();
        for (const name of Object.keys(TALL_PIECES)) scalePiece(name, tall ? TALL_PIECES[name] : 1);
        const box = container.getBoundingClientRect();
        const scale = positionScale(box);
        const wide = stageWidth > 761;
        // The page's right column: its own width and the menu button's (not the menu's panel, opened over it).
        const side = hudSide.getBoundingClientRect();
        const menu = menuOverGame() ? controlsToggle.getBoundingClientRect() : null;
        const column = Math.max(side.width || 0, menu ? menu.width : 0) + 16;
        const edge = stageWidth - column / scale;  // where the page's right column starts
        // Open, "More" stacks its pieces centred under it: the Clan column keeps clear of the widest one.
        let pieces = 0;
        if (moreOpen) {
            for (const name of SIDE_PIECES) {
                const piece = hudButtons[name];
                if (piece && piece.on && piece.w > 0) pieces = Math.max(pieces, sidePieceArt(name, piece).w);
            }
        }
        const clanEdge = stageWidth - Math.max(column / scale, pieces + 12);

        const globe = hudButtons.globe;
        if (globe && globe.w > 0 && pieceHome.globe) {
            const home = centred + pieceHome.globe.x;
            if (tall) {
                // Upright: on the left under the clock (the bar takes the top), its name and population beside it.
                const clock = hudClock && !hudClock.hidden ? hudClock.getBoundingClientRect() : null;
                const below = clock && clock.height ? (clock.bottom - box.top) / scale + 4 : pieceHome.globe.y;
                placePiece("globe", 6, below);
            } else {
                const empire = hudEmpire ? hudEmpire.getBoundingClientRect().width / scale : 0;
                placePiece("globe", wide ? Math.max(home, edge - empire - 6 - globe.w) : home, pieceHome.globe.y);
            }
        }
        // Bigger upright pieces keep their bottom where the game puts it (they grow upwards).
        const homeBottom = name => stageHeight + pieceHome[name].y + pieceHome[name].h;
        const clan = hudButtons.clanPanel;
        if (clan && clan.w > 0 && pieceHome.clanPanel) {
            const home = centred + pieceHome.clanPanel.x;
            // Upright, the page's right column is far above it: against the edge.
            const x = tall ? stageWidth - 8 - clan.w : wide ? Math.max(home, clanEdge - 4 - clan.w) : home;
            const y = tall ? homeBottom("clanPanel") - clan.h : stageHeight + pieceHome.clanPanel.y;
            if (hudGroup && clan.on) {
                // The button where the column's top was (upright: where its bottom was, the column above it).
                const size = tall ? TALL_PIECES.clanPanel : 1;
                const buttonY = tall ? homeBottom("clanPanel") - GROUP_H * size : y;
                const spot = placeGroup(x, buttonY, clan.w, clan.h, size, tall);
                placePiece("clanPanel", spot.x, spot.y);
                showGroupColumn(clan);
            } else {
                if (hudGroup) hudGroup.hidden = true;
                placePiece("clanPanel", x, y);
            }
        }
        const book = hudButtons.magicBox;
        const bar = hudButtons.bgBar;
        if (book && book.w > 0 && pieceHome.magicBox) {
            const fits = wide && bar && bar.x >= book.w + 12;
            if (fits) placePiece("magicBox", 4, stageHeight - book.h - 4);
            else if (tall) placePiece("magicBox", 4, homeBottom("magicBox") - book.h);
            else placePiece("magicBox", centred + pieceHome.magicBox.x, stageHeight + pieceHome.magicBox.y);
        }
    }

    function readButtons() {
        try {
            hudButtons = player && typeof player.seHudButtons === "function" ? player.seHudButtons() : null;
        } catch (error) {
            hudButtons = null;
        }
        if (!hudButtons) return;
        // "More" holds the side pieces the game has (the gear panel, the "Prize" box).
        const present = SIDE_PIECES.filter(name => hudButtons[name] && hudButtons[name].on).length;
        if (present !== morePieces) {
            morePieces = present;
            hudMore.querySelector(".hud-more-count").textContent = `+${present}`;
            hudMore.hidden = present === 0;
        }
        layoutPieces();
        if (hudGroup && !fullView) layoutGroupFixed();  // SE_VIEW's layout places it once fitted (layoutPieces)
        placeHud();  // the empire's name follows the globe
        placeButtons();
    }

    function updateDaily() {
        if (!hudDaily) return;
        const next = Number(config.dailyNext);
        if (config.dailyNext === null || config.dailyNext === undefined || !Number.isFinite(next)) {
            hudDaily.hidden = true;
            return;
        }
        const left = Math.max(0, Math.round(next - (Date.now() + clockOffset) / 1000));
        const ready = left === 0;
        hudDaily.classList.toggle("is-ready", ready);
        const hours = Math.floor(left / 3600);
        const minutes = Math.floor((left % 3600) / 60);
        hudDaily.querySelector(".hud-daily-time").textContent = ready ? t("Coletar!")
            : hours > 0 ? `${hours}h ${String(minutes).padStart(2, "0")}m` : `${minutes}m ${String(left % 60).padStart(2, "0")}s`;
    }

    function startSide() {
        if (!hudSide) return;
        if (hudGroup) {
            hudGroup.addEventListener("click", () => {
                groupOpen = !groupOpen;
                hudGroup.setAttribute("aria-expanded", String(groupOpen));
                readButtons();
            });
        }
        hudMore.addEventListener("click", () => {
            moreOpen = !moreOpen;
            hudMore.setAttribute("aria-expanded", String(moreOpen));
            showSidePieces();
        });
        updateDaily();
        setInterval(updateDaily, 1000);
        setInterval(readButtons, 500);
        window.addEventListener("resize", () => setTimeout(placeButtons, 60));
        document.addEventListener("fullscreenchange", () => setTimeout(placeButtons, 60));
    }

    function startHud() {
        if (!config.hudBar || !hudBar) return;
        startSide();
        hudBar.querySelector(".hud-add").addEventListener("click", () => {
            try {
                player.seHudCash();
            } catch (error) {
                // the game is not ready
            }
        });
        window.addEventListener("resize", placeHud);
        document.addEventListener("fullscreenchange", () => setTimeout(placeHud, 50));
        setInterval(readHud, 500);
    }

    if (hudClock) {
        window.addEventListener("resize", placeClock);
        document.addEventListener("fullscreenchange", () => setTimeout(placeClock, 50));
    }

    function updateDayNight() {
        const clock = argentinaNow();
        const [red, green, blue] = lightAt(clock.hour);
        try {
            if (player && typeof player.seSetDayLight === "function") player.seSetDayLight(red, green, blue);
        } catch (error) {
            // the game is still loading or changing maps: the next round tints it
        }
        const quiet = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        const weather = weatherNow(clock);
        setWeather(quiet ? "" : weather);
        updateClock(clock, weather);
    }

    function startDayNight() {
        if (!config.dayNight) return;
        updateDayNight();
        setInterval(updateDayNight, 10000);  // also tints a map loaded meanwhile (an attack, the way back home)
    }

    function setExpanded(value) {
        expanded = value;
        document.body.classList.toggle("tab-expanded", expanded);
        shell.classList.toggle("is-expanded", expanded);
        expand.textContent = expanded ? t("Restaurar janela") : t("Preencher aba");
        expand.setAttribute("aria-pressed", String(expanded));
    }

    let panelCloseTimer = 0;

    function hideControls() {
        clearTimeout(hideControlsTimer);
        clearTimeout(hoverControlsTimer);
        if (controlsPanel.contains(document.activeElement)) {
            revealOnFocus = false;
            controlsToggle.focus({ preventScroll: true });
            revealOnFocus = true;
        }
        controlsToggle.setAttribute("aria-expanded", "false");
        shell.classList.remove("controls-open");
        controlsActivated = false;
        if (controlsPanel.hidden) return;
        controlsPanel.classList.add("is-closing");
        clearTimeout(panelCloseTimer);
        panelCloseTimer = setTimeout(() => {
            controlsPanel.hidden = true;
            controlsPanel.classList.remove("is-closing");
        }, 170);
    }

    function scheduleControlsHide() {
        clearTimeout(hideControlsTimer);
        hideControlsTimer = setTimeout(() => {
            const focused = document.activeElement;
            const keyboardInDock = controlsDock.contains(focused) && focused.matches(":focus-visible");
            if (pointerInDock || keyboardInDock) scheduleControlsHide();
            else hideControls();
        }, 2500);
    }

    function showControls(activated = false) {
        clearTimeout(hoverControlsTimer);
        controlsActivated = controlsActivated || activated;
        clearTimeout(panelCloseTimer);
        controlsPanel.classList.remove("is-closing");
        controlsPanel.hidden = false;
        controlsToggle.setAttribute("aria-expanded", "true");
        shell.classList.add("controls-open");
        scheduleControlsHide();
    }

    controlsToggle.hidden = false;
    controlsToggle.addEventListener("click", () => {
        if (!controlsPanel.hidden && controlsActivated) hideControls();
        else showControls(true);
    });
    controlsDock.addEventListener("pointerenter", (event) => {
        if (event.pointerType !== "mouse") return;
        pointerInDock = true;
        hoverControlsTimer = setTimeout(() => showControls(), 180);
    });
    controlsDock.addEventListener("pointerleave", () => {
        pointerInDock = false;
        clearTimeout(hoverControlsTimer);
        scheduleControlsHide();
    });
    controlsDock.addEventListener("pointermove", scheduleControlsHide);
    controlsDock.addEventListener("focusin", () => {
        if (revealOnFocus) showControls();
    });
    controlsDock.addEventListener("focusout", scheduleControlsHide);
    controlsDock.addEventListener("input", scheduleControlsHide);

    volume.disabled = false;
    mute.hidden = false;
    expand.hidden = false;
    fullscreen.hidden = !document.fullscreenEnabled;
    // The picture: fluid (the default) or sharp (drawRatio); Ruffle reads the new density when its size changes.
    const sharpButton = document.getElementById("sharp-button");
    function showSharp() {
        sharpButton.textContent = preferences.sharp ? t("Imagem: nítida") : t("Imagem: fluida");
        sharpButton.setAttribute("aria-pressed", String(preferences.sharp));
    }
    if (sharpButton && fullView) {
        sharpButton.hidden = false;
        showSharp();
        sharpButton.addEventListener("click", () => {
            preferences.sharp = !preferences.sharp;
            savePreferences();
            showSharp();
            if (player) {
                const width = player.style.width;
                player.style.width = `${parseFloat(width) - 1}px`;
                requestAnimationFrame(() => {
                    player.style.width = width;
                    window.dispatchEvent(new Event("resize"));
                });
            }
        });
    }
    // Performance mode (SE_PERF_MODE, swf_perf_mode.py): the buildings' animations stop (flags and the like; the
    // units keep theirs). On by default; again every 5 s in the own village (gameMode 1), so new buildings stop too
    // (about 5 ms each time). Off reloads the page: the game starts every animation again.
    const perfButton = document.getElementById("perf-button");
    function showPerf() {
        perfButton.textContent = preferences.perf ? t("Modo desempenho: sim") : t("Modo desempenho: não");
        perfButton.setAttribute("aria-pressed", String(preferences.perf));
    }
    if (perfButton && config.perfMode) {
        perfButton.hidden = false;
        showPerf();
        perfButton.addEventListener("click", () => {
            preferences.perf = !preferences.perf;
            savePreferences();
            showPerf();
            if (preferences.perf) applyPerf();
            else window.location.reload();
        });
        setInterval(applyPerf, 5000);
    }
    function applyPerf() {
        if (!preferences.perf || !player || hudLast.mode !== 1) return;
        try {
            if (typeof player.sePerf === "function") player.sePerf();
        } catch (error) {
            // the game is loading or changing maps: the next round
        }
    }
    applyAudio();
    setExpanded(true);
    watchServerVersion();

    volume.addEventListener("input", () => {
        preferences.volume = Math.round(Math.max(0, Math.min(100, volume.valueAsNumber || 0)));
        preferences.muted = false;
        applyAudio();
        savePreferences();
    });
    mute.addEventListener("click", () => {
        if (preferences.muted || preferences.volume === 0) {
            preferences.muted = false;
            if (preferences.volume === 0) preferences.volume = 50;
        } else {
            preferences.muted = true;
        }
        applyAudio();
        savePreferences();
        audioStatus.textContent = preferences.muted ? t("Som silenciado.") : t("Som ativado em {volume}%.", { volume: preferences.volume });
    });
    expand.addEventListener("click", async () => {
        if (document.fullscreenElement === shell) {
            try {
                await document.exitFullscreen();
            } catch {
                status.textContent = t("Use Esc para sair da tela cheia do navegador.");
                return;
            }
        }
        setExpanded(!expanded);
    });
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            if (!controlsPanel.hidden) {
                hideControls();
                event.preventDefault();
                event.stopPropagation();
            } else if (expanded) {
                setExpanded(false);
                controlsToggle.focus({ preventScroll: true });
                event.preventDefault();
                event.stopPropagation();
            }
        }
    }, true);
    document.addEventListener("fullscreenchange", () => {
        fullscreen.textContent = document.fullscreenElement === shell ? t("Sair da tela cheia") : t("Tela cheia");
    });

    function fail(heading, description) {
        clearTimeout(loadingTimer);
        title.textContent = heading;
        message.textContent = description;
        overlay.hidden = false;
        retry.hidden = false;
        status.textContent = t("Não foi possível carregar sua vila.");
    }

    retry.addEventListener("click", () => window.location.reload());
    fullscreen.addEventListener("click", async () => {
        try {
            if (document.fullscreenElement === shell) await document.exitFullscreen();
            else await shell.requestFullscreen();
        } catch {
            status.textContent = t("O navegador não permitiu a tela cheia. Você pode continuar jogando aqui.");
        }
    });

    if (!window.WebAssembly) {
        fail(t("Seu navegador precisa ser atualizado"), t("Use uma versão atual do Chrome, Firefox, Edge ou Safari para abrir o jogo."));
        return;
    }

    window.RufflePlayer = window.RufflePlayer || {};
    window.RufflePlayer.config = { publicPath: runtimePath, polyfills: false, favorFlash: false };
    // SE_ABILITIES=on: Ruffle's wgpu-over-WebGL renderer (its usual pick, even with WebGPU present) crashes
    // drawing the ability effects' colour filters (freeze, poison, stone); its own WebGL renderer does not.
    // The server picks Ruffle's renderer and quality (SE_RUFFLE_RENDERER, SE_RUFFLE_QUALITY). Pages from an older
    // server only say webglRenderer: with SE_ABILITIES=on, Ruffle's own WebGL renderer.
    const ruffleSettings = config.ruffle || { renderer: config.webglRenderer ? "webgl" : "", quality: "16x16" };
    if (ruffleSettings.renderer) window.RufflePlayer.config.preferredRenderer = ruffleSettings.renderer;
    const script = document.createElement("script");
    script.src = `${runtimePath}ruffle.js`;
    script.addEventListener("error", () => {
        fail(t("O jogo está indisponível"), t("Não foi possível baixar os arquivos do jogo deste servidor. Tente novamente em instantes."));
    });
    script.addEventListener("load", startPlayer);
    document.head.appendChild(script);

    // Slow runtime downloads remain retriable without pretending the game loaded.
    loadingTimer = setTimeout(() => {
        message.textContent = t("O carregamento está demorando mais que o esperado. Verifique sua conexão e, se necessário, tente novamente.");
        retry.hidden = false;
    }, 45000);

    async function startPlayer() {
        // A tab that stood aside for a duel (duels.js) closed its game before it started: keep it closed.
        if (container.dataset.retired === "true") {
            clearTimeout(loadingTimer);
            overlay.hidden = true;
            return;
        }
        try {
            const ruffle = window.RufflePlayer.newest();
            player = ruffle.createPlayer();
            // The game's own fullscreen button (its options panel) puts the whole page in fullscreen, not the
            // player alone: alone, the page's bar, clock, labels and "More" are left out, and the pieces the page
            // moved stay where they were. Ruffle never sees the player itself in fullscreen, so each press of the
            // button asks again: it toggles.
            player.requestFullscreen = () => {
                const request = document.fullscreenElement === shell ? document.exitFullscreen() : shell.requestFullscreen();
                return Promise.resolve(request).catch(() => {
                    status.textContent = t("O navegador não permitiu a tela cheia. Você pode continuar jogando aqui.");
                });
            };
            // Ruffle hears of fullscreen changes on the player only: told of each one, it finds the player itself
            // is not in fullscreen and the game's button goes back to asking for it (so the next press leaves).
            document.addEventListener("fullscreenchange", () => player.dispatchEvent(new Event("fullscreenchange")));
            showSoundHint();
            startDayNight();
            startHud();
            startView();
            player.setAttribute("aria-label", "Social Empires");
            container.appendChild(player);
            player.addEventListener("loadedmetadata", applyAudio, { once: true });
            player.addEventListener("loadeddata", () => {
                clearTimeout(loadingTimer);
                overlay.hidden = true;
                applyAudio();
                if (villageChanged) {
                    pauseUpdatedVillage();
                    status.textContent = t("Sua vila foi atualizada. Recarregue para continuar jogando.");
                } else {
                    status.textContent = t("Jogo aberto no navegador. O carregamento da vila continua dentro do jogo.");
                }
            }, { once: true });

            const movie = new URL("flash/SELoader.swf", staticPath);
            movie.searchParams.set("swftoload", new URL(`flash/${config.gameVersion}`, staticPath).href);
            await player.ruffle().load({
                url: movie.href,
                publicPath: runtimePath,
                autoplay: "on",
                backgroundColor: "#669C2C",
                // Only with duels or clans on: the duel page opens the tournament arena (Base.__startDuel)
                // and the game's "Clan" button opens the clan window (window.seOpenClan).
                allowScriptAccess: Boolean(config.dayNight || document.getElementById("duel-config") || document.getElementById("clan-overlay-config")
                    || document.getElementById("pvp-overlay-config") || document.getElementById("season-pass-overlay-config")),
                allowFullscreen: true,
                splashScreen: false,
                quality: ruffleSettings.quality || "16x16",
                scale: config.fullView ? "noScale" : "showAll",
                forceScale: true,
                letterbox: config.fullView ? "off" : "on",
                // Preserve the old domains embedded in asset SWFs on this host.
                urlRewriteRules: [
                    [/^https?:\/\/(?:default01\.)?static\.socialpointgames\.com\/static\/socialempires\//i, staticPath],
                    [/^https?:\/\/dynamic\.flash1\.dev\.socialpoint\.es\/appsfb\/socialempiresdev\/srvempires\//i, dynamicPath],
                ],
                parameters: {
                    spdebug: "notnull", brk: "0", staticUrl: staticPath, dynamicUrl: dynamicPath,
                    skiphash12341: "notnull", fb_sig_user: String(config.userId), user_key: config.userKey,
                    // This token selects the bundled font SWFs; visible text comes from the pt-BR catalog.
                    language: "en", accessToken: "", sex: "m", lastLoggedIn: String(config.lastLoggedIn ?? config.serverTime), dailyBonus: "0",
                    gocash: new URL("/treasury", base).href,
                    // Facebook's "publish achievements" permission counts as granted: otherwise, from
                    // level 10, the game shows a "More achievements" hand that only asks Facebook for it.
                    publishActions: "1",
                    friendsInfo: JSON.stringify(config.friendsInfo), serverTime: String(config.serverTime),
                    forceSyncError: "1", forceAttackReload: "0", forceQuestReload: "0",
                    // Seconds between the game's command sends (SE_QUICK_SAVE); absent, the game's own interval.
                    ...(config.pushTime ? { push_time: String(config.pushTime) } : {}),
                },
            });
            applyAudio();
        } catch (error) {
            console.error("Unable to start Social Empires", error);
            fail(t("Não foi possível abrir o jogo"), t("Confira sua conexão e tente novamente. Se o problema continuar, avise o administrador."));
        }
    }
})();
