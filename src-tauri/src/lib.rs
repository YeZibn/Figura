mod supervisor;

use std::sync::Mutex;
use supervisor::{GatewayStatus, GatewaySupervisor, SharedGatewaySupervisor};
use tauri::{Manager, State};

#[tauri::command]
fn ping() -> &'static str {
    "chartagent-desktop"
}

#[tauri::command]
fn gateway_status(state: State<'_, SharedGatewaySupervisor>) -> GatewayStatus {
    state.lock().expect("gateway supervisor mutex poisoned").status()
}

#[tauri::command]
fn start_gateway(state: State<'_, SharedGatewaySupervisor>) -> GatewayStatus {
    state.lock().expect("gateway supervisor mutex poisoned").start()
}

#[tauri::command]
fn stop_gateway(state: State<'_, SharedGatewaySupervisor>) -> GatewayStatus {
    state.lock().expect("gateway supervisor mutex poisoned").stop()
}

pub fn run() {
    let supervisor = Mutex::new(GatewaySupervisor::from_env());
    tauri::Builder::default()
        .manage(supervisor)
        .setup(|app| {
            let state = app.state::<SharedGatewaySupervisor>();
            let _ = state.lock().expect("gateway supervisor mutex poisoned").start();
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![ping, gateway_status, start_gateway, stop_gateway])
        .run(|app_handle, event| {
            if matches!(event, tauri::RunEvent::Exit) {
                let state = app_handle.state::<SharedGatewaySupervisor>();
                let _ = state.lock().expect("gateway supervisor mutex poisoned").stop();
            }
        })
        .expect("error while running Figura desktop client");
}
