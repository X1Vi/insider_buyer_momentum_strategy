use chrono::Local;
use tracing_appender::non_blocking::WorkerGuard;

pub fn now_hms() -> String {
    Local::now().format("%H:%M:%S").to_string()
}

/// Initialize file-only structured logging. Stdout is left untouched since the
/// TUI takes over the terminal; all log output goes to `log_path` instead.
pub fn init(log_path: &str) -> anyhow::Result<WorkerGuard> {
    init_filtered(log_path, "spread_reversion=info")
}

/// Same, but with an explicit default filter directive.
///
/// Needed because each binary under `src/bin/` compiles as its own crate, so
/// its tracing target is the *binary* name (e.g. `btc_bot`), not
/// `spread_reversion`. A filter of `spread_reversion=info` therefore silently
/// discards everything such a binary logs — which is why `btc_bot.log` came out
/// empty on the first run. `RUST_LOG` still overrides when set.
pub fn init_filtered(log_path: &str, default_filter: &str) -> anyhow::Result<WorkerGuard> {
    init_inner(log_path, default_filter, false)
}

/// File **and** stdout. For binaries that do not take over the terminal with a
/// TUI — without this a headless bot looks dead while it is working, because
/// `init` deliberately keeps stdout clean for ratatui.
pub fn init_console(log_path: &str, default_filter: &str) -> anyhow::Result<WorkerGuard> {
    init_inner(log_path, default_filter, true)
}

fn init_inner(
    log_path: &str,
    default_filter: &str,
    to_stdout: bool,
) -> anyhow::Result<WorkerGuard> {
    let file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_path)?;
    let (writer, guard) = tracing_appender::non_blocking(file);

    let filter = tracing_subscriber::EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new(default_filter));

    if to_stdout {
        use tracing_subscriber::fmt::writer::MakeWriterExt;
        tracing_subscriber::fmt()
            .with_env_filter(filter)
            .with_target(false)
            .with_ansi(false)
            .with_writer(writer.and(std::io::stdout))
            .init();
    } else {
        tracing_subscriber::fmt()
            .with_env_filter(filter)
            .with_target(false)
            .with_ansi(false)
            .with_writer(writer)
            .init();
    }

    Ok(guard)
}
