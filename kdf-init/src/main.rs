//! kdf-init: minimal Rust init for initramfs with virtiofs and overlayfs support

mod cmdline;

use anyhow::{Context, Result};
use rustix::fs::Mode;
use rustix::mount::{mount, MountFlags};

struct KernelMount {
    source: &'static str,
    target: &'static str,
    fstype: &'static str,
    flags: MountFlags,
    data: &'static str,
}

const KERNEL_MOUNTS: &[KernelMount] = &[
    KernelMount {
        source: "proc",
        target: "/proc",
        fstype: "proc",
        flags: MountFlags::empty(),
        data: "",
    },
    KernelMount {
        source: "sysfs",
        target: "/sys",
        fstype: "sysfs",
        flags: MountFlags::empty(),
        data: "",
    },
    KernelMount {
        source: "devtmpfs",
        target: "/dev",
        fstype: "devtmpfs",
        flags: MountFlags::empty(),
        data: "",
    },
    KernelMount {
        source: "tmpfs",
        target: "/run",
        fstype: "tmpfs",
        flags: MountFlags::empty(),
        data: "mode=0755",
    },
];

fn mount_kernel_filesystems() -> Result<()> {
    for m in KERNEL_MOUNTS {
        // Create mount point if it doesn't exist
        rustix::fs::mkdir(m.target, Mode::from_raw_mode(0o755))
            .or_else(|e| if e == rustix::io::Errno::EXIST { Ok(()) } else { Err(e) })
            .with_context(|| format!("Failed to create {}", m.target))?;

        // Mount filesystem
        mount(m.source, m.target, m.fstype, m.flags, m.data)
            .with_context(|| format!("Failed to mount {}", m.target))?;

        println!("kdf-init: mounted {}", m.target);
    }

    Ok(())
}

fn main() -> Result<()> {
    println!("kdf-init: starting minimal Rust init");

    // Mount kernel filesystems
    mount_kernel_filesystems()?;

    // Parse kernel cmdline
    let cmdline_str = cmdline::read_cmdline()?;
    println!("kdf-init: kernel cmdline: {}", cmdline_str);

    let config = cmdline::parse_cmdline(&cmdline_str)?;

    println!("kdf-init: parsed configuration:");
    println!("  virtiofs mounts: {}", config.virtiofs_mounts.len());
    println!("  symlinks: {}", config.symlinks.len());
    println!("  env vars: {}", config.env_vars.len());
    println!("  command: {:?}", config.command);

    // TODO: Mount virtiofs shares with optional overlayfs
    // TODO: Create symlinks
    // TODO: Set environment variables
    // TODO: Execute command

    println!("kdf-init: initialization complete (stub)");
    Ok(())
}
