(() => {
    "use strict";

    const workspace = document.querySelector("[data-rivals-tabs]");
    if (!workspace) return;
    const tabs = Array.from(workspace.querySelectorAll("[data-rivals-tab]"));
    const panels = Array.from(workspace.querySelectorAll("[data-rivals-panel]"));
    const tablist = workspace.querySelector(".rivals-tabs");
    if (!tablist || !tabs.length || tabs.length !== panels.length) return;

    const select = (tab, updateHash = false) => {
        tabs.forEach((item) => {
            const selected = item === tab;
            item.setAttribute("aria-selected", String(selected));
            item.tabIndex = selected ? 0 : -1;
            const panel = panels.find((itemPanel) => `#${itemPanel.id}` === item.hash);
            if (panel) panel.hidden = !selected;
        });
        if (updateHash) history.replaceState(null, "", tab.hash);
    };
    tablist.setAttribute("role", "tablist");
    tabs.forEach((tab) => {
        tab.setAttribute("role", "tab");
        tab.setAttribute("aria-controls", tab.hash.slice(1));
        tab.addEventListener("click", (event) => {
            if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            event.preventDefault();
            select(tab, true);
        });
        tab.addEventListener("keydown", (event) => {
            const index = tabs.indexOf(tab);
            let next;
            if (event.key === "ArrowRight") next = tabs[(index + 1) % tabs.length];
            if (event.key === "ArrowLeft") next = tabs[(index - 1 + tabs.length) % tabs.length];
            if (event.key === "Home") next = tabs[0];
            if (event.key === "End") next = tabs[tabs.length - 1];
            if (!next) return;
            event.preventDefault();
            select(next, true);
            next.focus();
        });
    });
    panels.forEach((panel) => {
        panel.setAttribute("role", "tabpanel");
        panel.tabIndex = 0;
    });
    select(tabs.find((tab) => tab.hash === location.hash) || tabs[0]);
    workspace.classList.add("rivals-tabs-ready");
    window.addEventListener("hashchange", () => {
        const target = tabs.find((tab) => tab.hash === location.hash);
        if (target) select(target);
    });

    workspace.querySelectorAll("[data-raid-form]").forEach((form) => {
        const button = form.querySelector("button[type='submit']");
        if (!button || button.disabled) return;
        const label = button.firstChild.textContent;
        form.addEventListener("submit", () => {
            button.disabled = true;
            button.setAttribute("aria-busy", "true");
            button.firstChild.textContent = form.dataset.busyLabel || "Atacando…";
        });
        window.addEventListener("pageshow", (event) => {
            if (!event.persisted) return;
            button.disabled = false;
            button.removeAttribute("aria-busy");
            button.firstChild.textContent = label;
        });
    });
})();
