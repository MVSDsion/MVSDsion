// Embeds the packed program folder (MVSDSION_PAYLOAD, a .zip) and its build id.
use std::{env, fs, path::PathBuf};

fn main() {
    let out = PathBuf::from(env::var("OUT_DIR").unwrap());
    let payload = env::var("MVSDSION_PAYLOAD").unwrap_or_default();
    let target = out.join("payload.zip");
    if payload.is_empty() {
        // Development build without a program inside
        fs::write(&target, b"").unwrap();
    } else {
        fs::copy(&payload, &target).expect("MVSDSION_PAYLOAD could not be read");
        println!("cargo:rerun-if-changed={payload}");
    }
    let id = env::var("MVSDSION_BUILD_ID").unwrap_or_else(|_| "dev".into());
    println!("cargo:rustc-env=MVSDSION_BUILD_ID={id}");
    println!("cargo:rerun-if-env-changed=MVSDSION_PAYLOAD");
    println!("cargo:rerun-if-env-changed=MVSDSION_BUILD_ID");
}
