{
  pkgs,
  lib ? pkgs.lib,
  enableRust,
  enableBPF,
  enableKdf,
}:
let
  version = "6.17.8";
  localVersion = "-development";
in
{
  kernelArgs = {
    inherit enableRust;

    inherit version;
    src = pkgs.fetchurl {
      url = "mirror://kernel/linux/kernel/v6.x/linux-${version}.tar.xz";
      sha256 = "1nmi5xmsys023xgy55dikm1ihim7fp7pf2kc3k00d9zwfm5fd3as";
    };

    # Add kernel patches here
    kernelPatches = [
      {
        patch = ../patches/0001-rust-don-t-assert-sysroot_src-location.patch;
      }
    ];

    inherit localVersion;
    modDirVersion = version + localVersion;
  };

  kernelConfig = {
    # See https://github.com/NixOS/nixpkgs/blob/master/nixos/modules/system/boot/kernel_config.nix
    structuredExtraConfig =
      with lib.kernel;
      {
        DEBUG_FS = yes;
        DEBUG_KERNEL = yes;
        DEBUG_MISC = yes;
        DEBUG_BUGVERBOSE = yes;
        DEBUG_BOOT_PARAMS = yes;
        DEBUG_STACK_USAGE = yes;
        DEBUG_SHIRQ = yes;
        DEBUG_ATOMIC_SLEEP = yes;

        IKCONFIG = yes;
        IKCONFIG_PROC = yes;
        # Compile with headers
        IKHEADERS = yes;

        SLUB_DEBUG = yes;
        DEBUG_MEMORY_INIT = yes;
        KASAN = yes;

        # FRAME_WARN - warn at build time for stack frames larger tahn this.

        MAGIC_SYSRQ = yes;

        LOCALVERSION = freeform localVersion;

        LOCK_STAT = yes;
        PROVE_LOCKING = yes;

        FTRACE = yes;
        STACKTRACE = yes;
        IRQSOFF_TRACER = yes;

        KGDB = yes;
        UBSAN = yes;
        BUG_ON_DATA_CORRUPTION = yes;
        SCHED_STACK_END_CHECK = yes;
        UNWINDER_FRAME_POINTER = yes;
        "64BIT" = yes;

        # initramfs/initrd ssupport
        BLK_DEV_INITRD = yes;

        PRINTK = yes;
        PRINTK_TIME = yes;
        EARLY_PRINTK = yes;

        # Support elf and #! scripts
        BINFMT_ELF = yes;
        BINFMT_SCRIPT = yes;

        # Create a tmpfs/ramfs early at bootup.
        DEVTMPFS = yes;
        DEVTMPFS_MOUNT = yes;

        # tmpfs support with POSIX ACLs and extended attributes
        TMPFS = yes;
        TMPFS_POSIX_ACL = yes;
        TMPFS_XATTR = yes;

        TTY = yes;
        SERIAL_8250 = yes;
        SERIAL_8250_CONSOLE = yes;

        PROC_FS = yes;
        SYSFS = yes;

        MODULES = yes;
        MODULE_UNLOAD = yes;

        DEBUG_INFO_DWARF_TOOLCHAIN_DEFAULT = yes;
        GDB_SCRIPTS = yes;
        # FW_LOADER = yes;
      }
      // lib.optionalAttrs enableBPF {
        BPF_SYSCALL = yes;
        # Enable kprobes and kallsyms: https://www.kernel.org/doc/html/latest/trace/kprobes.html#configuring-kprobes
        # Debug FS is be enabled (done above) to show registered kprobes in /sys/kernel/debug: https://www.kernel.org/doc/html/latest/trace/kprobes.html#the-kprobes-debugfs-interface
        KPROBES = yes;
        KALLSYMS_ALL = yes;
      }
      // lib.optionalAttrs enableRust {
        GCC_PLUGINS = no;
        RUST = yes;
        RUST_OVERFLOW_CHECKS = yes;
        RUST_DEBUG_ASSERTIONS = yes;
      }
      // lib.optionalAttrs enableKdf {
        # ACPI support for proper shutdown/poweroff in QEMU
        ACPI = yes;
        ACPI_BUTTON = yes;

        # PCI bus support (required for VIRTIO_PCI)
        PCI = yes;

        # Virtio support for kdf-init/kdf-cli
        VIRTIO_MENU = yes;
        VIRTIO = yes;
        VIRTIO_PCI = yes;
        VIRTIO_BALLOON = yes;

        # Overlayfs support for kdf-init
        OVERLAY_FS = yes;

        # Virtiofs support for kdf-init/kdf-cli with DAX
        VIRTIO_FS = yes;
        FUSE_FS = yes;

        # Networking support - required for UNIX domain sockets
        NET = yes;

        # UNIX domain sockets - required for Rust std::process::Command with pre_exec
        # When pre_exec is used, Rust cannot use posix_spawn() and falls back to fork().
        # https://github.com/rust-lang/rust/blob/10776a4071b7ff4056bc8ae382d4a85d4be63cdb/library/std/src/sys/process/unix/unix.rs#L467
        # The fork path creates socketpair(AF_UNIX, SOCK_SEQPACKET) to communicate
        # exec errors from child back to parent. Without CONFIG_UNIX, socketpair returns ENOSYS.
        # https://github.com/rust-lang/rust/blob/10776a4071b7ff4056bc8ae382d4a85d4be63cdb/library/std/src/sys/process/unix/unix.rs#L78
        UNIX = yes;

        # DAX (Direct Access) support - allows guest to directly access host file cache
        # This avoids memory duplication and improves virtiofs performance
        DAX = yes;
        FS_DAX = yes; # Filesystem DAX support (depends on ZONE_DEVICE)
        ZONE_DEVICE = yes; # Device memory hotplug for DAX operations
        MEMORY_HOTPLUG = yes; # Required by ZONE_DEVICE
        MEMORY_HOTREMOVE = yes; # Required by ZONE_DEVICE
        SPARSEMEM_VMEMMAP = yes; # Required by ZONE_DEVICE
      };

    # Flags that get passed to generate-config.pl
    generateConfigFlags = {
      # Ignores any config errors (eg unused config options)
      ignoreConfigErrors = false;
      # Build every available module
      autoModules = false;
      preferBuiltin = false;
    };
  };
}
