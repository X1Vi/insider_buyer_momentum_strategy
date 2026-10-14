/// Reconstruct the running dummy P&L by replaying the last `total_pnl=₹...`
/// figure written to the log file. This is not a real account balance — it's
/// a paper-trading ledger derived purely from our own log history, so the
/// TUI can pick up where a previous run left off instead of resetting to 0.
pub fn replay_total_pnl(log_path: &str) -> f64 {
    let marker = "total_pnl=\u{20b9}";
    let Ok(contents) = std::fs::read_to_string(log_path) else {
        return 0.0;
    };

    contents
        .lines()
        .rev()
        .find_map(|line| {
            let idx = line.find(marker)?;
            let rest = &line[idx + marker.len()..];
            let num: String = rest
                .chars()
                .take_while(|c| c.is_ascii_digit() || matches!(c, '.' | '-' | '+'))
                .collect();
            num.parse::<f64>().ok()
        })
        .unwrap_or(0.0)
}
