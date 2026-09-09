#[tauri::command]
fn ping() -> &'static str {
    "chartagent-desktop"
}

pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![ping])
        .run(tauri::generate_context!())
        .expect("error while running ChartAgent desktop client");
}
