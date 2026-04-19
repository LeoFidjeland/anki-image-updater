//! Embed `asInvoker` UAC manifest + app icon so `CreateProcess` does not fail with error 740
//! (elevation mismatch) and we do not need rcedit (which can strip manifests).

fn main() {
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() != Ok("windows") {
        return;
    }

    let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
    let manifest = dir.join("../as-invoker.manifest");
    let icon = dir.join("../AppIcon.ico");

    let mut res = winres::WindowsResource::new();
    res.set_manifest_file(
        manifest
            .to_str()
            .expect("as-invoker.manifest path must be valid UTF-8"),
    );
    if icon.is_file() {
        res.set_icon(icon.to_string_lossy().as_ref());
    }
    res.compile().expect("winres compile (manifest + icon)");
}
