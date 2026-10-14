use std::io::{self, Stdout};
use std::time::Duration;

use crossterm::event::{self, Event, KeyCode, KeyModifiers};
use crossterm::execute;
use crossterm::terminal::{
    EnterAlternateScreen, LeaveAlternateScreen, disable_raw_mode, enable_raw_mode,
};
use ratatui::Terminal;
use ratatui::backend::CrosstermBackend;
use ratatui::layout::{Constraint, Direction as LayoutDirection, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{
    Axis, Block, Borders, Chart, Dataset, GraphType, List, ListItem, Paragraph,
};

use crate::state::{Direction, Level, SharedState};
use crate::{FETCH_INTERVAL_SECS, PAIR_A, PAIR_B};

const SIGNAL_FLASH: Duration = Duration::from_secs(6);

pub async fn run(state: SharedState) -> anyhow::Result<()> {
    let mut terminal = setup_terminal()?;
    let result = event_loop(&mut terminal, &state);
    restore_terminal(&mut terminal)?;
    result
}

fn setup_terminal() -> anyhow::Result<Terminal<CrosstermBackend<Stdout>>> {
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen)?;
    Ok(Terminal::new(CrosstermBackend::new(stdout))?)
}

fn restore_terminal(terminal: &mut Terminal<CrosstermBackend<Stdout>>) -> anyhow::Result<()> {
    disable_raw_mode()?;
    execute!(terminal.backend_mut(), LeaveAlternateScreen)?;
    terminal.show_cursor()?;
    Ok(())
}

fn event_loop(
    terminal: &mut Terminal<CrosstermBackend<Stdout>>,
    state: &SharedState,
) -> anyhow::Result<()> {
    loop {
        terminal.draw(|f| draw(f, state))?;

        if event::poll(Duration::from_millis(200))? {
            if let Event::Key(key) = event::read()? {
                let quit = key.code == KeyCode::Char('q')
                    || (key.code == KeyCode::Char('c')
                        && key.modifiers.contains(KeyModifiers::CONTROL));
                if quit {
                    return Ok(());
                }
            }
        }
    }
}

fn draw(f: &mut ratatui::Frame, state: &SharedState) {
    let s = state.lock().unwrap();
    let area = f.area();

    let rows = Layout::default()
        .direction(LayoutDirection::Vertical)
        .constraints([
            Constraint::Length(3),
            Constraint::Length(1),
            Constraint::Length(9),
            Constraint::Length(11),
            Constraint::Min(5),
            Constraint::Length(1),
        ])
        .split(area);

    draw_header(f, rows[0], &s);
    draw_banner(f, rows[1], &s);

    let stats_cols = Layout::default()
        .direction(LayoutDirection::Horizontal)
        .constraints([Constraint::Percentage(45), Constraint::Percentage(55)])
        .split(rows[2]);
    draw_market(f, stats_cols[0], &s);
    draw_position(f, stats_cols[1], &s);

    draw_chart(f, rows[3], &s);
    draw_events(f, rows[4], &s);
    draw_footer(f, rows[5], &s);
}

fn draw_header(f: &mut ratatui::Frame, area: Rect, s: &crate::state::AppState) {
    let conn = if s.connected {
        Span::styled("● LIVE", Style::default().fg(Color::Green))
    } else {
        Span::styled("● NO CONNECTION", Style::default().fg(Color::Red))
    };
    let lines = vec![
        Line::from(vec![
            Span::styled(
                " SPREAD REVERSION — PAPER TRADING ",
                Style::default()
                    .fg(Color::Black)
                    .bg(Color::Yellow)
                    .add_modifier(Modifier::BOLD),
            ),
            Span::raw("  "),
            Span::styled(
                "NO REAL ORDERS",
                Style::default().fg(Color::Red).add_modifier(Modifier::BOLD),
            ),
        ]),
        Line::from(vec![
            Span::raw(format!("pair={PAIR_A}/{PAIR_B}  tick={}  ", s.tick)),
            conn,
        ]),
    ];
    f.render_widget(
        Paragraph::new(lines).block(Block::default().borders(Borders::BOTTOM)),
        area,
    );
}

