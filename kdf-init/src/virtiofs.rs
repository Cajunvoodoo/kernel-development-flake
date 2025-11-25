//! Virtiofs mounting with optional overlayfs support

use anyhow::{Context, Result};
use rustix::fs::Mode;
use rustix::mount::{mount, MountFlags};

use crate::cmdline::VirtiofsMount;

fn check_virtiofs_support() -> Result<()> {
    // Check if virtiofs is available
    let filesystems = std::fs::read_to_string("/proc/filesystems")
        .context("Failed to read /proc/filesystems")?;

    if filesystems.contains("virtiofs") {
        println!("kdf-init: virtiofs support detected");
        Ok(())
    } else {
        anyhow::bail!(
            "virtiofs filesystem not supported by kernel. \
             Make sure CONFIG_VIRTIO_FS is enabled (either built-in or as a module) \
             and that the module is loaded before mounting virtiofs shares."
        )
    }
}

fn mkdir_p(path: &str) -> Result<()> {
    use std::path::Path;

    let path_obj = Path::new(path);

    // Collect all parent directories that need to be created
    let mut dirs_to_create = Vec::new();
    let mut current = path_obj;

    while let Some(parent) = current.parent() {
        if parent.as_os_str().is_empty() || parent == Path::new("/") {
            break;
        }
        if !parent.exists() {
            dirs_to_create.push(parent);
        }
        current = parent;
    }

    // Create directories from root to target
    dirs_to_create.reverse();
    for dir in dirs_to_create {
        rustix::fs::mkdir(dir, Mode::from_raw_mode(0o755))
            .or_else(|e| if e == rustix::io::Errno::EXIST { Ok(()) } else { Err(e) })
            .with_context(|| format!("Failed to create directory {}", dir.display()))?;
    }

    // Create the target directory itself
    rustix::fs::mkdir(path, Mode::from_raw_mode(0o755))
        .or_else(|e| if e == rustix::io::Errno::EXIST { Ok(()) } else { Err(e) })
        .with_context(|| format!("Failed to create directory {}", path))?;

    Ok(())
}

pub fn mount_virtiofs_shares(mounts: &[VirtiofsMount]) -> Result<()> {
    if mounts.is_empty() {
        return Ok(());
    }

    // Check virtiofs support before attempting to mount
    check_virtiofs_support()?;

    for vfs_mount in mounts {
        // Create mount point directory (with parents)
        mkdir_p(&vfs_mount.path)?;

        if vfs_mount.with_overlay {
            // Create overlayfs structure in /run/overlayfs/{tag}/
            let overlay_base = format!("/run/overlayfs/{}", vfs_mount.tag);
            let upper_dir = format!("{}/upper", overlay_base);
            let work_dir = format!("{}/work", overlay_base);
            let lower_dir = format!("{}/lower", overlay_base);

            // Create all overlay directories
            for dir in [&overlay_base, &upper_dir, &work_dir, &lower_dir] {
                rustix::fs::mkdir(dir, Mode::from_raw_mode(0o755))
                    .or_else(|e| if e == rustix::io::Errno::EXIST { Ok(()) } else { Err(e) })
                    .with_context(|| format!("Failed to create overlay directory {}", dir))?;
            }

            // Mount virtiofs as lower layer
            mount(
                &vfs_mount.tag,
                &lower_dir,
                "virtiofs",
                MountFlags::RDONLY,
                "",
            )
            .with_context(|| format!("Failed to mount virtiofs {} at {}", vfs_mount.tag, lower_dir))?;

            println!("kdf-init: mounted virtiofs {} (ro) at {}", vfs_mount.tag, lower_dir);

            // Mount overlayfs with writable upper layer
            let overlay_opts = format!(
                "lowerdir={},upperdir={},workdir={}",
                lower_dir, upper_dir, work_dir
            );
            mount(
                "overlay",
                &vfs_mount.path,
                "overlay",
                MountFlags::empty(),
                &overlay_opts,
            )
            .with_context(|| format!("Failed to mount overlayfs at {}", vfs_mount.path))?;

            println!(
                "kdf-init: mounted overlayfs (rw) at {} over virtiofs {}",
                vfs_mount.path, vfs_mount.tag
            );
        } else {
            // Direct virtiofs mount without overlay
            mount(
                &vfs_mount.tag,
                &vfs_mount.path,
                "virtiofs",
                MountFlags::empty(),
                "",
            )
            .with_context(|| format!("Failed to mount virtiofs {} at {}", vfs_mount.tag, vfs_mount.path))?;

            println!("kdf-init: mounted virtiofs {} at {}", vfs_mount.tag, vfs_mount.path);
        }
    }

    Ok(())
}
