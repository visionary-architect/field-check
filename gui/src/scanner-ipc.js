/**
 * Scanner IPC — Communication layer between Tauri frontend and Python sidecar.
 *
 * Manages the sidecar lifecycle and provides an event-based API for
 * sending commands and receiving scan events.
 */

import { Command } from "@tauri-apps/plugin-shell";

export class ScannerIPC {
  constructor() {
    this._child = null;
    this._listeners = new Map();
    this._ready = false;
  }

  /**
   * Spawn the Python sidecar process.
   * Resolves when the sidecar emits the "ready" event.
   */
  async spawn() {
    const command = Command.sidecar("binaries/scanner");

    command.stdout.on("data", (line) => {
      if (!line.trim()) return;
      try {
        const msg = JSON.parse(line);
        this._dispatch(msg.event, msg);
      } catch {
        console.warn("[scanner] Non-JSON stdout:", line);
      }
    });

    command.stderr.on("data", (line) => {
      console.warn("[scanner]", line);
    });

    command.on("close", (data) => {
      this._dispatch("close", data);
      this._child = null;
      this._ready = false;
    });

    this._child = await command.spawn();

    // Wait for ready event
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error("Sidecar startup timeout")), 15000);
      this.once("ready", () => {
        clearTimeout(timeout);
        this._ready = true;
        resolve();
      });
    });
  }

  /**
   * Send a scan command to the sidecar.
   * @param {string} path - Directory path to scan.
   * @param {object} config - Optional FieldCheckConfig overrides.
   */
  async scan(path, config = {}) {
    this._send({ cmd: "scan", path, config });
  }

  /** Cancel the current scan. */
  async cancel() {
    this._send({ cmd: "cancel" });
  }

  /** Gracefully shut down the sidecar. */
  async shutdown() {
    if (this._child) {
      this._send({ cmd: "shutdown" });
      // Give it a moment to exit cleanly
      await new Promise((resolve) => setTimeout(resolve, 500));
      this._child = null;
      this._ready = false;
    }
  }

  /**
   * Register an event listener.
   * @param {string} event - Event name (ready, phase, progress, complete, error, cancelled, close).
   * @param {function} callback - Handler function.
   */
  on(event, callback) {
    if (!this._listeners.has(event)) {
      this._listeners.set(event, []);
    }
    this._listeners.get(event).push(callback);
  }

  /**
   * Register a one-time event listener.
   * @param {string} event - Event name.
   * @param {function} callback - Handler function (removed after first call).
   */
  once(event, callback) {
    const wrapper = (data) => {
      this.off(event, wrapper);
      callback(data);
    };
    this.on(event, wrapper);
  }

  /**
   * Remove an event listener.
   * @param {string} event - Event name.
   * @param {function} callback - The same function reference passed to on().
   */
  off(event, callback) {
    const handlers = this._listeners.get(event);
    if (handlers) {
      const idx = handlers.indexOf(callback);
      if (idx !== -1) handlers.splice(idx, 1);
    }
  }

  /** Whether the sidecar is ready. */
  get isReady() {
    return this._ready;
  }

  // --- Internal ---

  _send(msg) {
    if (!this._child) {
      console.error("[scanner] Cannot send — sidecar not running");
      return;
    }
    this._child.write(JSON.stringify(msg) + "\n");
  }

  _dispatch(event, data) {
    const handlers = this._listeners.get(event);
    if (handlers) {
      for (const handler of handlers) {
        try {
          handler(data);
        } catch (err) {
          console.error(`[scanner] Error in ${event} handler:`, err);
        }
      }
    }
  }
}
