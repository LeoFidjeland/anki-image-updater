//! Windows-only launcher: materializes embedded PyApp, optional `self restore`, spawns PyApp with
//! its own console (first-run bootstrap visible), small egui window until http://127.0.0.1:8080/ responds.

#![cfg_attr(all(windows, not(debug_assertions)), windows_subsystem = "windows")]

#[cfg(not(windows))]
fn main() {
    eprintln!(
        "anki-image-updater-windows-launcher only builds for Windows (x86_64-pc-windows-msvc)."
    );
    std::process::exit(1);
}

#[cfg(windows)]
fn main() -> eframe::Result<()> {
    real::run()
}

#[cfg(windows)]
mod real {
    use anyhow::{anyhow, Context, Result};
    use egui::{CentralPanel, ProgressBar};
    use sha2::{Digest, Sha256};
    use std::fs;
    use std::io::Write;
    use std::path::{Path, PathBuf};
    use std::process::{Child, Command, Stdio};
    use std::time::{Duration, Instant};

    /// https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags
    const CREATE_NEW_CONSOLE: u32 = 0x0000_0010;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;

    const PYAPP_BYTES: &[u8] = include_bytes!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/assets/AnkiImageUpdaterPyApp.exe"
    ));

    pub fn run() -> eframe::Result<()> {
        let pyapp_path;
        let payload_sha;
        match materialize_pyapp() {
            Ok(v) => {
                pyapp_path = v.0;
                payload_sha = v.1;
            }
            Err(e) => {
                let _ = msgbox::create(
                    "Anki Image Updater",
                    &format!("Could not prepare Anki Image Updater:\n{e}"),
                    msgbox::IconType::Error,
                );
                std::process::exit(1);
            }
        }

        if let Err(e) = maybe_restore(&pyapp_path, &payload_sha) {
            let _ = msgbox::create(
                "Anki Image Updater",
                &format!("Could not refresh the Python environment:\n{e}"),
                msgbox::IconType::Error,
            );
            std::process::exit(1);
        }

        let home = match user_profile_dir() {
            Ok(h) => h,
            Err(e) => {
                let _ = msgbox::create(
                    "Anki Image Updater",
                    &format!("Could not resolve your profile folder:\n{e}"),
                    msgbox::IconType::Error,
                );
                std::process::exit(1);
            }
        };

        let child = match spawn_pyapp_with_console(&pyapp_path, &home) {
            Ok(c) => c,
            Err(e) => {
                let _ = msgbox::create(
                    "Anki Image Updater",
                    &format!("Could not start Anki Image Updater:\n{e}"),
                    msgbox::IconType::Error,
                );
                std::process::exit(1);
            }
        };

        let options = eframe::NativeOptions {
            viewport: egui::ViewportBuilder::default()
                .with_inner_size([440.0, 130.0])
                .with_title("Anki Image Updater"),
            ..Default::default()
        };

        eframe::run_native(
            "Anki Image Updater",
            options,
            Box::new(move |_cc| {
                Ok(Box::new(LauncherApp {
                    child,
                    last_poll: Instant::now() - Duration::from_secs(1),
                    attempts_left: 720,
                    hide_viewport: false,
                }) as Box<dyn eframe::App>)
            }),
        )
    }

    struct LauncherApp {
        child: Child,
        last_poll: Instant,
        attempts_left: i32,
        hide_viewport: bool,
    }

    impl eframe::App for LauncherApp {
        fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
            if let Ok(Some(_)) = self.child.try_wait() {
                ctx.send_viewport_cmd(egui::ViewportCommand::Close);
                return;
            }

            if self.hide_viewport {
                ctx.send_viewport_cmd(egui::ViewportCommand::Visible(false));
                ctx.send_viewport_cmd(egui::ViewportCommand::Minimized(true));
                return;
            }

            if self.attempts_left > 0 && self.last_poll.elapsed() >= Duration::from_millis(250) {
                self.last_poll = Instant::now();
                self.attempts_left -= 1;
                if probe_local_server() {
                    self.hide_viewport = true;
                }
            }

            CentralPanel::default().show(ctx, |ui| {
                ui.label(
                    "Preparing the app. The first launch can take a minute while Python and \
                     libraries are set up. A separate window shows download progress. This dialog \
                     hides when the tool is ready in your browser.",
                );
                ui.add(ProgressBar::new(0.4).animate(true));
            });
            ctx.request_repaint_after(Duration::from_millis(100));
        }

        fn on_close_event(&mut self) -> bool {
            kill_process_tree(self.child.id());
            true
        }
    }

    fn user_profile_dir() -> Result<PathBuf> {
        std::env::var_os("USERPROFILE")
            .map(PathBuf::from)
            .ok_or_else(|| anyhow!("USERPROFILE is not set"))
    }

    fn local_app_data() -> Result<PathBuf> {
        std::env::var_os("LOCALAPPDATA")
            .map(PathBuf::from)
            .ok_or_else(|| anyhow!("LOCALAPPDATA is not set"))
    }

    fn materialize_pyapp() -> Result<(PathBuf, String)> {
        if PYAPP_BYTES.len() < 10_000 {
            return Err(anyhow!(
                "Embedded PyApp is missing or too small — copy AnkiImageUpdaterPyApp.exe to \
                 packaging/windows/launcher-rust/assets/ before building."
            ));
        }

        let dir = local_app_data()?.join("anki-image-updater").join("pyapp");
        fs::create_dir_all(&dir).with_context(|| format!("create {}", dir.display()))?;
        let path = dir.join("AnkiImageUpdaterPyApp.exe");
        let hash_path = PathBuf::from(format!("{}.sha256", path.display()));

        let digest = Sha256::digest(PYAPP_BYTES);
        let hash_hex: String = digest.iter().map(|b| format!("{b:02x}")).collect();

        let need_write = !path.is_file()
            || !hash_path.is_file()
            || fs::read_to_string(&hash_path)
                .map(|s| s.trim() != hash_hex)
                .unwrap_or(true);

        if need_write {
            let mut f = fs::File::create(&path).with_context(|| format!("write {}", path.display()))?;
            f.write_all(PYAPP_BYTES)?;
            f.sync_all()?;
            fs::write(&hash_path, &hash_hex)?;
        }

        Ok((path, hash_hex))
    }

    fn maybe_restore(pyapp_path: &Path, payload_sha256: &str) -> Result<()> {
        let state_dir = local_app_data()?.join("com.leofidjeland.anki-image-updater");
        fs::create_dir_all(&state_dir)?;
        let marker = state_dir.join("pyapp_payload_sha256");

        if marker.is_file() {
            if let Ok(prev) = fs::read_to_string(&marker) {
                if prev.trim().eq_ignore_ascii_case(payload_sha256) {
                    return Ok(());
                }
            }
        }

        use std::os::windows::process::CommandExt;

        let status = Command::new(pyapp_path)
            .args(["self", "restore"])
            .current_dir(user_profile_dir()?)
            .stdin(Stdio::null())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .creation_flags(CREATE_NEW_CONSOLE)
            .status()
            .context("spawn PyApp self restore")?;

        if !status.success() {
            return Err(anyhow!(
                "PyApp self restore exited with code {:?}. Try deleting %LOCALAPPDATA%\\pyapp\\anki-image-updater.",
                status.code()
            ));
        }

        fs::write(marker, payload_sha256)?;
        Ok(())
    }

    fn spawn_pyapp_with_console(pyapp_path: &Path, home: &Path) -> Result<Child> {
        use std::os::windows::process::CommandExt;

        let mut cmd = Command::new(pyapp_path);
        cmd.current_dir(home)
            .stdin(Stdio::null())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .creation_flags(CREATE_NEW_CONSOLE);

        for a in std::env::args().skip(1) {
            cmd.arg(a);
        }

        cmd.spawn().context("spawn PyApp")
    }

    fn probe_local_server() -> bool {
        match ureq::get("http://127.0.0.1:8080/")
            .timeout(Duration::from_millis(500))
            .call()
        {
            Ok(resp) => (200..500).contains(&resp.status()),
            Err(_) => false,
        }
    }

    fn kill_process_tree(pid: u32) {
        use std::os::windows::process::CommandExt;
        let _ = Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .creation_flags(CREATE_NO_WINDOW)
            .status();
    }
}
