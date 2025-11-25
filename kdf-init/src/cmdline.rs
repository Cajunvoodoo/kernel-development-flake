//! Kernel cmdline parser for kdf-init parameters

use anyhow::{Context, Result};
use std::collections::HashMap;

/// Virtiofs mount specification
#[derive(Debug, Clone, PartialEq)]
pub struct VirtiofsMount {
    /// Virtiofs tag to mount
    pub tag: String,
    /// Path to mount at
    pub path: String,
    /// Whether to create overlayfs with writable layer
    pub with_overlay: bool,
}

/// Symlink specification
#[derive(Debug, Clone, PartialEq)]
pub struct Symlink {
    /// Source path for symlink
    pub source: String,
    /// Target path to link to
    pub target: String,
}

/// Parsed init configuration from kernel cmdline
#[derive(Debug, Default, PartialEq)]
pub struct Config {
    /// Virtiofs mounts to create
    pub virtiofs_mounts: Vec<VirtiofsMount>,
    /// Symlinks to create
    pub symlinks: Vec<Symlink>,
    /// Environment variables to set
    pub env_vars: HashMap<String, String>,
    /// Command to execute
    pub command: Option<String>,
}

/// Parse kernel cmdline into Config
///
/// Supports: init.virtiofs, init.symlinks, init.env.XXX, init.cmd
pub fn parse_cmdline(cmdline: &str) -> Result<Config> {
    let mut config = Config::default();

    for param in cmdline.split_whitespace() {
        if let Some(value) = param.strip_prefix("init.virtiofs=") {
            config.virtiofs_mounts = parse_virtiofs_mounts(value)?;
        } else if let Some(value) = param.strip_prefix("init.symlinks=") {
            config.symlinks = parse_symlinks(value)?;
        } else if let Some(rest) = param.strip_prefix("init.env.") {
            if let Some((key, value)) = rest.split_once('=') {
                config.env_vars.insert(key.to_string(), value.to_string());
            }
        } else if let Some(value) = param.strip_prefix("init.cmd=") {
            config.command = Some(value.to_string());
        }
    }

    Ok(config)
}

fn parse_virtiofs_mounts(value: &str) -> Result<Vec<VirtiofsMount>> {
    let mut mounts = Vec::new();

    for mount_spec in value.split(',') {
        if mount_spec.is_empty() {
            continue;
        }

        let parts: Vec<&str> = mount_spec.split(':').collect();

        let (tag, path, with_overlay) = match parts.as_slice() {
            [tag, path] => (*tag, *path, false),
            [tag, path, overlay] => (*tag, *path, *overlay == "Y"),
            _ => anyhow::bail!("Invalid virtiofs mount spec: {}", mount_spec),
        };

        mounts.push(VirtiofsMount {
            tag: tag.to_string(),
            path: path.to_string(),
            with_overlay,
        });
    }

    Ok(mounts)
}

fn parse_symlinks(value: &str) -> Result<Vec<Symlink>> {
    let mut symlinks = Vec::new();

    for symlink_spec in value.split(',') {
        if symlink_spec.is_empty() {
            continue;
        }

        let (source, target) = symlink_spec
            .split_once(':')
            .context(format!("Invalid symlink spec: {}", symlink_spec))?;

        symlinks.push(Symlink {
            source: source.to_string(),
            target: target.to_string(),
        });
    }

    Ok(symlinks)
}

