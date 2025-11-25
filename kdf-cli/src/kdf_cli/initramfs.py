"""Initramfs building utilities"""

import logging
import os
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger("kdf.initramfs")


def get_resource_dir() -> Path | None:
    """Get resource directory if running from Nix package, None otherwise"""
    resource_dir = os.environ.get("KDF_RESOURCE_DIR")
    if resource_dir:
        return Path(resource_dir)
    return None


def get_prebuilt_initramfs() -> Path | None:
    """Get path to prebuilt initramfs if available"""
    resource_dir = get_resource_dir()
    if resource_dir:
        initramfs_path = resource_dir / "initramfs.cpio"
        if initramfs_path.exists():
            return initramfs_path
    return None


def get_prebuilt_init() -> Path | None:
    """Get path to prebuilt kdf-init binary if available"""
    resource_dir = get_resource_dir()
    if resource_dir:
        init_path = resource_dir / "init"
        if init_path.exists():
            return init_path
    return None


def copy_file(src: Path, dst: Path) -> None:
    """Copy file from src to dst"""
    subprocess.run(["cp", str(src), str(dst)], check=True)


def get_module_dependencies(module_path: Path) -> list[str]:
    """Get module dependencies using modinfo"""
    try:
        result = subprocess.run(
            ["modinfo", "-F", "depends", str(module_path)],
            capture_output=True,
            text=True,
            check=True,
        )
        deps = result.stdout.strip()
        if deps:
            return [d.strip() for d in deps.split(",") if d.strip()]
        return []
    except subprocess.CalledProcessError:
        return []


def topological_sort_modules(modules: list[Path]) -> list[Path]:
    """Sort modules in dependency order using topological sort"""
    # Build dependency graph
    module_map = {}  # name (without .ko.xz) -> Path
    dependencies = {}  # name -> list of dependency names

    for module_path in modules:
        name = module_path.name
        # Remove compression extensions
        if name.endswith(".xz"):
            name = name[:-3]
        if name.endswith(".gz"):
            name = name[:-3]
        # Remove .ko extension
        if name.endswith(".ko"):
            name = name[:-3]

        module_map[name] = module_path
        dependencies[name] = get_module_dependencies(module_path)

    # Topological sort
    sorted_modules = []
    visited = set()

    def visit(name: str):
        if name in visited:
            return
        visited.add(name)

        # Visit dependencies first
        for dep in dependencies.get(name, []):
            if dep in module_map:  # Only if we have this dependency
                visit(dep)

        if name in module_map:
            sorted_modules.append(module_map[name])

    # Visit all modules
    for name in module_map:
        visit(name)

    return sorted_modules


def create_initramfs_archive(
    init_binary: Path, output_path: Path, modules: list[Path], moddir: str
) -> None:
    """Create initramfs cpio archive from init binary and optional kernel modules"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)

        # Copy init binary to temp directory
        init_path = tmppath / "init"
        copy_file(init_binary, init_path)
        subprocess.run(["chmod", "+x", str(init_path)], check=True)

        # Copy kernel modules if provided
        if modules:
            # Sort modules by dependencies
            sorted_modules = topological_sort_modules(modules)
            logger.info("Module load order after dependency resolution:")
            for idx, mod in enumerate(sorted_modules, 1):
                logger.info(f"  {idx}. {mod.name}")

            # Strip leading slash for creating directory in tmpdir
            moddir_relative = moddir.lstrip("/")
            modules_dir = tmppath / moddir_relative
            modules_dir.mkdir(parents=True, exist_ok=True)

            for idx, module_path in enumerate(sorted_modules):
                if not module_path.exists():
                    raise FileNotFoundError(f"Kernel module not found: {module_path}")

                # Decompress if needed and add numeric prefix for load order
                module_name = module_path.name
                prefix = f"{idx:02d}-"  # Two-digit prefix: 00-, 01-, etc.

                if module_name.endswith(".xz"):
                    # Decompress .xz module
                    decompressed_name = module_name[:-3]  # Remove .xz extension
                    final_name = prefix + decompressed_name
                    module_dest = modules_dir / final_name
                    subprocess.run(
                        ["xz", "-dc", str(module_path)],
                        stdout=open(module_dest, "wb"),
                        check=True,
                    )
                    logger.info(f"Added module: {module_name} -> {final_name}")
                elif module_name.endswith(".gz"):
                    # Decompress .gz module
                    decompressed_name = module_name[:-3]  # Remove .gz extension
                    final_name = prefix + decompressed_name
                    module_dest = modules_dir / final_name
                    subprocess.run(
                        ["gzip", "-dc", str(module_path)],
                        stdout=open(module_dest, "wb"),
                        check=True,
                    )
                    logger.info(f"Added module: {module_name} -> {final_name}")
                else:
                    # Copy as-is
                    final_name = prefix + module_name
                    module_dest = modules_dir / final_name
                    copy_file(module_path, module_dest)
                    logger.info(f"Added module: {module_name} -> {final_name}")

        # Create cpio archive
        with open(output_path, "wb") as f:
            subprocess.run(
                "find . -print0 | cpio --null -o -H newc",
                cwd=tmpdir,
                shell=True,
                stdout=f,
                check=True,
            )
