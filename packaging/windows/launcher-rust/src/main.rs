//! Windows-only launcher: materializes embedded PyApp, optional `self restore`, then starts PyApp in
//! a **new console** (bootstrap / install output). No separate GUI — PyApp’s console is the only
//! progress UI. This process exits immediately after spawn so we never `wait()` on the child.

#![cfg_attr(all(windows, not(debug_assertions)), windows_subsystem = "windows")]

#[cfg(not(windows))]
fn main() {
    eprintln!(
        "anki-image-updater-windows-launcher only builds for Windows (x86_64-pc-windows-msvc)."
    );
    std::process::exit(1);
}

#[cfg(windows)]
fn main() {
    real::run();
}

#[cfg(windows)]
mod real {
    use anyhow::{anyhow, Context, Result};
    use sha2::{Digest, Sha256};
    use std::fs::{self, OpenOptions};
    use std::io::Write;
    use std::path::{Path, PathBuf};
    use std::process::{Command, Stdio};
    use std::time::{SystemTime, UNIX_EPOCH};

    /// https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags
    const CREATE_NEW_CONSOLE: u32 = 0x0000_0010;

    const PYAPP_BYTES: &[u8] = include_bytes!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/assets/AnkiImageUpdaterPyApp.exe"
    ));

    fn launcher_debug_stderr() -> bool {
        std::env::var_os("ANKI_IMAGE_UPDATER_LAUNCHER_DEBUG").is_some()
    }

    fn attach_console_for_debug() {
        if !launcher_debug_stderr() {
            return;
        }
        const ATTACH_PARENT_PROCESS: u32 = 0xFFFF_FFFF;
        #[link(name = "kernel32")]
        extern "system" {
            fn AttachConsole(dw_process_id: u32) -> i32;
            fn AllocConsole() -> i32;
        }
        unsafe {
            if AttachConsole(ATTACH_PARENT_PROCESS) == 0 {
                let _ = AllocConsole();
            }
        }
    }

    fn eprintln_launcher_err(context: &str, e: &anyhow::Error) {
        if launcher_debug_stderr() {
            eprintln!("[anki-image-updater launcher] {context}\n{e:#}");
        }
    }

    /// `%LOCALAPPDATA%\anki-image-updater\launcher.log` — append-only, best-effort (never panics).
    fn launcher_log_path() -> Result<PathBuf> {
        Ok(local_app_data()?.join("anki-image-updater").join("launcher.log"))
    }

    fn log_timestamp() -> String {
        let d = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default();
        format!("{}.{:03}Z", d.as_secs(), d.subsec_millis())
    }

    fn log_append(line: &str) {
        let path = match launcher_log_path() {
            Ok(p) => p,
            Err(_) => return,
        };
        if let Some(parent) = path.parent() {
            let _ = fs::create_dir_all(parent);
        }
        if let Ok(mut f) = OpenOptions::new().create(true).append(true).open(&path) {
            let _ = writeln!(f, "{} {}", log_timestamp(), line);
        }
    }

    fn log_err(context: &str, e: &anyhow::Error) {
        log_append(&format!("ERROR {context}: {e:#}"));
    }

    fn user_hint_logfile() -> String {
        launcher_log_path()
            .map(|p| p.display().to_string())
            .unwrap_or_else(|_| "%LOCALAPPDATA%\\anki-image-updater\\launcher.log".to_string())
    }

    pub fn run() {
        attach_console_for_debug();

        let pyapp_path;
        let payload_sha;
        match materialize_pyapp() {
            Ok(v) => {
                pyapp_path = v.0;
                payload_sha = v.1;
            }
            Err(e) => {
                eprintln_launcher_err("Could not prepare Anki Image Updater", &e);
                log_err("materialize PyApp", &e);
                let hint = user_hint_logfile();
                let _ = msgbox::create(
                    "Anki Image Updater",
                    &format!(
                        "Could not prepare Anki Image Updater:\n{e}\n\nDetails: {hint}"
                    ),
                    msgbox::IconType::Error,
                );
                std::process::exit(1);
            }
        }

        if let Err(e) = maybe_restore(&pyapp_path, &payload_sha) {
            eprintln_launcher_err("Could not refresh the Python environment", &e);
            log_err("PyApp self restore", &e);
            let hint = user_hint_logfile();
            let _ = msgbox::create(
                "Anki Image Updater",
                &format!(
                    "Could not refresh the Python environment:\n{e}\n\nDetails: {hint}"
                ),
                msgbox::IconType::Error,
            );
            std::process::exit(1);
        }

        let home = match user_profile_dir() {
            Ok(h) => h,
            Err(e) => {
                eprintln_launcher_err("Could not resolve your profile folder", &e);
                log_err("USERPROFILE", &e);
                let hint = user_hint_logfile();
                let _ = msgbox::create(
                    "Anki Image Updater",
                    &format!(
                        "Could not resolve your profile folder:\n{e}\n\nDetails: {hint}"
                    ),
                    msgbox::IconType::Error,
                );
                std::process::exit(1);
            }
        };

        let pid = match spawn_pyapp_with_console(&pyapp_path, &home) {
            Ok(pid) => pid,
            Err(e) => {
                eprintln_launcher_err("Could not start Anki Image Updater (spawn PyApp)", &e);
                log_err("spawn PyApp", &e);
                let hint = user_hint_logfile();
                let _ = msgbox::create(
                    "Anki Image Updater",
                    &format!(
                        "Could not start Anki Image Updater:\n{e}\n\nDetails: {hint}"
                    ),
                    msgbox::IconType::Error,
                );
                std::process::exit(1);
            }
        };

        log_append(&format!("OK spawned PyApp pid={pid}"));
        // Do not drop `Child`: its destructor would wait until PyApp exits. `exit` skips
        // destructors; the OS closes handles and PyApp keeps running.
        std::process::exit(0);
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

    fn spawn_pyapp_with_console(pyapp_path: &Path, home: &Path) -> Result<u32> {
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

        let child = cmd.spawn().context("spawn PyApp")?;
        let pid = child.id();
        std::mem::forget(child);
        Ok(pid)
    }
}
