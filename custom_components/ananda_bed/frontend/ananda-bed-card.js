/**
 * Ananda Bed Lovelace Card
 *
 * Custom card for controlling an Ananda adjustable bed base.
 * Provides position sliders, preset buttons, pillow controls, and vibration selectors.
 *
 * Config:
 *   type: custom:ananda-bed-card
 *   name: ananda_bed   # entity name prefix
 */

const LitElement = Object.getPrototypeOf(customElements.get("ha-panel-lovelace"));
const html = LitElement.prototype.html;
const css = LitElement.prototype.css;

class AnandaBedCard extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      _config: { type: Object },
    };
  }

  setConfig(config) {
    if (!config.name) {
      throw new Error("Please define 'name' (entity prefix)");
    }
    this._config = config;
  }

  // Entity ID helpers
  _entity(suffix) {
    return `${this._config.name}_${suffix}`;
  }

  _coverId(part) {
    return `cover.${this._entity(part)}`;
  }

  _buttonId(preset) {
    return `button.${this._entity(preset)}`;
  }

  _selectId(part) {
    return `select.${this._entity(part)}`;
  }

  // State helpers
  _coverState(part) {
    const entity = this.hass.states[this._coverId(part)];
    return entity ? entity.attributes.current_position || 0 : 0;
  }

  _selectState(part) {
    const entity = this.hass.states[this._selectId(part)];
    return entity ? entity.state : "off";
  }

  // Actions
  _setCoverPosition(part, position) {
    this.hass.callService("cover", "set_cover_position", {
      entity_id: this._coverId(part),
      position: parseInt(position),
    });
  }

  _coverAction(part, action) {
    this.hass.callService("cover", action, {
      entity_id: this._coverId(part),
    });
  }

  _pressButton(preset) {
    this.hass.callService("button", "press", {
      entity_id: this._buttonId(preset),
    });
  }

  _setVibration(part, option) {
    this.hass.callService("select", "select_option", {
      entity_id: this._selectId(part),
      option,
    });
  }

  render() {
    if (!this.hass || !this._config) return html``;

    const headPos = this._coverState("head");
    const feetPos = this._coverState("feet");
    const headVib = this._selectState("head_vibration");
    const feetVib = this._selectState("feet_vibration");
    const displayName = this._config.title || this._config.name.replace(/_/g, " ");

    return html`
      <ha-card>
        <!-- Header -->
        <div class="card-header">${displayName}</div>

        <div class="card-content">
          <!-- Position Section -->
          <div class="section">
            <div class="section-title">Position</div>
            <div class="position-row">
              <div class="slider-group">
                <div class="slider-label">Head ${headPos}%</div>
                <div class="slider-controls">
                  <ha-icon-button @click=${() => this._coverAction("head", "open_cover")}>
                    <ha-icon icon="mdi:chevron-up"></ha-icon>
                  </ha-icon-button>
                  <input
                    type="range"
                    min="0"
                    max="100"
                    .value=${headPos}
                    class="vertical-slider"
                    @change=${(e) => this._setCoverPosition("head", e.target.value)}
                  />
                  <ha-icon-button @click=${() => this._coverAction("head", "close_cover")}>
                    <ha-icon icon="mdi:chevron-down"></ha-icon>
                  </ha-icon-button>
                </div>
                <ha-icon-button @click=${() => this._coverAction("head", "stop_cover")}>
                  <ha-icon icon="mdi:stop"></ha-icon>
                </ha-icon-button>
              </div>

              <div class="bed-icon">
                <ha-icon icon="mdi:bed"></ha-icon>
              </div>

              <div class="slider-group">
                <div class="slider-label">Feet ${feetPos}%</div>
                <div class="slider-controls">
                  <ha-icon-button @click=${() => this._coverAction("feet", "open_cover")}>
                    <ha-icon icon="mdi:chevron-up"></ha-icon>
                  </ha-icon-button>
                  <input
                    type="range"
                    min="0"
                    max="100"
                    .value=${feetPos}
                    class="vertical-slider"
                    @change=${(e) => this._setCoverPosition("feet", e.target.value)}
                  />
                  <ha-icon-button @click=${() => this._coverAction("feet", "close_cover")}>
                    <ha-icon icon="mdi:chevron-down"></ha-icon>
                  </ha-icon-button>
                </div>
                <ha-icon-button @click=${() => this._coverAction("feet", "stop_cover")}>
                  <ha-icon icon="mdi:stop"></ha-icon>
                </ha-icon-button>
              </div>
            </div>
          </div>

          <!-- Presets Section -->
          <div class="section">
            <div class="section-title">Presets</div>
            <div class="preset-row">
              <div class="preset-btn" @click=${() => this._pressButton("flat")}>
                <ha-icon icon="mdi:minus"></ha-icon>
                <span>Flat</span>
              </div>
              <div class="preset-btn" @click=${() => this._pressButton("preset_1")}>
                <ha-icon icon="mdi:numeric-1-box"></ha-icon>
                <span>I</span>
              </div>
              <div class="preset-btn" @click=${() => this._pressButton("preset_2_tv")}>
                <ha-icon icon="mdi:television"></ha-icon>
                <span>TV</span>
              </div>
              <div class="preset-btn" @click=${() => this._pressButton("zero_gravity")}>
                <ha-icon icon="mdi:orbit"></ha-icon>
                <span>Zero-G</span>
              </div>
              <div class="preset-btn" @click=${() => this._pressButton("anti_snore")}>
                <ha-icon icon="mdi:sleep"></ha-icon>
                <span>Snore</span>
              </div>
            </div>
          </div>

          <!-- Pillow Section -->
          <div class="section">
            <div class="section-title">Pillow Tilt</div>
            <div class="pillow-row">
              <ha-icon-button @click=${() => this._pressButton("pillow_up")}>
                <ha-icon icon="mdi:arrow-up-bold"></ha-icon>
              </ha-icon-button>
              <ha-icon icon="mdi:pillow"></ha-icon>
              <ha-icon-button @click=${() => this._pressButton("pillow_down")}>
                <ha-icon icon="mdi:arrow-down-bold"></ha-icon>
              </ha-icon-button>
            </div>
          </div>

          <!-- Vibration Section -->
          <div class="section">
            <div class="section-title">Vibration</div>
            <div class="vibration-row">
              <div class="vibration-group">
                <label>Head</label>
                <div class="segmented">
                  ${["off", "low", "medium", "high"].map(
                    (opt) => html`
                      <button
                        class="seg-btn ${headVib === opt ? "active" : ""}"
                        @click=${() => this._setVibration("head_vibration", opt)}
                      >
                        ${opt}
                      </button>
                    `
                  )}
                </div>
              </div>
              <div class="vibration-group">
                <label>Feet</label>
                <div class="segmented">
                  ${["off", "low", "medium", "high"].map(
                    (opt) => html`
                      <button
                        class="seg-btn ${feetVib === opt ? "active" : ""}"
                        @click=${() => this._setVibration("feet_vibration", opt)}
                      >
                        ${opt}
                      </button>
                    `
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </ha-card>
    `;
  }

  static get styles() {
    return css`
      :host {
        --primary-color: var(--ha-card-header-color, var(--primary-text-color));
      }
      .card-header {
        padding: 16px 16px 0;
        font-size: 1.4em;
        font-weight: 500;
        text-transform: capitalize;
      }
      .card-content {
        padding: 16px;
      }
      .section {
        margin-bottom: 16px;
      }
      .section-title {
        font-size: 0.9em;
        font-weight: 500;
        text-transform: uppercase;
        color: var(--secondary-text-color);
        margin-bottom: 8px;
      }

      /* Position sliders */
      .position-row {
        display: flex;
        align-items: center;
        justify-content: space-around;
      }
      .slider-group {
        display: flex;
        flex-direction: column;
        align-items: center;
      }
      .slider-label {
        font-size: 0.85em;
        margin-bottom: 4px;
      }
      .slider-controls {
        display: flex;
        flex-direction: column;
        align-items: center;
      }
      .vertical-slider {
        writing-mode: vertical-lr;
        direction: rtl;
        height: 120px;
        width: 28px;
        margin: 4px 0;
        accent-color: var(--primary-color);
      }
      .bed-icon {
        --mdc-icon-size: 48px;
        color: var(--secondary-text-color);
      }

      /* Presets */
      .preset-row {
        display: flex;
        justify-content: space-around;
        flex-wrap: wrap;
        gap: 8px;
      }
      .preset-btn {
        display: flex;
        flex-direction: column;
        align-items: center;
        cursor: pointer;
        padding: 8px 12px;
        border-radius: 8px;
        transition: background 0.2s;
        font-size: 0.8em;
      }
      .preset-btn:hover {
        background: var(--secondary-background-color);
      }
      .preset-btn ha-icon {
        --mdc-icon-size: 24px;
        margin-bottom: 4px;
      }

      /* Pillow */
      .pillow-row {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 16px;
      }
      .pillow-row ha-icon {
        --mdc-icon-size: 32px;
        color: var(--secondary-text-color);
      }

      /* Vibration */
      .vibration-row {
        display: flex;
        gap: 16px;
        flex-wrap: wrap;
      }
      .vibration-group {
        flex: 1;
        min-width: 140px;
      }
      .vibration-group label {
        display: block;
        font-size: 0.85em;
        margin-bottom: 4px;
      }
      .segmented {
        display: flex;
        border: 1px solid var(--divider-color);
        border-radius: 8px;
        overflow: hidden;
      }
      .seg-btn {
        flex: 1;
        padding: 6px 4px;
        border: none;
        background: none;
        cursor: pointer;
        font-size: 0.75em;
        text-transform: capitalize;
        color: var(--primary-text-color);
        transition: background 0.2s;
      }
      .seg-btn:not(:last-child) {
        border-right: 1px solid var(--divider-color);
      }
      .seg-btn.active {
        background: var(--primary-color);
        color: var(--text-primary-color, #fff);
      }
      .seg-btn:hover:not(.active) {
        background: var(--secondary-background-color);
      }
    `;
  }

  getCardSize() {
    return 6;
  }

  static getConfigElement() {
    return document.createElement("ananda-bed-card-editor");
  }

  static getStubConfig() {
    return { name: "ananda_bed" };
  }
}

customElements.define("ananda-bed-card", AnandaBedCard);

// Register with HA's custom card picker
window.customCards = window.customCards || [];
window.customCards.push({
  type: "ananda-bed-card",
  name: "Ananda Bed",
  description: "Control an Ananda adjustable bed (position, presets, vibration)",
});
