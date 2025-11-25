"""Nix integration for kernel resolution"""

import logging
import subprocess
import tempfile
from pathlib import Path

from kdf_cli.initramfs import get_prebuilt_init, create_initramfs_archive

logger = logging.getLogger("kdf.nix")

# Virtiofs module dependencies (order doesn't matter - dependency resolution happens during initramfs build)
VIRTIOFS_MODULES = [
    "drivers/virtio/virtio.ko",
    "drivers/virtio/virtio_ring.ko",
    "drivers/virtio/virtio_pci_modern_dev.ko",
    "drivers/virtio/virtio_pci_legacy_dev.ko",
    "drivers/virtio/virtio_pci.ko",
    "fs/fuse/fuse.ko",
    "fs/fuse/virtiofs.ko",
]


def get_system_kernel_version() -> str:
    """Get the current system kernel version using uname"""
    result = subprocess.run(["uname", "-r"], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def nix_build_output(nix_expr: str, output: str | None = None) -> str:
    """
    Build a Nix expression and return the output path.

    Args:
        nix_expr: Nix expression to build
        output: Optional output name (e.g., "modules", "dev"). If None, uses default output.

    Returns:
        Nix store path as a string
    """
    if output:
        full_expr = f"({nix_expr}).{output}"
    else:
        full_expr = nix_expr

    result = subprocess.run(
        ["nix-build", "--no-out-link", "-E", full_expr],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def get_kernel_derivations(version: str | None = None) -> tuple[str, str]:
    """
    Get the Nix store paths for kernel and modules derivations.

    Args:
        version: Kernel version string (e.g., "6.6" or "6.12") or None for default kernel

    Returns:
        Tuple of (kernel_drv_path, modules_drv_path)
    """
    if version is None or version == "":
        # Use default linuxPackages
        nix_expr = "with import <nixpkgs> {}; linuxPackages.kernel"
        logger.info("Using default linuxPackages kernel")
    else:
        # Parse version to get major.minor
        parts = version.split(".")
        if len(parts) < 2:
            raise ValueError(
                f"Invalid kernel version format: {version} (need at least major.minor, e.g., '6.6')"
            )

        major = parts[0]
        minor = parts[1]

        # Use linuxPackages_{major}_{minor}
        package_name = f"linuxPackages_{major}_{minor}"
        nix_expr = f"with import <nixpkgs> {{}}; {package_name}.kernel"
        logger.info(f"Using {package_name} from nixpkgs")

    try:
        # Build kernel (default output)
        kernel_drv = nix_build_output(nix_expr)

        # Build modules output
        modules_drv = nix_build_output(nix_expr, "modules")

        logger.info(f"Kernel derivation: {kernel_drv}")
        logger.info(f"Modules derivation: {modules_drv}")

        return kernel_drv, modules_drv

    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to resolve kernel: {e.stderr}")
        raise


def get_kernel_image_path(kernel_drv: str) -> Path:
    """
    Get the path to the kernel image (bzImage) from the kernel derivation.

    Args:
        kernel_drv: Nix store path to kernel derivation

    Returns:
        Path to kernel image
    """
    kernel_path = Path(kernel_drv)

    # Try common kernel image names
    for image_name in ["bzImage", "Image", "vmlinuz", "zImage"]:
        kernel_image = kernel_path / image_name
        if kernel_image.exists():
            logger.info(f"Found kernel image: {kernel_image}")
            return kernel_image

    raise FileNotFoundError(f"Could not find kernel image in {kernel_path}")


def find_modules(modules_drv: str, module_patterns: list[str]) -> list[Path]:
    """
    Find kernel modules in the kernel modules directory.

    Args:
        modules_drv: Nix store path to kernel modules derivation
        module_patterns: List of module paths relative to lib/modules/VERSION/kernel/
                        (e.g., "drivers/virtio/virtio.ko")

    Returns:
        List of module paths (dependency resolution handled by initramfs builder)
    """
    modules = []
    modules_base = Path(modules_drv)

    # Find the kernel version directory
    modules_dir = modules_base / "lib" / "modules"
    kernel_dirs = list(modules_dir.glob("*"))
    if not kernel_dirs:
        raise FileNotFoundError(f"No kernel version directories found in {modules_dir}")

    kernel_dir = kernel_dirs[0]
    kernel_base = kernel_dir / "kernel"

    for pattern in module_patterns:
        # Try with compression extensions
        found = False
        for ext in [".xz", ".gz", ""]:
            module_path = Path(str(kernel_base / pattern) + ext)
            if module_path.exists():
                modules.append(module_path)
                logger.info(f"Found module: {module_path}")
                found = True
                break

        if not found:
            raise FileNotFoundError(f"Could not find module {pattern} in {kernel_base}")

    return modules


def resolve_kernel_and_initramfs(
    version: str | None = None, custom_initramfs: Path | None = None
) -> tuple[Path, Path]:
    """
    High-level function to resolve kernel and initramfs from nixpkgs.

    If custom_initramfs is provided, it will be used as-is.
    Otherwise, builds an initramfs with virtiofs modules from the resolved kernel.

    Args:
        version: Kernel version string or None to use system kernel
        custom_initramfs: Optional custom initramfs path. If None, builds one with virtiofs modules.

    Returns:
        Tuple of (kernel_image_path, initramfs_path)
    """
    # Get kernel and modules derivations
    kernel_drv, modules_drv = get_kernel_derivations(version)

    # Get kernel image path
    kernel_image = get_kernel_image_path(kernel_drv)

    # If custom initramfs provided, use it
    if custom_initramfs is not None:
        return kernel_image, custom_initramfs

    # Otherwise, build initramfs with virtiofs modules
    # Get prebuilt init binary
    init_binary = get_prebuilt_init()
    if init_binary is None:
        raise FileNotFoundError(
            "No prebuilt init binary available. "
            "Please build kdf-cli from the Nix package or provide --initramfs."
        )

    # Find virtiofs modules
    modules = find_modules(modules_drv, VIRTIOFS_MODULES)

    # Create temporary initramfs file
    import os

    fd, initramfs_tmpfile = tempfile.mkstemp(suffix=".cpio", prefix="kdf-initramfs-")
    os.close(fd)  # Close the file descriptor, we just need the path
    initramfs_path = Path(initramfs_tmpfile)

    logger.info(f"Building initramfs with {len(modules)} virtiofs modules")
    create_initramfs_archive(init_binary, initramfs_path, modules, "/init-modules")

    return kernel_image, initramfs_path
