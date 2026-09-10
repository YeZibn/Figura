use serde::Serialize;
use std::env;
use std::io::{Read, Write};
use std::net::{Shutdown, TcpStream, ToSocketAddrs};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread::sleep;
use std::time::{Duration, Instant};

const DEFAULT_HOST: &str = "127.0.0.1";
const DEFAULT_PORT: u16 = 8765;
const DEFAULT_STARTUP_TIMEOUT_MS: u64 = 10_000;
const DEFAULT_SHUTDOWN_TIMEOUT_MS: u64 = 2_000;

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct GatewayStatus {
    pub state: String,
    pub url: String,
    pub owned: bool,
    pub error: Option<String>,
}

struct GatewayConfig {
    enabled: bool,
    external: bool,
    host: String,
    port: u16,
    executable: String,
    args: Vec<String>,
    startup_timeout: Duration,
    shutdown_timeout: Duration,
    config_error: Option<String>,
}

pub struct GatewaySupervisor {
    config: GatewayConfig,
    child: Option<Child>,
    status: GatewayStatus,
}

impl GatewaySupervisor {
    pub fn from_env() -> Self {
        let mode = env::var("CHARTAGENT_MODE")
            .or_else(|_| env::var("VITE_CHARTAGENT_MODE"))
            .unwrap_or_else(|_| "mock".to_string());
        let enabled = mode.eq_ignore_ascii_case("gateway");
        let host = env::var("CHARTAGENT_GATEWAY_HOST").unwrap_or_else(|_| DEFAULT_HOST.to_string());
        let port = env::var("CHARTAGENT_GATEWAY_PORT")
            .ok()
            .and_then(|value| value.parse().ok())
            .unwrap_or(DEFAULT_PORT);
        let executable_override = env::var("CHARTAGENT_GATEWAY_EXECUTABLE").ok();
        let executable = executable_override
            .clone()
            .unwrap_or_else(|| "conda".to_string());
        let default_args = if executable_override.is_some() {
            vec![
                "-m".to_string(),
                "chartagent.gateway".to_string(),
                "--host".to_string(),
                host.clone(),
                "--port".to_string(),
                port.to_string(),
            ]
        } else {
            vec![
                "run".to_string(),
                "-n".to_string(),
                env::var("CHARTAGENT_CONDA_ENV").unwrap_or_else(|_| "agent".to_string()),
                "python".to_string(),
                "-m".to_string(),
                "chartagent.gateway".to_string(),
                "--host".to_string(),
                host.clone(),
                "--port".to_string(),
                port.to_string(),
            ]
        };
        let (args, config_error) = match env::var("CHARTAGENT_GATEWAY_ARGS") {
            Ok(raw) => match serde_json::from_str::<Vec<String>>(&raw) {
                Ok(args) => (args, None),
                Err(_) => (default_args, Some("Gateway arguments are invalid".to_string())),
            },
            Err(_) => (default_args, None),
        };
        let startup_timeout = bounded_duration("CHARTAGENT_GATEWAY_STARTUP_MS", DEFAULT_STARTUP_TIMEOUT_MS);
        let shutdown_timeout = bounded_duration("CHARTAGENT_GATEWAY_SHUTDOWN_MS", DEFAULT_SHUTDOWN_TIMEOUT_MS);
        let url = format!("http://{}:{}/api/v1", host, port);
        Self {
            config: GatewayConfig {
                enabled,
                external: env_flag("CHARTAGENT_GATEWAY_EXTERNAL"),
                host,
                port,
                executable,
                args,
                startup_timeout,
                shutdown_timeout,
                config_error,
            },
            child: None,
            status: GatewayStatus {
                state: if enabled { "starting" } else { "stopped" }.to_string(),
                url,
                owned: false,
                error: None,
            },
        }
    }

    pub fn status(&mut self) -> GatewayStatus {
        self.reap_exited_child();
        if self.config.enabled && self.status.state == "ready" && !self.config.external {
            if !health_ok(&self.config.host, self.config.port) {
                self.status.state = "unavailable".to_string();
                self.status.error = Some("Gateway health check failed".to_string());
            }
        }
        self.status.clone()
    }

