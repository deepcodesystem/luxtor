/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

const HELP_SUBJECT = "Order limit issue";
const HELP_MESSAGE =
    "My Order surpasses the allowed limit. I kindly request a validation code so that I can complete the purchase without delay.\n\nThanks for your assistance.";

function toArray(list) {
    return Array.from(list || []);
}

function isFiniteNumber(value) {
    return typeof value === "number" && Number.isFinite(value);
}

publicWidget.registry.LxCartOrderLimit = publicWidget.Widget.extend({
    selector: "#shop_cart",

    start() {
        this._observer = null;
        this._syncTimeout = null;
        this._qtySyncTimeout = null;
        this._statusSyncToken = 0;
        this._didScrollToRoot = false;
        this._debugEnabled = window.location.search.indexOf("lx_dbg=1") !== -1;

        this._bindCurrentDom();
        this._syncVisibility();
        this._refreshFromServer();
        this._installObservers();
        if (this._debugEnabled) {
            this._printDebug();
        }

        return this._super(...arguments);
    },

    destroy() {
        if (this._observer) {
            this._observer.disconnect();
            this._observer = null;
        }
        if (this._syncTimeout) {
            window.clearTimeout(this._syncTimeout);
            this._syncTimeout = null;
        }
        if (this._qtySyncTimeout) {
            window.clearTimeout(this._qtySyncTimeout);
            this._qtySyncTimeout = null;
        }
        return this._super(...arguments);
    },

    _getRoot() {
        return document.getElementById("lx-limit-root");
    },

    _getForm() {
        return document.getElementById("lx-validate-form");
    },

    _getFeedback() {
        return document.getElementById("lx-feedback");
    },

    _getSuccessBox() {
        return document.getElementById("lx-verif-success");
    },

    _rootData() {
        const root = this._getRoot();
        if (!root) {
            return {};
        }
        const dataset = root.dataset || {};
        const limit = parseFloat(dataset.lxLimit || "0") || 0;
        const total = parseFloat(dataset.lxTotal || "0") || 0;
        return {
            limit,
            total,
            ok: dataset.lxOk === "1",
            shouldShow: dataset.lxShouldShow === "1",
            token: dataset.lxToken || "",
            helpdeskUrl: dataset.helpdeskUrl || "/helpdesk/customer-care-1",
        };
    },

    _parseAmount(text) {
        if (!text) {
            return NaN;
        }
        let value = String(text).replace(/[^\d,.\-]/g, "");
        const hasComma = value.indexOf(",") !== -1;
        const hasDot = value.indexOf(".") !== -1;
        if (hasComma && hasDot && value.lastIndexOf(",") > value.lastIndexOf(".")) {
            value = value.replace(/\./g, "").replace(",", ".");
        } else if (hasComma && !hasDot) {
            value = value.replace(",", ".");
        } else {
            value = value.replace(/,/g, "");
        }
        const number = parseFloat(value);
        return Number.isFinite(number) ? number : NaN;
    },

    _readCartTotal() {
        const selectors = [
            ".o_wsale_cart_summary .oe_total .oe_currency_value",
            ".o_wsale_cart_summary .oe_total .monetary_field",
            ".js_cart_summary .oe_total .oe_currency_value",
            ".js_cart_summary .oe_total .monetary_field",
            "#amount_total_summary.monetary_field",
            "#order_total .monetary_field",
            "[data-order-total] .monetary_field",
            "[data-order-total] .oe_currency_value",
        ];

        for (const selector of selectors) {
            const element = document.querySelector(selector);
            const text = (element?.textContent || "").trim();
            if (!text) {
                continue;
            }
            const parsed = this._parseAmount(text);
            if (isFiniteNumber(parsed)) {
                return parsed;
            }
        }

        const labels = toArray(document.querySelectorAll("td, th, div, span")).filter((el) => {
            return /\bTotal\b/i.test((el.textContent || "").trim());
        });

        for (const label of labels) {
            const sibling = label.nextElementSibling;
            const text = (sibling?.textContent || "").trim();
            if (!text) {
                continue;
            }
            const parsed = this._parseAmount(text);
            if (isFiniteNumber(parsed)) {
                return parsed;
            }
        }

        return NaN;
    },

    _getCheckoutButtons() {
        const selector = [
            'a[name="website_sale_main_button"]',
            'button[name="website_sale_main_button"]',
            ".js_proceed_to_checkout",
            ".o_wsale_btn_checkout",
            'a.btn-primary[href*="/shop/checkout"]',
            'a[href*="/shop/checkout"]',
        ].join(",");

        return toArray(document.querySelectorAll(selector)).filter((button) => {
            return button.id !== "lx-helpdesk-btn" && button.id !== "lx-validate-btn";
        });
    },

    _enforceCheckoutDisabled(disable, current, limit) {
        for (const button of this._getCheckoutButtons()) {
            if (disable) {
                button.classList.add("disabled");
                button.setAttribute("aria-disabled", "true");
                button.style.pointerEvents = "none";
                if (isFiniteNumber(current) && isFiniteNumber(limit)) {
                    button.title = `Order limit exceeded (${current.toFixed(2)} >= ${limit.toFixed(2)})`;
                }
            } else {
                button.classList.remove("disabled");
                button.removeAttribute("aria-disabled");
                button.style.pointerEvents = "";
                button.removeAttribute("title");
            }
        }
    },

    _showFeedback(message) {
        const feedback = this._getFeedback();
        if (!feedback) {
            return;
        }
        feedback.textContent = message || "";
        feedback.classList.toggle("d-none", !message);
    },

    _setVerificationSuccess(message) {
        const root = this._getRoot();
        const success = this._getSuccessBox();

        if (root) {
            root.dataset.lxOk = "1";
            root.classList.add("d-none");
        }
        if (success) {
            success.textContent = message || "Authorization successful. You can proceed to checkout.";
            success.classList.remove("d-none");
        }
        this._showFeedback("");
    },

    _showValidateForm() {
        const form = this._getForm();
        if (!form) {
            return;
        }
        form.classList.remove("d-none");
        form.setAttribute("aria-hidden", "false");

        const input = document.getElementById("lx-code-input");
        if (input) {
            try {
                input.focus({ preventScroll: true });
            } catch (_) {
                input.focus();
            }
        }
    },

    _hideValidateForm() {
        const form = this._getForm();
        if (!form) {
            return;
        }
        form.classList.add("d-none");
        form.setAttribute("aria-hidden", "true");
        this._showFeedback("");
    },

    _openHelpdesk() {
        const { helpdeskUrl, token } = this._rootData();
        if (!helpdeskUrl) {
            return;
        }
        try {
            const url = new URL(helpdeskUrl, window.location.origin);
            url.searchParams.set("subject", HELP_SUBJECT);
            url.searchParams.set("msg", HELP_MESSAGE);
            if (token) {
                url.searchParams.set("lx_token", token);
            }
            window.open(url.toString(), "_blank");
        } catch (_) {
            // Keep the cart usable even if the helpdesk URL is malformed.
        }
    },

    _bindCurrentDom() {
        const helpdeskButton = document.getElementById("lx-helpdesk-btn");
        if (helpdeskButton && !helpdeskButton._lxBound) {
            helpdeskButton._lxBound = true;
            helpdeskButton.addEventListener("click", (event) => {
                event.preventDefault();
                this._openHelpdesk();
                this._showValidateForm();
                const form = this._getForm();
                if (form) {
                    form.scrollIntoView({ behavior: "smooth", block: "center" });
                }
            });
        }

        const form = this._getForm();
        if (form && !form._lxBound) {
            form._lxBound = true;
            form.addEventListener("submit", (event) => this._postValidateXHR(event));
        }

        if (!this._qtyListenerBound) {
            this._qtyListenerBound = true;
            const schedule = () => this._scheduleQtySync();
            document.addEventListener("click", (event) => {
                const target = event.target;
                if (!(target instanceof Element)) {
                    return;
                }
                if (target.closest(".css_quantity button, .css_quantity a, .bootstrap-touchspin-up, .bootstrap-touchspin-down")) {
                    schedule();
                }
            }, true);
            document.addEventListener("change", (event) => {
                const target = event.target;
                if (target instanceof HTMLInputElement && target.classList.contains("js_quantity")) {
                    schedule();
                }
            }, true);
            document.addEventListener("input", (event) => {
                const target = event.target;
                if (target instanceof HTMLInputElement && target.classList.contains("js_quantity")) {
                    schedule();
                }
            }, true);
        }
    },

    _installObservers() {
        if (document.body && !this._observer) {
            this._observer = new MutationObserver(() => {
                this._bindCurrentDom();
                this._scheduleSync();
            });
            this._observer.observe(document.body, {
                childList: true,
                subtree: true,
                characterData: true,
            });
        }

        window.addEventListener("pageshow", () => {
            this._bindCurrentDom();
            this._syncVisibility();
        });

        window.addEventListener("lx:cart:totals", (event) => {
            const total = event?.detail?.total;
            this._syncVisibility(Number.isFinite(total) ? total : NaN);
        });
    },

    _scheduleSync() {
        window.clearTimeout(this._syncTimeout);
        this._syncTimeout = window.setTimeout(() => this._syncVisibility(), 120);
    },

    _scheduleQtySync() {
        const checkpoints = [200, 600, 1200, 2200];
        const token = ++this._statusSyncToken;
        window.clearTimeout(this._qtySyncTimeout);
        let index = 0;
        const run = async () => {
            if (token !== this._statusSyncToken) {
                return;
            }
            await this._refreshFromServer();
            if (index >= checkpoints.length - 1) {
                return;
            }
            index += 1;
            this._qtySyncTimeout = window.setTimeout(run, checkpoints[index]);
        };
        this._qtySyncTimeout = window.setTimeout(run, checkpoints[index]);
    },

    async _refreshFromServer() {
        const root = this._getRoot();
        if (!root) {
            return;
        }

        let data;
        try {
            data = await rpc("/shop/order_limit_status", {});
        } catch (_) {
            this._syncVisibility();
            return;
        }

        if (!data?.ok) {
            this._syncVisibility();
            return;
        }

        root.dataset.lxLimit = String(data.limit || 0);
        root.dataset.lxTotal = String(data.total || 0);
        root.dataset.lxOk = data.verified ? "1" : "0";
        root.dataset.lxShouldShow = data.should_show ? "1" : "0";
        root.dataset.lxToken = data.token || "";
        const tokenInput = document.querySelector('#lx-validate-form input[name="lx_token"]');
        if (tokenInput) {
            tokenInput.value = data.token || "";
        }

        if (!data.should_show) {
            this._hideValidateForm();
        }

        this._syncVisibility(Number.isFinite(data.total) ? data.total : NaN);
    },

    _syncVisibility(totalOverride) {
        const root = this._getRoot();
        if (!root) {
            return;
        }

        const data = this._rootData();
        let total = isFiniteNumber(totalOverride) ? totalOverride : data.total;
        if (!isFiniteNumber(total) || total <= 0) {
            total = data.total;
        }
        if (!isFiniteNumber(total) || total <= 0) {
            total = this._readCartTotal();
        }

        const over = Boolean(data.limit) && isFiniteNumber(total) && total >= data.limit;
        const shouldShow = over && !data.ok;

        root.dataset.lxTotal = String(total || 0);
        root.classList.toggle("d-none", !shouldShow);

        if (!shouldShow) {
            this._hideValidateForm();
        }

        this._enforceCheckoutDisabled(shouldShow, total, data.limit);

        if (shouldShow && data.shouldShow && !this._didScrollToRoot) {
            this._didScrollToRoot = true;
            window.setTimeout(() => {
                const currentRoot = this._getRoot();
                if (currentRoot) {
                    currentRoot.scrollIntoView({ behavior: "smooth", block: "start" });
                }
            }, 250);
        }
    },

    async _postValidateXHR(event) {
        event.preventDefault();
        const form = this._getForm();
        if (!form) {
            return;
        }

        const button = document.getElementById("lx-validate-btn");
        const payload = new FormData(form);
        this._showFeedback("");

        if (button) {
            button.disabled = true;
        }

        try {
            const response = await fetch(form.getAttribute("action") || "/shop/order/validate_code", {
                method: "POST",
                headers: { "X-Requested-With": "XMLHttpRequest" },
                body: payload,
                credentials: "same-origin",
            });
            const data = await response.json();
            if (data?.ok) {
                this._setVerificationSuccess(data.message);
                this._syncVisibility();
                try {
                    window.dispatchEvent(new CustomEvent("lx:verify:ok"));
                } catch (_) {
                    // Ignore custom-event failures on older browsers.
                }
                return;
            }
            this._showFeedback(data?.message || "Invalid code.");
        } catch (_) {
            this._showFeedback("An error occurred. Please try again.");
        } finally {
            if (button) {
                button.disabled = false;
            }
        }
    },

    _printDebug() {
        const root = this._getRoot();
        const form = this._getForm();
        const data = this._rootData();
        const domTotal = this._readCartTotal();

        const debug = {
            root_exists: Boolean(root),
            form_exists: Boolean(form),
            limit: data.limit,
            total: data.total,
            dom_total: isFiniteNumber(domTotal) ? domTotal : "NaN",
            ok: data.ok,
            should_show: data.shouldShow,
            token: data.token || "NO_TOKEN",
        };

        window.__lxOrderLimitDebug = debug;

        console.group("[Luxtor] Cart order-limit");
        console.log(debug);
        if (root) {
            console.log("lx-limit-root rect:", root.getBoundingClientRect());
            console.log("lx-limit-root text:", root.innerText);
        }
        console.groupEnd();

        if (this._debugEnabled) {
            alert(
                "Luxtor debug\n"
                + `limit=${debug.limit}\n`
                + `total=${debug.total}\n`
                + `dom_total=${debug.dom_total}\n`
                + `ok=${debug.ok}\n`
                + `should_show=${debug.should_show}\n`
                + `token=${debug.token}`
            );
        }
    },
});

export default publicWidget.registry.LxCartOrderLimit;
