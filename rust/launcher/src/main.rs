//! MVSDsion launcher.
//!
//! A one-file PyInstaller program unpacks ~200 MB into a temporary folder on
//! every start. This launcher unpacks the program once per version into
//! `%LOCALAPPDATA%\MVSDsionNT\app\<build id>` and afterwards starts it
//! directly, so later starts skip the unpacking completely.
#![windows_subsystem = "windows"]

use std::ffi::OsStr;
use std::fs::{self, File};
use std::io::{self, BufWriter, Cursor};
use std::os::windows::ffi::OsStrExt;
use std::path::{Component, Path, PathBuf};
use std::process::{self, Command};

const PAYLOAD: &[u8] = include_bytes!(concat!(env!("OUT_DIR"), "/payload.zip"));
const BUILD_ID: &str = env!("MVSDSION_BUILD_ID");
const PROGRAM: &str = "MVSDsion.exe";
const COMPLETE: &str = ".complete";

#[link(name = "user32")]
extern "system" {
    fn MessageBoxW(hwnd: *mut core::ffi::c_void, text: *const u16, caption: *const u16, kind: u32) -> i32;
}

fn wide(text: &str) -> Vec<u16> {
    OsStr::new(text).encode_wide().chain(Some(0)).collect()
}

fn fail(message: &str) -> ! {
    let text = wide(message);
    let caption = wide("MVSDsion");
    // MB_ICONERROR
    unsafe { MessageBoxW(core::ptr::null_mut(), text.as_ptr(), caption.as_ptr(), 0x10) };
    process::exit(1);
}

fn app_root() -> PathBuf {
    let base = std::env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .unwrap_or_else(std::env::temp_dir);
    base.join("MVSDsionNT").join("app")
}

/// Only plain relative paths may come out of the archive.
fn safe_path(name: &str) -> Option<PathBuf> {
    let path = Path::new(name);
    if path.components().all(|part| matches!(part, Component::Normal(_))) {
        Some(path.to_path_buf())
    } else {
        None
    }
}

fn unpack(target: &Path) -> io::Result<()> {
    let mut archive = zip::ZipArchive::new(Cursor::new(PAYLOAD))
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
    for index in 0..archive.len() {
        let mut entry = archive
            .by_index(index)
            .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
        let Some(relative) = safe_path(entry.name()) else { continue };
        let path = target.join(relative);
        if entry.is_dir() {
            fs::create_dir_all(&path)?;
            continue;
        }
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        let mut output = BufWriter::with_capacity(1 << 20, File::create(&path)?);
        io::copy(&mut entry, &mut output)?;
    }
    File::create(target.join(COMPLETE))?;
    Ok(())
}

/// Unpacks into a temporary folder first, so a cancelled start never leaves a half copy.
fn ensure_unpacked(root: &Path, folder: &Path) -> io::Result<()> {
    if folder.join(COMPLETE).is_file() && folder.join(PROGRAM).is_file() {
        return Ok(());
    }
    fs::create_dir_all(root)?;
    let staging = root.join(format!(".unpacking-{}", process::id()));
    let _ = fs::remove_dir_all(&staging);
    unpack(&staging)?;
    if folder.exists() {
        // An older broken copy, or another launcher was faster
        if folder.join(COMPLETE).is_file() {
            let _ = fs::remove_dir_all(&staging);
            return Ok(());
        }
        fs::remove_dir_all(folder)?;
    }
    fs::rename(&staging, folder)
}

/// Removes copies of older versions (skipped while they are still running).
fn remove_old_versions(root: &Path, keep: &Path) {
    let Ok(entries) = fs::read_dir(root) else { return };
    for entry in entries.flatten() {
        let path = entry.path();
        if path != keep && path.is_dir() {
            let _ = fs::remove_dir_all(&path);
        }
    }
}

fn main() {
    if PAYLOAD.is_empty() {
        fail("This launcher was built without the MVSDsion program inside.");
    }
    let root = app_root();
    let folder = root.join(BUILD_ID);
    if let Err(error) = ensure_unpacked(&root, &folder) {
        fail(&format!("MVSDsion could not be unpacked to\n{}\n\n{error}", folder.display()));
    }
    remove_old_versions(&root, &folder);

    let launcher = std::env::current_exe().unwrap_or_default();
    let mut command = Command::new(folder.join(PROGRAM));
    command.args(std::env::args_os().skip(1));
    // Lets MVSDsion point autostart, shortcuts and restarts at this launcher
    command.env("MVSDSION_LAUNCHER", &launcher);
    match command.status() {
        Ok(status) => process::exit(status.code().unwrap_or(0)),
        Err(error) => fail(&format!("MVSDsion could not be started.\n\n{error}")),
    }
}