    pub fn start(&mut self) -> GatewayStatus {
        if !self.config.enabled {
            self.status.state = "stopped".to_string();
            self.status.owned = false;
            self.status.error = None;
            return self.status();
        }
        self.status.state = "starting".to_string();
        self.status.error = None;
        if self.config.config_error.is_some() {
            self.status.state = "unavailable".to_string();
            self.status.error = self.config.config_error.clone();
            return self.status();
        }
        if self.config.external {
            self.status.owned = false;
            if wait_for_health(&self.config.host, self.config.port, self.config.startup_timeout) {
                self.status.state = "ready".to_string();
            } else {
                self.status.state = "unavailable".to_string();
                self.status.error = Some("External Gateway is unavailable".to_string());
            }
            return self.status();
        }
        self.reap_exited_child();
        if self.child.is_none() {
            let mut command = Command::new(&self.config.executable);
            command
                .args(&self.config.args)
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null());
            match command.spawn() {
                Ok(child) => {
                    self.child = Some(child);
                    self.status.owned = true;
                }
                Err(_) => {
                    self.status.state = "unavailable".to_string();
                    self.status.error = Some("Gateway could not be started".to_string());
                    return self.status();
                }
            }
        }
        if wait_for_health(&self.config.host, self.config.port, self.config.startup_timeout) {
            self.status.state = "ready".to_string();
        } else {
            self.status.state = "unavailable".to_string();
            self.status.error = Some("Gateway did not become ready".to_string());
            self.stop_owned_child();
        }
        self.status()
    }

    pub fn stop(&mut self) -> GatewayStatus {
        self.stop_owned_child();
        self.status.state = "stopped".to_string();
        self.status.owned = false;
        self.status.error = None;
        self.status()
    }

    fn reap_exited_child(&mut self) {
        if let Some(child) = self.child.as_mut() {
            if child.try_wait().ok().flatten().is_some() {
                self.child = None;
                self.status.owned = false;
                if self.status.state == "ready" {
                    self.status.state = "unavailable".to_string();
                    self.status.error = Some("Gateway process exited".to_string());
                }
            }
        }
    }

    fn stop_owned_child(&mut self) {
        if !self.config.external {
            if let Some(mut child) = self.child.take() {
                let _ = child.kill();
                let deadline = Instant::now() + self.config.shutdown_timeout;
                while Instant::now() < deadline {
                    if child.try_wait().ok().flatten().is_some() {
                        return;
                    }
                    sleep(Duration::from_millis(25));
                }
                let _ = child.wait();
            }
        }
    }
}

impl Drop for GatewaySupervisor {
    fn drop(&mut self) {
        self.stop_owned_child();
    }
}

pub type SharedGatewaySupervisor = Mutex<GatewaySupervisor>;

fn env_flag(key: &str) -> bool {
    matches!(env::var(key).ok().as_deref(), Some("1" | "true" | "TRUE" | "yes" | "YES"))
}

fn bounded_duration(key: &str, default_ms: u64) -> Duration {
    let millis = env::var(key)
        .ok()
        .and_then(|value| value.parse::<u64>().ok())
        .unwrap_or(default_ms)
        .clamp(100, 60_000);
    Duration::from_millis(millis)
}

fn wait_for_health(host: &str, port: u16, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if health_ok(host, port) {
            return true;
        }
        sleep(Duration::from_millis(100));
    }
    false
}

fn health_ok(host: &str, port: u16) -> bool {
    let address = match (host, port).to_socket_addrs().ok().and_then(|mut addresses| addresses.next()) {
        Some(address) => address,
        None => return false,
    };
    let mut stream = match TcpStream::connect_timeout(&address, Duration::from_millis(250)) {
        Ok(stream) => stream,
        Err(_) => return false,
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    let request = format!(
        "GET /api/v1/health HTTP/1.1\r\nHost: {}:{}\r\nConnection: close\r\n\r\n",
        host, port
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut response = Vec::new();
    let mut buffer = [0_u8; 4096];
    while response.len() < 16 * 1024 {
        match stream.read(&mut buffer) {
            Ok(0) => break,
            Ok(size) => response.extend_from_slice(&buffer[..size]),
            Err(_) => break,
        }
        let decoded = String::from_utf8_lossy(&response);
        if response.windows(4).any(|window| window == b"\r\n\r\n") && decoded.contains("\"version\":\"v1\"") {
            break;
        }
    }
    let _ = stream.shutdown(Shutdown::Both);
    let body = String::from_utf8_lossy(&response);
    body.contains(" 200 ") && body.contains("\"version\":\"v1\"")
}

#[cfg(test)]
mod tests {
    use super::{GatewaySupervisor, DEFAULT_PORT};

    #[test]
    fn default_configuration_is_mock_and_uses_agent_command() {
        std::env::remove_var("CHARTAGENT_MODE");
        std::env::remove_var("VITE_CHARTAGENT_MODE");
        std::env::remove_var("CHARTAGENT_GATEWAY_EXECUTABLE");
        std::env::remove_var("CHARTAGENT_GATEWAY_ARGS");
        let supervisor = GatewaySupervisor::from_env();
        assert_eq!(supervisor.status.state, "stopped");
        assert_eq!(supervisor.config.port, DEFAULT_PORT);
        assert_eq!(supervisor.config.executable, "conda");
        assert!(supervisor.config.args.contains(&"agent".to_string()));
    }
}
