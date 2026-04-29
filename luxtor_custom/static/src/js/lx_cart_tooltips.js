/** @odoo-module **/
/**
 * LxCartExcelTips — Tooltip cards on Remote / ZigBee / Charger cart lines.
 */

import publicWidget from "@web/legacy/js/public/public_widget";

const CART_ROOT_SELECTOR = "#cart_products";
const GROUP_CLASS = "lx-product-group";
const GROUP_SELECTOR = `.${GROUP_CLASS}`;
const PARENT_ROW_SELECTOR = ".o_cart_product[data-lx-line-id]";
const ACC_BLOCK_SELECTOR = ".lx-acc-block[data-lx-parent-id]";
const ACC_LINE_SELECTOR = ".lx_accessory_line";

const CART_TIPS = {
    REMOTE: `
        <div class="lx-bullet">Not required, one Remote controls up to <strong>5 Roller blinds</strong>.</div>
        <div class="lx-tipline">
            Tip: For installation on another floor or in another home, please add the necessary remotes in the
            <strong>"Available options"</strong> section.
        </div>
    `,
    ZIGBEE: `
        <div class="lx-bullet">Not required, one ZigBee Gateway can manage up to <strong>30 Roller blinds</strong>.</div>
        <div class="lx-tipline">
            Tip: For installation on another floor or in another home, please add the necessary ZigBee Gateways in the
            <strong>"Available options"</strong> section.
        </div>
    `,
    CHARGER: `
        <div class="lx-bullet">Not required, one Charger can power all devices.</div>
        <div class="lx-tipline">
            Tip: For installation on another floor or in another home, please add the necessary chargers in the
            <strong>"Available options"</strong> section.
        </div>
    `,
};

function addCartTooltip(el, html) {
    if (!el || el.querySelector(".lx-cart-tipwrap")) return;

    const wrap = document.createElement("span");
    wrap.className = "lx-cart-tipwrap";

    const q = document.createElement("span");
    q.className = "lx-cart-q";
    q.textContent = "?";

    const box = document.createElement("div");
    box.className = "lx-cart-tipbox";
    box.innerHTML = html;

    wrap.appendChild(q);
    wrap.appendChild(box);

    const br = el.querySelector("br");
    if (br) el.insertBefore(wrap, br);
    else el.appendChild(wrap);

    el.style.display = "inline-flex";
    el.style.alignItems = "center";
    el.style.gap = "6px";
}

function parseSortNumber(value, fallback = 0) {
    const number = Number.parseInt(value || "", 10);
    return Number.isNaN(number) ? fallback : number;
}

/**
 * Match each .lx-acc-block[data-lx-parent-id] to its parent
 * .o_cart_product[data-lx-line-id] using server-assigned IDs,
 * then wrap both in a .lx-product-group card.
 * DOM order doesn't matter — IDs are the source of truth.
 */
function unwrapProductGroups(root) {
    root.querySelectorAll(GROUP_SELECTOR).forEach((group) => {
        const parent = group.parentNode;
        if (!parent) return;
        while (group.firstChild) {
            parent.insertBefore(group.firstChild, group);
        }
        group.remove();
    });
}

function collectElementsByDataset(root, selector, datasetKey) {
    const elementsById = new Map();

    root.querySelectorAll(selector).forEach((element) => {
        const id = (element.dataset[datasetKey] || "").trim();
        if (!id) return;
        if (!elementsById.has(id)) {
            elementsById.set(id, []);
        }
        elementsById.get(id).push(element);
    });

    return elementsById;
}

function collapseDuplicateParentRows(parentRowsById) {
    const canonicalParents = new Map();

    parentRowsById.forEach((rows, parentId) => {
        if (!rows.length) return;
        const canonicalRow = rows[rows.length - 1];
        rows.slice(0, -1).forEach((row) => row.remove());
        canonicalParents.set(parentId, canonicalRow);
    });

    return canonicalParents;
}

function mergeAccessoryBlocks(accBlocks) {
    if (!accBlocks.length) return null;

    const canonicalBlock = accBlocks[accBlocks.length - 1];
    const accessoryRows = [];
    const seenRowKeys = new Set();

    accBlocks.forEach((block) => {
        Array.from(block.children).forEach((child) => {
            if (!(child instanceof HTMLElement)) {
                return;
            }

            if (!child.classList.contains(ACC_LINE_SELECTOR.slice(1))) {
                if (block !== canonicalBlock) {
                    canonicalBlock.appendChild(child);
                }
                return;
            }

            const rowKey = (child.dataset.lxAccLineId || "").trim()
                || `${child.dataset.productId || ""}:${(child.textContent || "").trim()}`;
            if (seenRowKeys.has(rowKey)) {
                child.remove();
                return;
            }

            seenRowKeys.add(rowKey);
            accessoryRows.push(child);
        });
    });

    accessoryRows.sort((left, right) => {
        const leftSequence = parseSortNumber(left.dataset.lxSequence);
        const rightSequence = parseSortNumber(right.dataset.lxSequence);
        if (leftSequence !== rightSequence) {
            return leftSequence - rightSequence;
        }
        return parseSortNumber(left.dataset.lxAccLineId) - parseSortNumber(right.dataset.lxAccLineId);
    });

    if (!accessoryRows.length) {
        accBlocks.forEach((block) => block.remove());
        return null;
    }

    canonicalBlock.replaceChildren(...accessoryRows);
    accBlocks.forEach((block) => {
        if (block !== canonicalBlock) {
            block.remove();
        }
    });

    return canonicalBlock;
}