/// Read kernel cmdline from /proc/cmdline
pub fn read_cmdline() -> Result<String> {
    std::fs::read_to_string("/proc/cmdline")
        .context("Failed to read /proc/cmdline")
        .map(|s| s.trim().to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_empty_cmdline() {
        let config = parse_cmdline("").unwrap();
        assert_eq!(config, Config::default());
    }

    #[test]
    fn test_parse_virtiofs_basic() {
        let config = parse_cmdline("init.virtiofs=share:/mnt/share").unwrap();
        assert_eq!(config.virtiofs_mounts.len(), 1);
        assert_eq!(config.virtiofs_mounts[0].tag, "share");
        assert_eq!(config.virtiofs_mounts[0].path, "/mnt/share");
        assert_eq!(config.virtiofs_mounts[0].with_overlay, false);
    }

    #[test]
    fn test_parse_virtiofs_with_overlay() {
        let config = parse_cmdline("init.virtiofs=share:/mnt/share:Y").unwrap();
        assert_eq!(config.virtiofs_mounts.len(), 1);
        assert_eq!(config.virtiofs_mounts[0].with_overlay, true);
    }

    #[test]
    fn test_parse_virtiofs_multiple() {
        let config = parse_cmdline("init.virtiofs=share1:/mnt/a,share2:/mnt/b:Y").unwrap();
        assert_eq!(config.virtiofs_mounts.len(), 2);
        assert_eq!(config.virtiofs_mounts[0].tag, "share1");
        assert_eq!(config.virtiofs_mounts[0].path, "/mnt/a");
        assert_eq!(config.virtiofs_mounts[0].with_overlay, false);
        assert_eq!(config.virtiofs_mounts[1].tag, "share2");
        assert_eq!(config.virtiofs_mounts[1].path, "/mnt/b");
        assert_eq!(config.virtiofs_mounts[1].with_overlay, true);
    }

    #[test]
    fn test_parse_symlinks() {
        let config = parse_cmdline("init.symlinks=/bin/sh:/bin/bash,/usr/bin/vi:/usr/bin/vim").unwrap();
        assert_eq!(config.symlinks.len(), 2);
        assert_eq!(config.symlinks[0].source, "/bin/sh");
        assert_eq!(config.symlinks[0].target, "/bin/bash");
        assert_eq!(config.symlinks[1].source, "/usr/bin/vi");
        assert_eq!(config.symlinks[1].target, "/usr/bin/vim");
    }

    #[test]
    fn test_parse_env_vars() {
        let config = parse_cmdline("init.env.PATH=/usr/bin init.env.HOME=/root").unwrap();
        assert_eq!(config.env_vars.len(), 2);
        assert_eq!(config.env_vars.get("PATH"), Some(&"/usr/bin".to_string()));
        assert_eq!(config.env_vars.get("HOME"), Some(&"/root".to_string()));
    }

    #[test]
    fn test_parse_command() {
        let config = parse_cmdline("init.cmd=/bin/sh").unwrap();
        assert_eq!(config.command, Some("/bin/sh".to_string()));
    }

    #[test]
    fn test_parse_full_cmdline() {
        let cmdline = "console=ttyS0 init.virtiofs=share:/mnt:Y init.symlinks=/bin/sh:/bin/bash init.env.PATH=/usr/bin init.cmd=/bin/sh quiet";
        let config = parse_cmdline(cmdline).unwrap();

        assert_eq!(config.virtiofs_mounts.len(), 1);
        assert_eq!(config.virtiofs_mounts[0].tag, "share");
        assert_eq!(config.virtiofs_mounts[0].path, "/mnt");
        assert_eq!(config.virtiofs_mounts[0].with_overlay, true);

        assert_eq!(config.symlinks.len(), 1);
        assert_eq!(config.symlinks[0].source, "/bin/sh");
        assert_eq!(config.symlinks[0].target, "/bin/bash");

        assert_eq!(config.env_vars.get("PATH"), Some(&"/usr/bin".to_string()));
        assert_eq!(config.command, Some("/bin/sh".to_string()));
    }

    #[test]
    fn test_parse_invalid_virtiofs() {
        let result = parse_cmdline("init.virtiofs=invalid");
        assert!(result.is_err());
    }

    #[test]
    fn test_parse_invalid_symlink() {
        let result = parse_cmdline("init.symlinks=invalid");
        assert!(result.is_err());
    }
}