fn draw_banner(f: &mut ratatui::Frame, area: Rect, s: &crate::state::AppState) {
    let text = match &s.last_signal {
        Some(sig) if sig.at.elapsed() < SIGNAL_FLASH => {
            let style = if sig.good {
                Style::default().fg(Color::Black).bg(Color::Green)
            } else {
                Style::default().fg(Color::Black).bg(Color::Red)
            };
            Paragraph::new(Line::from(Span::styled(
                format!(" ⚡ {} — {} ", sig.title, sig.body),
                style.add_modifier(Modifier::BOLD),
            )))
        }
        _ => Paragraph::new(""),
    };
    f.render_widget(text, area);
}

fn draw_market(f: &mut ratatui::Frame, area: Rect, s: &crate::state::AppState) {
    let z_color = if s.z.abs() > 2.0 {
        Color::Yellow
    } else if s.z.abs() > 1.0 {
        Color::Cyan
    } else {
        Color::Gray
    };
    let lines = vec![
        Line::from(format!("{PAIR_A}:  {:.2}", s.price_a)),
        Line::from(format!("{PAIR_B}:  {:.2}", s.price_b)),
        Line::from(format!("spread:  {:.4}", s.spread)),
        Line::from(format!("mean:    {:.4}", s.mean)),
        Line::from(format!("std:     {:.4}", s.std)),
        Line::from(vec![
            Span::raw("z-score: "),
            Span::styled(
                format!("{:+.3}", s.z),
                Style::default().fg(z_color).add_modifier(Modifier::BOLD),
            ),
        ]),
    ];
    f.render_widget(
        Paragraph::new(lines).block(Block::default().borders(Borders::ALL).title(" Market ")),
        area,
    );
}

fn draw_position(f: &mut ratatui::Frame, area: Rect, s: &crate::state::AppState) {
    let lines = match &s.position {
        None => vec![
            Line::from(Span::styled(
                "FLAT",
                Style::default()
                    .fg(Color::Gray)
                    .add_modifier(Modifier::BOLD),
            )),
            Line::from("waiting for |z| > 2.0 to enter"),
        ],
        Some(pos) => {
            let side = if matches!(pos.direction, Direction::Long) {
                Span::styled(
                    "LONG SPREAD",
                    Style::default()
                        .fg(Color::Green)
                        .add_modifier(Modifier::BOLD),
                )
            } else {
                Span::styled(
                    "SHORT SPREAD",
                    Style::default().fg(Color::Red).add_modifier(Modifier::BOLD),
                )
            };
            let pnl_color = if pos.unrealized_pnl >= 0.0 {
                Color::Green
            } else {
                Color::Red
            };
            vec![
                Line::from(side),
                Line::from(vec![
                    Span::styled("BUY   ", Style::default().fg(Color::Green)),
                    Span::raw(format!("{} x {}", pos.qty, pos.buy_symbol)),
                ]),
                Line::from(vec![
                    Span::styled("SHORT ", Style::default().fg(Color::Red)),
                    Span::raw(format!("{} x {}", pos.qty, pos.short_symbol)),
                ]),
                Line::from(format!(
                    "entry z: {:+.2}  entry spread: {:.4}  opened at tick {}",
                    pos.entry_z, pos.entry_spread, pos.entry_tick
                )),
                Line::from(vec![
                    Span::raw("unrealized pnl: "),
                    Span::styled(
                        format!("\u{20b9}{:+.2}", pos.unrealized_pnl),
                        Style::default().fg(pnl_color).add_modifier(Modifier::BOLD),
                    ),
                ]),
            ]
        }
    };

    let pnl_line = Line::from(vec![
        Span::raw("session P&L: "),
        Span::styled(
            format!("\u{20b9}{:+.2}", s.session_pnl),
            Style::default().fg(if s.session_pnl >= 0.0 {
                Color::Green
            } else {
                Color::Red
            }),
        ),
        Span::raw("   ledger P&L (from log): "),
        Span::styled(
            format!("\u{20b9}{:+.2}", s.ledger_pnl),
            Style::default().fg(if s.ledger_pnl >= 0.0 {
                Color::Green
            } else {
                Color::Red
            }),
        ),
    ]);

    let mut all = lines;
    all.push(Line::from(""));
    all.push(pnl_line);

    f.render_widget(
        Paragraph::new(all).block(Block::default().borders(Borders::ALL).title(" Position ")),
        area,
    );
}

