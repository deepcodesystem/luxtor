/** @odoo-module **/
/**
 * Product page widgets:
 *   - LxHeadrailTitles        — inject card titles on headrail variant attribute
 */

import publicWidget from "@web/legacy/js/public/public_widget";

publicWidget.registry.LxHeadrailTitles = publicWidget.Widget.extend({
    selector: '.oe_website_sale',

    start() {
        this._styleDimensionLabels();
        this._applyTitles();
        this._renameHeaderText();
        this._resetImageBorders();
        this._bindCassetteZoom();

        this._onChange = () => {
            this._styleDimensionLabels();
            this._applyTitles();
            this._renameHeaderText();
            this._resetImageBorders();
            this._bindCassetteZoom();
        };
        this.el.addEventListener('change', this._onChange, { passive: true });
        this.el.addEventListener('click',  this._onChange, { passive: true });
        document.addEventListener('combination_found', this._onChange, true);

        // Observe the stable wrapper — js_add_cart_variants gets replaced by Odoo
        this._observer = new MutationObserver(() => {
            this._styleDimensionLabels();
            this._applyTitles();
            this._renameHeaderText();
            this._resetImageBorders();
            this._bindCassetteZoom();
        });
        this._observer.observe(this.el, { childList: true, subtree: true, characterData: true });

        return this._super(...arguments);
    },

    destroy() {
        this._hideCassettePreview();
        if (this._observer) this._observer.disconnect();
        if (this._onChange) {
            this.el.removeEventListener('change', this._onChange);
            this.el.removeEventListener('click',  this._onChange);
            document.removeEventListener('combination_found', this._onChange, true);
        }
        return this._super(...arguments);
    },

    _renameHeaderText() {
        this.el.querySelectorAll(
            'li.variant_attribute .o_variant_selected_value, li.variant_attribute h6.attribute_name span.text-muted'
        ).forEach((span) => {
            const t = span.textContent || '';
            const r = t.replace(/R-?002-?21/gi, 'Futura').replace(/R-?002-?22/gi, 'Futura+');
            if (r !== t) span.textContent = r;
        });
    },

    _mapPrettyName(name) {
        const n = (name || '').trim();
        if (/R-?002-?21/i.test(n)) return 'Futura';
        if (/R-?002-?22/i.test(n)) return 'Futura +';
        return n;
    },

    _styleDimensionLabels() {
        const labels = this.el.querySelectorAll(
            '#lx_dims_express .lx-dim-heading, #lx_dims_express label[for="lx_location_input"], #lx_dims_express label[for="lx_width_input"], #lx_dims_express label[for="lx_height_input"]'
        );
        labels.forEach((label) => {
            label.style.setProperty('display', 'block', 'important');
            label.style.setProperty('margin', '0 0 0.5rem 0', 'important');
            label.style.setProperty('padding', '0', 'important');
            label.style.setProperty('border', '0', 'important');
            label.style.setProperty('background', 'transparent', 'important');
            label.style.setProperty('text-transform', 'uppercase', 'important');
            label.style.setProperty('font-size', '0.82rem', 'important');
            label.style.setProperty('font-weight', '700', 'important');
            label.style.setProperty('letter-spacing', '0.05em', 'important');
            label.style.setProperty('color', '#6b7280', 'important');
            label.style.setProperty('line-height', '1.2', 'important');
            label.style.setProperty('font-style', 'normal', 'important');
            label.style.setProperty('font-family', '"Poppins", "Odoo Unicode Support Noto", sans-serif', 'important');
            label.style.setProperty('text-align', 'left', 'important');
            label.style.setProperty('box-shadow', 'none', 'important');

            const badge = label.querySelector('.notificationmessage');
            if (badge) {
                badge.style.setProperty('text-transform', 'none', 'important');
                badge.style.setProperty('font-weight', '400', 'important');
                badge.style.setProperty('letter-spacing', 'normal', 'important');
            }
        });
    },

    _bindCassetteZoom() {
        if (window.matchMedia && window.matchMedia('(pointer: coarse)').matches) {
            return;
        }
        this._ensureCassettePreview();
        this.el.querySelectorAll(
            '.js_add_cart_variants > li.variant_attribute:first-of-type label.css_attribute_image,' +
            '.js_add_cart_variants > li.variant_attribute:first-of-type label.css_attribute_color'
        ).forEach((label) => {
            if (label.dataset.lxZoomBound === '1') {
                return;
            }
            label.dataset.lxZoomBound = '1';
            label.style.setProperty('transition', 'outline-color .24s ease, transform .32s cubic-bezier(.16,1,.3,1), box-shadow .24s ease', 'important');

            label.addEventListener('mouseenter', (event) => {
                label.style.setProperty('transform', 'translateY(-2px) scale(1.03)', 'important');
                label.style.setProperty('box-shadow', '0 18px 40px rgba(15, 23, 42, .14)', 'important');
                this._showCassettePreview(label, event);
            });

            label.addEventListener('mousemove', (event) => {
                const rect = label.getBoundingClientRect();
                if (!rect.width || !rect.height) {
                    return;
                }
                const x = Math.max(0, Math.min(100, ((event.clientX - rect.left) / rect.width) * 100));
                const y = Math.max(0, Math.min(100, ((event.clientY - rect.top) / rect.height) * 100));
                this._moveCassettePreview(label, x, y);
            });

            label.addEventListener('mouseleave', () => {
                label.style.setProperty('transform', 'translateY(0) scale(1)', 'important');
                label.style.setProperty('box-shadow', 'none', 'important');
                this._hideCassettePreview();
            });
        });
    },

    _ensureCassettePreview() {
        if (this._cassettePreviewEl?.isConnected) {
            return this._cassettePreviewEl;
        }
        const preview = document.createElement('div');
        preview.className = 'lx-cassette-zoom-popup';
        preview.innerHTML = '<div class="lx-cassette-zoom-surface"></div>';
        document.body.appendChild(preview);
        this._cassettePreviewEl = preview;
        this._cassettePreviewSurfaceEl = preview.querySelector('.lx-cassette-zoom-surface');
        return preview;
    },

    _showCassettePreview(label, event) {
        const preview = this._ensureCassettePreview();
        const surface = this._cassettePreviewSurfaceEl;
        if (!preview || !surface) {
            return;
        }
        const style = window.getComputedStyle(label);
        surface.style.backgroundImage = style.backgroundImage;
        surface.style.backgroundColor = style.backgroundColor;
        surface.style.backgroundRepeat = 'no-repeat';
        surface.style.backgroundSize = '300% auto';
        surface.style.backgroundPosition = '50% 50%';
        preview.classList.add('is-visible');
        if (event) {
            const rect = label.getBoundingClientRect();
            const x = Math.max(0, Math.min(100, ((event.clientX - rect.left) / rect.width) * 100));
            const y = Math.max(0, Math.min(100, ((event.clientY - rect.top) / rect.height) * 100));
            this._moveCassettePreview(label, x, y);
        }
    },

    _moveCassettePreview(label, x, y) {
        const preview = this._cassettePreviewEl;
        const surface = this._cassettePreviewSurfaceEl;
        if (!preview || !surface) {
            return;
        }
        const rect = label.getBoundingClientRect();
        const popupWidth = 320;
        const popupHeight = 320;
        const gap = 18;
        let left = rect.right + gap;
        let top = rect.top + (rect.height / 2) - (popupHeight / 2);

        if (left + popupWidth > window.innerWidth - 16) {
            left = rect.left - popupWidth - gap;
        }
        if (left < 16) {
            left = Math.max(16, window.innerWidth - popupWidth - 16);
        }
        top = Math.max(16, Math.min(top, window.innerHeight - popupHeight - 16));

        preview.style.left = `${left}px`;
        preview.style.top = `${top}px`;
        surface.style.backgroundPosition = `${x}% ${y}%`;
    },

    _hideCassettePreview() {
        if (this._cassettePreviewEl) {
            this._cassettePreviewEl.classList.remove('is-visible');
        }
    },

    _stripHoverTitles(scope) {
        const root = scope || this.el;
        root.querySelectorAll(
            '.js_add_cart_variants > li.variant_attribute:first-of-type li.list-inline-item,' +
            '.js_add_cart_variants > li.variant_attribute:first-of-type label.css_attribute_image,' +
            '.js_add_cart_variants > li.variant_attribute:first-of-type label.css_attribute_color,' +
            '.js_add_cart_variants > li.variant_attribute:first-of-type label.css_attribute_image *,' +
            '.js_add_cart_variants > li.variant_attribute:first-of-type label.css_attribute_color *,' +
            '.js_add_cart_variants > li.variant_attribute:first-of-type input.js_variant_change'
        ).forEach((node) => {
            node.removeAttribute('title');
            node.removeAttribute('data-bs-original-title');
        });
    },

    // Strip inline border-color Odoo injects from attribute value html_color
    _resetImageBorders() {
        this.el.querySelectorAll(
            '.js_add_cart_variants > li.variant_attribute:first-of-type label.css_attribute_image,' +
            '.js_add_cart_variants > li.variant_attribute:first-of-type label.css_attribute_color'
        ).forEach((label) => {
            label.style.removeProperty('border-color');
            label.style.removeProperty('border');
        });
        this._stripHoverTitles();
    },

    _applyTitles() {
        const variants = this.el.querySelector('.js_add_cart_variants');
        if (!variants) return;

        const firstAttr = variants.querySelector('li.variant_attribute');
        if (!firstAttr) return;

        firstAttr.querySelectorAll('li.list-inline-item').forEach((item) => {
            // V18: css_attribute_color | V19 image display type: css_attribute_image
            const label = item.querySelector('label.css_attribute_color, label.css_attribute_image');
            if (!label) return;
            const input = item.querySelector('input.js_variant_change');

            const raw = (input && (input.getAttribute('data-value_name') || input.dataset.value_name))
                        || label.getAttribute('title')
                        || '';
            const pretty = this._mapPrettyName(raw);
            label.removeAttribute('title');
            item.removeAttribute('title');
            if (input) {
                input.removeAttribute('title');
            }

            let span = label.querySelector('.lx-var-title');
            if (!span) {
                span = document.createElement('span');
                span.className = 'lx-var-title';
                label.appendChild(span);
            }
            if (span.textContent !== pretty) {
                span.textContent = pretty;
            }
        });

        this._stripHoverTitles(variants);
    },
});
