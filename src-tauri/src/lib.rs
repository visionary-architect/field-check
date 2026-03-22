/// Field Check Tauri application.
///
/// All scan logic runs in the Python sidecar — this Rust layer
/// only handles windowing, sidecar lifecycle, and native dialogs.

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .run(tauri::generate_context!())
        .expect("error while running field-check");
}
