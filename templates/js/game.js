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
    const preferences = { volume: 100, muted: false };

    try {
        const saved = JSON.parse(localStorage.getItem(preferenceKey));
        if (saved && typeof saved === "object") {
            if (Number.isFinite(saved.volume) && saved.volume >= 0 && saved.volume <= 100) {
                preferences.volume = Math.round(saved.volume);
            }
            preferences.muted = saved.muted === true;
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
        const scale = Math.max(0.6, box.width / 760);
        hudClock.style.setProperty("--hud-scale", scale.toFixed(3));
        hudClock.style.left = `${box.left - stage.left + 8 * scale}px`;
        // below the resource bar: the page's own one (SE_HUD) or the game's
        hudClock.style.top = `${box.top - stage.top + (hudShown ? 52 : 96) * scale}px`;
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
        const scale = Math.max(0.6, box.width / 760);
        hudBar.style.setProperty("--hud-scale", scale.toFixed(3));
        hudBar.style.left = `${box.left - stage.left + 6 * scale}px`;
        hudBar.style.top = `${box.top - stage.top + 6 * scale}px`;
        if (hudEmpire) {  // right of the World globe, against the movie's right edge
            hudEmpire.style.setProperty("--hud-scale", scale.toFixed(3));
            hudEmpire.style.right = `${stage.right - box.right}px`;
            hudEmpire.style.top = `${box.top - stage.top + 22 * scale}px`;
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

    function startHud() {
        if (!config.hudBar || !hudBar) return;
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

    function hideControls() {
        clearTimeout(hideControlsTimer);
        clearTimeout(hoverControlsTimer);
        if (controlsPanel.contains(document.activeElement)) {
            revealOnFocus = false;
            controlsToggle.focus({ preventScroll: true });
            revealOnFocus = true;
        }
        controlsPanel.hidden = true;
        controlsToggle.setAttribute("aria-expanded", "false");
        shell.classList.remove("controls-open");
        controlsActivated = false;
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
            showSoundHint();
            startDayNight();
            startHud();
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
                scale: "showAll",
                forceScale: true,
                letterbox: "on",
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
