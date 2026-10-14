use std::io::Write;
use tracing::error;

/// Pushover priority levels.
/// -2 = no notification (silent), -1 = quiet, 0 = normal, 1 = high, 2 = emergency.
pub const PRIORITY_NORMAL: i32 = 0;
pub const PRIORITY_HIGH: i32 = 1;

/// Send a push notification to your phone via Pushover. Reads the app token and
/// user key from the environment (PUSHOVER_APP_TOKEN / PUSHOVER_USER_KEY).
/// Returns true if the message was accepted (HTTP 2xx). Silently returns false
/// (no-op) when the env vars are not set, so the bot still runs headless.
pub async fn pushover(title: &str, message: &str, priority: i32) -> bool {
    let Ok(token) = std::env::var("PUSHOVER_APP_TOKEN") else {
        return false;
    };
    if token.trim().is_empty() {
        return false;
    }
    let Ok(user) = std::env::var("PUSHOVER_USER_KEY") else {
        return false;
    };
    if user.trim().is_empty() {
        return false;
    }

    let client = reqwest::Client::new();
    let resp = match client
        .post("https://api.pushover.net/1/messages.json")
        .form(&[
            ("token", token.trim().to_string()),
            ("user", user.trim().to_string()),
            ("title", title.to_string()),
            ("message", message.to_string()),
            ("priority", priority.to_string()),
        ])
        .send()
        .await
    {
        Ok(r) => r,
        Err(e) => {
            error!(error = %e, "pushover_send_failed");
            return false;
        }
    };

    if resp.status().is_success() {
        true
    } else {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        error!(status = %status, body = %body, "pushover_rejected");
        false
    }
}

/// Fire a best-effort desktop notification plus a terminal bell. The desktop
/// toast silently does nothing if there's no notification daemon (e.g.
/// headless/sandboxed environments) — the bell is the reliable fallback.
pub fn fire(title: &str, body: &str) {
    let _ = notify_rust::Notification::new()
        .summary(title)
        .body(body)
        .appname("spread_reversion")
        .timeout(notify_rust::Timeout::Milliseconds(6000))
        .show();

    let _ = write!(std::io::stdout(), "\x07");
    let _ = std::io::stdout().flush();
}
