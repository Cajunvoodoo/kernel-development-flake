#!/usr/bin/env python3
"""kdf: Kernel development flake - Manage kdf-init initramfs and kernel execution"""

import argparse
import logging
import subprocess
import sys
from pathlib import Path

from kdf_cli.bg_tasks import BackgroundTaskManager
from kdf_cli.qemu import QemuCommand
from kdf_cli.virtiofs import VirtiofsError, create_virtiofs_tasks
from kdf_cli.nix import resolve_kernel_and_initramfs
from kdf_cli.initramfs import (
    get_prebuilt_initramfs,
    get_prebuilt_init,
    copy_file,
    create_initramfs_archive,
)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("kdf.log"), logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("kdf")


def cmd_build_initramfs(args):
    """Build initramfs cpio archive from init binary"""
    try:
        # Parse module paths if provided
        modules = []
        if args.modules:
            for module_path_str in args.modules:
                module_path = Path(module_path_str)
                modules.append(module_path)

        # Determine output path
        output_path = args.output if args.output else Path("./initramfs.cpio")

        # Special case: No modules and no custom init - just copy prebuilt initramfs if available
        if not modules and args.init_binary is None:
            prebuilt_initramfs = get_prebuilt_initramfs()
            if prebuilt_initramfs is not None:
                logger.info(f"Copying prebuilt initramfs to: {output_path}")
                copy_file(prebuilt_initramfs, output_path)
                return

        # Determine which init binary to use
        if args.init_binary is None:
            # Try to use prebuilt init
            prebuilt_init = get_prebuilt_init()
            if prebuilt_init is None:
                raise FileNotFoundError(
                    "No init binary specified and no prebuilt init available. "
                    "Please provide an init binary as the first argument."
                )
            logger.info(f"Using prebuilt init binary: {prebuilt_init}")
            init_binary = prebuilt_init
        else:
            if not args.init_binary.exists():
                raise FileNotFoundError(f"Init binary not found: {args.init_binary}")
            init_binary = args.init_binary

        # Build initramfs directly to output
        create_initramfs_archive(init_binary, output_path, modules, args.moddir)
        logger.info(f"Created initramfs: {output_path}")
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


def cmd_run(args):
    """Run QEMU with kernel and initramfs"""
    # Handle --release flag to resolve kernel from nixpkgs
    if args.release is not None:
        try:
            kernel, initramfs = resolve_kernel_and_initramfs(
                version=args.release if args.release else None,
                custom_initramfs=args.initramfs,
            )
            logger.info(f"Resolved kernel: {kernel}")
            logger.info(f"Resolved initramfs: {initramfs}")
        except Exception as e:
            logger.error(f"Failed to resolve kernel from nixpkgs: {e}")
            sys.exit(1)
    else:
        # Use provided kernel
        kernel = args.kernel
        if not kernel.exists():
            logger.error(f"Kernel not found: {kernel}")
            sys.exit(1)

        # Determine which initramfs to use
        initramfs: Path
        if args.initramfs is not None:
            initramfs = args.initramfs
        else:
            # Try to use prebuilt initramfs
            prebuilt_initramfs = get_prebuilt_initramfs()
            if prebuilt_initramfs is None:
                logger.error(
                    "No initramfs specified and no prebuilt initramfs available. "
                    "Please provide --initramfs or build kdf-cli from the Nix package."
                )
                sys.exit(1)
            # TODO: ty doesn't understand that sys.exit(1) never returns, so it can't narrow the type
            initramfs = prebuilt_initramfs  # type: ignore[invalid-assignment]
            logger.info(f"Using prebuilt initramfs: {initramfs}")

        if not initramfs.exists():
            logger.error(f"Initramfs not found: {initramfs}")
            sys.exit(1)

    # Create background task manager
    task_manager = BackgroundTaskManager()

    try:
        # Create virtiofs tasks (but don't start yet)
        if args.virtiofs:
            create_virtiofs_tasks(args.virtiofs, task_manager)

        # Start all background tasks
        task_manager.start_all()

        # Build QEMU command with optional DAX support for virtiofs
        enable_dax = args.virtiofs_dax and args.virtiofs
        qemu_cmd = QemuCommand(kernel, initramfs, args.memory, enable_dax)

        # Register all tasks with QEMU (adds runtime info like sockets)
        task_manager.register_all_with_qemu(qemu_cmd)

        # Set moddir for kernel module loading
        if args.moddir:
            qemu_cmd.init_config.moddir = args.moddir

        # Add additional cmdline
        if args.cmdline:
            qemu_cmd.add_cmdline(args.cmdline)

        # Build and run command
        cmd = qemu_cmd.build()
        logger.info("Running QEMU with command:")
        logger.info(" ".join(cmd))
        subprocess.run(cmd)
    except (ValueError, VirtiofsError) as e:
        logger.error(f"Error: {e}")
        sys.exit(1)
    finally:
        task_manager.cleanup()


def main():
    parser = argparse.ArgumentParser(
        prog="kdf", description="kdf: Kernel development flake tools"
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommands")

    # build initramfs subcommand
    build_parser = subparsers.add_parser("build", help="Build subcommands")
    build_subparsers = build_parser.add_subparsers(dest="build_command")

    initramfs_parser = build_subparsers.add_parser(
        "initramfs", help="Build initramfs cpio archive"
    )
    initramfs_parser.add_argument(
        "init_binary",
        type=Path,
        nargs="?",
        default=None,
        help="Path to init binary (default: use prebuilt kdf-init if available)",
    )
    initramfs_parser.add_argument(
        "--output", "-o", type=Path, help="Output cpio file (default: ./initramfs.cpio)"
    )
    initramfs_parser.add_argument(
        "--module",
        "-m",
        action="append",
        dest="modules",
        help="Kernel module to include (can be specified multiple times)",
    )
    initramfs_parser.add_argument(
        "--moddir",
        default="/init-modules",
        help="Directory to store modules in initramfs (default: /init-modules)",
    )

    # run subcommand
    run_parser = subparsers.add_parser("run", help="Run kernel with initramfs in QEMU")
    kernel_group = run_parser.add_mutually_exclusive_group(required=True)
    kernel_group.add_argument("--kernel", type=Path, help="Path to kernel image")
    kernel_group.add_argument(
        "--release",
        "-r",
        nargs="?",
        const="",
        metavar="VERSION",
        help="Use nixpkgs kernel release (optionally specify version, defaults to system kernel)",
    )
    run_parser.add_argument(
        "--initramfs",
        type=Path,
        default=None,
        help="Path to initramfs cpio (default: use prebuilt if available)",
    )
    run_parser.add_argument(
        "--virtiofs",
        "-v",
        action="append",
        help="Virtiofs share: tag:host_path:guest_path[:overlay]",
    )
    run_parser.add_argument(
        "--cmdline", default="", help="Additional kernel cmdline arguments"
    )
    run_parser.add_argument(
        "--memory", "-m", default="512M", help="QEMU memory (default: 512M)"
    )
    run_parser.add_argument(
        "--virtiofs-dax",
        action="store_true",
        help="Enable virtiofs DAX (shared memory backing) for better performance",
    )
    run_parser.add_argument(
        "--moddir",
        default="/init-modules",
        help="Directory to load kernel modules from (default: /init-modules)",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "build":
        if not args.build_command:
            build_parser.print_help()
            sys.exit(1)
        if args.build_command == "initramfs":
            cmd_build_initramfs(args)
    elif args.command == "run":
        cmd_run(args)


if __name__ == "__main__":
    main()
