/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

const STORAGE_KEY = "lx_helpdesk_prefill";

function getParam(name) {
    const value = new URLSearchParams(window.location.search).get(name);
    return value ? value.trim() : "";
}

function readSaved() {
    try {
        const raw = sessionStorage.getItem(STORAGE_KEY);
        if (raw) {
            return JSON.parse(raw);
        }
    } catch (_) {
        // Ignore storage parsing failures and continue with empty defaults.
    }
    return { s: "", m: "", t: "" };
}

function savePayload(subject, message, token) {
    try {
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
            s: subject || "",
            m: message || "",
            t: token || "",
            ts: Date.now(),
        }));
    } catch (_) {
        // Storage can fail in private mode; the page should still work.
    }
}

function clearSaved() {
    try {
        sessionStorage.removeItem(STORAGE_KEY);
    } catch (_) {
        // Ignore storage cleanup failures.
    }
}

function applyValueToInput(element, value) {
    if (!element) {
        return;
    }
    element.value = value;
    element.setAttribute("value", value);
    if (typeof element.defaultValue !== "undefined") {
        element.defaultValue = value;
    }
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
}

function pickFirst(selectors) {
    for (const selector of selectors) {
        const element = document.querySelector(selector);
        if (element) {
            return element;
        }
    }
    return null;
}

publicWidget.registry.LxHelpdeskPrefill = publicWidget.Widget.extend({
    selector: '[data-lx-helpdesk-prefill="1"]',

    start() {
        this._observer = null;
        this._saveFromUrlOnce();
        this._prefill();
        return this._super(...arguments);
    },

    destroy() {
        if (this._observer) {
            this._observer.disconnect();
            this._observer = null;
        }
        return this._super(...arguments);
    },

    _saveFromUrlOnce() {
        const subject = getParam("subject");
        const message = getParam("msg");
        const token = getParam("lx_token");
        if (!subject && !message && !token) {
            return;
        }
        savePayload(subject, message, token);
    },

    _ensureTokenField(token) {
        const form = pickFirst([
            "#helpdesk_ticket_form",
            "form[action*='/website/form/']",
            "form.o_website_form",
            "#wrap form",
        ]);

        if (!form) {
            return false;
        }

        let field = form.querySelector('input[name="lx_verif_token"]');
        if (!field) {
            field = document.createElement("input");
            field.type = "hidden";
            field.name = "lx_verif_token";
            form.appendChild(field);
        }

        field.value = token || "";
        field.setAttribute("value", token || "");
        return true;
    },

    _tryFillOnce() {
        const saved = readSaved();
        const subjectValue = saved.s || "";
        const messageValue = saved.m || "";
        const tokenValue = saved.t || "";

        if (!subjectValue && !messageValue && !tokenValue) {
            return true;
        }

        const subjectInput = pickFirst([
            "#helpdesk5",
            'input[name="helpdesk5"]',
            'input[name="subject"]',
            'input[name="ticket_subject"]',
        ]);
        const messageInput = pickFirst([
            "#helpdesk6",
            'textarea[name="helpdesk6"]',
            'textarea[name="description"]',
            'textarea[name="ticket_description"]',
            "#wrap textarea",
        ]);

        let done = true;

        if (subjectValue) {
            if (subjectInput) {
                applyValueToInput(subjectInput, subjectValue);
            } else {
                done = false;
            }
        }

        if (messageValue) {
            if (messageInput) {
                applyValueToInput(messageInput, messageValue);
            } else {
                done = false;
            }
        }

        if (tokenValue) {
            done = this._ensureTokenField(tokenValue) && done;
        }

        if (done) {
            clearSaved();
            window.setTimeout(() => {
                if (subjectValue && subjectInput) {
                    subjectInput.setAttribute("value", subjectValue);
                }
                if (messageValue && messageInput) {
                    messageInput.defaultValue = messageValue;
                }
            }, 300);
        }

        return done;
    },

    _prefill() {
        if (this._tryFillOnce()) {
            return;
        }

        let tries = 0;
        const interval = window.setInterval(() => {
            tries += 1;
            if (this._tryFillOnce() || tries >= 60) {
                window.clearInterval(interval);
            }
        }, 150);

        this._observer = new MutationObserver(() => {
            if (this._tryFillOnce()) {
                this._observer.disconnect();
                this._observer = null;
            }
        });
        this._observer.observe(document.documentElement, { childList: true, subtree: true });

        window.addEventListener("pageshow", () => {
            this._tryFillOnce();
        });
    },
});

export default publicWidget.registry.LxHelpdeskPrefill;