fn draw_chart(f: &mut ratatui::Frame, area: Rect, s: &crate::state::AppState) {
    if s.history.len() < 2 {
        f.render_widget(
            Paragraph::new("warming up — not enough data for a chart yet")
                .block(Block::default().borders(Borders::ALL).title(" Spread ")),
            area,
        );
        return;
    }

    let points: Vec<(f64, f64)> = s
        .history
        .iter()
        .enumerate()
        .map(|(i, v)| (i as f64, *v))
        .collect();
    let mean_line: Vec<(f64, f64)> = vec![(0.0, s.mean), (points.len() as f64 - 1.0, s.mean)];

    let min = s.history.iter().cloned().fold(f64::INFINITY, f64::min);
    let max = s.history.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
    let pad = ((max - min).abs() * 0.1).max(0.01);

    let datasets = vec![
        Dataset::default()
            .name("spread")
            .marker(ratatui::symbols::Marker::Braille)
            .graph_type(GraphType::Line)
            .style(Style::default().fg(Color::Cyan))
            .data(&points),
        Dataset::default()
            .name("mean")
            .marker(ratatui::symbols::Marker::Dot)
            .graph_type(GraphType::Line)
            .style(Style::default().fg(Color::DarkGray))
            .data(&mean_line),
    ];

    let chart = Chart::new(datasets)
        .block(Block::default().borders(Borders::ALL).title(format!(
            " Spread (last {}/{} — window) ",
            s.history.len(),
            s.window
        )))
        .x_axis(Axis::default().bounds([0.0, (points.len() as f64 - 1.0).max(1.0)]))
        .y_axis(Axis::default().bounds([min - pad, max + pad]).labels(vec![
            format!("{:.3}", min - pad),
            format!("{:.3}", max + pad),
        ]));

    f.render_widget(chart, area);
}

fn draw_events(f: &mut ratatui::Frame, area: Rect, s: &crate::state::AppState) {
    let items: Vec<ListItem> = s
        .events
        .iter()
        .rev()
        .take(area.height.saturating_sub(2) as usize)
        .map(|e| {
            let color = match e.level {
                Level::Info => Color::Gray,
                Level::Warn => Color::Yellow,
                Level::Error => Color::Red,
                Level::Entry => Color::Green,
                Level::Exit => Color::Magenta,
            };
            ListItem::new(Line::from(vec![
                Span::styled(format!("{}  ", e.ts), Style::default().fg(Color::DarkGray)),
                Span::styled(e.text.clone(), Style::default().fg(color)),
            ]))
        })
        .collect();

    f.render_widget(
        List::new(items).block(Block::default().borders(Borders::ALL).title(" Events ")),
        area,
    );
}

fn draw_footer(f: &mut ratatui::Frame, area: Rect, s: &crate::state::AppState) {
    let mut text = format!(
        "q: quit   fetch every {FETCH_INTERVAL_SECS}s   tick={}",
        s.tick
    );
    if let Some(err) = &s.last_error {
        text.push_str(&format!("   last error: {err}"));
    }
    f.render_widget(
        Paragraph::new(text).style(Style::default().fg(Color::DarkGray)),
        area,
    );
}
