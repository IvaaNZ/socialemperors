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
        try {
            const ruffle = window.RufflePlayer.newest();
            player = ruffle.createPlayer();
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
                allowScriptAccess: false,
                allowFullscreen: true,
                splashScreen: false,
                quality: "16x16",
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
                    friendsInfo: JSON.stringify(config.friendsInfo), serverTime: String(config.serverTime),
                    forceSyncError: "1", forceAttackReload: "0", forceQuestReload: "0",
                },
            });
            applyAudio();
        } catch (error) {
            console.error("Unable to start Social Empires", error);
            fail(t("Não foi possível abrir o jogo"), t("Confira sua conexão e tente novamente. Se o problema continuar, avise o administrador."));
        }
    }
})();
