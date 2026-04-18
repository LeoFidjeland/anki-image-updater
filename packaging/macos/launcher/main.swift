import AppKit
import CryptoKit
import Foundation

/// Lightweight GUI shell around the PyApp binary: shows first-launch feedback while the
/// Rust bootstrapper downloads / unpacks Python and runs `pip`, then hides once NiceGUI is up.

private let serverURL = URL(string: "http://127.0.0.1:8080/")!

/// Matches `CFBundleIdentifier` in Info.plist — small launcher state (not PyApp’s own cache).
private let launcherStateDirName = "com.leofidjeland.anki-image-updater"

/// PyApp only bootstraps when its install directory is missing; if that folder exists it skips
/// reinstall. When we ship a new `AnkiImageUpdaterPyApp` binary, fingerprint it and run
/// `self restore` once so users are not stuck with a broken or stale environment.
private func sha256Hex(ofFile path: String) -> String? {
    guard let data = try? Data(contentsOf: URL(fileURLWithPath: path)) else { return nil }
    let digest = SHA256.hash(data: data)
    return digest.map { String(format: "%02x", $0) }.joined()
}

private func maybeRestorePyAppInstallIfPayloadChanged(pyappPath: String) throws {
    guard let hash = sha256Hex(ofFile: pyappPath) else {
        throw NSError(
            domain: "AnkiImageUpdater",
            code: 1,
            userInfo: [NSLocalizedDescriptionKey: "Could not read PyApp payload for fingerprinting."]
        )
    }

    guard let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first else {
        throw NSError(
            domain: "AnkiImageUpdater",
            code: 2,
            userInfo: [NSLocalizedDescriptionKey: "Could not resolve Application Support directory."]
        )
    }

    let stateDir = base.appendingPathComponent(launcherStateDirName, isDirectory: true)
    try FileManager.default.createDirectory(at: stateDir, withIntermediateDirectories: true)
    let marker = stateDir.appendingPathComponent("pyapp_payload_sha256", isDirectory: false)

    if let previous = try? String(contentsOf: marker, encoding: .utf8),
       previous.trimmingCharacters(in: .whitespacesAndNewlines) == hash
    {
        return
    }

    let restore = Process()
    restore.executableURL = URL(fileURLWithPath: pyappPath)
    restore.arguments = ["self", "restore"]
    restore.currentDirectoryURL = URL(fileURLWithPath: NSHomeDirectory(), isDirectory: true)

    try restore.run()
    restore.waitUntilExit()
    guard restore.terminationStatus == 0 else {
        throw NSError(
            domain: "AnkiImageUpdater",
            code: Int(restore.terminationStatus),
            userInfo: [NSLocalizedDescriptionKey:
                "Installer maintenance failed (exit \(restore.terminationStatus)). You can quit, delete ~/Library/Application Support/pyapp/anki-image-updater, and try again."]
        )
    }

    try hash.write(to: marker, atomically: true, encoding: .utf8)
}

private func pollUntilServerReady(window: NSWindow, attemptsRemaining: Int) {
    guard attemptsRemaining > 0 else { return }

    let task = URLSession.shared.dataTask(with: serverURL) { _, response, _ in
        if let http = response as? HTTPURLResponse, (200 ..< 500).contains(http.statusCode) {
            DispatchQueue.main.async { window.orderOut(nil) }
        } else {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
                pollUntilServerReady(window: window, attemptsRemaining: attemptsRemaining - 1)
            }
        }
    }
    task.resume()
}

@objc(AppDelegate)
final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    var window: NSWindow?
    var childTask: Process?

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if let task = childTask, task.isRunning {
            task.terminate()
        }
        return true
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if let task = childTask, task.isRunning {
            task.terminate()
            childTask = nil
        }
        return .terminateNow
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let bundlePath = Bundle.main.bundlePath
        let pyappPath = "\(bundlePath)/Contents/MacOS/AnkiImageUpdaterPyApp"

        guard FileManager.default.isExecutableFile(atPath: pyappPath) else {
            let alert = NSAlert()
            alert.messageText = "Missing application files"
            alert.informativeText = "Could not find AnkiImageUpdaterPyApp inside the app bundle."
            alert.runModal()
            NSApp.terminate(nil)
            return
        }

        do {
            try maybeRestorePyAppInstallIfPayloadChanged(pyappPath: pyappPath)
        } catch {
            let alert = NSAlert()
            alert.messageText = "Could not prepare installation"
            alert.informativeText = error.localizedDescription
            alert.runModal()
            NSApp.terminate(nil)
            return
        }

        let w = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 440, height: 130),
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        w.title = "Anki Image Updater"
        w.isReleasedWhenClosed = false

        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 12
        stack.edgeInsets = NSEdgeInsets(top: 18, left: 18, bottom: 18, right: 18)

        let label = NSTextField(wrappingLabelWithString:
            "Preparing the app. The first launch can take a minute while Python and libraries are set up. "
            + "This window closes automatically when the tool is ready in your browser.")
        label.font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
        label.maximumNumberOfLines = 5

        let progress = NSProgressIndicator()
        progress.style = .bar
        progress.isIndeterminate = true
        progress.controlSize = .small
        progress.startAnimation(nil)

        stack.addArrangedSubview(label)
        stack.addArrangedSubview(progress)

        w.contentView = stack
        w.center()
        w.delegate = self
        window = w
        w.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        let task = Process()
        task.executableURL = URL(fileURLWithPath: pyappPath)
        var forwarded = CommandLine.arguments
        if !forwarded.isEmpty { forwarded.removeFirst() }
        task.arguments = forwarded
        // Finder-launched apps often have cwd "/". Use a writable directory for bootstrap temp files.
        task.currentDirectoryURL = URL(fileURLWithPath: NSHomeDirectory(), isDirectory: true)

        childTask = task

        do {
            try task.run()
        } catch {
            let alert = NSAlert()
            alert.messageText = "Could not start Anki Image Updater"
            alert.informativeText = error.localizedDescription
            alert.runModal()
            NSApp.terminate(nil)
            return
        }

        // ~3 minutes of polling (720 * 0.25s) — enough for slow networks on first pip install.
        pollUntilServerReady(window: w, attemptsRemaining: 720)

        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            task.waitUntilExit()
            DispatchQueue.main.async {
                self?.childTask = nil
                NSApp.terminate(nil)
            }
        }
    }
}

private let appDelegate = AppDelegate()
NSApplication.shared.delegate = appDelegate
NSApplication.shared.setActivationPolicy(.regular)
_ = NSApplicationMain(CommandLine.argc, CommandLine.unsafeArgv)
