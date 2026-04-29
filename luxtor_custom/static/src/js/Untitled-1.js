/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

publicWidget.registry.LxLiveVariantWHPreview = publicWidget.Widget.extend({
  selector: ".oe_website_sale",
  start() {
    const r = this._super(...arguments);
    const form = document.querySelector("form[action*='/shop/cart']");
    let box = document.getElementById("lx-dim-preview");
    if (!box) {
      box = document.createElement("div");
      box.id = "lx-dim-preview";
      box.className = "alert alert-info mb-3";
      box.textContent = "—";
      if (form) {
        form.insertBefore(box, form.firstChild);   // insert at top of form
      } else {
        document.body.insertBefore(box, document.body.firstChild);
      }
    }

    const readVariants = () => {
      const out = [];
      const radios = document.querySelectorAll(".js_variant_change[type='radio']:checked, .js_variant_change[type='checkbox']:checked");
      let i = 0;
      for (i = 0; i < radios.length; i += 1) {
        const el = radios[i];
        let v = el.getAttribute("data-value_name") || el.title || "";
        if (!v) {
          const lid = el.getAttribute("id");
          if (lid) {
            const lab = document.querySelector("label[for='" + lid + "']");
            if (lab) { v = (lab.textContent || "").trim(); }
          }
        }
        if (v) { out.push(v); }
      }
      const selects = document.querySelectorAll("select.js_variant_change");
      let j = 0;
      for (j = 0; j < selects.length; j += 1) {
        const s = selects[j];
        let t = "";
        if (s.selectedIndex >= 0) {
          const o = s.options[s.selectedIndex];
          if (o) { t = (o.text || "").trim(); }
        }
        if (t) { out.push(t); }
      }
      return out;
    };

    const update = () => {
      let name = "";
      const h1 = document.querySelector("h1[itemprop='name']");
      if (h1) { name = h1.textContent || ""; }

      let W = "1";
      let H = "1";
      const wi = document.querySelector("#lx_width_input");
      if (wi && wi.value) { W = wi.value; }
      const hi = document.querySelector("#lx_height_input");
      if (hi && hi.value) { H = hi.value; }

      const v = readVariants();
      const parts = [];
      if (name) { parts.push(name); }
      if (v.length) { parts.push(v.join(" · ")); }
      parts.push("(" + W + "m * " + H + "m)");

      box.textContent = parts.join(" - ");
    };

    document.addEventListener("input", function(){ update(); }, true);
    update();
    setTimeout(update, 50);
    setTimeout(update, 200);
    return r;
  },
});

export default publicWidget.registry.LxLiveVariantWHPreview;
