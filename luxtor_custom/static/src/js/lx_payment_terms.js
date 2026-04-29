/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

publicWidget.registry.LxPaymentTerms = publicWidget.Widget.extend({
    selector: "#payment_method .lx-payment-form",

    start() {
        this._super(...arguments);
        this.el.addEventListener("change", (ev) => {
            const input = ev.target;
            if (!(input instanceof HTMLInputElement) || input.name !== "lx_payment_terms") {
                return;
            }
            this._syncSelection(input.value);
        });
        return Promise.resolve();
    },

    async _syncSelection(choice) {
        if (!choice) {
            return;
        }
        try {
            const res = await rpc("/shop/payment/update_terms", {
                lx_payment_terms: choice,
            });
            if (!res || !res.ok) {
                return;
            }
            this._applySummary(res.summary || {}, res.currency || {});
        } catch (_) {
            // Keep the current UI if the preview sync fails; final submit still persists.
        }
    },

    _applySummary(summary, currency) {
        this._setText("lx_payment_choice_label", summary.choice_label || "");
        this._setMoney("lx_payment_due_now_value", summary.order_total, currency);
        this._setMoney("lx_payment_remaining_value", summary.remaining_to_pay, currency);

        const partial = !!summary.is_partial;
        const totalLabel = document.getElementById("lx_payment_total_label");
        if (totalLabel) {
            totalLabel.textContent = partial ? "Amount due now" : "Total";
        }
        this._setMoney("lx_payment_order_total", partial ? summary.amount_due_now : summary.order_total, currency);

        const remainingRows = [
            document.getElementById("lx_payment_remaining_row"),
            document.getElementById("lx_payment_order_total_row"),
        ];
        for (const row of remainingRows) {
            if (row) {
                row.classList.toggle("d-none", !partial);
            }
        }
    },

    _setText(id, value) {
        const el = document.getElementById(id);
        if (el) {
            el.textContent = value || "";
        }
    },

    _setMoney(id, value, currency) {
        const el = document.getElementById(id);
        if (!el || typeof value !== "number") {
            return;
        }
        el.textContent = this._formatMoney(value, currency);
    },

    _formatMoney(amount, currency) {
        const dp = Number.isFinite(currency?.decimal_places) ? currency.decimal_places : 2;
        const symbol = currency?.symbol || "";
        const position = currency?.position || "after";
        const fixed = Number(amount || 0).toFixed(dp);
        if (!symbol) {
            return fixed;
        }
        return position === "before" ? `${symbol} ${fixed}` : `${fixed} ${symbol}`;
    },
});

export default publicWidget.registry.LxPaymentTerms;