function groupCartLines(root) {
    unwrapProductGroups(root);

    const parentRows = collapseDuplicateParentRows(
        collectElementsByDataset(root, PARENT_ROW_SELECTOR, "lxLineId")
    );
    const accBlocksByParentId = collectElementsByDataset(root, ACC_BLOCK_SELECTOR, "lxParentId");

    accBlocksByParentId.forEach((accBlocks, parentId) => {
        const parentRow = parentRows.get(parentId);
        if (!parentRow || !parentRow.parentNode) {
            return;
        }

        const mergedBlock = mergeAccessoryBlocks(accBlocks);
        if (!mergedBlock) {
            return;
        }

        const group = document.createElement("div");
        group.className = GROUP_CLASS;

        parentRow.parentNode.insertBefore(group, parentRow);
        group.appendChild(parentRow);
        group.appendChild(mergedBlock);
    });
}

function decorateCartLines(root) {
    // Rebuild groups from data attributes only. This avoids stale wrappers
    // or wrong pairings caused by incremental AJAX DOM updates.
    groupCartLines(root);

    // Parent rows — text-based tooltip matching
    root.querySelectorAll(".o_cart_product h6").forEach((h6) => {
        const text = (h6.textContent || "").toUpperCase();
        if (text.includes("REMOTE CONTROL")) addCartTooltip(h6, CART_TIPS.REMOTE);
        else if (text.includes("ZIGBEE"))    addCartTooltip(h6, CART_TIPS.ZIGBEE);
        else if (text.includes("CHARGER"))   addCartTooltip(h6, CART_TIPS.CHARGER);
    });

    // Accessory rows — data-lx-tip set by QWeb
    root.querySelectorAll(".lx_accessory_line[data-lx-tip]").forEach((row) => {
        const key  = row.dataset.lxTip;
        const html = CART_TIPS[key];
        if (!html) return;
        const nameEl = row.querySelector(".fw-normal");
        if (nameEl) addCartTooltip(nameEl, html);
    });
}

publicWidget.registry.LxCartExcelTips = publicWidget.Widget.extend({
    selector: CART_ROOT_SELECTOR,

    start() {
        const res = this._super(...arguments);
        this._decorateTimer = null;
        this._isApplyingDecorations = false;
        this._setupObservers();
        this._scheduleDecorate(0);
        return res;
    },

    _setupObservers() {
        this._disconnectObservers();
        this._observeRoot(this._getCurrentRoot());
        this._observeDocument();
    },

    _disconnectObservers() {
        if (this._rootObserver) {
            this._rootObserver.disconnect();
        }
        if (this._documentObserver) {
            this._documentObserver.disconnect();
        }
    },

    _getCurrentRoot() {
        const liveRoot = document.querySelector(this.selector);
        if (liveRoot) {
            return liveRoot;
        }
        return this.el && document.contains(this.el) ? this.el : null;
    },

    _observeRoot(root) {
        if (!root) {
            return;
        }

        if (this._rootObserver) {
            this._rootObserver.disconnect();
        }
        this.el = root;
        this._rootObserver = new MutationObserver((mutations) => {
            if (this._isApplyingDecorations) {
                return;
            }
            const hasStructuralChange = mutations.some(
                (mutation) => mutation.type === "childList"
                    && (mutation.addedNodes.length || mutation.removedNodes.length)
            );
            if (hasStructuralChange) {
                this._scheduleDecorate();
            }
        });
        this._rootObserver.observe(root, { childList: true, subtree: true });
    },

    _observeDocument() {
        if (!document.body) {
            return;
        }

        this._documentObserver = new MutationObserver((mutations) => {
            if (this._isApplyingDecorations) {
                return;
            }

            const currentRoot = this._getCurrentRoot();
            if (currentRoot !== this.el) {
                this._observeRoot(currentRoot);
                this._scheduleDecorate(0);
                return;
            }

            const cartRootTouched = mutations.some((mutation) =>
                [...mutation.addedNodes, ...mutation.removedNodes].some((node) =>
                    node.nodeType === Node.ELEMENT_NODE
                    && (node.id === "cart_products" || node.querySelector?.(this.selector))
                )
            );
            if (cartRootTouched) {
                this._scheduleDecorate();
            }
        });
        this._documentObserver.observe(document.body, { childList: true, subtree: true });
    },

    _scheduleDecorate(delay = 120) {
        clearTimeout(this._decorateTimer);
        this._decorateTimer = setTimeout(() => this._applyDecorations(), delay);
    },

    _applyDecorations() {
        if (this._isApplyingDecorations) {
            return;
        }

        const root = this._getCurrentRoot();
        if (!root) {
            return;
        }

        this._isApplyingDecorations = true;
        this._disconnectObservers();

        try {
            this.el = root;
            decorateCartLines(root);
        } finally {
            this._isApplyingDecorations = false;
            this._observeRoot(this._getCurrentRoot());
            this._observeDocument();
        }
    },

    destroy() {
        clearTimeout(this._decorateTimer);
        this._disconnectObservers();
        return this._super(...arguments);
    },
});

export default publicWidget.registry.LxCartExcelTips;
