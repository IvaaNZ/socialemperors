(() => {
    "use strict";
    const forms = Array.from(document.querySelectorAll("[data-treasury-claim]"));
    const buttons = forms.map((form) => form.querySelector("button[type='submit']")).filter(Boolean);
    const states = buttons.map((button) => ({ button, disabled: button.disabled, label: button.textContent }));
    let submitting = false;

    forms.forEach((form) => {
        form.addEventListener("submit", (event) => {
            if (submitting) {
                event.preventDefault();
                return;
            }
            submitting = true;
            buttons.forEach((button) => { button.disabled = true; });
            const button = form.querySelector("button[type='submit']");
            if (button) {
                button.textContent = form.dataset.busyLabel || "Resgatando…";
                button.setAttribute("aria-busy", "true");
            }
        });
    });
    window.addEventListener("pageshow", (event) => {
        if (!event.persisted) return;
        submitting = false;
        states.forEach(({ button, disabled, label }) => {
            button.disabled = disabled;
            button.textContent = label;
            button.removeAttribute("aria-busy");
        });
    });
})();
