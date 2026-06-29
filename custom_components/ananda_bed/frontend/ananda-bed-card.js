/**
 * Ananda Bed Lovelace Card (Vanilla Web Component)
 *
 * Custom card for controlling an Ananda adjustable bed base.
 * No framework dependencies -- pure HTMLElement + Shadow DOM.
 *
 * Config:
 *   type: custom:ananda-bed-card
 *   name: ananda_bed   # entity name prefix
 */

class AnandaBedCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = null;
  }

  // --- HA Card API ---

  setConfig(config) {
    if (!config.name) {
      // Try to auto-detect: find any cover entity ending in _head from our integration
      config = { ...config, name: "" }; // will be resolved on first hass set
    }
    this._config = config;
    if (this._hass) this._render();
  }

  set hass(hass) {
    const oldHass = this._hass;
    this._hass = hass;
    // Auto-detect entity prefix if not configured
    if (!this._config.name) {
      const cover = Object.keys(hass.states).find(
        (e) => e.startsWith("cover.") && e.endsWith("_head")
      );
      if (cover) {
        this._config = { ...this._config, name: cover.slice(6, -5) };
      }
    }
    // Only re-render if our relevant entities changed
    if (!this._config.name) return;
    const prefix = this._config.name;
    const entities = [`cover.${prefix}_head`, `cover.${prefix}_feet`,
      `select.${prefix}_head_vibration`, `select.${prefix}_feet_vibration`];
    const changed = !oldHass || entities.some(
      (e) => hass.states[e] !== oldHass.states[e]
    );
    if (changed) this._render();
  }

  getCardSize() {
    return 6;
  }

  // GUI config editor for the card picker
  static getConfigElement() {
    return document.createElement("ananda-bed-card-editor");
  }

  // --- Entity helpers ---

  _entity(domain, suffix) {
    return `${domain}.${this._config.name}_${suffix}`;
  }

  _coverPos(part) {
    const e = this._hass.states[this._entity("cover", part)];
    return e ? e.attributes.current_position || 0 : 0;
  }

  _coverTarget(part) {
    const e = this._hass.states[this._entity("cover", part)];
    return e ? e.attributes.target_position : null;
  }

  _selectState(part) {
    const e = this._hass.states[this._entity("select", part)];
    return e ? e.state : "off";
  }

  // --- Actions ---

  _setCoverPosition(part, position) {
    this._hass.callService("cover", "set_cover_position", {
      entity_id: this._entity("cover", part),
      position: parseInt(position),
    });
  }

  _coverAction(part, action) {
    this._hass.callService("cover", action, {
      entity_id: this._entity("cover", part),
    });
  }

  _pressButton(suffix) {
    this._hass.callService("button", "press", {
      entity_id: this._entity("button", suffix),
    });
  }

  _setVibration(part, option) {
    this._hass.callService("select", "select_option", {
      entity_id: this._entity("select", part),
      option,
    });
  }

  // --- Rendering ---

  _render() {
    if (!this._hass || !this._config) return;

    const headPos = this._coverPos("head");
    const feetPos = this._coverPos("feet");
    const headTarget = this._coverTarget("head");
    const feetTarget = this._coverTarget("feet");
    const headLabel = headTarget != null ? `Head ${headPos}% → ${headTarget}%` : `Head ${headPos}%`;
    const feetLabel = feetTarget != null ? `Feet ${feetPos}% → ${feetTarget}%` : `Feet ${feetPos}%`;
    const headVib = this._selectState("head_vibration");
    const feetVib = this._selectState("feet_vibration");
    const title = this._config.title || this._config.name.replace(/_/g, " ");

    const vibOptions = ["off", "low", "medium", "high"];

    const vibButtons = (part, current) =>
      vibOptions
        .map(
          (opt) =>
            `<button class="seg-btn ${current === opt ? "active" : ""}" data-vib="${part}" data-opt="${opt}">${opt}</button>`
        )
        .join("");

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        .card-content { padding: 16px; }
        .section { margin-bottom: 16px; }
        .section-title {
          font-size: 0.9em; font-weight: 500; text-transform: uppercase;
          color: var(--secondary-text-color, #888); margin-bottom: 8px;
        }

        /* Position */
        .position-row { display: flex; align-items: center; justify-content: space-around; }
        .slider-group { display: flex; flex-direction: column; align-items: center; gap: 4px; }
        .slider-label { font-size: 0.85em; }
        .slider-controls { display: flex; flex-direction: column; align-items: center; }
        .vertical-slider {
          writing-mode: vertical-lr; direction: rtl;
          height: 120px; width: 28px; margin: 4px 0;
          accent-color: var(--primary-color, #03a9f4);
        }
        .bed-icon { font-size: 2em; color: var(--secondary-text-color, #888); }

        /* Buttons (generic) */
        .icon-btn {
          background: none; border: none; cursor: pointer; padding: 8px;
          border-radius: 50%; color: var(--primary-text-color, #333);
          font-size: 1.2em; line-height: 1;
        }
        .icon-btn:hover { background: var(--secondary-background-color, #eee); }

        /* Presets */
        .preset-row { display: flex; justify-content: space-around; flex-wrap: wrap; gap: 8px; }
        .preset-btn {
          display: flex; flex-direction: column; align-items: center;
          cursor: pointer; padding: 8px 12px; border-radius: 8px;
          border: none; background: none; font-size: 0.8em;
          color: var(--primary-text-color, #333);
        }
        .preset-btn:hover { background: var(--secondary-background-color, #eee); }
        .preset-btn span.icon { font-size: 1.5em; margin-bottom: 4px; }

        /* Pillow */
        .pillow-row { display: flex; align-items: center; justify-content: center; gap: 16px; }
        .pillow-icon { font-size: 1.5em; color: var(--secondary-text-color, #888); }

        /* Vibration */
        .vibration-row { display: flex; gap: 16px; flex-wrap: wrap; }
        .vibration-group { flex: 1; min-width: 140px; }
        .vibration-group label { display: block; font-size: 0.85em; margin-bottom: 4px; }
        .segmented {
          display: flex; border: 1px solid var(--divider-color, #ddd); border-radius: 8px; overflow: hidden;
        }
        .seg-btn {
          flex: 1; padding: 6px 4px; border: none; background: none;
          cursor: pointer; font-size: 0.75em; text-transform: capitalize;
          color: var(--primary-text-color, #333);
        }
        .seg-btn:not(:last-child) { border-right: 1px solid var(--divider-color, #ddd); }
        .seg-btn.active {
          background: var(--primary-color, #03a9f4);
          color: var(--text-primary-color, #fff);
        }
        .seg-btn:hover:not(.active) { background: var(--secondary-background-color, #eee); }
      </style>

      <ha-card header="${title}">
        <div class="card-content">
          <!-- Position -->
          <div class="section">
            <div class="section-title">Position</div>
            <div class="position-row">
              <div class="slider-group">
                <div class="slider-label">${headLabel}</div>
                <div class="slider-controls">
                  <button class="icon-btn" data-cover="head" data-action="open_cover">&#9650;</button>
                  <input type="range" min="0" max="100" value="${headPos}" class="vertical-slider" data-slider="head">
                  <button class="icon-btn" data-cover="head" data-action="close_cover">&#9660;</button>
                </div>
                <button class="icon-btn" data-cover="head" data-action="stop_cover">&#9632;</button>
              </div>
              <div class="bed-icon">&#128716;</div>
              <div class="slider-group">
                <div class="slider-label">${feetLabel}</div>
                <div class="slider-controls">
                  <button class="icon-btn" data-cover="feet" data-action="open_cover">&#9650;</button>
                  <input type="range" min="0" max="100" value="${feetPos}" class="vertical-slider" data-slider="feet">
                  <button class="icon-btn" data-cover="feet" data-action="close_cover">&#9660;</button>
                </div>
                <button class="icon-btn" data-cover="feet" data-action="stop_cover">&#9632;</button>
              </div>
            </div>
          </div>

          <!-- Presets -->
          <div class="section">
            <div class="section-title">Presets</div>
            <div class="preset-row">
              <button class="preset-btn" data-preset="flat"><span class="icon">&#9644;</span>Flat</button>
              <button class="preset-btn" data-preset="preset_1"><span class="icon">&#8544;</span>I</button>
              <button class="preset-btn" data-preset="preset_2_tv"><span class="icon">&#8545;</span>II</button>
              <button class="preset-btn" data-preset="zero_gravity"><span class="icon">&#127756;</span>Zero-G</button>
              <button class="preset-btn" data-preset="anti_snore"><span class="icon">&#128564;</span>Snore</button>
            </div>
          </div>

          <!-- Pillow -->
          <div class="section">
            <div class="section-title">Pillow Tilt</div>
            <div class="pillow-row">
              <button class="icon-btn" data-preset="pillow_down">&#9660;</button>
              <span class="pillow-icon">&#8736;</span>
              <button class="icon-btn" data-preset="pillow_up">&#9650;</button>
            </div>
          </div>

          <!-- Vibration -->
          <div class="section">
            <div class="section-title">Vibration</div>
            <div class="vibration-row">
              <div class="vibration-group">
                <label>Head</label>
                <div class="segmented">${vibButtons("head_vibration", headVib)}</div>
              </div>
              <div class="vibration-group">
                <label>Feet</label>
                <div class="segmented">${vibButtons("feet_vibration", feetVib)}</div>
              </div>
            </div>
          </div>
        </div>
      </ha-card>
    `;

    // Attach event listeners via delegation
    this._attachEvents();
  }

  _attachEvents() {
    const root = this.shadowRoot;

    // Sliders
    root.querySelectorAll("[data-slider]").forEach((el) => {
      el.addEventListener("change", (e) => {
        this._setCoverPosition(e.target.dataset.slider, e.target.value);
      });
    });

    // Cover actions (open/stop/close)
    root.querySelectorAll("[data-cover]").forEach((el) => {
      el.addEventListener("click", (e) => {
        const btn = e.currentTarget;
        this._coverAction(btn.dataset.cover, btn.dataset.action);
      });
    });

    // Preset & pillow buttons
    root.querySelectorAll("[data-preset]").forEach((el) => {
      el.addEventListener("click", (e) => {
        this._pressButton(e.currentTarget.dataset.preset);
      });
    });

    // Vibration buttons
    root.querySelectorAll("[data-vib]").forEach((el) => {
      el.addEventListener("click", (e) => {
        const btn = e.currentTarget;
        this._setVibration(btn.dataset.vib, btn.dataset.opt);
      });
    });
  }
}

customElements.define("ananda-bed-card", AnandaBedCard);

// Simple GUI config editor for the card picker
class AnandaBedCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._built = false;
  }

  setConfig(config) {
    this._config = config;
    this._updateValues();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
  }

  _build() {
    this._built = true;
    const options = this._hass
      ? Object.keys(this._hass.states)
          .filter((e) => e.startsWith("cover.") && e.endsWith("_head"))
          .map((e) => e.slice(6, -5))
      : [];

    this.shadowRoot.innerHTML = `
      <style>
        .editor { padding: 16px; }
        label { display: block; margin-bottom: 4px; font-weight: 500; }
        select, input { width: 100%; padding: 8px; border: 1px solid var(--divider-color, #ccc); border-radius: 4px; box-sizing: border-box; margin-bottom: 12px; }
      </style>
      <div class="editor">
        <label for="title">Card Title</label>
        <input id="title" type="text" placeholder="e.g. Master Bedroom Bed">

        <label for="name">Bed (entity prefix)</label>
        ${options.length > 0
          ? `<select id="name">${options.map((o) => `<option value="${o}">${o}</option>`).join("")}</select>`
          : `<input id="name" type="text" placeholder="e.g. ananda_bed">`
        }
      </div>
    `;

    this.shadowRoot.getElementById("title").addEventListener("input", (e) => {
      this._config = { ...this._config, title: e.target.value };
      this._fireChanged();
    });

    this.shadowRoot.getElementById("name").addEventListener("change", (e) => {
      this._config = { ...this._config, name: e.target.value };
      this._fireChanged();
    });

    this._updateValues();
  }

  _updateValues() {
    if (!this._built) return;
    const titleEl = this.shadowRoot.getElementById("title");
    const nameEl = this.shadowRoot.getElementById("name");
    // Only update if not currently focused (don't fight the user)
    if (titleEl && document.activeElement !== titleEl && this.shadowRoot.activeElement !== titleEl) {
      titleEl.value = this._config.title || "";
    }
    if (nameEl && document.activeElement !== nameEl && this.shadowRoot.activeElement !== nameEl) {
      nameEl.value = this._config.name || "";
    }
  }

  _fireChanged() {
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config } }));
  }
}

customElements.define("ananda-bed-card-editor", AnandaBedCardEditor);

// Register with HA's custom card picker
window.customCards = window.customCards || [];
window.customCards.push({
  type: "ananda-bed-card",
  name: "Ananda Bed",
  description: "Control an Ananda adjustable bed (position, presets, vibration)",
});
