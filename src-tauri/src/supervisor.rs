use serde::{Deserialize, Serialize};
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
    pub agent_state: String,
    pub agent_reason: Option<String>,
}

#[derive(Deserialize)]
struct HealthResponse {
    version: String,
    status: String,
    agent: Option<AgentHealthResponse>,
}

#[derive(Deserialize)]
struct AgentHealthResponse {
    status: String,
    reason: Option<String>,
}

struct HealthSnapshot {
    agent_state: String,
    agent_reason: Option<String>,
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
                agent_state: if enabled { "starting" } else { "stopped" }.to_string(),
                agent_reason: None,
            },
        }
    }

    pub fn status(&mut self) -> GatewayStatus {
        self.reap_exited_child();
        if self.config.enabled && self.status.state == "ready" && !self.config.external {
            if let Some(snapshot) = health_snapshot(&self.config.host, self.config.port) {
                self.apply_health(snapshot);
            } else {
                self.mark_gateway_unavailable("Gateway health check failed", "gateway_health_failed");
            }
        }
        self.status.clone()
    }

    pub fn start(&mut self) -> GatewayStatus {
        if !self.config.enabled {
            self.status.state = "stopped".to_string();
            self.status.owned = false;
            self.status.error = None;
            self.status.agent_state = "stopped".to_string();
            self.status.agent_reason = None;
            return self.status();
        }
        self.status.state = "starting".to_string();
        self.status.error = None;
        self.status.agent_state = "starting".to_string();
        self.status.agent_reason = None;
        if self.config.config_error.is_some() {
            self.status.state = "unavailable".to_string();
            self.status.error = self.config.config_error.clone();
            self.status.agent_state = "unavailable".to_string();
            self.status.agent_reason = Some("runtime_configuration".to_string());
            return self.status();
        }
        if self.config.external {
            self.status.owned = false;
            if let Some(snapshot) = wait_for_health(&self.config.host, self.config.port, self.config.startup_timeout) {
                self.status.state = "ready".to_string();
                self.apply_health(snapshot);
            } else {
                self.mark_gateway_unavailable("External Gateway is unavailable", "gateway_health_failed");
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
                    self.mark_gateway_unavailable("Gateway could not be started", "gateway_start_failed");
                    return self.status();
                }
            }
        }
        if let Some(snapshot) = wait_for_health(&self.config.host, self.config.port, self.config.startup_timeout) {
            self.status.state = "ready".to_string();
            self.apply_health(snapshot);
        } else {
            self.mark_gateway_unavailable("Gateway did not become ready", "gateway_health_failed");
            self.stop_owned_child();
        }
        self.status()
    }

    pub fn stop(&mut self) -> GatewayStatus {
        self.stop_owned_child();
        self.status.state = "stopped".to_string();
        self.status.owned = false;
        self.status.error = None;
        self.status.agent_state = "stopped".to_string();
        self.status.agent_reason = None;
        self.status()
    }

    fn apply_health(&mut self, snapshot: HealthSnapshot) {
        self.status.agent_state = snapshot.agent_state;
        self.status.agent_reason = snapshot.agent_reason;
    }

    fn mark_gateway_unavailable(&mut self, message: &str, reason: &str) {
        self.status.state = "unavailable".to_string();
        self.status.error = Some(message.to_string());
        self.status.agent_state = "unavailable".to_string();
        self.status.agent_reason = Some(reason.to_string());
    }

    fn reap_exited_child(&mut self) {
        let exited = self
            .child
            .as_mut()
            .map(|child| child.try_wait().ok().flatten().is_some())
            .unwrap_or(false);
        if exited {
            self.child = None;
            self.status.owned = false;
            if self.status.state == "ready" {
                self.mark_gateway_unavailable("Gateway process exited", "gateway_process_exited");
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

fn wait_for_health(host: &str, port: u16, timeout: Duration) -> Option<HealthSnapshot> {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if let Some(snapshot) = health_snapshot(host, port) {
            return Some(snapshot);
        }
        sleep(Duration::from_millis(100));
    }
    None
}

fn health_snapshot(host: &str, port: u16) -> Option<HealthSnapshot> {
    let address = match (host, port).to_socket_addrs().ok().and_then(|mut addresses| addresses.next()) {
        Some(address) => address,
        None => return None,
    };
    let mut stream = match TcpStream::connect_timeout(&address, Duration::from_millis(250)) {
        Ok(stream) => stream,
        Err(_) => return None,
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    let request = format!(
        "GET /api/v1/health HTTP/1.1\r\nHost: {}:{}\r\nConnection: close\r\n\r\n",
        host, port
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return None;
    }
    let mut response = Vec::new();
    let mut buffer = [0_u8; 4096];
    while response.len() < 16 * 1024 {
        match stream.read(&mut buffer) {
            Ok(0) => break,
            Ok(size) => response.extend_from_slice(&buffer[..size]),
            Err(_) => break,
        }
        if let Some(snapshot) = parse_health_response(&response) {
            let _ = stream.shutdown(Shutdown::Both);
            return Some(snapshot);
        }
    }
    let _ = stream.shutdown(Shutdown::Both);
    parse_health_response(&response)
}

fn parse_health_response(response: &[u8]) -> Option<HealthSnapshot> {
    let header_end = response.windows(4).position(|window| window == b"\r\n\r\n")?;
    let headers = String::from_utf8_lossy(&response[..header_end]);
    if !headers.contains(" 200 ") {
        return None;
    }
    let payload: HealthResponse = serde_json::from_slice(&response[header_end + 4..]).ok()?;
    if payload.version != "v1" || payload.status != "ok" {
        return None;
    }
    let agent = match payload.agent {
        Some(agent) => agent,
        None => {
            return Some(HealthSnapshot {
                agent_state: "unknown".to_string(),
                agent_reason: None,
            });
        }
    };
    let agent_state = match agent.status.as_str() {
        "ready" => "ready",
        "unavailable" => "unavailable",
        _ => "unknown",
    };
    let agent_reason = if agent_state == "unavailable" {
        match agent.reason.as_deref() {
            Some("missing_configuration" | "invalid_configuration" | "initialization_failed") => agent.reason,
            _ => Some("initialization_failed".to_string()),
        }
    } else {
        None
    };
    Some(HealthSnapshot {
        agent_state: agent_state.to_string(),
        agent_reason,
    })
}

#[cfg(test)]
mod tests {
    use super::{parse_health_response, GatewaySupervisor, DEFAULT_PORT};

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

    #[test]
    fn health_parser_keeps_gateway_and_agent_status_separate() {
        let response = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{\"version\":\"v1\",\"status\":\"ok\",\"agent\":{\"status\":\"unavailable\",\"reason\":\"missing_configuration\"}}";
        let snapshot = parse_health_response(response).expect("health response should parse");
        assert_eq!(snapshot.agent_state, "unavailable");
        assert_eq!(snapshot.agent_reason.as_deref(), Some("missing_configuration"));
    }
}
